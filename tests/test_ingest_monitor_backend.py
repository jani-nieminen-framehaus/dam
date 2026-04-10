"""Tests for ingest monitor — status file writes and Flask endpoints."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_update_ingest_status_includes_current_path_and_dest_root(tmp_path):
    """_update_ingest_status writes current_path and dest_root to JSON."""
    import dam_config
    orig = dam_config.INGEST_STATUS_FILE
    dam_config.INGEST_STATUS_FILE = tmp_path / "ingest_status.json"

    try:
        from card_ingest import _update_ingest_status
        _update_ingest_status(
            dam_config.INGEST_STATUS_FILE,
            "copying",
            current=5,
            total=100,
            current_path="2026-04-07/DSCF2601.JPG",
            dest_root="/Volumes/Photos2",
        )
        data = json.loads(dam_config.INGEST_STATUS_FILE.read_text())
        assert data["current_path"] == "2026-04-07/DSCF2601.JPG"
        assert data["dest_root"] == "/Volumes/Photos2"
        assert data["status"] == "copying"
        assert data["current"] == 5
        assert data["total"] == 100
    finally:
        dam_config.INGEST_STATUS_FILE = orig


def test_update_ingest_status_current_path_defaults_to_none(tmp_path):
    """current_path absent from JSON when not provided."""
    import dam_config
    orig = dam_config.INGEST_STATUS_FILE
    dam_config.INGEST_STATUS_FILE = tmp_path / "ingest_status.json"

    try:
        from card_ingest import _update_ingest_status
        _update_ingest_status(dam_config.INGEST_STATUS_FILE, "scanning")
        data = json.loads(dam_config.INGEST_STATUS_FILE.read_text())
        assert data.get("current_path") is None
    finally:
        dam_config.INGEST_STATUS_FILE = orig


def test_write_ingest_phase_writes_status(tmp_path):
    """_write_ingest_phase writes the given status string to INGEST_STATUS_FILE."""
    import dam_config
    orig = dam_config.INGEST_STATUS_FILE
    dam_config.INGEST_STATUS_FILE = tmp_path / "ingest_status.json"

    try:
        from dam_scanner import _write_ingest_phase
        _write_ingest_phase("scanning_db")
        data = json.loads(dam_config.INGEST_STATUS_FILE.read_text())
        assert data["status"] == "scanning_db"
        assert "timestamp" in data
    finally:
        dam_config.INGEST_STATUS_FILE = orig
