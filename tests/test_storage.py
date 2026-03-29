"""Tests for storage identity and root resolution helpers."""

from pathlib import Path

from platform_utils import MountInfo
from storage_utils import (
    canonical_volume_label,
    choose_ingest_destination,
    resolve_archive_file,
    resolve_scan_roots,
)


def test_canonical_volume_label_maps_numeric_suffix():
    assert canonical_volume_label("Photos2") == "Archive 2"
    assert canonical_volume_label("kuvia1") == "Archive 1"


def test_resolve_scan_roots_prefers_local_archive_mounts(monkeypatch):
    mounts = [
        MountInfo(Path("/Volumes/kuvia1"), "kuvia1", "smbfs", False, True),
        MountInfo(Path("/Volumes/Photos1"), "Photos1", "exfat", True, False),
        MountInfo(Path("/Volumes/kuvia2"), "kuvia2", "smbfs", False, False),
        MountInfo(Path("/Volumes/Photos2"), "Photos2", "exfat", True, False),
    ]
    monkeypatch.setattr("storage_utils.find_archive_mounts", lambda ignore: mounts)
    monkeypatch.setattr("storage_utils.is_dir_writable", lambda path: "Photos" in str(path))
    monkeypatch.setattr("storage_utils.free_bytes", lambda path: 200 if path.name.endswith("2") else 100)

    roots = resolve_scan_roots([Path("/Volumes/Kuvia1"), Path("/Volumes/kuvia2")], set())
    assert roots == [Path("/Volumes/Photos1"), Path("/Volumes/Photos2")]


def test_choose_ingest_destination_matches_preferred_alias(monkeypatch):
    mounts = [
        MountInfo(Path("/Volumes/Photos1"), "Photos1", "exfat", True, False),
        MountInfo(Path("/Volumes/Photos2"), "Photos2", "exfat", True, False),
    ]
    monkeypatch.setattr("storage_utils.find_archive_mounts", lambda ignore: mounts)
    monkeypatch.setattr("storage_utils.is_dir_writable", lambda path: True)
    monkeypatch.setattr("storage_utils.free_bytes", lambda path: 200 if path.name.endswith("2") else 100)

    chosen = choose_ingest_destination(Path("/Volumes/kuvia2"), set())
    assert chosen == Path("/Volumes/Photos2")


def test_resolve_archive_file_uses_alternate_root(tmp_path, monkeypatch):
    target_root = tmp_path / "Photos2"
    image = target_root / "2025-03-01" / "IMG001.RW2"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"raw")

    monkeypatch.setattr("storage_utils.resolve_scan_roots", lambda roots, ignore, aliases=None: [target_root])

    resolved = resolve_archive_file(
        "/Volumes/kuvia2/2025-03-01/IMG001.RW2",
        "Archive 2",
        "2025-03-01/IMG001.RW2",
        [Path("/Volumes/kuvia2")],
        set(),
    )
    assert resolved == image
