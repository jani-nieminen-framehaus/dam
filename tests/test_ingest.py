"""Tests for card_ingest module — checksum and copy functions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from card_ingest import collect_files, copy_file_with_md5, md5_file


def test_md5_known_content(tmp_path):
    """MD5 of known content matches expected hash."""
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    # echo -n "hello world" | md5
    assert md5_file(f) == "5eb63bbbe01eeed093cb22bb8f5acdc3"


def test_md5_empty_file(tmp_path):
    """MD5 of empty file matches known empty hash."""
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    assert md5_file(f) == "d41d8cd98f00b204e9800998ecf8427e"


def test_md5_binary_content(tmp_path):
    """MD5 works on binary data."""
    f = tmp_path / "binary.bin"
    f.write_bytes(bytes(range(256)))
    h = md5_file(f)
    assert len(h) == 32
    assert all(c in "0123456789abcdef" for c in h)


def test_collect_files_skips_missing_file(tmp_path, monkeypatch):
    """collect_files should skip files that disappear during scan."""
    card_path = tmp_path / "card"
    dcim = card_path / "DCIM"
    dcim.mkdir(parents=True)
    existing = dcim / "keep.arw"
    missing = dcim / "gone.arw"
    existing.write_bytes(b"ok")

    def fake_get_date(path):
        if path == missing:
            raise FileNotFoundError(path)
        return "2026-03-28"

    monkeypatch.setattr("card_ingest.get_date_exiftool", fake_get_date)

    files = collect_files(card_path)
    assert files == [(existing, "2026-03-28", "keep.arw")]


def test_copy_file_with_md5_copies_content_and_hash(tmp_path):
    """Streamed copy returns the source hash and preserves file content."""
    src = tmp_path / "source.raf"
    dst = tmp_path / "dest.raf"
    payload = bytes(range(256)) * 4096
    src.write_bytes(payload)

    src_hash = copy_file_with_md5(src, dst)

    assert dst.read_bytes() == payload
    assert src_hash == md5_file(src)
    assert md5_file(dst) == src_hash


def test_copy_file_with_md5_cleans_up_partial_destination(tmp_path, monkeypatch):
    """Failed streamed copies should not leave a partial file behind."""
    src = tmp_path / "source.raf"
    dst = tmp_path / "dest.raf"
    src.write_bytes(b"0123456789")

    def broken_copystat(_src, _dst):
        raise OSError("metadata failed")

    monkeypatch.setattr("card_ingest.shutil.copystat", broken_copystat)

    try:
        copy_file_with_md5(src, dst)
    except OSError as exc:
        assert "metadata failed" in str(exc)
    else:
        raise AssertionError("copy_file_with_md5 should have raised")

    assert not dst.exists()
