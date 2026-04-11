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
    TAGGER_STATUS_FILE,
    TAGGER_WORKERS,
    TEXT_MODEL,
    THUMB_DIR,
    VISION_MODEL,
)
from dam_db import get_db, serialize_vector, wal_checkpoint

# ── Prompts ────────────────────────────────────────────────────────────────────

VISION_PROMPT = """You are writing catalog entries for a documentary photography archive. Describe what is in this photograph in 2-4 short, factual sentences. Name specific subjects, objects, settings, and actions. Mention light quality only if distinctive. Do NOT start with "The photograph", "In the image", "The image captures", "This photograph" or similar. Start directly with the subject. Do NOT use phrases like "adding to the sense of", "suggesting a", "serves to highlight", "drawing the viewer's eye". Be concrete, not interpretive."""

TAGGER_PROMPT = """Description: {description}
Technical: {technical}
Context: {context}"""

TRIPTYCH_THEMES = {"care", "aging", "memory", "family", "illness", "passage of time",
                   "elderly", "hospital", "grief", "waiting", "dignity", "hands",
                   "vulnerability", "tenderness", "intimacy", "nurturing", "protection"}


# ── Ollama API ─────────────────────────────────────────────────────────────────


def ollama_post(endpoint, payload, timeout=120, base_url=None, max_retries=3):
    """POST to Ollama API with retry, return parsed JSON."""
    url = f"{base_url or OLLAMA_BASE}{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.URLError as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  Ollama retry {attempt + 1}/{max_retries} in {wait}s: {e}")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Ollama unreachable at {url} after {max_retries} attempts: {e}") from e


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


