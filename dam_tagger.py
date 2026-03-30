#!/opt/homebrew/bin/python3
"""
DAM Tagger — AI keywording + semantic search embeddings

Pipeline per image:
  1. Load thumbnail (never touches RAW)
  2. LLaVA 34b → documentary description
  3. dam-tagger (fine-tuned Mistral 7B) → keyword extraction in photographer's style
  4. nomic-embed-text → 768-dim embedding for semantic search
  5. Write description + keywords + embedding back to DB

Usage:
    python3 dam_tagger.py                        # tag all untagged
    python3 dam_tagger.py --sample 10            # tag 10 random images, verbose output
    python3 dam_tagger.py --limit 500            # tag up to 500
    python3 dam_tagger.py --since 2026-01-01     # only images from date onward
    python3 dam_tagger.py --camera S1IIE         # only one body
    python3 dam_tagger.py --retag                # redo already-tagged images
    python3 dam_tagger.py --search "isolation"   # semantic search demo (no tagging)

Models required (must be in Ollama):
    ollama list should show: llava:34b, dam-tagger, nomic-embed-text
"""

import base64
import json
import struct
import sys
import time
import urllib.error
import urllib.request

# Force line-buffered stdout so dam.py subprocess shows output in real time
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

from dam_config import (
    BURST_GAP_SECONDS,
    BURST_MIN_SIZE,
    EMBED_MODEL,
    MODEL_CTX,
    OLLAMA_BASE,
    OLLAMA_BASE_EMBED,
    OLLAMA_BASE_TEXT,
    OLLAMA_BASE_VISION,
    SKIP_PATH_PATTERNS,
    TEXT_MODEL,
    THUMB_DIR,
    VISION_MODEL,
)
from dam_db import get_db

# ── Prompts ────────────────────────────────────────────────────────────────────

VISION_PROMPT = """You are writing catalog entries for a documentary photography archive. Describe what is in this photograph in 2-4 short, factual sentences. Name specific subjects, objects, settings, and actions. Mention light quality only if distinctive. Do NOT start with "The photograph", "In the image", "The image captures", "This photograph" or similar. Start directly with the subject. Do NOT use phrases like "adding to the sense of", "suggesting a", "serves to highlight", "drawing the viewer's eye". Be concrete, not interpretive."""

TAGGER_PROMPT = """Description: {description}
Technical: {technical}
Context: {context}"""

TRIPTYCH_THEMES = {"care", "aging", "memory", "family", "illness", "passage of time",
                   "elderly", "hospital", "grief", "waiting", "dignity", "hands",
                   "vulnerability", "tenderness", "intimacy", "nurturing", "protection"}


# ── Ollama API ─────────────────────────────────────────────────────────────────


def ollama_post(endpoint, payload, timeout=120, base_url=None):
    """POST to Ollama API, return parsed JSON."""
    url = f"{base_url or OLLAMA_BASE}{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama unreachable at {url}: {e}") from e


def check_models():
    """Verify required models are available on their respective endpoints."""
    import urllib.request

    model_endpoints = [
        (VISION_MODEL, OLLAMA_BASE_VISION),
        (TEXT_MODEL, OLLAMA_BASE_TEXT),
        (EMBED_MODEL, OLLAMA_BASE_EMBED),
    ]
    missing = []
    for model, base in model_endpoints:
        try:
            url = f"{base}/api/tags"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            available = {m["name"] for m in data.get("models", [])}
            if not any(model in a for a in available):
                missing.append(f"{model} (on {base})")
        except Exception as e:
            missing.append(f"{model} (endpoint {base} unreachable: {e})")
    return missing


