#!/opt/homebrew/bin/python3
"""
DAM Card Watcher — auto-detect SD card mount and trigger full ingest pipeline.

Runs as a LaunchAgent. When a new volume with a DCIM folder appears,
fires: dam ingest → scan → thumbnails → AI tag (background).

Logs to ~/Documents/dam/card_watcher.log
"""

import contextlib
import logging
import os
import subprocess
import time
from pathlib import Path

from dam_config import DAM_ROOT, IGNORE_VOLUMES, INGEST_TIMEOUT, POLL_INTERVAL

DAM_SCRIPT = DAM_ROOT / "dam.py"
PYTHON = "/opt/homebrew/bin/python3"
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
    """Return set of volume paths that have a DCIM folder."""
    cards = set()
    volumes = Path("/Volumes")
    if not volumes.exists():
        return cards
    for vol in volumes.iterdir():
        if vol.name in IGNORE_VOLUMES:
            continue
        dcim = vol / "DCIM"
        if dcim.exists() and dcim.is_dir():
            cards.add(str(vol))
    return cards


def notify(title, message):
    """macOS notification via osascript."""
    with contextlib.suppress(Exception):
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{message}" with title "{title}"',
            ],
            timeout=5,
        )


def run_ingest(card_path):
    """Run full DAM ingest pipeline for a detected card."""
    vol_name = Path(card_path).name
    log.info(f"═══ CARD DETECTED: {vol_name} ═══")
    notify("DAM", f"Card detected: {vol_name} — starting ingest")

    # LaunchAgents get minimal PATH — ensure homebrew tools are available
    env = os.environ.copy()
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

    except subprocess.TimeoutExpired:
        log.error("Ingest TIMED OUT after 2 hours")
        notify("DAM", f"Ingest timed out: {vol_name}")
    except Exception as e:
        log.error(f"Ingest error: {e}")
        notify("DAM", f"Ingest error: {vol_name}")


def main():
    log.info("DAM Card Watcher started")
    log.info(f"  Polling /Volumes every {POLL_INTERVAL}s")
    log.info(f"  Ignoring: {', '.join(sorted(IGNORE_VOLUMES))}")

    global seen_cards
    # On startup, mark any currently mounted cards as seen
    # (don't re-ingest cards that were already in when watcher started)
    seen_cards = get_mounted_cards()
    if seen_cards:
        log.info(f"  Already mounted (skipping): {', '.join(Path(c).name for c in seen_cards)}")

    while True:
        try:
            current = get_mounted_cards()
            new_cards = current - seen_cards

            for card_path in new_cards:
                # Small delay — let the OS finish mounting
                time.sleep(2)
                # Verify DCIM still there (card might have been pulled)
                if (Path(card_path) / "DCIM").exists():
                    run_ingest(card_path)
                    seen_cards.add(card_path)

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
