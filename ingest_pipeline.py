#!/opt/homebrew/bin/python3
"""Shared orchestration for card ingest pipeline steps."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from dam_config import DAM_ROOT, LAST_INGEST_FILE
from dam_scanner import run_preview_backfill
from platform_utils import spawn_background_process

_SCRIPT_ROOT = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else DAM_ROOT
INGEST_SCRIPT = _SCRIPT_ROOT / "card_ingest.py"
SCANNER_SCRIPT = _SCRIPT_ROOT / "dam_scanner.py"
TAGGER_SCRIPT = _SCRIPT_ROOT / "dam_tagger.py"

Announce = Callable[[str], None]


@dataclass
class IngestPipelineResult:
    """Summary of one ingest orchestration run."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    elapsed: float = 0.0


def _default_announce(message: str) -> None:
    print(message)


def _run_step(
    cmd: list[str],
    description: str,
    *,
    capture_output: bool,
    timeout: float | None,
    cwd: Path | str,
    env: dict[str, str] | None,
    announce: Announce | None,
) -> subprocess.CompletedProcess:
    if announce:
        announce(f"\nDAM ── {description}\n" + "-" * 50)
    return subprocess.run(
        cmd,
        capture_output=capture_output,
        text=capture_output,
        timeout=timeout,
        cwd=str(cwd),
        env=env,
    )


def _append_process_output(result: IngestPipelineResult, proc: subprocess.CompletedProcess) -> None:
    if proc.stdout:
        result.stdout += proc.stdout
    if proc.stderr:
        result.stderr += proc.stderr


def _remaining_timeout(total_timeout: float | None, start: float, cmd: list[str]) -> float | None:
    if total_timeout is None:
        return None
    remaining = total_timeout - (time.time() - start)
    if remaining <= 0:
        raise subprocess.TimeoutExpired(cmd, total_timeout)
    return remaining


def launch_background_tagger(*, python: str | None = None, announce: Announce | None = _default_announce) -> None:
    """Launch AI tagging for the latest ingest manifest in a detached process."""
    if announce:
        announce("\nDAM ── STEP 5/5 — AI Tagging (background)\n" + "-" * 50)
    tag_log = DAM_ROOT / "tagger_run.log"
    tag_cmd = [python or sys.executable, str(TAGGER_SCRIPT)]
    if LAST_INGEST_FILE.exists():
        tag_cmd.extend(["--manifest", str(LAST_INGEST_FILE)])
    spawn_background_process(tag_cmd, tag_log, cwd=DAM_ROOT)
    if announce:
        announce(f"  Tagger launched in background. Monitor: tail -f {tag_log}")
        announce("\nIngest complete. AI tagging running in background.")


def run_ingest_pipeline(
    card_args: Sequence[str | Path] | None = None,
    *,
    dry_run: bool = False,
    no_tag: bool = False,
    python: str | None = None,
    capture_output: bool = False,
    timeout: float | None = None,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    announce: Announce | None = _default_announce,
) -> IngestPipelineResult:
    """Run copy -> scan -> thumbs -> optional background tag as one shared flow."""
    start = time.time()
    result = IngestPipelineResult(returncode=0)
    py = python or sys.executable
    run_cwd = cwd or DAM_ROOT

    ingest_cmd = [py, str(INGEST_SCRIPT)]
    if card_args:
        ingest_cmd.extend(str(arg) for arg in card_args if arg is not None)
    if dry_run:
        ingest_cmd.append("--dry-run")

    proc = _run_step(
        ingest_cmd,
        "STEP 1/5 — Card Ingest",
        capture_output=capture_output,
        timeout=_remaining_timeout(timeout, start, ingest_cmd),
        cwd=run_cwd,
        env=env,
        announce=announce,
    )
    _append_process_output(result, proc)
    if proc.returncode != 0:
        if announce:
            announce(f"\nIngest failed (exit {proc.returncode}). Aborting.")
        result.returncode = proc.returncode
        result.elapsed = time.time() - start
        return result

    if dry_run:
        if announce:
            announce("\nDry run complete. No DB changes made.")
        result.elapsed = time.time() - start
        return result

    scan_cmd = [py, str(SCANNER_SCRIPT), "--no-thumbs"]
    proc = _run_step(
        scan_cmd,
        "STEP 2/5 — Scanning New Files",
        capture_output=capture_output,
        timeout=_remaining_timeout(timeout, start, scan_cmd),
        cwd=run_cwd,
        env=env,
        announce=announce,
    )
    _append_process_output(result, proc)
    if proc.returncode != 0:
        if announce:
            announce(f"\nScan failed (exit {proc.returncode}). Thumbnails skipped.")
        result.returncode = proc.returncode
        result.elapsed = time.time() - start
        return result

    thumbs_cmd = [py, str(SCANNER_SCRIPT), "--no-scan"]
    proc = _run_step(
        thumbs_cmd,
        "STEP 3/5 — Generating Thumbnails for New Files",
        capture_output=capture_output,
        timeout=_remaining_timeout(timeout, start, thumbs_cmd),
        cwd=run_cwd,
        env=env,
        announce=announce,
    )
    _append_process_output(result, proc)
    if proc.returncode != 0:
        if announce:
            announce(f"\nThumbnail generation failed (exit {proc.returncode}).")
        result.returncode = proc.returncode
        result.elapsed = time.time() - start
        return result

    if announce:
        announce("\nDAM ── STEP 4/5 — Generating Lightbox Previews\n" + "-" * 50)
    preview_dir = DAM_ROOT / "previews"
    run_preview_backfill(preview_dir)

    if no_tag:
        if announce:
            announce("\nIngest complete (AI tagging skipped).")
        result.elapsed = time.time() - start
        return result

    launch_background_tagger(python=py, announce=announce)
    result.elapsed = time.time() - start
    return result
