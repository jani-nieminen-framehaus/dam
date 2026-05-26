#!/usr/bin/env python3
"""tools/describe_all.py — Phase 8 long-runner for Qwen image descriptions.

Single-worker batch describer. Picks unfinished images newest-first
(ORDER BY id DESC) so any newly-ingested SD card rises to the top of the
queue automatically — the older backlog drains underneath.

Behavior:
  - Filter: described_at IS NULL AND id IN (SELECT image_id FROM
    image_embeddings_siglip). The siglip-filter skips the 1130 RAF
    stragglers without previews; they'll be picked up after the RAF
    backfill is done.
  - Per-image commit. Killable, resumable. No partial state.
  - SIGINT/SIGTERM: graceful — finish current image, commit, exit 0.
    Second signal forces immediate exit (130).
  - Single-writer enforced via lockfile at ~/.dam/describer.pid.
    Stale PIDs (process gone) are auto-removed.
  - Heartbeat: writes vlm_status.json in DAM_ROOT every iteration,
    same shape as tagger_status.json / ingest_status.json.
  - Failed images: kept in-memory skip set for this run. Hard-abort
    if >100 failures (something is systemically wrong).

Usage:
  python3 tools/describe_all.py              # run until queue is empty
  python3 tools/describe_all.py --limit 5    # describe at most 5 (dry-run-ish)
  python3 tools/describe_all.py --dry-run    # print plan, no model load, no writes
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

DAM_DIR = Path(os.path.expanduser("~/.dam"))
DB_PATH = DAM_DIR / "dam.db"
LOCKFILE = DAM_DIR / "describer.pid"
STATUS_FILE = Path(os.path.expanduser("~/Documents/dam/vlm_status.json"))

# Hard sanity limit — if more than this fail in one run, abort.
MAX_FAILURES = 100

# ── Signal handling ──────────────────────────────────────────────────────────

_stop_requested = False
_signal_count = 0


def _handle_signal(signum, frame):
    """First signal: graceful stop after current image. Second: hard exit."""
    global _stop_requested, _signal_count
    _signal_count += 1
    if _signal_count == 1:
        _stop_requested = True
        print(
            f"\n[vlm] signal {signum} received — will exit after current image. "
            f"Send signal again to force-exit (will lose current image's work)."
        )
    else:
        print(f"\n[vlm] second signal — force exit, releasing lock.")
        _release_lock_silent()
        sys.exit(130)


# ── Lockfile ─────────────────────────────────────────────────────────────────


def _release_lock_silent():
    try:
        LOCKFILE.unlink()
    except FileNotFoundError:
        pass


def acquire_lock():
    """Single-writer enforcement. Detects and removes stale lockfiles
    (PID dead). Exits cleanly if another live describer is running."""
    DAM_DIR.mkdir(parents=True, exist_ok=True)
    if LOCKFILE.exists():
        raw = LOCKFILE.read_text().strip()
        try:
            other = int(raw)
        except ValueError:
            print(f"[vlm] stale lockfile (unparseable contents {raw!r}), removing")
            LOCKFILE.unlink()
        else:
            try:
                os.kill(other, 0)
            except ProcessLookupError:
                print(f"[vlm] stale lockfile (pid {other} not running), removing")
                LOCKFILE.unlink()
            except PermissionError:
                # Process exists but is owned by someone else; be conservative.
                print(f"[vlm] pid {other} exists but is not ours — refusing to start")
                sys.exit(1)
            else:
                print(f"[vlm] another describer is already running (pid {other}), exiting")
                sys.exit(0)
    LOCKFILE.write_text(str(os.getpid()))

# ── Status heartbeat ─────────────────────────────────────────────────────────


def write_status(
    *,
    status: str,
    current: int,
    total: int,
    current_path: str | None = None,
    current_id: int | None = None,
    last_description: str | None = None,
    eta_seconds: float | None = None,
):
    """Atomic write — temp file + rename — so external readers never see a
    half-written JSON. Same shape as tagger_status.json / ingest_status.json."""
    payload = {
        "status": status,
        "current": current,
        "total": total,
        "current_path": current_path,
        "current_id": current_id,
        "last_description": last_description,
        "eta_seconds": eta_seconds,
        "timestamp": datetime.utcnow().isoformat(),
    }
    tmp = STATUS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=None))
    tmp.replace(STATUS_FILE)


# ── ETA ──────────────────────────────────────────────────────────────────────


def format_eta(seconds: float) -> str:
    """e.g. 1080000s -> '12d 12h'."""
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    if d > 0:
        return f"{d}d {h}h"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"

# ── Queue query ──────────────────────────────────────────────────────────────


def count_pending(conn) -> int:
    """How many images still need a description.

    NOTE: this counts ALL images with described_at IS NULL, including the
    ~1,130 RAF stragglers without previews. Those get silently filtered
    at iteration time via pick_input(). The SigLIP-embedded filter that
    USED to live here was removed because it excluded fresh ingests
    (which aren't SigLIP-embedded yet — embedding is currently a one-shot
    tool, not part of the live pipeline). See REBUILD_RESUME.
    """
    return conn.execute(
        "SELECT COUNT(*) FROM images WHERE described_at IS NULL"
    ).fetchone()[0]


def next_pending(conn, skip_ids: set[int]):
    """Newest-first pop. skip_ids excludes both failed-this-run and
    no-preview rows accumulated this run.
    Returns sqlite3.Row or None when queue is empty."""
    if skip_ids:
        placeholders = ",".join("?" * len(skip_ids))
        sql = f"""
            SELECT id, file_path, file_name
              FROM images
             WHERE described_at IS NULL
               AND id NOT IN ({placeholders})
             ORDER BY id DESC
             LIMIT 1
        """
        return conn.execute(sql, tuple(skip_ids)).fetchone()
    return conn.execute(
        """SELECT id, file_path, file_name
             FROM images
            WHERE described_at IS NULL
            ORDER BY id DESC
            LIMIT 1"""
    ).fetchone()

# ── Main loop ────────────────────────────────────────────────────────────────


def run(limit: int | None = None, dry_run: bool = False):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # image_embeddings_siglip is a vec0 virtual table; the sqlite-vec extension
    # must be loaded on this connection or any SELECT touching it errors with
    # "no such module: vec0". The runner doesn't query embeddings directly, but
    # the filter "id IN (SELECT image_id FROM image_embeddings_siglip)" does.
    import sqlite_vec
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    total_pending = count_pending(conn)
    print(f"[vlm] pending: {total_pending} images")
    if total_pending == 0:
        print("[vlm] nothing to do.")
        return

    if limit is not None:
        print(f"[vlm] limit: {limit} (this run will stop after {limit} successes)")

    if dry_run:
        # Show what would be processed, no model load, no writes.
        print("[vlm] DRY RUN — first 5 pending (newest first):")
        rows = conn.execute(
            """SELECT id, file_name FROM images
                WHERE described_at IS NULL
                ORDER BY id DESC LIMIT 5"""
        ).fetchall()
        for r in rows:
            print(f"  id={r['id']:>6}  {r['file_name']}")
        return

    # Import dam_vlm only when we're actually going to use the model.
    # This keeps --dry-run and --help instant.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from dam_vlm import pick_input, describe_image_to_db, get_model

    print("[vlm] loading model (first call, ~60-120s)...")
    get_model()  # warm the singleton; printout from dam_vlm shows the time

    # Two skip sets:
    #   no_preview_ids — expected (the ~1,130 RAF stragglers without previews);
    #     unlimited, accumulates silently, excluded from queue.
    #   failed_ids     — model/describe errors; capped at MAX_FAILURES to
    #     catch systemic problems early. Excluded from queue.
    no_preview_ids: set[int] = set()
    failed_ids: set[int] = set()
    completed = 0
    times: list[float] = []  # rolling window for ETA, max 100 entries
    run_start = time.time()

    write_status(
        status="describing",
        current=0,
        total=total_pending,
        current_path=None,
        current_id=None,
    )

    while not _stop_requested:
        if limit is not None and completed >= limit:
            print(f"[vlm] reached limit ({limit}), stopping cleanly.")
            break

        row = next_pending(conn, no_preview_ids | failed_ids)
        if row is None:
            print("[vlm] queue empty (or all remaining are skipped this run).")
            break

        image_id = row["id"]
        file_name = row["file_name"]
        inp = pick_input(image_id)
        if inp is None:
            # Expected for the ~1,130 RAF stragglers. Silent skip (no log spam)
            # — they'll be picked up after the RAF preview backfill.
            no_preview_ids.add(image_id)
            continue

        # Heartbeat BEFORE inference so external watchers see what we're on
        write_status(
            status="describing",
            current=completed + 1,
            total=total_pending,
            current_path=file_name,
            current_id=image_id,
        )

        t0 = time.time()
        try:
            text = describe_image_to_db(conn, image_id, inp)
            conn.commit()
        except Exception as e:
            conn.rollback()
            elapsed = time.time() - t0
            print(f"[vlm] id={image_id} ({file_name}) FAILED after {elapsed:.1f}s: {e}")
            failed_ids.add(image_id)
            _check_failure_budget(failed_ids)
            continue

        elapsed = time.time() - t0
        times.append(elapsed)
        if len(times) > 100:
            times.pop(0)
        completed += 1

        # Per-image one-liner so you can tail and verify quality
        snippet = text[:120].replace("\n", " ")
        if len(text) > 120:
            snippet += "…"
        print(f"[vlm] id={image_id:>6} ({elapsed:>4.1f}s) {file_name}: {snippet}")

        # ETA every 100 successful images
        if completed % 100 == 0:
            avg = sum(times) / len(times)
            remaining = total_pending - completed
            eta = remaining * avg
            wallclock = time.time() - run_start
            print(
                f"[vlm] ── progress: {completed}/{total_pending} "
                f"({100*completed/total_pending:.1f}%) "
                f"avg {avg:.1f}s/img  this run {format_eta(wallclock)}  "
                f"ETA {format_eta(eta)}"
            )
            # Refresh status with ETA at milestones
            write_status(
                status="describing",
                current=completed,
                total=total_pending,
                current_path=file_name,
                current_id=image_id,
                last_description=snippet,
                eta_seconds=eta,
            )

    # ── Loop exit ────────────────────────────────────────────────────────────

    reason = (
        "stopped (signal)" if _stop_requested
        else f"limit reached ({limit})" if (limit is not None and completed >= limit)
        else "queue drained"
    )
    print(
        f"\n[vlm] {reason}. "
        f"described this run: {completed}, "
        f"failed this run: {len(failed_ids)}, "
        f"no preview (RAF stragglers): {len(no_preview_ids)}, "
        f"still pending in DB: {count_pending(conn)}"
    )
    write_status(
        status="idle",
        current=completed,
        total=total_pending,
        current_path=None,
        current_id=None,
    )
    conn.close()


def _check_failure_budget(skip_ids: set[int]):
    if len(skip_ids) > MAX_FAILURES:
        print(
            f"\n[vlm] aborting: {len(skip_ids)} failures exceeds MAX_FAILURES={MAX_FAILURES}. "
            "Something is systemically wrong. Investigate before restarting."
        )
        _release_lock_silent()
        sys.exit(1)

# ── Entry point ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Describe pending images using Qwen 2.5 VL (MLX). Newest-first, killable."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of images to describe this run (default: unlimited)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the next 5 pending images and exit. No model load, no DB writes."
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"[vlm] ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run:
        acquire_lock()
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

    try:
        run(limit=args.limit, dry_run=args.dry_run)
    finally:
        if not args.dry_run:
            _release_lock_silent()


if __name__ == "__main__":
    main()
