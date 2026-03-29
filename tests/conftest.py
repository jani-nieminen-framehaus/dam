"""Shared test fixtures for DAM test suite."""

import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure project root is on path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def tmp_dam_root(tmp_path):
    """Create a temporary DAM root with thumbs/ dir and empty DB, monkeypatch dam_config."""
    dam_root = tmp_path / "dam"
    dam_root.mkdir()
    (dam_root / "thumbs").mkdir()
    (dam_root / "static").mkdir()

    db_path = dam_root / "dam.db"

    # Monkeypatch dam_config module attributes BEFORE importing dam_schema,
    # so init_db() uses the temp paths.
    import dam_config

    original = {
        "DAM_ROOT": dam_config.DAM_ROOT,
        "DB_PATH": dam_config.DB_PATH,
        "THUMB_DIR": dam_config.THUMB_DIR,
        "SPA_DIR": dam_config.SPA_DIR,
        "INGEST_STATUS_FILE": dam_config.INGEST_STATUS_FILE,
    }
    dam_config.DAM_ROOT = dam_root
    dam_config.DB_PATH = db_path
    dam_config.THUMB_DIR = dam_root / "thumbs"
    dam_config.SPA_DIR = dam_root / "static"
    dam_config.INGEST_STATUS_FILE = dam_root / "ingest_status.json"

    # Use the real production schema via dam_schema.init_db()
    from dam_schema import init_db

    conn = init_db()
    conn.close()

    yield dam_root

    # Restore
    for k, v in original.items():
        setattr(dam_config, k, v)


@pytest.fixture
def db_conn(tmp_dam_root):
    """Connected sqlite3 to the temp DB."""
    import dam_config

    conn = sqlite3.connect(str(dam_config.DB_PATH))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def sample_image_row():
    """A minimal image row dict for inserting into test DB."""
    return {
        "file_path": "/Volumes/kuvia2/2025-03-01/P1000001.RW2",
        "file_name": "P1000001.RW2",
        "file_type": "RW2",
        "volume": "Archive 2",
        "relative_path": "2025-03-01/P1000001.RW2",
        "date_folder": "2025-03-01",
        "date_taken": "2025-03-01T14:30:00",
        "camera_short": "S1IIE",
        "mount": "L-mount",
        "rating": 0,
        "pick": "unmarked",
        "edit_status": "unculled",
        "has_jpeg": 1,
        "orphan_jpeg": 0,
    }


@pytest.fixture
def db_with_images(db_conn, sample_image_row):
    """DB with a few test images inserted."""
    for i in range(1, 4):
        row = dict(sample_image_row)
        row["file_path"] = f"/Volumes/kuvia2/2025-03-01/P100000{i}.RW2"
        row["file_name"] = f"P100000{i}.RW2"
        row["relative_path"] = f"2025-03-01/P100000{i}.RW2"
        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        db_conn.execute(f"INSERT INTO images ({cols}) VALUES ({placeholders})", list(row.values()))
    db_conn.commit()
    return db_conn


@pytest.fixture
def app_client(tmp_dam_root):
    """Flask test client with temp DB."""
    import importlib

    import dam_api

    importlib.reload(dam_api)

    dam_api.app.config["TESTING"] = True
    with dam_api.app.test_client() as client:
        yield client
