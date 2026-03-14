"""Tests for dam_api — Flask endpoint validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _insert_test_image(tmp_dam_root):
    """Insert a test image row and return its id."""
    import sqlite3

    import dam_config

    conn = sqlite3.connect(str(dam_config.DB_PATH))
    conn.execute("""
        INSERT INTO images (file_path, file_name, file_type, rating, pick, edit_status)
        VALUES ('/test/IMG001.RW2', 'IMG001.RW2', 'RW2', 0, 'unmarked', 'unculled')
    """)
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return row_id


# ── PATCH validation ──────────────────────────────────────────────────────────


def test_patch_valid_rating(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(f"/api/images/{img_id}", json={"rating": 4}, content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["rating"] == 4


def test_patch_invalid_rating_too_high(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(f"/api/images/{img_id}", json={"rating": 6}, content_type="application/json")
    assert resp.status_code == 400
    assert "rating" in resp.get_json()["error"]


def test_patch_invalid_rating_negative(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(f"/api/images/{img_id}", json={"rating": -1}, content_type="application/json")
    assert resp.status_code == 400


def test_patch_valid_pick(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(f"/api/images/{img_id}", json={"pick": "pick"}, content_type="application/json")
    assert resp.status_code == 200
    assert resp.get_json()["pick"] == "pick"


def test_patch_invalid_pick(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(f"/api/images/{img_id}", json={"pick": "invalid_value"}, content_type="application/json")
    assert resp.status_code == 400


def test_patch_unknown_field(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(
        f"/api/images/{img_id}", json={"nonexistent_field": "value"}, content_type="application/json"
    )
    assert resp.status_code == 400
    assert "not patchable" in resp.get_json()["error"]


def test_patch_no_body(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(f"/api/images/{img_id}", content_type="application/json")
    assert resp.status_code == 400


def test_patch_valid_edit_status(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(f"/api/images/{img_id}", json={"edit_status": "selected"}, content_type="application/json")
    assert resp.status_code == 200
    assert resp.get_json()["edit_status"] == "selected"


# ── GET endpoints ─────────────────────────────────────────────────────────────


def test_get_images_empty(tmp_dam_root, app_client):
    resp = app_client.get("/api/images")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["images"] == []
    assert data["total_filtered"] == 0


def test_get_images_with_data(tmp_dam_root, app_client):
    _insert_test_image(tmp_dam_root)
    resp = app_client.get("/api/images")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["images"]) == 1


def test_get_stats(tmp_dam_root, app_client):
    resp = app_client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "total" in data
    assert "by_camera" in data


def test_get_filters(tmp_dam_root, app_client):
    resp = app_client.get("/api/filters")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "cameras" in data
    assert "pick_values" in data
    assert "edit_status_values" in data


def test_get_image_detail_404(tmp_dam_root, app_client):
    resp = app_client.get("/api/images/99999")
    assert resp.status_code == 404