def vision_describe(image_b64):
    """Run LLaVA on a base64 image, return description string."""
    resp = ollama_post(
        "/api/generate",
        {
            "model": VISION_MODEL,
            "prompt": VISION_PROMPT,
            "images": [image_b64],
            "stream": False,
            "options": {
                "temperature": 0.3,  # Low temp = consistent, factual descriptions
                "num_predict": 150,  # Cap output length — forces concise descriptions
                "num_ctx": MODEL_CTX,
            },
        },
        timeout=180,
        base_url=OLLAMA_BASE_VISION,
    )
    return resp.get("response", "").strip()


def text_extract_keywords(description, technical="", context=""):
    """Run dam-tagger (fine-tuned Mistral 7B) on description, return keyword dict.

    The dam-tagger model outputs comma-separated keywords trained on the
    photographer's own tagging style. We parse and deduplicate the output,
    then classify keywords into factual/mood/technical categories for
    backwards compatibility with the existing DB schema.
    """
    prompt = TAGGER_PROMPT.format(
        description=description,
        technical=technical or "N/A",
        context=context or "N/A",
    )
    resp = ollama_post(
        "/api/generate",
        {
            "model": TEXT_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": 80,
            },
        },
        timeout=60,
        base_url=OLLAMA_BASE_TEXT,
    )
    raw = resp.get("response", "").strip()

    # Trim at first newline or closing paren (model sometimes leaks past keywords)
    for stop_char in ("\n", ")", "Technical", "Note"):
        idx = raw.find(stop_char)
        if idx > 0:
            raw = raw[:idx]

    # Parse comma-separated keywords, deduplicate, clean
    seen = set()
    keywords = []
    for kw in raw.split(","):
        kw = kw.strip().strip('"').strip("'").strip()
        kw_lower = kw.lower()
        if kw and len(kw) > 1 and kw_lower not in seen:
            seen.add(kw_lower)
            keywords.append(kw_lower)

    # Cap at 12 keywords
    keywords = keywords[:12]

    # Classify into categories for DB compatibility
    mood_words = {
        "serenity", "serene", "tranquil", "tranquility", "melancholy",
        "contemplation", "contemplative", "warmth", "isolation", "solitude",
        "joy", "stillness", "quietness", "nostalgia", "intimacy", "tension",
        "calm", "calmness", "peaceful", "peacefulness", "moody", "dramatic",
        "gentle", "harsh", "somber", "ethereal", "dreamlike", "gritty", "raw",
        "tender", "tenderness", "playful", "playfulness", "mysterious",
        "desolate", "vulnerability", "innocence", "happiness", "domesticity",
        "engagement", "curiosity", "protection", "nurturing", "emptiness",
        "dignity", "grief", "waiting", "seclusion", "quietude",
    }
    technical_words = {
        "shallow depth of field", "high contrast", "backlit", "motion blur",
        "long exposure", "soft lighting", "natural light", "artificial lighting",
        "high-key lighting", "low light", "macro photography", "close-up",
        "straight-on composition", "flat lighting", "diffused light",
        "soft shadows", "even lighting", "dimmed lighting",
    }

    factual = []
    mood = []
    technical = []
    for kw in keywords:
        if kw in mood_words:
            mood.append(kw)
        elif kw in technical_words:
            technical.append(kw)
        else:
            factual.append(kw)

    # Infer triptych relevance from keywords
    triptych = bool(seen & TRIPTYCH_THEMES)

    return {
        "factual": factual,
        "mood": mood,
        "technical": technical,
        "triptych_relevant": triptych,
    }


def embed_text(text):
    """Embed text via nomic-embed-text, return list of floats."""
    resp = ollama_post(
        "/api/embeddings",
        {
            "model": EMBED_MODEL,
            "prompt": text,
        },
        timeout=30,
        base_url=OLLAMA_BASE_EMBED,
    )
    return resp.get("embedding", [])


def serialize_vector(floats):
    """Pack float list to binary blob for sqlite-vec."""
    return struct.pack(f"{len(floats)}f", *floats)


# ── Burst detection ────────────────────────────────────────────────────────────


