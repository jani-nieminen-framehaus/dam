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


def test_get_filters_includes_new_fields(tmp_dam_root, app_client):
    resp = app_client.get("/api/filters")
    data = resp.get_json()
    assert "projects" in data
    assert "subjects" in data
    assert "triptych_values" in data
    assert "narrative_values" in data
    assert "color_values" in data


# ── DELETE endpoint ───────────────────────────────────────────────────────────


def test_delete_image(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.delete(f"/api/images/{img_id}")
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] == img_id
    # Verify it's gone
    resp2 = app_client.get(f"/api/images/{img_id}")
    assert resp2.status_code == 404


def test_delete_image_404(tmp_dam_root, app_client):
    resp = app_client.delete("/api/images/99999")
    assert resp.status_code == 404


# ── Bulk PATCH ────────────────────────────────────────────────────────────────


def test_bulk_patch(tmp_dam_root, app_client):
    id1 = _insert_test_image(tmp_dam_root)
    # Insert a second image with different path
    import sqlite3

    import dam_config

    conn = sqlite3.connect(str(dam_config.DB_PATH))
    conn.execute(
        "INSERT INTO images (file_path, file_name, file_type, rating, pick) "
        "VALUES ('/test/IMG002.RW2', 'IMG002.RW2', 'RW2', 0, 'unmarked')"
    )
    conn.commit()
    id2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    resp = app_client.patch(
        "/api/images/bulk",
        json={"ids": [id1, id2], "patch": {"rating": 3, "pick": "pick"}},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["updated"] == 2

    # Verify both updated
    r1 = app_client.get(f"/api/images/{id1}").get_json()
    r2 = app_client.get(f"/api/images/{id2}").get_json()
    assert r1["rating"] == 3
    assert r2["pick"] == "pick"


def test_bulk_patch_invalid(tmp_dam_root, app_client):
    resp = app_client.patch(
        "/api/images/bulk",
        json={"ids": [1], "patch": {"rating": 99}},
        content_type="application/json",
    )
    assert resp.status_code == 400


# ── Bulk DELETE ───────────────────────────────────────────────────────────────


def test_bulk_delete(tmp_dam_root, app_client):
    id1 = _insert_test_image(tmp_dam_root)
    import sqlite3

    import dam_config

    conn = sqlite3.connect(str(dam_config.DB_PATH))
    conn.execute(
        "INSERT INTO images (file_path, file_name, file_type) VALUES ('/test/IMG003.RW2', 'IMG003.RW2', 'RW2')"
    )
    conn.commit()
    id2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    resp = app_client.delete(
        "/api/images/bulk",
        json={"ids": [id1, id2]},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] == 2


# ── Projects (many-to-many) ──────────────────────────────────────────────────


def test_add_and_remove_project(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)

    # Add project
    resp = app_client.post(
        f"/api/images/{img_id}/projects",
        json={"name": "triptych"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert "triptych" in resp.get_json()["projects"]

    # Remove project
    resp = app_client.delete(f"/api/images/{img_id}/projects/triptych")
    assert resp.status_code == 200
    assert "triptych" not in resp.get_json()["projects"]


# ── Subjects (many-to-many) ──────────────────────────────────────────────────


def test_add_and_remove_subject(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)

    resp = app_client.post(
        f"/api/images/{img_id}/subjects",
        json={"name": "Jorma"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert "Jorma" in resp.get_json()["subjects"]

    resp = app_client.delete(f"/api/images/{img_id}/subjects/Jorma")
    assert resp.status_code == 200
    assert "Jorma" not in resp.get_json()["subjects"]


# ── Keywords (many-to-many) ──────────────────────────────────────────────────


def test_add_and_remove_keyword(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)

    resp = app_client.post(
        f"/api/images/{img_id}/keywords",
        json={"keyword": "isolation"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert "isolation" in resp.get_json()["keywords"]

    resp = app_client.delete(f"/api/images/{img_id}/keywords/isolation")
    assert resp.status_code == 200
    assert "isolation" not in resp.get_json()["keywords"]


# ── PATCH: color_label, triptych, notes ──────────────────────────────────────


def test_patch_color_label(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(
        f"/api/images/{img_id}",
        json={"color_label": "red"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["color_label"] == "red"


def test_patch_invalid_color_label(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(
        f"/api/images/{img_id}",
        json={"color_label": "magenta"},
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_patch_triptych_leg(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(
        f"/api/images/{img_id}",
        json={"triptych_leg": "abstract"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["triptych_leg"] == "abstract"


def test_patch_notes(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(
        f"/api/images/{img_id}",
        json={"notes": "Jorma's hands, backlit"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["notes"] == "Jorma's hands, backlit"


def test_patch_narrative_arc(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    resp = app_client.patch(
        f"/api/images/{img_id}",
        json={"narrative_arc": "middle"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["narrative_arc"] == "middle"


# ── Filter by new fields ─────────────────────────────────────────────────────


def test_filter_by_color_label(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    app_client.patch(
        f"/api/images/{img_id}",
        json={"color_label": "green"},
        content_type="application/json",
    )
    # Filter matches
    resp = app_client.get("/api/images?color_label=green")
    assert resp.status_code == 200
    assert len(resp.get_json()["images"]) == 1

    # Filter doesn't match
    resp = app_client.get("/api/images?color_label=red")
    assert len(resp.get_json()["images"]) == 0


def test_filter_by_project(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    app_client.post(
        f"/api/images/{img_id}/projects",
        json={"name": "triptych"},
        content_type="application/json",
    )
    resp = app_client.get("/api/images?project=triptych")
    assert resp.status_code == 200
    assert len(resp.get_json()["images"]) == 1

    resp = app_client.get("/api/images?project=street")
    assert len(resp.get_json()["images"]) == 0


def test_filter_by_subject(tmp_dam_root, app_client):
    img_id = _insert_test_image(tmp_dam_root)
    app_client.post(
        f"/api/images/{img_id}/subjects",
        json={"name": "Jorma"},
        content_type="application/json",
    )
    resp = app_client.get("/api/images?subject=Jorma")
    assert resp.status_code == 200
    assert len(resp.get_json()["images"]) == 1

    resp = app_client.get("/api/images?subject=Heidi")
    assert len(resp.get_json()["images"]) == 0


def test_filter_combined_subject_camera_date(tmp_dam_root, app_client):
    """The taxonomy's example: 'every frame of Jorma from the Nikon, December 2025'."""
    import sqlite3

    import dam_config

    conn = sqlite3.connect(str(dam_config.DB_PATH))
    conn.execute(
        "INSERT INTO images (file_path, file_name, file_type, camera_short, date_taken) "
        "VALUES ('/test/DSC001.NEF', 'DSC001.NEF', 'NEF', 'Zf', '2025-12-15T14:30:00')"
    )
    conn.commit()
    img_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    app_client.post(
        f"/api/images/{img_id}/subjects",
        json={"name": "Jorma"},
        content_type="application/json",
    )

    resp = app_client.get("/api/images?subject=Jorma&camera=Zf&date_from=2025-12-01&date_to=2025-12-31")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["images"]) == 1
    assert data["images"][0]["camera_short"] == "Zf"
