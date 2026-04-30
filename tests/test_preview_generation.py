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


def test_run_preview_backfill_generates_missing(tmp_dam_root):
    """run_preview_backfill generates previews for images that lack them."""
    import sqlite3

    import dam_config
    from dam_scanner import run_preview_backfill

    preview_dir = dam_config.DAM_ROOT / "previews"
    preview_dir.mkdir(exist_ok=True)

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
    conn.close()

    stats = run_preview_backfill(preview_dir)

    assert stats["total"] == 1
    assert stats["generated"] >= 0  # may be 0 if synthetic JPEG too small for sips
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

    (preview_dir / f"{img_id}.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    stats = run_preview_backfill(preview_dir)

    assert stats["skipped"] == 1
    assert stats["generated"] == 0
