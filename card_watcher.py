#!/opt/homebrew/bin/python3
"""
DAM Card Watcher — auto-detect SD/CFexpress card mount and trigger full ingest pipeline.

Runs as a LaunchAgent. When a new volume with a DCIM folder appears,
fires the shared ingest pipeline: copy → scan → thumbnails → AI tag (background).

Logs to ~/Documents/dam/card_watcher.log
"""

import logging
import os
import sys
import time
from pathlib import Path
from subprocess import TimeoutExpired

from dam_config import DAM_ROOT, IGNORE_VOLUMES, INGEST_TIMEOUT, POLL_INTERVAL
from ingest_pipeline import run_ingest_pipeline
from platform_utils import find_dcim_mounts, launch_ingest_monitor, volume_label

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


def run_ingest(card_path):
    """Run full DAM ingest pipeline for a detected card.

    Returns True on success, False on failure (enables retry on next poll).
    """
    vol_name = Path(card_path).name
    log.info(f"═══ CARD DETECTED: {vol_name} ═══")
    launch_ingest_monitor(vol_name)

    env = os.environ.copy()
    if sys.platform == "darwin":
        env["PATH"] = "/opt/homebrew/bin:/opt/homebrew/sbin:" + env.get("PATH", "/usr/bin:/bin")

    start = time.time()
    try:
        result = run_ingest_pipeline(
            [card_path],
            python=PYTHON,
            capture_output=True,
            timeout=INGEST_TIMEOUT,
            cwd=str(DAM_ROOT),
            env=env,
            announce=log.info,
        )
        elapsed = time.time() - start

        if result.returncode == 0:
            log.info(f"Ingest complete in {elapsed:.0f}s")
        else:
            log.error(f"Ingest FAILED (exit {result.returncode})")
            log.error(result.stderr[-500:] if result.stderr else "no stderr")

        if result.stdout:
            for line in result.stdout.strip().split("\n")[-20:]:
                log.info(f"  {line}")

        return result.returncode == 0

    except TimeoutExpired:
        log.error("Ingest TIMED OUT after 2 hours")
        return False
    except Exception as e:
        log.error(f"Ingest error: {e}")
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
