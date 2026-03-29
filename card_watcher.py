#!/opt/homebrew/bin/python3
"""
DAM Card Watcher — auto-detect SD/CFexpress card mount and trigger full ingest pipeline.

Runs as a LaunchAgent. When a new volume with a DCIM folder appears,
fires: dam ingest → scan → thumbnails → AI tag (background).

Logs to ~/Documents/dam/card_watcher.log
"""

import contextlib
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from dam_config import DAM_ROOT, IGNORE_VOLUMES, INGEST_TIMEOUT, POLL_INTERVAL
from platform_utils import find_dcim_mounts, notify_desktop, volume_label

DAM_SCRIPT = DAM_ROOT / "dam.py"
PYTHON = sys.executable
LOG_FILE = DAM_ROOT / "card_watcher.log"

# ── Logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("card_watcher")

# ── State ──────────────────────────────────────────────────────────
seen_cards = set()  # cards we've already processed this session


def get_mounted_cards():
    """Return set of volume paths that have a DCIM folder.

    Logs each volume's status for diagnostics (helps debug CFexpress detection).
    """
    cards = {str(p) for p in find_dcim_mounts(IGNORE_VOLUMES)}
    for p in sorted(cards):
        log.debug(f"  Volume {volume_label(Path(p))}: DCIM found — card detected")
    return cards


def notify(title, message):
    """Best-effort desktop notification."""
    with contextlib.suppress(Exception):
        notify_desktop(title, message)


def run_ingest(card_path):
    """Run full DAM ingest pipeline for a detected card.

    Returns True on success, False on failure (enables retry on next poll).
    """
    vol_name = Path(card_path).name
    log.info(f"═══ CARD DETECTED: {vol_name} ═══")
    notify("DAM", f"Card detected: {vol_name} — starting ingest")

    # LaunchAgents get minimal PATH — ensure homebrew tools are available
    env = os.environ.copy()
    if sys.platform == "darwin":
        env["PATH"] = "/opt/homebrew/bin:/opt/homebrew/sbin:" + env.get("PATH", "/usr/bin:/bin")

    start = time.time()
    try:
        result = subprocess.run(
            [PYTHON, str(DAM_SCRIPT), "ingest", card_path],
            capture_output=True,
            text=True,
            timeout=INGEST_TIMEOUT,
            cwd=str(DAM_ROOT),
            env=env,
        )
        elapsed = time.time() - start

        if result.returncode == 0:
            log.info(f"Ingest complete in {elapsed:.0f}s")
            notify("DAM", f"Ingest done: {vol_name} ({elapsed:.0f}s)")
        else:
            log.error(f"Ingest FAILED (exit {result.returncode})")
            log.error(result.stderr[-500:] if result.stderr else "no stderr")
            notify("DAM", f"Ingest FAILED: {vol_name}")

        # Log stdout summary (last 20 lines)
        if result.stdout:
            for line in result.stdout.strip().split("\n")[-20:]:
                log.info(f"  {line}")

        return result.returncode == 0

    except subprocess.TimeoutExpired:
        log.error("Ingest TIMED OUT after 2 hours")
        notify("DAM", f"Ingest timed out: {vol_name}")
        return False
    except Exception as e:
        log.error(f"Ingest error: {e}")
        notify("DAM", f"Ingest error: {vol_name}")
        return False


def main():
    log.info("DAM Card Watcher started")
    log.info(f"  Polling mounted volumes every {POLL_INTERVAL}s")
    log.info(f"  Ignoring: {', '.join(sorted(IGNORE_VOLUMES))}")

    global seen_cards
    # On startup, mark any currently mounted cards as seen
    # (don't re-ingest cards that were already in when watcher started)
    seen_cards = get_mounted_cards()
    if seen_cards:
        log.info(f"  Already mounted (skipping): {', '.join(volume_label(Path(c)) for c in seen_cards)}")

    while True:
        try:
            current = get_mounted_cards()
            new_cards = current - seen_cards

            for card_path in new_cards:
                # Settle time — let OS finish mounting (CFexpress readers may be slower)
                time.sleep(3)
                # Verify DCIM still there (card might have been pulled)
                if (Path(card_path) / "DCIM").exists():
                    success = run_ingest(card_path)
                    if success:
                        seen_cards.add(card_path)
                    else:
                        log.info(f"Will retry {Path(card_path).name} on next poll")

            # Clean up ejected cards from seen set
            gone = seen_cards - current
            if gone:
                for g in gone:
                    log.info(f"Card ejected: {Path(g).name}")
                seen_cards -= gone

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("Card Watcher stopped")
            break
        except Exception as e:
            log.error(f"Watcher error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
