"""Tests for the shared ingest pipeline orchestration."""

from pathlib import Path
from subprocess import CompletedProcess


def test_ingest_pipeline_runs_copy_scan_thumbs_and_background_tagger(monkeypatch, tmp_path):
    import ingest_pipeline

    calls = []
    spawned = []

    monkeypatch.setattr(ingest_pipeline, "INGEST_SCRIPT", Path("/app/card_ingest.py"))
    monkeypatch.setattr(ingest_pipeline, "SCANNER_SCRIPT", Path("/app/dam_scanner.py"))
    monkeypatch.setattr(ingest_pipeline, "TAGGER_SCRIPT", Path("/app/dam_tagger.py"))
    monkeypatch.setattr(ingest_pipeline, "DAM_ROOT", tmp_path)
    manifest = tmp_path / "last_ingest.json"
    manifest.write_text("{}")
    monkeypatch.setattr(ingest_pipeline, "LAST_INGEST_FILE", manifest)

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(ingest_pipeline.subprocess, "run", fake_run)
    monkeypatch.setattr(
        ingest_pipeline,
        "run_preview_backfill",
        lambda *args, **kwargs: {"total": 0, "generated": 0, "skipped": 0, "failed": 0, "elapsed": 0.0},
    )
    monkeypatch.setattr(
        ingest_pipeline,
        "spawn_background_process",
        lambda cmd, log_file, cwd=None: spawned.append((cmd, log_file, cwd)),
    )

    result = ingest_pipeline.run_ingest_pipeline(["/Volumes/CARD"], python="/python", announce=None)

    assert result.returncode == 0
    assert [call[0] for call in calls] == [
        ["/python", "/app/card_ingest.py", "/Volumes/CARD"],
        ["/python", "/app/dam_scanner.py", "--no-thumbs"],
        ["/python", "/app/dam_scanner.py", "--no-scan"],
    ]
    assert spawned == [
        (
            ["/python", "/app/dam_tagger.py", "--manifest", str(manifest)],
            tmp_path / "tagger_run.log",
            tmp_path,
        )
    ]


def test_ingest_pipeline_dry_run_stops_after_copy(monkeypatch):
    import ingest_pipeline

    calls = []
    monkeypatch.setattr(ingest_pipeline, "INGEST_SCRIPT", Path("/app/card_ingest.py"))

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ingest_pipeline.subprocess, "run", fake_run)

    result = ingest_pipeline.run_ingest_pipeline(["/Volumes/CARD"], dry_run=True, python="/python", announce=None)

    assert result.returncode == 0
    assert calls == [["/python", "/app/card_ingest.py", "/Volumes/CARD", "--dry-run"]]


def test_ingest_pipeline_generates_previews_after_thumbs(monkeypatch):
    """Ingest pipeline runs preview generation after thumbnails."""
    import ingest_pipeline

    monkeypatch.setattr(ingest_pipeline, "INGEST_SCRIPT", Path("/app/card_ingest.py"))
    monkeypatch.setattr(ingest_pipeline, "SCANNER_SCRIPT", Path("/app/dam_scanner.py"))

    def fake_run(cmd, **kwargs):
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ingest_pipeline.subprocess, "run", fake_run)

    preview_calls = []

    def fake_backfill(preview_dir, **kwargs):
        preview_calls.append(str(preview_dir))
        return {"total": 0, "generated": 0, "skipped": 0, "failed": 0, "elapsed": 0.0}

    monkeypatch.setattr(ingest_pipeline, "run_preview_backfill", fake_backfill)

    result = ingest_pipeline.run_ingest_pipeline(no_tag=True, python="/python", announce=None)

    assert result.returncode == 0
    assert len(preview_calls) == 1
    assert preview_calls[0].endswith("/previews")


def test_ingest_pipeline_stops_when_scan_fails(monkeypatch):
    import ingest_pipeline

    calls = []
    monkeypatch.setattr(ingest_pipeline, "INGEST_SCRIPT", Path("/app/card_ingest.py"))
    monkeypatch.setattr(ingest_pipeline, "SCANNER_SCRIPT", Path("/app/dam_scanner.py"))

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return CompletedProcess(cmd, 7 if "--no-thumbs" in cmd else 0, stdout="", stderr="scan failed")

    monkeypatch.setattr(ingest_pipeline.subprocess, "run", fake_run)
    monkeypatch.setattr(ingest_pipeline, "spawn_background_process", lambda *args, **kwargs: None)

    result = ingest_pipeline.run_ingest_pipeline(["/Volumes/CARD"], python="/python", announce=None)

    assert result.returncode == 7
    assert calls == [
        ["/python", "/app/card_ingest.py", "/Volumes/CARD"],
        ["/python", "/app/dam_scanner.py", "--no-thumbs"],
    ]
    assert "scan failed" in result.stderr
