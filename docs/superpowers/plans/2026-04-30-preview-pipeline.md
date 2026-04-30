# Preview Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and serve 2048px lightbox previews so culling decisions aren't made on 300px thumbnails.

**Architecture:** A shared `generate_preview()` function in `dam_scanner.py` handles extraction + resize. Three call sites use it: the existing on-demand API endpoint, a new `dam previews` CLI backfill command, and the ingest pipeline's post-thumbnail pass. The filesystem is the cache — no schema changes.

**Tech Stack:** exiftool (RAW extraction), sips (resize), ThreadPoolExecutor (parallelism), tqdm (progress), Flask (on-demand endpoint).

**Spec:** `docs/superpowers/specs/2026-04-30-preview-pipeline-design.md`

---

### Task 1: Shared `generate_preview()` function

**Files:**
- Modify: `dam_scanner.py` (add function after `extract_thumbnail_file_only`)
- Create: `tests/test_preview_generation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_preview_generation.py`:

```python
"""Tests for preview generation pipeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_generate_preview_from_jpeg(tmp_dam_root):
    """generate_preview copies a JPEG and resizes to max_dim."""
    import dam_config
    from dam_scanner import generate_preview

    preview_dir = dam_config.DAM_ROOT / "previews"
    preview_dir.mkdir(exist_ok=True)

    # Create a JPEG large enough to pass _is_usable_jpeg (≥32 bytes, valid header)
    src = tmp_dam_root / "test.jpg"
    src.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\x00" * 20  # pad to >32 bytes
        + b"\xff\xd9"
    )

    result = generate_preview(
        image_id=42,
        file_path=str(src),
        preview_dir=preview_dir,
        max_dim=2048,
    )

    assert result is not None
    assert result == preview_dir / "42.jpg"
    assert result.exists()


def test_generate_preview_skips_existing(tmp_dam_root):
    """generate_preview returns immediately if a valid preview already exists."""
    import dam_config
    from dam_scanner import generate_preview

    preview_dir = dam_config.DAM_ROOT / "previews"
    preview_dir.mkdir(exist_ok=True)

    # Pre-create a valid cached preview
    cached = preview_dir / "99.jpg"
    cached.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    result = generate_preview(
        image_id=99,
        file_path="/nonexistent/file.jpg",
        preview_dir=preview_dir,
        max_dim=2048,
    )

    assert result == cached


def test_generate_preview_returns_none_for_missing_source(tmp_dam_root):
    """generate_preview returns None when source file doesn't exist."""
    import dam_config
    from dam_scanner import generate_preview

    preview_dir = dam_config.DAM_ROOT / "previews"
    preview_dir.mkdir(exist_ok=True)

    result = generate_preview(
        image_id=1,
        file_path="/nonexistent/file.raf",
        preview_dir=preview_dir,
        max_dim=2048,
    )

    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_preview_generation.py -v`
Expected: FAIL with `ImportError: cannot import name 'generate_preview' from 'dam_scanner'`

- [ ] **Step 3: Write the `generate_preview` function**

Add to `dam_scanner.py` after the `extract_thumbnail_file_only` function (after line 581):

```python
PREVIEW_MAX_DIM = 2048


def _is_usable_jpeg(path: Path) -> bool:
    """Check file is a valid JPEG (header check + minimum size)."""
    try:
        if path.stat().st_size < 32:
            return False
        with path.open("rb") as fh:
            return fh.read(3) == b"\xff\xd8\xff"
    except OSError:
        return False


def generate_preview(image_id, file_path, preview_dir, max_dim=PREVIEW_MAX_DIM):
    """Generate a resized preview JPEG for a single image.

    Returns Path to the preview file on success, None on failure.
    Safe to call from threads — no DB writes.
    """
    preview_path = preview_dir / f"{image_id}.jpg"

    # Already cached and valid
    if _is_usable_jpeg(preview_path):
        return preview_path

    fpath = Path(file_path)
    if not fpath.exists():
        return None

    try:
        ext = fpath.suffix.lower()
        if ext in RAW_EXTENSIONS:
            for tag in ["-JpgFromRaw", "-PreviewImage"]:
                result = subprocess.run(
                    ["exiftool", "-b", tag, str(fpath)],
                    capture_output=True,
                    timeout=15,
                )
                if result.stdout and len(result.stdout) > 1000:
                    preview_path.write_bytes(result.stdout)
                    _resize_thumbnail(preview_path, max_dim)
                    if _is_usable_jpeg(preview_path):
                        return preview_path
        elif ext in JPEG_EXTENSIONS:
            shutil.copy2(str(fpath), str(preview_path))
            _resize_thumbnail(preview_path, max_dim)
            if _is_usable_jpeg(preview_path):
                return preview_path
    except Exception:
        pass

    # Clean up failed attempt
    if preview_path.exists():
        with contextlib.suppress(OSError):
            preview_path.unlink()
    return None
```

