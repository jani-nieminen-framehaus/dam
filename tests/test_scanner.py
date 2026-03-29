"""Tests for dam_scanner module — pure functions only (no DB, no exiftool)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dam_scanner import (
    build_row,
    compute_season,
    compute_time_of_day,
    format_shutter_speed,
    file_identity,
    get_camera_short,
    get_mount,
    parse_date_folder,
    parse_volume,
    upsert_image,
)

# ── compute_time_of_day ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "hour,expected",
    [
        (5, "dawn"),
        (6, "dawn"),
        (7, "morning"),
        (10, "morning"),
        (11, "midday"),
        (13, "midday"),
        (14, "afternoon"),
        (16, "afternoon"),
        (17, "golden"),
        (18, "golden"),
        (19, "evening"),
        (21, "evening"),
        (22, "night"),
        (2, "night"),
        (0, "night"),
        (None, None),
    ],
)
def test_compute_time_of_day(hour, expected):
    assert compute_time_of_day(hour) == expected


# ── compute_season ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "month,expected",
    [
        (1, "winter"),
        (2, "winter"),
        (12, "winter"),
        (3, "spring"),
        (4, "spring"),
        (5, "spring"),
        (6, "summer"),
        (7, "summer"),
        (8, "summer"),
        (9, "autumn"),
        (10, "autumn"),
        (11, "autumn"),
        (None, None),
    ],
)
def test_compute_season(month, expected):
    assert compute_season(month) == expected


# ── parse_volume ──────────────────────────────────────────────────────────────


def test_parse_volume_standard():
    assert parse_volume("/Volumes/Kuvia1/2025-01-01/IMG.RW2") == "Archive 1"


def test_parse_volume_no_volumes():
    assert parse_volume("/Users/test/photos/IMG.RW2") is None


def test_parse_volume_short_path():
    assert parse_volume("/Volumes") is None


def test_parse_volume_windows_drive():
    assert parse_volume(r"E:\Photos2\2025\IMG.RW2") == "E"


# ── parse_date_folder ─────────────────────────────────────────────────────────


def test_parse_date_folder_found():
    assert parse_date_folder("/Volumes/kuvia2/2025-03-01/IMG.RW2") == "2025-03-01"


def test_parse_date_folder_not_found():
    assert parse_date_folder("/Volumes/kuvia2/random/IMG.RW2") is None


# ── format_shutter_speed ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "val,expected",
    [
        (0.004, "1/250"),
        (0.001, "1/1000"),
        (0.5, "1/2"),
        (1.0, "1.0s"),
        (2.5, "2.5s"),
        (None, None),
        (0, None),
        (-1, None),
    ],
)
def test_format_shutter_speed(val, expected):
    assert format_shutter_speed(val) == expected


# ── get_camera_short ──────────────────────────────────────────────────────────


def test_camera_short_exact():
    assert get_camera_short("DC-S1M2ES") == "S1IIE"


def test_camera_short_nikon():
    assert get_camera_short("NIKON Z f") == "Zf"


def test_camera_short_unknown():
    assert get_camera_short("SomeUnknownCamera") == "SomeUnknownCamera"


def test_camera_short_none():
    assert get_camera_short(None) is None


# ── get_mount ─────────────────────────────────────────────────────────────────


def test_mount_known():
    assert get_mount("S1IIE") == "L-mount"
    assert get_mount("Zf") == "Z-mount"
    assert get_mount("XT30II") == "X-mount"


def test_mount_unknown():
    assert get_mount("Unknown") is None
    assert get_mount(None) is None


# ── discover_primary_files ────────────────────────────────────────────────────


def test_discover_primary_files(tmp_path):
    """Discovers RAW and JPEG files as primary, ignores sidecars."""
    vol = tmp_path / "TestVol"
    date_dir = vol / "2025-03-01"
    date_dir.mkdir(parents=True)

    (date_dir / "IMG001.RW2").write_bytes(b"raw")
    (date_dir / "IMG001.JPG").write_bytes(b"jpg")
    (date_dir / "IMG001.xmp").write_bytes(b"xmp")
    (date_dir / "IMG002.JPG").write_bytes(b"standalone jpg")

    from dam_scanner import discover_primary_files

    files = discover_primary_files([vol])

    names = {f.name for f in files}
    # Both RAW and JPEG are primary extensions
    assert "IMG001.RW2" in names
    assert "IMG002.JPG" in names
    # Sidecars are not primary
    assert "IMG001.xmp" not in names


def test_upsert_image_inserts_new_row(db_conn, tmp_path):
    """Scanner can insert a newly discovered image row into the DB."""
    archive_root = tmp_path / "Photos2"
    archive_root.mkdir()
    image_path = archive_root / "2025-03-01" / "DSC0001.ARW"
    image_path.parent.mkdir()
    image_path.write_bytes(b"raw-data")

    row = build_row(
        image_path,
        archive_root,
        {
            "Model": "ILCE-1",
            "Make": "Sony",
            "DateTimeOriginal": "2025:03:01 12:34:56",
        },
        {
            "has_jpeg": 0,
            "has_xmp": 0,
            "has_on1": 0,
            "has_radiant": 0,
            "sidecar_count": 0,
            "edited_anywhere": 0,
        },
    )

    upsert_image(db_conn, row)
    db_conn.commit()

    inserted = db_conn.execute(
        "SELECT file_name, relative_path FROM images WHERE file_name = ?",
        ("DSC0001.ARW",),
    ).fetchone()
    assert inserted is not None
    assert inserted["relative_path"] == "2025-03-01/DSC0001.ARW"


def test_file_identity_uses_archive_root_for_dated_subfolder(tmp_path):
    """Folder-scoped scans should still resolve to the containing archive root."""
    archive_root = tmp_path / "Photos2"
    dated_root = archive_root / "2026-03-28"
    dated_root.mkdir(parents=True)
    image_path = dated_root / "DSC02409.ARW"
    image_path.write_bytes(b"raw-data")

    identity = file_identity(image_path, [dated_root])

    assert identity == ("Archive 2", "2026-03-28/DSC02409.ARW")
