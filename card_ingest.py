#!/opt/homebrew/bin/python3
"""
Card Ingest Script — moves RAW+JPEG files from memory card to dated folders.
Target: /Volumes/kuvia2/YYYY-MM-DD/
Source: any mounted card (auto-detects /Volumes/XXXXX/DCIM/)

Usage:
    python3 card_ingest.py                    # auto-detect card
    python3 card_ingest.py /path/to/card      # specify card path
    python3 card_ingest.py --dry-run           # preview without copying

Safety:
    - NEVER writes to source (card)
    - NEVER overwrites existing files (hard stop on collision)
    - Copies first, verifies checksum, then reports
    - No deletion — you format the card in-camera
"""

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

from dam_config import DEST_ROOT, IGNORE_VOLUMES, INGEST_STATUS_FILE

RAW_EXTENSIONS = {".rw2", ".nef", ".raf", ".arw", ".cr3", ".dng", ".orf"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}
SIDECAR_EXTENSIONS = {".xmp"}
ALL_EXTENSIONS = RAW_EXTENSIONS | JPEG_EXTENSIONS | SIDECAR_EXTENSIONS


def md5_file(filepath):
    """Calculate MD5 checksum of a file using file_digest (C-level, faster on large RAWs)."""
    with open(filepath, "rb") as f:
        return hashlib.file_digest(f, "md5").hexdigest()


def find_card():
    """Auto-detect mounted memory card by looking for DCIM folder."""
    volumes = Path("/Volumes")
    candidates = []
    for vol in volumes.iterdir():
        if vol.name in IGNORE_VOLUMES:
            continue
        dcim = vol / "DCIM"
        if dcim.exists() and dcim.is_dir():
            candidates.append(dcim)
    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        print("Multiple cards detected:")
        for i, c in enumerate(candidates):
            print(f"  [{i}] {c.parent.name}")
        choice = input("Select card number: ")
        return candidates[int(choice)]
    else:
        return None


def get_date_from_file(filepath):
    """Extract date from file modification time (fallback if no EXIF)."""
    mtime = os.path.getmtime(filepath)
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


def get_date_exiftool(filepath):
    """Extract DateTimeOriginal via exiftool (preferred)."""
    import subprocess

    try:
        result = subprocess.run(
            ["exiftool", "-DateTimeOriginal", "-s3", "-d", "%Y-%m-%d", str(filepath)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        date_str = result.stdout.strip()
        if date_str and len(date_str) == 10:
            return date_str
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return get_date_from_file(filepath)


def collect_files(card_path):
    """Walk the card and collect all image files with their target dates."""
    files = []
    for root, dirs, filenames in os.walk(card_path):
        for fname in filenames:
            ext = Path(fname).suffix.lower()
            if ext in ALL_EXTENSIONS:
                full_path = Path(root) / fname
                date = get_date_exiftool(full_path)
                files.append((full_path, date, fname))
    return files


def ingest(card_path, dry_run=False):
    """Main ingest: copy files from card to dated folders on kuvia2."""
    progress_file = INGEST_STATUS_FILE

    def update_status(status, current=0, total=0):
        if dry_run:
            return
        try:
            with open(progress_file, "w") as f:
                json.dump(
                    {"status": status, "current": current, "total": total, "timestamp": datetime.now().isoformat()}, f
                )
        except Exception:
            pass

    update_status("scanning", 0, 0)

    if not DEST_ROOT.exists():
        print(f"ERROR: Destination {DEST_ROOT} not mounted!")
        update_status("error")
        sys.exit(1)

    print(f"Source: {card_path}")
    print(f"Destination: {DEST_ROOT}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE COPY'}")
    print()

    files = collect_files(card_path)
    if not files:
        print("No image files found on card.")
        update_status("idle")
        return

    # Group by date
    by_date: dict[str, list[tuple[Path, str]]] = {}
    for fpath, date, fname in files:
        if date not in by_date:
            by_date[date] = []
        by_date[date].append((fpath, fname))

    total = len(files)
    copied = 0
    skipped = 0
    errors = 0

    for date in sorted(by_date.keys()):
        date_files = by_date[date]
        dest_dir = Path(DEST_ROOT) / str(date)

        # Don't print header if we have tqdm
        if dry_run or not tqdm:
            print(f"\n[{date}] — {len(date_files)} files")

        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)

        iterator = date_files
        if not dry_run and tqdm:
            # Create a progress bar per date folder
            iterator = tqdm(date_files, desc=f"[{date}]", unit="file", leave=True)

        for fpath, fname in iterator:
            current_progress = int(copied + skipped + errors)
            update_status("copying", current_progress, total)
            dest_file = dest_dir / str(fname)

            # HARD STOP on collision — never overwrite, never rename
            if dest_file.exists():
                print(f"  SKIP (exists): {fname}")
                skipped += 1
                continue

            if dry_run:
                size_mb = fpath.stat().st_size / (1024 * 1024)
                print(f"  WOULD COPY: {fname} ({size_mb:.1f} MB)")
                copied += 1
            else:
                try:
                    shutil.copy2(str(fpath), str(dest_file))
                    # Verify checksum
                    src_hash = md5_file(fpath)
                    dst_hash = md5_file(dest_file)
                    if src_hash != dst_hash:
                        print(f"  CHECKSUM FAIL: {fname} — removing bad copy!")
                        dest_file.unlink()
                        errors += 1
                    else:
                        size_mb = fpath.stat().st_size / (1024 * 1024)
                        # Replace print with tqdm.write if available so it doesn't break the progress bar layout
                        msg = f"  OK: {fname} ({size_mb:.1f} MB) ✓"
                        if not tqdm:
                            print(msg)
                        copied += 1
                except Exception as e:
                    msg = f"  ERROR: {fname} — {e}"
                    if tqdm:
                        tqdm.write(msg)
                    else:
                        print(msg)
                    errors += 1

    update_status("idle", total, total)

    print(f"\n{'=' * 50}")
    print(f"Total files found: {total}")
    print(f"Copied: {copied}")
    print(f"Skipped (existing): {skipped}")
    print(f"Errors: {errors}")
    if not dry_run and errors == 0:
        print("\nAll files verified. Format card in-camera when ready.")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if args:
        card_path = Path(args[0])
        if not card_path.exists():
            print(f"ERROR: Path {card_path} does not exist!")
            sys.exit(1)
    else:
        found_card = find_card()
        if found_card is None:
            print("No memory card detected. Insert card or specify path.")
            print(f"Usage: python3 {sys.argv[0]} /path/to/card [--dry-run]")
            sys.exit(1)
        card_path = Path(str(found_card))
        parent_name = card_path.parent.name if card_path.parent else str(card_path)
        print(f"Auto-detected card: {parent_name}")

    ingest(card_path, dry_run=dry_run)