def detect_bursts(rows):
    """Detect burst sequences: same camera, consecutive images within BURST_GAP_SECONDS.

    Returns:
        representatives: list of row dicts (one per burst + all non-burst images)
        burst_map: dict mapping representative image_id -> [sibling image_ids]
        total_skipped: int count of sibling images that will be auto-tagged
    """
    if not rows:
        return [], {}, 0

    from datetime import datetime

    # Sort by camera then date for burst detection
    sorted_rows = sorted(rows, key=lambda r: (r["camera_short"] or "", r["date_taken"] or ""))

    # Group into bursts
    bursts = []  # list of lists of rows
    current = [sorted_rows[0]]

    for i in range(1, len(sorted_rows)):
        prev = sorted_rows[i - 1]
        curr = sorted_rows[i]

        same_camera = (prev["camera_short"] or "") == (curr["camera_short"] or "")
        if same_camera and prev["date_taken"] and curr["date_taken"]:
            try:
                t_prev = datetime.fromisoformat(prev["date_taken"])
                t_curr = datetime.fromisoformat(curr["date_taken"])
                gap = abs((t_curr - t_prev).total_seconds())
                if gap <= BURST_GAP_SECONDS:
                    current.append(curr)
                    continue
            except (ValueError, TypeError):
                pass

        bursts.append(current)
        current = [curr]
    bursts.append(current)

    # Build representative list and sibling map
    representatives = []
    burst_map = {}  # rep_id -> [sibling_ids]
    total_skipped = 0

    for group in bursts:
        if len(group) >= BURST_MIN_SIZE:
            # True burst: first image is representative, rest are siblings
            rep = group[0]
            representatives.append(rep)
            siblings = [r["id"] for r in group[1:]]
            burst_map[rep["id"]] = siblings
            total_skipped += len(siblings)
        else:
            # Not a burst: every image stands on its own
            representatives.extend(group)

    # Re-sort representatives by date DESC (original tag order)
    representatives.sort(key=lambda r: r["date_taken"] or "", reverse=True)

    return representatives, burst_map, total_skipped