_MOOD_WORDS = {
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
_TECHNICAL_WORDS = {
    "shallow depth of field", "high contrast", "backlit", "motion blur",
    "long exposure", "soft lighting", "natural light", "artificial lighting",
    "high-key lighting", "low light", "macro photography", "close-up",
    "straight-on composition", "flat lighting", "diffused light",
    "soft shadows", "even lighting", "dimmed lighting",
}


def _parse_raw_keywords(raw):
    """Parse comma-separated model output into deduplicated keyword list (max 12)."""
    for stop_char in ("\n", ")", "Technical", "Note"):
        idx = raw.find(stop_char)
        if idx > 0:
            raw = raw[:idx]

    seen = set()
    keywords = []
    for kw in raw.split(","):
        kw = kw.strip().strip('"').strip("'").strip().lower()
        if kw and len(kw) > 1 and kw not in seen:
            seen.add(kw)
            keywords.append(kw)
    return keywords[:12], seen


def text_extract_keywords(description, technical="", context=""):
    """Run dam-tagger (fine-tuned Mistral 7B) on description, return keyword dict."""
    prompt = TAGGER_PROMPT.format(
        description=description,
        technical=technical or "N/A",
        context=context or "N/A",
    )
    resp = ollama_post(
        "/api/generate",
        {"model": TEXT_MODEL, "prompt": prompt, "stream": False, "options": {"num_predict": 80}},
        timeout=60,
        base_url=OLLAMA_BASE_TEXT,
    )

    keywords, seen = _parse_raw_keywords(resp.get("response", "").strip())

    factual = [kw for kw in keywords if kw not in _MOOD_WORDS and kw not in _TECHNICAL_WORDS]
    mood = [kw for kw in keywords if kw in _MOOD_WORDS]
    technical_kws = [kw for kw in keywords if kw in _TECHNICAL_WORDS]

    return {
        "factual": factual,
        "mood": mood,
        "technical": technical_kws,
        "triptych_relevant": bool(seen & TRIPTYCH_THEMES),
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




# ── Burst detection ────────────────────────────────────────────────────────────


def _is_burst_continuation(prev, curr):
    """Return True if curr continues a burst sequence from prev."""
    from datetime import datetime

    if (prev["camera_short"] or "") != (curr["camera_short"] or ""):
        return False
    if not prev["date_taken"] or not curr["date_taken"]:
        return False
    try:
        t_prev = datetime.fromisoformat(prev["date_taken"])
        t_curr = datetime.fromisoformat(curr["date_taken"])
        return abs((t_curr - t_prev).total_seconds()) <= BURST_GAP_SECONDS
    except (ValueError, TypeError):
        return False


def detect_bursts(rows):
    """Detect burst sequences: same camera, consecutive images within BURST_GAP_SECONDS.

    Returns:
        representatives: list of row dicts (one per burst + all non-burst images)
        burst_map: dict mapping representative image_id -> [sibling image_ids]
        total_skipped: int count of sibling images that will be auto-tagged
    """
    if not rows:
        return [], {}, 0

    sorted_rows = sorted(rows, key=lambda r: (r["camera_short"] or "", r["date_taken"] or ""))

    # Group consecutive rows into burst groups
    bursts = [[sorted_rows[0]]]
    for i in range(1, len(sorted_rows)):
        if _is_burst_continuation(sorted_rows[i - 1], sorted_rows[i]):
            bursts[-1].append(sorted_rows[i])
        else:
            bursts.append([sorted_rows[i]])

    representatives = []
    burst_map = {}
    total_skipped = 0

    for group in bursts:
        if len(group) >= BURST_MIN_SIZE:
            representatives.append(group[0])
            burst_map[group[0]["id"]] = [r["id"] for r in group[1:]]
            total_skipped += len(group) - 1
        else:
            representatives.extend(group)

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


def _write_tagger_status(status, current=0, total=0, current_path=None, current_id=None, last_keywords=None):
    """Write tagger progress to tagger_status.json (non-fatal on error)."""
    from datetime import datetime
    import dam_config as _dc
    try:
        with open(_dc.TAGGER_STATUS_FILE, "w") as f:
            json.dump(
                {
                    "status": status,
                    "current": current,
                    "total": total,
                    "current_path": current_path,
                    "current_id": current_id,
                    "last_keywords": last_keywords or [],
                    "timestamp": datetime.now().isoformat(),
                },
                f,
            )
    except OSError:
        pass


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
               i.file_path, i.triptych_leg, i.relative_path
        FROM images i
        {where}
        {order}
        {lim_clause}
    """
    return conn.execute(sql, params).fetchall()


# ── Main tagging loop ───────────────────────────────────────────────────────────


def _parse_tagger_args(args):
    """Parse tagger CLI arguments into a dict."""
    opts = {"sample": None, "limit": None, "since": None, "camera": None,
            "manifest_path": None, "retag": False, "verbose": False, "skip_bursts": True,
            "workers": TAGGER_WORKERS}
    valued_flags = {"--sample": "sample", "--limit": "limit", "--since": "since",
                    "--camera": "camera", "--manifest": "manifest_path", "--workers": "workers"}
    int_flags = {"sample", "limit", "workers"}
    i = 0
    while i < len(args):
        flag = valued_flags.get(args[i])
        if flag and i + 1 < len(args):
            opts[flag] = int(args[i + 1]) if flag in int_flags else args[i + 1]
            if flag == "sample":
                opts["verbose"] = True
            i += 2
        elif args[i] == "--retag":
            opts["retag"] = True
            i += 1
        elif args[i] == "--verbose":
            opts["verbose"] = True
            i += 1
        elif args[i] == "--no-skip-bursts":
            opts["skip_bursts"] = False
            i += 1
        else:
            i += 1
    return opts


def _warm_models():
    """Verify and pre-warm all required Ollama models."""
    print("Checking models...")
    missing = check_models()
    if missing:
        print(f"ERROR: Missing Ollama models: {', '.join(missing)}")
        print("Run: ollama pull <model>")
        sys.exit(1)
    print(f"  ✓ {VISION_MODEL}, {TEXT_MODEL}, {EMBED_MODEL} ready")

    print("  Pre-warming models (keeps all 3 resident in unified memory)...")
    embed_text("warmup")
    ollama_post(
        "/api/generate",
        {"model": VISION_MODEL, "prompt": "warmup", "stream": False, "options": {"num_predict": 1, "num_ctx": MODEL_CTX}},
        timeout=60, base_url=OLLAMA_BASE_VISION,
    )
    ollama_post(
        "/api/generate",
        {"model": TEXT_MODEL, "prompt": "warmup", "stream": False, "options": {"num_predict": 1, "num_ctx": MODEL_CTX}},
        timeout=120, base_url=OLLAMA_BASE_TEXT,
    )
    print("  ✓ All models loaded\n")


def _ai_pipeline(image_id, thumb_path):
    """Run vision + keywords + embed for one image. Thread-safe (no DB writes, no printing)."""
    img_b64 = base64.b64encode(thumb_path.read_bytes()).decode()

    t0 = time.time()
    description = vision_describe(img_b64)
    t_vision = time.time() - t0

    t0 = time.time()
    kw_dict = text_extract_keywords(description)
    t_kw = time.time() - t0

    t0 = time.time()
    embedding = embed_text(description)
    t_embed = time.time() - t0

    if not embedding:
        raise RuntimeError("Empty embedding returned")

    blob = serialize_vector(embedding)
    return description, kw_dict, blob, t_vision, t_kw, t_embed


def _write_tag_results(conn, image_id, description, kw_dict, blob):
    """Write AI tagging results to database."""
    conn.execute(
        "UPDATE images SET ai_description = ?, ai_tagged_at = CURRENT_TIMESTAMP WHERE id = ?",
        (description, image_id),
    )
    write_keywords(conn, image_id, kw_dict)
    conn.execute(
        "INSERT OR REPLACE INTO image_embeddings (image_id, embedding) VALUES (?, ?)",
        (image_id, blob),
    )
    conn.commit()


def _tag_single_image(conn, image_id, thumb_path, verbose):
    """Run full AI pipeline with DB writes and optional verbose output. Sequential mode only."""
    description, kw_dict, blob, t_vision, t_kw, t_embed = _ai_pipeline(image_id, thumb_path)

    if verbose:
        print(f"\n  DESCRIPTION ({t_vision:.1f}s):")
        for line in description.split(". "):
            if line.strip():
                print(f"    {line.strip()}.")
        print()
        print(f"  KEYWORDS ({t_kw:.1f}s):")
        print(f"    factual:   {kw_dict.get('factual', [])}")
        print(f"    mood:      {kw_dict.get('mood', [])}")
        print(f"    technical: {kw_dict.get('technical', [])}")
        print(f"    triptych:  {kw_dict.get('triptych_relevant', False)}")
        print()

    _write_tag_results(conn, image_id, description, kw_dict, blob)
    return description, kw_dict, blob, t_vision, t_kw, t_embed


def _prepare_candidates(opts):
    """Select candidate rows and apply burst detection. Returns (conn, rows, burst_map, total_siblings) or None."""
    conn = get_db()
    rows = select_candidate_rows(
        conn,
        since=opts["since"], camera=opts["camera"], retag=opts["retag"],
        manifest_path=opts["manifest_path"], sample=opts["sample"], limit=opts["limit"],
    )

    if not rows:
        print("No images to tag. All thumbnailed images already have descriptions.")
        print("Use --retag to redo existing tags.")
        conn.close()
        return None

    burst_map = {}
    total_siblings = 0
    if opts["skip_bursts"] and not opts["sample"]:
        rows, burst_map, total_siblings = detect_bursts(rows)
        if total_siblings > 0:
            burst_count = sum(1 for v in burst_map.values() if v)
            print(f"Burst detection: {burst_count:,} bursts found")
            print(f"  Representatives to tag:  {len(rows):,}")
            print(f"  Siblings (auto-propagate): {total_siblings:,}")
            print(f"  Time saved (est): {total_siblings * 28 / 3600:.1f} hours\n")

    return conn, rows, burst_map, total_siblings


def _tag_loop_sequential(conn, rows, burst_map, total, verbose):
    """Sequential tagging loop. Supports verbose output."""
    tagged = 0
    errors = 0
    start = time.time()

    for idx, row in enumerate(rows, 1):
        thumb_path = THUMB_DIR / f"{row['id']}.jpg"
        if not thumb_path.exists():
            print(f"  [{idx}/{total}] SKIP (no thumb): {row['file_name']}")
            continue

        print(f"[{idx}/{total}] {row['file_name']}  {(row['date_taken'] or '')[:10]}  {row['camera_short'] or '?'}")

        try:
            description, kw_dict, blob, t_vision, t_kw, t_embed = _tag_single_image(conn, row["id"], thumb_path, verbose)
            tagged += 1
            all_kws = (
                kw_dict.get("factual", []) + kw_dict.get("mood", []) + kw_dict.get("technical", [])
            )
            _write_tagger_status(
                "tagging",
                current=tagged,
                total=total,
                current_path=row["relative_path"],
                current_id=row["id"],
                last_keywords=all_kws[:6],
            )

            siblings = burst_map.get(row["id"], [])
            if siblings:
                propagate_burst_tags(conn, row["id"], siblings, description, kw_dict, blob)
                conn.commit()

            elapsed = time.time() - start
            rate = tagged / elapsed
            eta = (total - tagged) / rate if rate > 0 else 0
            sib_str = f" +{len(siblings)} siblings" if siblings else ""

            if verbose:
                print(f"  ✓ Tagged in {t_vision + t_kw + t_embed:.1f}s "
                      f"(vision {t_vision:.1f}s / kw {t_kw:.1f}s / embed {t_embed:.1f}s){sib_str}\n"
                      f"  {'─' * 50}")
            else:
                print(f"  ✓  {t_vision:.0f}s vision | {tagged}/{total} done | ETA {eta / 60:.0f}m{sib_str}")

        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            errors += 1
            conn.rollback()

    return tagged, errors


def _tag_loop_parallel(conn, rows, burst_map, total, workers):
    """Parallel tagging loop. Runs AI pipeline in thread pool, DB writes in main thread."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    tagged = 0
    errors = 0
    start = time.time()

    # Pre-filter rows with thumbnails
    work = []
    for idx, row in enumerate(rows, 1):
        thumb_path = THUMB_DIR / f"{row['id']}.jpg"
        if not thumb_path.exists():
            print(f"  [{idx}/{total}] SKIP (no thumb): {row['file_name']}")
            continue
        work.append((idx, row, thumb_path))

    print(f"  Parallel mode: {workers} workers, {len(work)} images queued\n")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_ai_pipeline, row["id"], thumb_path): (idx, row)
            for idx, row, thumb_path in work
        }

        for future in as_completed(futures):
            idx, row = futures[future]
            image_id = row["id"]

            try:
                description, kw_dict, blob, t_vision, t_kw, t_embed = future.result()

                _write_tag_results(conn, image_id, description, kw_dict, blob)
                tagged += 1
                all_kws = (
                    kw_dict.get("factual", []) + kw_dict.get("mood", []) + kw_dict.get("technical", [])
                )
                _write_tagger_status(
                    "tagging",
                    current=tagged,
                    total=len(work),
                    current_path=row["relative_path"],
                    current_id=image_id,
                    last_keywords=all_kws[:6],
                )

                siblings = burst_map.get(image_id, [])
                if siblings:
                    propagate_burst_tags(conn, image_id, siblings, description, kw_dict, blob)
                    conn.commit()

                elapsed = time.time() - start
                rate = tagged / elapsed
                eta = (total - tagged) / rate if rate > 0 else 0
                sib_str = f" +{len(siblings)} siblings" if siblings else ""

                print(f"  ✓ [{idx}/{total}] {row['file_name']}  {t_vision:.0f}s vision | "
                      f"{tagged}/{total} done | {rate:.1f}/s | ETA {eta / 60:.0f}m{sib_str}")

            except Exception as e:
                print(f"  ✗ [{idx}/{total}] {row['file_name']} ERROR: {e}")
                errors += 1

    return tagged, errors


