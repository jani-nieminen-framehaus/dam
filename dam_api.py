#!/opt/homebrew/bin/python3
"""
DAM API — Flask JSON API + static file server
Run: gunicorn -w 4 -b 0.0.0.0:5000 dam_api:app

Endpoints:
    GET   /                       SPA entry point
    GET   /api/images             Paginated image feed (keyset pagination)
    GET   /api/images/<id>        Single image detail
    PATCH /api/images/<id>        Update workflow fields
    GET   /api/thumbs/<filename>  Thumbnail file
    GET   /api/stats              DB summary
    GET   /api/filters            Available filter values for UI
"""

import json
import os
import struct
import subprocess
import typing
import urllib.error
import urllib.request

from flask import Flask, abort, jsonify, request, send_from_directory

from dam_config import (
    EMBED_MODEL,
    INGEST_STATUS_FILE,
    OLLAMA_BASE,
    PAGE_SIZE,
    SPA_DIR,
    THUMB_DIR,
)
from dam_db import get_db

app = Flask(__name__, static_folder=None)


def row_to_dict(row) -> dict[str, typing.Any]:
    d: dict[str, typing.Any] = dict(row)
    for field in ("projects", "subjects", "keywords"):
        val = d.get(field)
        if isinstance(val, str):
            try:
                d[field] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                d[field] = []
    return d


# ── Validation ────────────────────────────────────────────────────────────────

PATCHABLE = {
    "rating",
    "pick",
    "edit_status",
    "color_label",
    "is_selkie",
    "notes",
    "triptych_leg",
    "narrative_arc",
    "location_type",
}
PICK_VALUES = {"pick", "reject", "unmarked"}
EDIT_STATUS_VALUES = {"unculled", "rejected", "selected", "developed", "printed", "exhibited"}
COLOR_VALUES = {"red", "yellow", "green", "blue", "purple", "none"}
TRIPTYCH_VALUES = {"color_doc", "bw_portrait", "abstract", None}
NARRATIVE_VALUES = {"beginning", "middle", "current", None}


def validate_patch(data):
    clean = {}
    for key, val in data.items():
        if key not in PATCHABLE:
            return None, f"Field not patchable: {key}"
        if key == "rating":
            if not isinstance(val, int) or not (0 <= val <= 5):
                return None, "rating must be integer 0-5"
        elif key == "pick" and val not in PICK_VALUES:
            return None, f"pick must be one of {PICK_VALUES}"
        elif key == "edit_status" and val not in EDIT_STATUS_VALUES:
            return None, f"edit_status must be one of {EDIT_STATUS_VALUES}"
        elif key == "color_label" and val not in COLOR_VALUES:
            return None, f"color_label must be one of {COLOR_VALUES}"
        elif key == "triptych_leg" and val not in TRIPTYCH_VALUES:
            return None, f"triptych_leg must be one of {TRIPTYCH_VALUES}"
        elif key == "narrative_arc" and val not in NARRATIVE_VALUES:
            return None, f"narrative_arc must be one of {NARRATIVE_VALUES}"
        elif key == "is_selkie" and not isinstance(val, bool):
            return None, "is_selkie must be boolean"
        clean[key] = val
    return clean, None


# ── Filters ───────────────────────────────────────────────────────────────────


def build_filters(args):
    clauses, params = [], []

    if v := args.get("camera"):
        clauses.append("i.camera_short = ?")
        params.append(v)
    if v := args.get("volume"):
        clauses.append("i.volume = ?")
        params.append(v)
    if v := args.get("rating_min"):
        clauses.append("i.rating >= ?")
        params.append(int(v))
    if v := args.get("rating_max"):
        clauses.append("i.rating <= ?")
        params.append(int(v))
    if v := args.get("pick"):
        clauses.append("i.pick = ?")
        params.append(v)
    if v := args.get("edit_status"):
        clauses.append("i.edit_status = ?")
        params.append(v)
    if v := args.get("triptych_leg"):
        clauses.append("i.triptych_leg = ?")
        params.append(v)
    if v := args.get("date_from"):
        clauses.append("i.date_taken >= ?")
        params.append(v)
    if v := args.get("date_to"):
        clauses.append("i.date_taken <= ?")
        params.append(v)
    if v := args.get("is_selkie"):
        clauses.append("i.is_selkie = ?")
        params.append(1 if v.lower() == "true" else 0)

    # Keyset cursor
    cursor_date = args.get("cursor_date")
    cursor_id = args.get("cursor_id")
    if cursor_date and cursor_id:
        clauses.append("(i.date_taken < ? OR (i.date_taken = ? AND i.id < ?))")
        params.extend([cursor_date, cursor_date, int(cursor_id)])

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


# ── Routes ────────────────────────────────────────────────────────────────────


@app.route("/")
def spa():
    return send_from_directory(str(SPA_DIR), "index.html")


@app.route("/api/ingest/status", methods=["GET"])
def ingest_status():
    progress_file = INGEST_STATUS_FILE
    if not progress_file.exists():
        return jsonify({"status": "idle"})
    try:
        with open(progress_file, "r") as f:
            data = json.load(f)
            return jsonify(data)
    except Exception:
        return jsonify({"status": "error", "message": "Could not read status file"})