def propagate_burst_tags(conn, rep_id, sibling_ids, description, kw_dict, embedding_blob):
    """Copy AI tags from burst representative to all siblings."""
    if not sibling_ids:
        return

    for sid in sibling_ids:
        conn.execute(
            """UPDATE images SET
                ai_description = ?,
                ai_tagged_at   = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (description, sid),
        )
        write_keywords(conn, sid, kw_dict)
        if embedding_blob:
            conn.execute(
                """INSERT OR REPLACE INTO image_embeddings (image_id, embedding)
                   VALUES (?, ?)""",
                (sid, embedding_blob),
            )


# ── Keyword writing ─────────────────────────────────────────────────────────────


def write_keywords(conn, image_id, keywords_dict):
    """Write keyword dict into keywords + image_keywords tables."""
    all_kws = keywords_dict.get("factual", []) + keywords_dict.get("mood", []) + keywords_dict.get("technical", [])
    # Deduplicate, lowercase
    all_kws = list({k.lower().strip() for k in all_kws if k and len(k) > 1})

    for kw in all_kws:
        conn.execute("INSERT OR IGNORE INTO keywords (keyword) VALUES (?)", (kw,))
        row = conn.execute("SELECT id FROM keywords WHERE keyword = ?", (kw,)).fetchone()
        if row:
            conn.execute(
                "INSERT OR IGNORE INTO image_keywords (image_id, keyword_id) VALUES (?, ?)", (image_id, row["id"])
            )


def load_ingest_manifest(path):
    """Load an ingest manifest for scoping tag runs to one batch."""
    with open(path, "r") as f:
        data = json.load(f)

    volume = data.get("volume")
    relative_paths = [p for p in data.get("relative_paths", []) if p]
    if not volume or not relative_paths:
        raise ValueError(f"Invalid ingest manifest: {path}")
    return volume, sorted(set(relative_paths))


def select_candidate_rows(conn, since=None, camera=None, retag=False, manifest_path=None, sample=None, limit=None):
    """Return candidate image rows for tagging."""
    clauses = []
    params = []

    if manifest_path:
        volume, relative_paths = load_ingest_manifest(manifest_path)
        conn.execute("DROP TABLE IF EXISTS temp_ingest_scope")
        conn.execute("CREATE TEMP TABLE temp_ingest_scope (relative_path TEXT PRIMARY KEY)")
        conn.executemany(
            "INSERT OR IGNORE INTO temp_ingest_scope (relative_path) VALUES (?)",
            [(path,) for path in relative_paths],
        )
        clauses.append("i.volume = ?")
        params.append(volume)
        clauses.append("EXISTS (SELECT 1 FROM temp_ingest_scope s WHERE s.relative_path = i.relative_path)")

    if not retag:
        clauses.append("i.ai_description IS NULL")
    if since:
        clauses.append("i.date_taken >= ?")
        params.append(since)
    if camera:
        clauses.append("i.camera_short = ?")
        params.append(camera)

    clauses.append("EXISTS (SELECT 1 FROM thumbnails t WHERE t.image_id = i.id)")

    for pattern in SKIP_PATH_PATTERNS:
        clauses.append("i.file_path NOT LIKE ?")
        params.append(f"%{pattern}%")

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    order = "ORDER BY RANDOM()" if sample else "ORDER BY i.date_taken DESC"
    lim_clause = f"LIMIT {sample or limit or 999999}"
    sql = f"""
        SELECT i.id, i.file_name, i.date_taken, i.camera_short,
               i.file_path, i.triptych_leg
        FROM images i
        {where}
        {order}
        {lim_clause}
    """
    return conn.execute(sql, params).fetchall()


# ── Main tagging loop ───────────────────────────────────────────────────────────


def tag_images(args):
    sample = None
    limit = None
    since = None
    camera = None
    manifest_path = None
    retag = False
    verbose = False
    skip_bursts = True  # Default: ON — skip burst duplicates

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--sample":
            sample = int(args[i + 1])
            i += 2
            verbose = True
        elif a == "--limit":
            limit = int(args[i + 1])
            i += 2
        elif a == "--since":
            since = args[i + 1]
            i += 2
        elif a == "--camera":
            camera = args[i + 1]
            i += 2
        elif a == "--manifest":
            manifest_path = args[i + 1]
            i += 2
        elif a == "--retag":
            retag = True
            i += 1
        elif a == "--verbose":
            verbose = True
            i += 1
        elif a == "--no-skip-bursts":
            skip_bursts = False
            i += 1
        else:
            i += 1

    # Check models
    print("Checking models...")
    missing = check_models()
    if missing:
        print(f"ERROR: Missing Ollama models: {', '.join(missing)}")
        print("Run: ollama pull <model>")
        sys.exit(1)
    print(f"  ✓ {VISION_MODEL}, {TEXT_MODEL}, {EMBED_MODEL} ready")

    # Pre-warm all models into GPU memory (avoids cold-start on first image)
    print("  Pre-warming models (keeps all 3 resident in unified memory)...")
    embed_text("warmup")  # nomic — fastest, load first
    ollama_post(
        "/api/generate",
        {
            "model": VISION_MODEL,
            "prompt": "warmup",
            "stream": False,
            "options": {"num_predict": 1, "num_ctx": MODEL_CTX},
        },
        timeout=60,
        base_url=OLLAMA_BASE_VISION,
    )
    ollama_post(
        "/api/generate",
        {"model": TEXT_MODEL, "prompt": "warmup", "stream": False, "options": {"num_predict": 1, "num_ctx": MODEL_CTX}},
        timeout=120,
        base_url=OLLAMA_BASE_TEXT,
    )
    print("  ✓ All models loaded\n")

    conn = get_db()
    rows = select_candidate_rows(
        conn,
        since=since,
        camera=camera,
        retag=retag,
        manifest_path=manifest_path,
        sample=sample,
        limit=limit,
    )
    total_raw = len(rows)

    if total_raw == 0:
        print("No images to tag. All thumbnailed images already have descriptions.")
        print("Use --retag to redo existing tags.")
        conn.close()
        return

    # Burst stacking: detect bursts and reduce to representatives
    burst_map = {}
    total_burst_siblings = 0
    if skip_bursts and not sample:
        rows, burst_map, total_burst_siblings = detect_bursts(rows)
        total = len(rows)
        burst_count = len([v for v in burst_map.values() if v])
        if total_burst_siblings > 0:
            print(f"Burst detection: {burst_count:,} bursts found")
            print(f"  Representatives to tag:  {total:,}")
            print(f"  Siblings (auto-propagate): {total_burst_siblings:,}")
            print(f"  Time saved (est): {total_burst_siblings * 28 / 3600:.1f} hours\n")
    else:
        total = total_raw

    mode = "SAMPLE" if sample else "FULL RUN"
    print(f"{'=' * 60}")
    print(f"DAM Tagger — {mode}")
    print(
        f"Images to process: {total:,}"
        + (f" (+{total_burst_siblings:,} burst siblings)" if total_burst_siblings else "")
    )
    print(f"Vision model:  {VISION_MODEL}")
    print(f"Text model:    {TEXT_MODEL}")
    print(f"Embed model:   {EMBED_MODEL}")
    print(f"{'=' * 60}\n")

    tagged = 0
    errors = 0
    start = time.time()

    for idx, row in enumerate(rows, 1):
        image_id = row["id"]
        file_name = row["file_name"]
        date_str = (row["date_taken"] or "")[:10]
        camera = row["camera_short"] or "?"

        thumb_path = THUMB_DIR / f"{image_id}.jpg"
        if not thumb_path.exists():
            print(f"  [{idx}/{total}] SKIP (no thumb): {file_name}")
            continue

        print(f"[{idx}/{total}] {file_name}  {date_str}  {camera}")

        try:
            # Step 1: encode thumbnail
            img_bytes = thumb_path.read_bytes()
            img_b64 = base64.b64encode(img_bytes).decode()

            # Step 2: LLaVA description
            t0 = time.time()
            description = vision_describe(img_b64)
            t_vision = time.time() - t0

            if verbose:
                print(f"\n  DESCRIPTION ({t_vision:.1f}s):")
                for line in description.split(". "):
                    if line.strip():
                        print(f"    {line.strip()}.")
                print()

            # Step 3: keyword extraction (dam-tagger: fine-tuned on photographer's style)
            t0 = time.time()
            kw_dict = text_extract_keywords(description)
            t_kw = time.time() - t0

            if verbose:
                print(f"  KEYWORDS ({t_kw:.1f}s):")
                print(f"    factual:   {kw_dict.get('factual', [])}")
                print(f"    mood:      {kw_dict.get('mood', [])}")
                print(f"    technical: {kw_dict.get('technical', [])}")
                print(f"    triptych:  {kw_dict.get('triptych_relevant', False)}")
                print()

            # Step 4: embedding
            t0 = time.time()
            embedding = embed_text(description)
            t_embed = time.time() - t0

            if not embedding:
                raise RuntimeError("Empty embedding returned")

            # Step 5: write to DB
            conn.execute(
                """UPDATE images SET
                    ai_description = ?,
                    ai_tagged_at   = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (description, image_id),
            )

            write_keywords(conn, image_id, kw_dict)

            # Upsert embedding
            blob = serialize_vector(embedding)
            conn.execute(
                """INSERT OR REPLACE INTO image_embeddings (image_id, embedding)
                   VALUES (?, ?)""",
                (image_id, blob),
            )

            conn.commit()
            tagged += 1

            # Propagate to burst siblings if any
            siblings = burst_map.get(image_id, [])
            if siblings:
                propagate_burst_tags(conn, image_id, siblings, description, kw_dict, blob)
                conn.commit()

            elapsed = time.time() - start
            rate = tagged / elapsed
            eta = (total - tagged) / rate if rate > 0 else 0
            sib_str = f" +{len(siblings)} siblings" if siblings else ""

            if verbose:
                print(
                    f"  ✓ Tagged in {t_vision + t_kw + t_embed:.1f}s "
                    f"(vision {t_vision:.1f}s / kw {t_kw:.1f}s / embed {t_embed:.1f}s){sib_str}\n"
                    f"  {'─' * 50}"
                )
            else:
                print(f"  ✓  {t_vision:.0f}s vision | {tagged}/{total} done | ETA {eta / 60:.0f}m{sib_str}")

        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            errors += 1
            conn.rollback()

    elapsed = time.time() - start
    total_tagged_with_siblings = tagged + sum(len(burst_map.get(r["id"], [])) for r in rows[:tagged])
    print(f"\n{'=' * 60}")
    print(f"Done: {tagged:,} tagged, {errors:,} errors in {elapsed:.1f}s")
    if total_burst_siblings > 0:
        print(f"Burst propagation: {total_tagged_with_siblings - tagged:,} siblings auto-tagged")
        print(f"Total images with AI data: {total_tagged_with_siblings:,}")
    if tagged > 0:
        print(f"Average: {elapsed / tagged:.1f}s per representative image")
    conn.close()