Also add `import contextlib` at the top of `dam_scanner.py` if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_preview_generation.py -v`
Expected: 3 passed

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All tests pass (134+3 = 137)

- [ ] **Step 6: Commit**

```bash
git add dam_scanner.py tests/test_preview_generation.py
git commit -m "feat: add shared generate_preview() function for 2048px lightbox previews"
```

---

### Task 2: Rewire the on-demand API endpoint to use `generate_preview()`

**Files:**
- Modify: `dam_api.py` (preview endpoint, lines 320-375)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api.py` after `test_preview_invalid_cache_falls_back_to_thumbnail`:

```python
def test_preview_serves_cached_valid_jpeg(tmp_dam_root, app_client):
    """GET /api/previews/<id>.jpg serves a cached preview directly."""
    img_id = _insert_test_image(tmp_dam_root)
    import dam_api

    dam_api.PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    preview = dam_api.PREVIEW_DIR / f"{img_id}.jpg"
    # Valid JPEG with enough content
    preview.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    resp = app_client.get(f"/api/previews/{img_id}.jpg")

    assert resp.status_code == 200
    assert resp.data[:3] == b"\xff\xd8\xff"
```

- [ ] **Step 2: Run test to verify it passes (sanity check — this path already works)**

Run: `python3 -m pytest tests/test_api.py::test_preview_serves_cached_valid_jpeg -v`
Expected: PASS (cached path already works)

- [ ] **Step 3: Refactor the preview endpoint to use `generate_preview()`**

Replace the `preview()` function in `dam_api.py` with:

```python
from dam_scanner import generate_preview, PREVIEW_MAX_DIM

PREVIEW_DIR = THUMB_DIR.parent / "previews"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)


def _is_usable_jpeg(path: Path) -> bool:
    """Cheaply reject empty or corrupt cached previews before serving them."""
    try:
        if path.stat().st_size < 32:
            return False
        with path.open("rb") as fh:
            return fh.read(3) == b"\xff\xd8\xff"
    except OSError:
        return False


@app.route("/api/previews/<int:image_id>.jpg")
def preview(image_id):
    """Serve a 2048px preview, generating on-demand if needed.

    Falls back to the grid thumbnail when generation fails or the source
    file is unavailable.
    """
    preview_path = PREVIEW_DIR / f"{image_id}.jpg"

    if _is_usable_jpeg(preview_path):
        return send_file(str(preview_path), mimetype="image/jpeg")

    try:
        db = _db()
        row = db.execute(
            "SELECT file_path, volume, relative_path FROM images WHERE id = ?",
            (image_id,),
        ).fetchone()
        if not row:
            abort(404)

        resolved = resolve_archive_file(
            row["file_path"], row["volume"], row["relative_path"],
            DEFAULT_VOLUMES, IGNORE_VOLUMES, VOLUME_ALIASES,
        )
        if resolved is not None:
            result = generate_preview(image_id, str(resolved), PREVIEW_DIR)
            if result is not None:
                return send_file(str(result), mimetype="image/jpeg")
    except Exception:
        pass

    # Final fallback: serve thumb
    thumb_path = THUMB_DIR / f"{image_id}.jpg"
    if thumb_path.exists():
        return send_file(str(thumb_path), mimetype="image/jpeg")
    abort(404)
```

Remove the old `_PREVIEW_MAX_DIM = 1600` constant — it's now `PREVIEW_MAX_DIM = 2048` in `dam_scanner.py`.

- [ ] **Step 4: Run API tests**