@app.route("/api/thumbs/<path:filename>")
def thumb(filename):
    return send_from_directory(str(THUMB_DIR), filename)


@app.route("/api/images", methods=["GET"])
def images():
    limit = min(int(request.args.get("limit", PAGE_SIZE)), 200)
    where, params = build_filters(request.args)

    sql = f"""
        SELECT i.*,
            COALESCE(json_group_array(DISTINCT p.name)
                FILTER (WHERE p.name IS NOT NULL), '[]') AS projects,
            COALESCE(json_group_array(DISTINCT s.name)
                FILTER (WHERE s.name IS NOT NULL), '[]') AS subjects,
            COALESCE(json_group_array(DISTINCT k.keyword)
                FILTER (WHERE k.keyword IS NOT NULL), '[]') AS keywords
        FROM images i
        LEFT JOIN image_projects ip  ON i.id = ip.image_id
        LEFT JOIN projects p         ON ip.project_id = p.id
        LEFT JOIN image_subjects isb ON i.id = isb.image_id
        LEFT JOIN subjects s         ON isb.subject_id = s.id
        LEFT JOIN image_keywords ik  ON i.id = ik.image_id
        LEFT JOIN keywords k         ON ik.keyword_id = k.id
        {where}
        GROUP BY i.id
        ORDER BY i.date_taken DESC, i.id DESC
        LIMIT ?
    """

    # Count without cursor or limit
    count_args = {k: v for k, v in request.args.items() if k not in ("cursor_date", "cursor_id", "limit")}
    count_where, count_params = build_filters(count_args)
    count_sql = f"SELECT COUNT(*) FROM images i {count_where}"

    db = get_db()
    try:
        rows = db.execute(sql, [*params, limit]).fetchall()
        total = db.execute(count_sql, count_params).fetchone()[0]
    finally:
        db.close()

    result = [row_to_dict(r) for r in rows]
    next_cursor = None
    if len(result) == limit:
        last = result[-1]
        next_cursor = {"date": last["date_taken"], "id": last["id"]}

    return jsonify({"images": result, "next_cursor": next_cursor, "total_filtered": total})


# ── AI Embeddings ─────────────────────────────────────────────────────────────


def get_embedding(text):
    """Fetch embedding from local Ollama instance."""
    url = f"{OLLAMA_BASE}/api/embeddings"
    payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data.get("embedding", [])
    except urllib.error.URLError as e:
        print(f"Error connecting to Ollama: {e}")
        return None


def serialize_vector(floats: list):
    """Pack float list to binary blob for sqlite-vec."""
    return struct.pack(f"{len(floats)}f", *floats)


@app.route("/api/search", methods=["GET"])
def search():
    query = request.args.get("q")
    if not query:
        return jsonify({"images": [], "next_cursor": None, "total_filtered": 0})

    limit = min(int(request.args.get("limit", PAGE_SIZE)), 200)

    # 1. Get embedding for query
    embedding = get_embedding(query)
    if not embedding:
        return jsonify({"error": "Failed to generate embedding via Ollama"}), 500

    blob = serialize_vector(embedding)

    # 2. Search sqlite-vec
    sql = """
        SELECT i.*,
            e.distance as _distance,
            COALESCE(json_group_array(DISTINCT p.name)
                FILTER (WHERE p.name IS NOT NULL), '[]') AS projects,
            COALESCE(json_group_array(DISTINCT s.name)
                FILTER (WHERE s.name IS NOT NULL), '[]') AS subjects,
            COALESCE(json_group_array(DISTINCT k.keyword)
                FILTER (WHERE k.keyword IS NOT NULL), '[]') AS keywords
        FROM image_embeddings e
        JOIN images i ON i.id = e.image_id
        LEFT JOIN image_projects ip  ON i.id = ip.image_id
        LEFT JOIN projects p         ON ip.project_id = p.id
        LEFT JOIN image_subjects isb ON i.id = isb.image_id
        LEFT JOIN subjects s         ON isb.subject_id = s.id
        LEFT JOIN image_keywords ik  ON i.id = ik.image_id
        LEFT JOIN keywords k         ON ik.keyword_id = k.id
        WHERE e.embedding MATCH ? AND e.k = ?
        GROUP BY i.id
        ORDER BY e.distance
    """

    db = get_db()
    try:
        rows = db.execute(sql, (blob, limit)).fetchall()
    finally:
        db.close()

    result = [row_to_dict(r) for r in rows]

    # Send same format as /api/images so frontend grid works unchanged
    return jsonify({"images": result, "next_cursor": None, "total_filtered": len(result)})


@app.route("/api/images/<int:image_id>", methods=["GET"])
def image_detail(image_id):
    db = get_db()
    try:
        row = db.execute("SELECT * FROM images_flat WHERE id = ?", (image_id,)).fetchone()
    finally:
        db.close()
    if not row:
        abort(404)
    return jsonify(row_to_dict(row))