# ── Semantic search ─────────────────────────────────────────────────────────────


def semantic_search(query, limit=20):
    """Embed query and find nearest images by cosine similarity."""
    print(f"Semantic search: '{query}'")
    print("Embedding query...")

    embedding = embed_text(query)
    if not embedding:
        print("ERROR: Failed to get embedding for query")
        sys.exit(1)

    blob = serialize_vector(embedding)

    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT
                i.id, i.file_name, i.date_taken, i.camera_short,
                i.ai_description,
                e.distance
               FROM image_embeddings e
               JOIN images i ON i.id = e.image_id
               WHERE embedding MATCH ?
               AND k = ?
               ORDER BY e.distance
            """,
            (blob, limit),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("No results. Have you run the tagger yet?")
        return

    print(f"\nTop {len(rows)} results for '{query}':\n")
    for i, row in enumerate(rows, 1):
        dist = row["distance"]
        score = 1 - dist  # cosine: 1=identical, 0=orthogonal
        print(
            f"  {i:2}. [{score:.3f}] {row['file_name']}  {(row['date_taken'] or '')[:10]}  {row['camera_short'] or '?'}"
        )
        if row["ai_description"]:
            # First sentence only
            first = row["ai_description"].split(".")[0].strip()
            print(f"       {first[:100]}")
        print()


# ── Entry point ─────────────────────────────────────────────────────────────────

HELP = """
DAM Tagger

Commands:
  (no args)                  Tag all untagged images (newest first, bursts stacked)
  --sample N                 Tag N random images, print full verbose output
  --limit N                  Cap at N images
  --since YYYY-MM-DD         Only images from this date onward
  --camera BODY              Only images from this camera (e.g. S1IIE, Zf, XPro3)
  --manifest PATH            Only tag images from one ingest batch
  --retag                    Redo already-tagged images
  --verbose                  Print descriptions and keywords for each image
  --no-skip-bursts           Disable burst stacking (tag every image individually)
  --search "your query"      Semantic search demo (no tagging)

Burst stacking (default ON):
  Detects sequences of 3+ images from the same camera within 2s.
  Tags one representative per burst, propagates to all siblings.
"""

if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] in ("-h", "--help"):
        print(HELP)
        sys.exit(0)

    if args and args[0] == "--search":
        if len(args) < 2:
            print('Usage: dam_tagger.py --search "your query"')
            sys.exit(1)
        query = " ".join(args[1:])
        semantic_search(query)
    else:
        tag_images(args)