Run: `python3 -m pytest tests/test_api.py -v`
Expected: All pass (44 tests)

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add dam_api.py tests/test_api.py
git commit -m "refactor: rewire preview endpoint to use shared generate_preview(), bump to 2048px"
```

---

### Task 3: `dam previews` backfill CLI command

**Files:**
- Modify: `dam_scanner.py` (add `run_preview_backfill` function)
- Modify: `dam.py` (add `previews` command)
- Create: `tests/test_preview_generation.py` (add backfill tests)

- [ ] **Step 1: Write the failing test for backfill**

Add to `tests/test_preview_generation.py`:

```python
def test_run_preview_backfill_generates_missing(tmp_dam_root):
    """run_preview_backfill generates previews for images that lack them."""
    import sqlite3

    import dam_config
    from dam_scanner import run_preview_backfill

    preview_dir = dam_config.DAM_ROOT / "previews"
    preview_dir.mkdir(exist_ok=True)

    # Insert a test image with a JPEG source (≥32 bytes for _is_usable_jpeg)
    src = tmp_dam_root / "test.jpg"
    src.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\x00" * 20
        + b"\xff\xd9"
    )

    conn = sqlite3.connect(str(dam_config.DB_PATH))
    conn.execute(
        "INSERT INTO images (file_path, file_name, file_type, rating, pick, edit_status) "
        "VALUES (?, 'test.jpg', 'JPG', 0, 'unmarked', 'unculled')",
        (str(src),),
    )
    conn.commit()
    img_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    stats = run_preview_backfill(preview_dir)

    assert stats["total"] == 1
    assert stats["generated"] >= 0  # May be 0 if JPEG is too small for sips
    assert stats["skipped"] == 0