def _tag_loop(conn, rows, burst_map, verbose, workers=1):
    """Run the tagging loop. Dispatches to sequential or parallel based on workers."""
    total = len(rows)
    if workers > 1 and not verbose:
        return _tag_loop_parallel(conn, rows, burst_map, total, workers)
    if verbose and workers > 1:
        print(f"  Note: verbose mode forces sequential execution (ignoring --workers {workers})")
    return _tag_loop_sequential(conn, rows, burst_map, total, verbose)


def tag_images(args):
    opts = _parse_tagger_args(args)
    _warm_models()

    result = _prepare_candidates(opts)
    if result is None:
        return
    conn, rows, burst_map, total_siblings = result

    total = len(rows)
    _write_tagger_status("tagging", current=0, total=total)
    mode = "SAMPLE" if opts["sample"] else "FULL RUN"
    print(f"{'=' * 60}")
    print(f"DAM Tagger — {mode}")
    print(f"Images to process: {total:,}" + (f" (+{total_siblings:,} burst siblings)" if total_siblings else ""))
    print(f"Vision model:  {VISION_MODEL}")
    print(f"Text model:    {TEXT_MODEL}")
    print(f"Embed model:   {EMBED_MODEL}")
    workers = opts["workers"]
    print(f"Workers:       {workers}" + (" (parallel)" if workers > 1 and not opts["verbose"] else " (sequential)"))
    print(f"{'=' * 60}\n")

    start = time.time()
    try:
        tagged, errors = _tag_loop(conn, rows, burst_map, opts["verbose"], workers=opts["workers"])
    except Exception:
        _write_tagger_status("error", current=0, total=total)
        raise
    elapsed = time.time() - start

    total_with_siblings = tagged + sum(len(burst_map.get(r["id"], [])) for r in rows[:tagged])
    print(f"\n{'=' * 60}")
    print(f"Done: {tagged:,} tagged, {errors:,} errors in {elapsed:.1f}s")
    if total_siblings > 0:
        print(f"Burst propagation: {total_with_siblings - tagged:,} siblings auto-tagged")
        print(f"Total images with AI data: {total_with_siblings:,}")
    if tagged > 0:
        print(f"Average: {elapsed / tagged:.1f}s per representative image")
    conn.close()
    wal_checkpoint()  # Truncate WAL after bulk writes
    _write_tagger_status("done", current=tagged, total=total)


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
  --verbose                  Print descriptions and keywords for each image (forces sequential)
  --workers N                Concurrent AI pipelines (default: from config, typically 6)
  --no-skip-bursts           Disable burst stacking (tag every image individually)
  --search "your query"      Semantic search demo (no tagging)

Parallel mode (default ON when workers > 1):
  Runs N images through the AI pipeline simultaneously using ThreadPoolExecutor.
  Set OLLAMA_NUM_PARALLEL on your Ollama instance to match for true GPU parallelism.
  Verbose mode forces sequential execution.
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
