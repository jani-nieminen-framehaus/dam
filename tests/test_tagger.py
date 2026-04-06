"""Tests for dam_tagger module — burst detection, keyword parsing, and selection."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dam_tagger import detect_bursts, select_candidate_rows, text_extract_keywords

# ── detect_bursts ─────────────────────────────────────────────────────────────


def _make_row(id, camera, date_taken):
    """Create a minimal row dict for burst detection."""
    return {
        "id": id,
        "camera_short": camera,
        "date_taken": date_taken,
        "file_name": f"IMG{id:04d}.RW2",
        "file_path": f"/test/IMG{id:04d}.RW2",
        "triptych_leg": None,
    }


def test_detect_bursts_basic():
    """3+ images within 2s from same camera form a burst."""
    rows = [
        _make_row(1, "S1IIE", "2025-03-01T14:30:00"),
        _make_row(2, "S1IIE", "2025-03-01T14:30:01"),
        _make_row(3, "S1IIE", "2025-03-01T14:30:02"),
    ]
    reps, burst_map, skipped = detect_bursts(rows)

    assert len(reps) == 1  # one representative
    assert reps[0]["id"] == 1
    assert 1 in burst_map
    assert set(burst_map[1]) == {2, 3}
    assert skipped == 2


def test_detect_bursts_different_cameras():
    """Bursts are not detected across different cameras — sorting groups
    same-camera images, so 2 S1IIE images become adjacent (below min_size).
    All 3 images should appear as independent representatives."""
    rows = [
        _make_row(1, "S1IIE", "2025-03-01T14:30:00"),
        _make_row(2, "Zf", "2025-03-01T14:30:01"),
        _make_row(3, "S1IIE", "2025-03-01T14:30:02"),
    ]
    reps, burst_map, skipped = detect_bursts(rows)

    # 2 S1IIE images form a group of 2 (below min_size=3) → both independent
    # 1 Zf image is its own group → independent
    # Total: 3 representatives, no bursts
    assert len(reps) == 3
    assert burst_map == {}
    assert skipped == 0


def test_detect_bursts_no_burst_large_gap():
    """Images >2s apart don't form bursts."""
    rows = [
        _make_row(1, "S1IIE", "2025-03-01T14:30:00"),
        _make_row(2, "S1IIE", "2025-03-01T14:30:10"),
        _make_row(3, "S1IIE", "2025-03-01T14:30:20"),
    ]
    reps, burst_map, skipped = detect_bursts(rows)

    assert len(reps) == 3
    assert burst_map == {}
    assert skipped == 0


def test_detect_bursts_two_bursts():
    """Two separate bursts from the same camera."""
    rows = [
        # Burst 1
        _make_row(1, "S1IIE", "2025-03-01T14:30:00"),
        _make_row(2, "S1IIE", "2025-03-01T14:30:01"),
        _make_row(3, "S1IIE", "2025-03-01T14:30:02"),
        # Gap
        _make_row(4, "S1IIE", "2025-03-01T14:35:00"),
        _make_row(5, "S1IIE", "2025-03-01T14:35:01"),
        _make_row(6, "S1IIE", "2025-03-01T14:35:02"),
    ]
    reps, burst_map, skipped = detect_bursts(rows)

    assert len(reps) == 2
    assert len(burst_map) == 2
    assert skipped == 4


def test_detect_bursts_empty():
    """Empty input returns empty."""
    reps, burst_map, skipped = detect_bursts([])
    assert reps == []
    assert burst_map == {}
    assert skipped == 0


def test_detect_bursts_below_min_size():
    """2 images in quick succession don't form a burst (min is 3).
    They group together but since < BURST_MIN_SIZE, both become
    independent representatives (no images are dropped)."""
    rows = [
        _make_row(1, "S1IIE", "2025-03-01T14:30:00"),
        _make_row(2, "S1IIE", "2025-03-01T14:30:01"),
    ]
    reps, burst_map, skipped = detect_bursts(rows)

    # Both images are independent representatives — nothing is dropped
    assert len(reps) == 2
    assert burst_map == {}
    assert skipped == 0


# ── text_extract_keywords (with mocked Ollama) ──────────────────────────────


def test_keyword_parsing_valid_json(monkeypatch):
    """Comma-separated response is parsed correctly."""
    valid_response = {
        "response": "man, window, isolation, backlit, aging"
    }
    monkeypatch.setattr("dam_tagger.ollama_post", lambda *a, **kw: valid_response)

    result = text_extract_keywords("A man stands by a window.")
    assert "man" in result["factual"]
    assert "window" in result["factual"]
    assert "isolation" in result["mood"]
    assert result["triptych_relevant"] is True  # "aging" is in TRIPTYCH_THEMES


def test_keyword_parsing_markdown_fences(monkeypatch):
    """Keywords with trailing noise are still parsed."""
    noisy_response = {
        "response": "chair, calm, soft lighting\nNote: these are approximate"
    }
    monkeypatch.setattr("dam_tagger.ollama_post", lambda *a, **kw: noisy_response)

    result = text_extract_keywords("A chair in a room.")
    assert "chair" in result["factual"]
    assert "calm" in result["mood"]
    assert "soft lighting" in result["technical"]


def test_keyword_parsing_malformed(monkeypatch):
    """Empty response returns safe defaults."""
    monkeypatch.setattr("dam_tagger.ollama_post", lambda *a, **kw: {"response": ""})

    result = text_extract_keywords("Something.")
    assert result["factual"] == []
    assert result["mood"] == []
    assert result["triptych_relevant"] is False


def test_select_candidate_rows_respects_manifest(db_conn, tmp_path):
    db_conn.execute(
        """INSERT INTO images
           (id, file_path, file_name, file_type, volume, relative_path, date_taken, camera_short)
           VALUES
           (1, '/Volumes/Photos2/2026-03-28/A.ARW', 'A.ARW', 'ARW', 'Archive 2', '2026-03-28/A.ARW', '2026-03-28T10:00:00', 'A1'),
           (2, '/Volumes/Photos2/2026-03-28/B.ARW', 'B.ARW', 'ARW', 'Archive 2', '2026-03-28/B.ARW', '2026-03-28T10:00:01', 'A1'),
           (3, '/Volumes/Photos2/2026-03-27/C.ARW', 'C.ARW', 'ARW', 'Archive 2', '2026-03-27/C.ARW', '2026-03-27T10:00:00', 'A1')"""
    )
    db_conn.execute("INSERT INTO thumbnails (image_id, thumb_path) VALUES (1, '1.jpg'), (2, '2.jpg'), (3, '3.jpg')")
    manifest = tmp_path / "last_ingest.json"
    manifest.write_text(
        json.dumps(
            {
                "volume": "Archive 2",
                "relative_paths": ["2026-03-28/A.ARW", "2026-03-28/B.ARW"],
            }
        )
    )
    db_conn.commit()

    rows = select_candidate_rows(db_conn, manifest_path=manifest)

    assert [row["id"] for row in rows] == [2, 1]
