"""Tests for card_ingest module — checksum functions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from card_ingest import md5_file


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