@app.route("/api/images/<int:image_id>", methods=["PATCH"])
def image_patch(image_id):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No JSON body"}), 400
    clean, err = validate_patch(data)
    if err:
        return jsonify({"error": err}), 400
    if not clean:
        return jsonify({"error": "Nothing to update"}), 400

    # Safety: column names in set_clause come from `clean`, whose keys are
    # validated against the PATCHABLE set (hardcoded string literals above).
    # User input never reaches column name positions; values use parameterised ?.
    set_clause = ", ".join(f"{k} = ?" for k in clean)
    values = [*clean.values(), image_id]

    db = get_db()
    try:
        db.execute(f"UPDATE images SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        db.commit()
        row = db.execute("SELECT * FROM images_flat WHERE id = ?", (image_id,)).fetchone()
    finally:
        db.close()

    if not row:
        abort(404)
    return jsonify(row_to_dict(row))


@app.route("/api/images/<int:image_id>/open_external", methods=["POST"])
def image_open_external(image_id):
    db = get_db()
    try:
        row = db.execute("SELECT file_path FROM images WHERE id = ?", (image_id,)).fetchone()
    finally:
        db.close()

    if not row or not row["file_path"]:
        abort(404)

    abs_path = row["file_path"]
    if not os.path.exists(abs_path):
        return jsonify({"error": "File not found on disk"}), 404

    data = request.get_json(silent=True) or {}
    app_name = data.get("app")

    try:
        if app_name:
            subprocess.run(["open", "-a", app_name, abs_path], check=True)
        else:
            # -W = wait for app, -n = open new instance, but without -a it just opens "With..." dialog
            # Actually, standard "open" without -a opens the default app.
            subprocess.run(["open", abs_path], check=True)
        return jsonify({"success": True, "action": "opened_external"})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"Launch failed: {e}"}), 500


@app.route("/api/images/<int:image_id>/open_jpeg", methods=["POST"])
def image_open_jpeg(image_id):
    db = get_db()
    try:
        row = db.execute("SELECT file_path, jpeg_path FROM images_flat WHERE id = ?", (image_id,)).fetchone()
    finally:
        db.close()

    if not row:
        abort(404)

    target_path = row["jpeg_path"] or row["file_path"]
    if not target_path or not os.path.exists(target_path):
        return jsonify({"error": "File not found on disk"}), 404

    try:
        subprocess.run(["open", target_path], check=True)
        return jsonify({"success": True, "action": "opened_jpeg"})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"Launch failed: {e}"}), 500


@app.route("/api/stats", methods=["GET"])
def stats():
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        thumbs = db.execute("SELECT COUNT(*) FROM thumbnails").fetchone()[0]
        by_camera = [
            {"camera": r[0] or "unknown", "count": r[1]}
            for r in db.execute("SELECT camera_short, COUNT(*) FROM images GROUP BY camera_short ORDER BY 2 DESC")
        ]
        by_volume = [
            {"volume": r[0] or "unknown", "count": r[1]}
            for r in db.execute("SELECT volume, COUNT(*) FROM images GROUP BY volume ORDER BY 2 DESC")
        ]
        by_status = [
            {"status": r[0], "count": r[1]}
            for r in db.execute("SELECT edit_status, COUNT(*) FROM images GROUP BY edit_status ORDER BY 2 DESC")
        ]
        by_pick = [
            {"pick": r[0], "count": r[1]}
            for r in db.execute("SELECT pick, COUNT(*) FROM images GROUP BY pick ORDER BY 2 DESC")
        ]
    finally:
        db.close()

    return jsonify(
        {
            "total": total,
            "thumbnails_cached": thumbs,
            "by_camera": by_camera,
            "by_volume": by_volume,
            "by_edit_status": by_status,
            "by_pick": by_pick,
        }
    )


@app.route("/api/filters", methods=["GET"])
def filters():
    db = get_db()
    try:
        cameras = [
            r[0]
            for r in db.execute("SELECT DISTINCT camera_short FROM images WHERE camera_short IS NOT NULL ORDER BY 1")
        ]
        volumes = [r[0] for r in db.execute("SELECT DISTINCT volume FROM images WHERE volume IS NOT NULL ORDER BY 1")]
        triptych_legs = [
            r[0]
            for r in db.execute("SELECT DISTINCT triptych_leg FROM images WHERE triptych_leg IS NOT NULL ORDER BY 1")
        ]
        date_range = db.execute(
            "SELECT MIN(date_taken), MAX(date_taken) FROM images WHERE date_taken IS NOT NULL"
        ).fetchone()
    finally:
        db.close()

    return jsonify(
        {
            "cameras": cameras,
            "volumes": volumes,
            "triptych_legs": triptych_legs,
            "pick_values": sorted(PICK_VALUES),
            "edit_status_values": sorted(EDIT_STATUS_VALUES),
            "color_values": sorted(COLOR_VALUES),
            "date_min": date_range[0],
            "date_max": date_range[1],
        }
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Use gunicorn: gunicorn -w 4 -b 0.0.0.0:5001 dam_api:app")
    app.run(debug=True, port=5001)
