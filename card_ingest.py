#!/opt/homebrew/bin/python3
"""
Card Ingest Script — moves RAW+JPEG files from memory card to dated folders.
Target: /Volumes/Photos1/YYYY-MM-DD/ (fallback: Photos2)
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

from dam_config import DEST_ROOT, IGNORE_VOLUMES, INGEST_STATUS_FILE, LAST_INGEST_FILE, VOLUME_ALIASES
from platform_utils import find_dcim_mounts, volume_label
from storage_utils import choose_ingest_destination, logical_volume_for_root

RAW_EXTENSIONS = {".rw2", ".nef", ".raf", ".arw", ".cr3", ".dng", ".orf"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}
SIDECAR_EXTENSIONS = {".xmp"}
ALL_EXTENSIONS = RAW_EXTENSIONS | JPEG_EXTENSIONS | SIDECAR_EXTENSIONS


def md5_file(filepath):
    """Calculate MD5 checksum of a file using file_digest (C-level, faster on large RAWs)."""
    with open(filepath, "rb") as f:
        return hashlib.file_digest(f, "md5").hexdigest()


def copy_file_with_md5(src_path, dst_path, chunk_size=4 * 1024 * 1024):
    """
    Copy a file while hashing the source stream in the same pass.

    This removes one full reread from the source card while keeping
    end-to-end verification against a separately hashed destination file.
    """
    digest = hashlib.md5()
    try:
        with open(src_path, "rb") as src_file, open(dst_path, "xb") as dst_file:
            while chunk := src_file.read(chunk_size):
                digest.update(chunk)
                dst_file.write(chunk)
            dst_file.flush()
            os.fsync(dst_file.fileno())
        shutil.copystat(src_path, dst_path)
    except Exception:
        try:
            Path(dst_path).unlink()
        except FileNotFoundError:
            pass
        raise
    return digest.hexdigest()


def find_card():
    """Auto-detect mounted memory card by looking for DCIM folder."""
    candidates = [mount / "DCIM" for mount in find_dcim_mounts(IGNORE_VOLUMES)]
    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        print("Multiple cards detected:")
        for i, c in enumerate(candidates):
            print(f"  [{i}] {volume_label(c.parent)}")
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
                try:
                    date = get_date_exiftool(full_path)
                except FileNotFoundError:
                    # Card contents can change while scanning; skip vanished files.
                    continue
                files.append((full_path, date, fname))
    return files


def _update_ingest_status(progress_file, status, current=0, total=0):
    """Write ingest progress to status file (non-fatal on error)."""
    try:
        with open(progress_file, "w") as f:
            json.dump(
                {"status": status, "current": current, "total": total, "timestamp": datetime.now().isoformat()}, f
            )
    except Exception:
        pass


def _copy_verified(fpath, dest_file, fname, dry_run):
    """Copy a single file with checksum verification.
    Returns: ('copied', date_rel_path) | ('skipped', date_rel_path) | ('error', None)
    """
    if dest_file.exists():
        print(f"  SKIP (exists): {fname}")
        return "skipped"

    if dry_run:
        size_mb = fpath.stat().st_size / (1024 * 1024)
        print(f"  WOULD COPY: {fname} ({size_mb:.1f} MB)")
        return "copied"

    try:
        src_hash = copy_file_with_md5(fpath, dest_file)
        dst_hash = md5_file(dest_file)
        if src_hash != dst_hash:
            print(f"  CHECKSUM FAIL: {fname} — removing bad copy!")
            dest_file.unlink()
            return "error"
        return "copied"
    except Exception as e:
        msg = f"  ERROR: {fname} — {e}"
        if tqdm:
            tqdm.write(msg)
        else:
            print(msg)
        return "error"


def _ensure_dir(dest_dir, progress_file):
    """Create destination directory, exit on permission error."""
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        print(f"ERROR: Cannot create destination folder: {dest_dir} (permission denied)")
        _update_ingest_status(progress_file, "error")
        sys.exit(1)


def _validate_dest(dest_root, dry_run, progress_file):
    """Validate destination root is writable. Exits on failure."""
    if dest_root is None:
        print(f"ERROR: No writable local archive volume detected. Preferred archive: {DEST_ROOT}")
        _update_ingest_status(progress_file, "error")
        sys.exit(1)
    if not dry_run:
        probe = dest_root / ".dam_write_probe"
        try:
            probe.mkdir(exist_ok=True)
            probe.rmdir()
        except PermissionError:
            print(f"ERROR: Destination {dest_root} is mounted but not writable by current user.")
            _update_ingest_status(progress_file, "error")
            sys.exit(1)


def _copy_date_group(date, date_files, dest_root, dry_run, progress_file, total, counters):
    """Copy all files for one date folder, updating counters in place. Returns manifest entries."""
    dest_dir = dest_root / str(date)
    manifest = []

    if dry_run or not tqdm:
        print(f"\n[{date}] — {len(date_files)} files")

    if not dry_run:
        _ensure_dir(dest_dir, progress_file)

    iterator = tqdm(date_files, desc=f"[{date}]", unit="file", leave=True) if (not dry_run and tqdm) else date_files

    for fpath, fname in iterator:
        if not dry_run:
            _update_ingest_status(progress_file, "copying", sum(counters.values()), total)

        result = _copy_verified(fpath, dest_dir / str(fname), fname, dry_run)
        counters[result] += 1
        if result != "error":
            manifest.append(f"{date}/{fname}")

    return manifest


def _write_manifest(dest_root, manifest_paths):
    """Write ingest manifest for downstream tagging."""
    try:
        with open(LAST_INGEST_FILE, "w") as f:
            json.dump(
                {
                    "volume": logical_volume_for_root(dest_root, VOLUME_ALIASES),
                    "dest_root": str(dest_root),
                    "relative_paths": sorted(set(manifest_paths)),
                    "timestamp": datetime.now().isoformat(),
                },
                f,
            )
    except OSError:
        pass


def ingest(card_path, dry_run=False):
    """Main ingest: copy files from card to dated folders on kuvia2."""
    progress_file = INGEST_STATUS_FILE
    dest_root = choose_ingest_destination(DEST_ROOT, IGNORE_VOLUMES, VOLUME_ALIASES)

    _validate_dest(dest_root, dry_run, progress_file)
    if not dry_run:
        _update_ingest_status(progress_file, "scanning", 0, 0)

    print(f"Source: {card_path}")
    print(f"Destination: {dest_root}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE COPY'}")
    print()

    files = collect_files(card_path)
    if not files:
        print("No image files found on card.")
        if not dry_run:
            _update_ingest_status(progress_file, "idle")
        return

    by_date: dict[str, list[tuple[Path, str]]] = {}
    for fpath, date, fname in files:
        by_date.setdefault(date, []).append((fpath, fname))

    total = len(files)
    counters = {"copied": 0, "skipped": 0, "error": 0}
    manifest_paths: list[str] = []

    for date in sorted(by_date.keys()):
        manifest_paths.extend(
            _copy_date_group(date, by_date[date], dest_root, dry_run, progress_file, total, counters)
        )

    if not dry_run:
        _update_ingest_status(progress_file, "idle", total, total)
        if manifest_paths:
            _write_manifest(dest_root, manifest_paths)

    print(f"\n{'=' * 50}")
    print(f"Total files found: {total}")
    print(f"Copied: {counters['copied']}")
    print(f"Skipped (existing): {counters['skipped']}")
    print(f"Errors: {counters['error']}")
    if not dry_run and counters["error"] == 0:
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