def test_run_preview_backfill_skips_existing(tmp_dam_root):
    """run_preview_backfill skips images that already have a valid preview."""
    import sqlite3

    import dam_config
    from dam_scanner import run_preview_backfill

    preview_dir = dam_config.DAM_ROOT / "previews"
    preview_dir.mkdir(exist_ok=True)

    conn = sqlite3.connect(str(dam_config.DB_PATH))
    conn.execute(
        "INSERT INTO images (file_path, file_name, file_type, rating, pick, edit_status) "
        "VALUES ('/test/img.jpg', 'img.jpg', 'JPG', 0, 'unmarked', 'unculled')"
    )
    conn.commit()
    img_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    # Pre-create valid cached preview
    (preview_dir / f"{img_id}.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    stats = run_preview_backfill(preview_dir)

    assert stats["skipped"] == 1
    assert stats["generated"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_preview_generation.py::test_run_preview_backfill_generates_missing tests/test_preview_generation.py::test_run_preview_backfill_skips_existing -v`
Expected: FAIL with `ImportError: cannot import name 'run_preview_backfill'`

- [ ] **Step 3: Write `run_preview_backfill` function**

Add to `dam_scanner.py` after `generate_preview`:

```python
def run_preview_backfill(preview_dir, max_dim=PREVIEW_MAX_DIM):
    """Generate 2048px previews for all images missing one.

    Returns dict with stats: total, generated, skipped, failed, elapsed.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    conn = init_db()
    rows = conn.execute(
        "SELECT id, file_path, volume, relative_path FROM images"
    ).fetchall()
    conn.close()

    preview_dir.mkdir(parents=True, exist_ok=True)

    # Partition into needs-generation vs already-cached
    to_generate = []
    skipped = 0
    for row in rows:
        preview_path = preview_dir / f"{row['id']}.jpg"
        if _is_usable_jpeg(preview_path):
            skipped += 1
            continue
        resolved = resolve_archive_file(
            row["file_path"], row["volume"], row["relative_path"],
            DEFAULT_VOLUMES, IGNORE_VOLUMES, VOLUME_ALIASES,
        )
        if resolved is None:
            continue  # Volume not mounted — skip silently
        to_generate.append((row["id"], str(resolved)))

    total = len(to_generate)
    if total == 0:
        print(f"  All previews up to date ({skipped:,} cached).")
        return {"total": len(rows), "generated": 0, "skipped": skipped, "failed": 0, "elapsed": 0.0}

    print(f"\nGenerating {total:,} previews ({skipped:,} cached, {THUMB_WORKERS} workers)...")
    start = time.time()
    generated = 0
    failed = 0

    try:
        from tqdm import tqdm
        progress = tqdm(total=total, unit="img", desc="Previews")
    except ImportError:
        progress = None

    with ThreadPoolExecutor(max_workers=THUMB_WORKERS) as executor:
        futures = {
            executor.submit(generate_preview, img_id, fpath, preview_dir, max_dim): img_id
            for img_id, fpath in to_generate
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    generated += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
            if progress:
                progress.update(1)

    if progress:
        progress.close()

    elapsed = time.time() - start
    print(f"  Done: {generated:,} generated, {failed:,} failed in {elapsed:.1f}s")
    return {"total": len(rows), "generated": generated, "skipped": skipped, "failed": failed, "elapsed": elapsed}
```

- [ ] **Step 4: Run the backfill tests**

Run: `python3 -m pytest tests/test_preview_generation.py -v`
Expected: All pass (5 tests)

- [ ] **Step 5: Add `dam previews` CLI command**

Add to `dam.py` after `cmd_thumbs`:

```python
def cmd_previews(_args):
    from dam_scanner import run_preview_backfill
    preview_dir = DAM_ROOT / "previews"
    sys.exit(0 if run_preview_backfill(preview_dir)["failed"] == 0 else 1)
```

Add to the `COMMANDS` dict:

```python
"previews": cmd_previews,
```

Add to `HELP` string:

```
  previews                             Generate missing 2048px lightbox previews
```

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add dam_scanner.py dam.py tests/test_preview_generation.py
git commit -m "feat: add dam previews backfill command (2048px lightbox previews, 8 workers)"
```

---

### Task 4: Integrate preview generation into ingest pipeline

**Files:**
- Modify: `ingest_pipeline.py` (add previews step after thumbs)
- Modify: `tests/test_ingest_pipeline.py` (add preview step verification)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ingest_pipeline.py`:

```python
def test_ingest_pipeline_generates_previews_after_thumbs(tmp_dam_root, monkeypatch):
    """Ingest pipeline runs preview generation after thumbnails."""
    import ingest_pipeline

    steps_run = []

    def fake_run(cmd, **kwargs):
        steps_run.append(cmd[1] if len(cmd) > 1 else cmd[0])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    # Also mock the preview backfill to track that it's called
    preview_called = []

    def fake_backfill(preview_dir, **kwargs):
        preview_called.append(str(preview_dir))
        return {"total": 0, "generated": 0, "skipped": 0, "failed": 0, "elapsed": 0.0}

    monkeypatch.setattr(ingest_pipeline, "run_preview_backfill", fake_backfill)

    result = ingest_pipeline.run_ingest_pipeline(
        capture_output=True, no_tag=True, announce=None,
    )

    assert result.returncode == 0
    assert len(preview_called) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_ingest_pipeline.py::test_ingest_pipeline_generates_previews_after_thumbs -v`
Expected: FAIL (preview backfill not called yet)

- [ ] **Step 3: Add preview step to ingest pipeline**

In `ingest_pipeline.py`, add the import at the top:

```python
from dam_scanner import run_preview_backfill
```

After the thumbnail step (after line 171, before the `if no_tag:` check), add:

```python
    # Step 3b: Generate 2048px lightbox previews for new images
    if announce:
        announce("\nDAM ── Generating lightbox previews\n" + "-" * 50)
    preview_dir = DAM_ROOT / "previews"
    run_preview_backfill(preview_dir)
```

Also update step numbering: the tagger becomes step 5/5, and update the step labels to reflect 5 steps total:
- Step 1/5 — Card Ingest
- Step 2/5 — Scanning New Files
- Step 3/5 — Generating Thumbnails
- Step 4/5 — Generating Lightbox Previews
- Step 5/5 — AI Tagging (background)

- [ ] **Step 4: Run the pipeline tests**

Run: `python3 -m pytest tests/test_ingest_pipeline.py -v`
Expected: All pass

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add ingest_pipeline.py tests/test_ingest_pipeline.py
git commit -m "feat: add preview generation step to ingest pipeline (step 4/5)"
```

---

### Task 5: Clean up old `_PREVIEW_MAX_DIM` and remove duplicated logic from `dam_api.py`

**Files:**
- Modify: `dam_api.py` (remove old constants/helpers now in dam_scanner)

- [ ] **Step 1: Verify no references to old `_PREVIEW_MAX_DIM`**

Run: `grep -rn '_PREVIEW_MAX_DIM\|1600' dam_api.py`
Ensure the old 1600px constant is gone and replaced by the import from `dam_scanner`.

- [ ] **Step 2: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 3: Rebuild frontend** (no code changes, just ensuring build is fresh with 2048px)

Run: `cd frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add dam_api.py static/
git commit -m "chore: remove duplicated preview constants, rebuild frontend"
```

---

### Task 6: End-to-end verification

- [ ] **Step 1: Run full test suite one final time**

Run: `python3 -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 2: Run backfill on a small sample (manual check)**

Run: `python3 dam.py previews`
Expected: Generates previews for images missing them, shows progress + summary.

- [ ] **Step 3: Start app shell and verify lightbox**

Run: `python3 dam.py serve --window`
Expected: Lightbox shows 2048px previews (sharp enough for cull decisions).

- [ ] **Step 4: Final commit if any cleanup needed**

Only if manual testing reveals issues.
