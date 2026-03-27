#!/opt/homebrew/bin/python3
"""
DAM Scanner — Phase 1
Walks photo volumes, extracts EXIF via exiftool, populates SQLite.

Usage:
    python3 dam_scanner.py                     # scan default volumes
    python3 dam_scanner.py /Volumes/kuvia2     # scan specific path
    python3 dam_scanner.py --rescan            # force rescan all (ignore indexed_at)
    python3 dam_scanner.py --stats             # show DB stats and exit
    python3 dam_scanner.py --dry-run           # find files but don't write DB

DB location: ~/Documents/dam/dam.db
Thumb cache: ~/Documents/dam/thumbs/

Safety:
    - READ-ONLY on filesystem (never modifies image files or sidecars)
    - Resumable: skips files already indexed (by file_path)
    - Batch exiftool calls for speed (~100 files per batch)
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dam_config import BATCH_SIZE, DB_PATH, DEFAULT_VOLUMES, THUMB_DIR, THUMB_WORKERS
from dam_schema import init_db

# Primary files — these define an image group
RAW_EXTENSIONS = {".rw2", ".nef", ".raf", ".arw", ".cr3", ".dng", ".orf"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}
PRIMARY_EXTENSIONS = RAW_EXTENSIONS | JPEG_EXTENSIONS

# Sidecar extensions (not indexed as primary, tracked as group members)
SIDECAR_EXTENSIONS = {".xmp", ".on1", ".radiant"}

# Camera model → friendly short name
CAMERA_SHORT_MAP = {
    "DC-S1M2ES": "S1IIE",
    "DC-S1": "S1",
    "NIKON Z f": "Zf",
    "NIKON Z F": "Zf",
    "X-T30 II": "XT30II",
    "X-T30": "XT30",
    "X-H2": "XH2",
    "X-Pro3": "XPro3",
    "ILCE-1": "A1",  # sold but may exist in archive
    "GFX 100 II": "GFX100II",  # sold but may exist in archive
    "iPhone 14 Pro": "iPhone14Pro",
    "iPhone 15 Pro": "iPhone15Pro",
    "DC-LX100M2": "LX100II",
    "Canon EOS R5": "R5",
    "Canon EOS R6": "R6",
    "Canon EOS R6 Mark II": "R6II",
    "Canon EOS R7": "R7",
    "Canon EOS R3": "R3",
    "Canon EOS R": "R",
    "Canon PowerShot G7 X Mark III": "G7XIII",
}

# Camera model → mount system
MOUNT_MAP = {
    "S1IIE": "L-mount",
    "S1": "L-mount",
    "Zf": "Z-mount",
    "XT30II": "X-mount",
    "XT30": "X-mount",
    "XH2": "X-mount",
    "XPro3": "X-mount",
    "A1": "E-mount",
    "GFX100II": "G-mount",
    "LX100II": "integrated",
    "G7XIII": "integrated",
    "R5": "RF-mount",
    "R6": "RF-mount",
    "R6II": "RF-mount",
    "R7": "RF-mount",
    "R3": "RF-mount",
    "R": "RF-mount",
}

# === EXIF FIELDS TO EXTRACT ===
EXIF_TAGS = [
    "-Make",
    "-Model",
    "-SerialNumber",
    "-LensModel",
    "-LensSerialNumber",
    "-DateTimeOriginal",
    "-FNumber",
    "-ExposureTime",
    "-ISO",
    "-FocalLength",
    "-FocalLengthIn35mmFormat",
    "-ExposureCompensation",
    "-MeteringMode",
    "-WhiteBalance",
    "-Flash",
    "-ImageWidth",
    "-ImageHeight",
    "-Orientation",
    "-ColorSpace",
    "-BitsPerSample",
    "-GPSLatitude",
    "-GPSLongitude",
    "-GPSAltitude",
]


# Schema and init_db are defined in dam_schema.py


# ============================================================
# FILE DISCOVERY
# ============================================================


def discover_primary_files(volumes):
    """Walk volumes and find all primary image files (RAW + standalone JPEG)."""
    files = []
    for vol in volumes:
        if not vol.exists():
            print(f"  SKIP: {vol} not mounted")
            continue
        print(f"  Scanning {vol}...")
        count = 0
        for root, dirs, filenames in os.walk(vol):
            # Skip hidden dirs and system dirs
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                ext = Path(fname).suffix.lower()
                if ext in PRIMARY_EXTENSIONS:
                    files.append(Path(root) / fname)
                    count += 1
        print(f"    Found {count:,} primary files")
    return files


def detect_sidecars(primary_path):
    """Detect sidecar files belonging to the same image group."""
    folder = primary_path.parent
    stem = primary_path.stem

    sidecars = {
        "has_jpeg": False,
        "has_xmp": False,
        "has_on1": False,
        "has_radiant": False,
        "sidecar_count": 0,
    }

    # Check for JPEG pair (only relevant if primary is RAW)
    if primary_path.suffix.lower() in RAW_EXTENSIONS:
        for jext in (".JPG", ".jpg", ".JPEG", ".jpeg"):
            if (folder / (stem + jext)).exists():
                sidecars["has_jpeg"] = True
                sidecars["sidecar_count"] += 1
                break

    # Check for XMP: stem.xmp and stem.RW2.xmp variants
    for xmp_name in [stem + ".xmp", stem + ".XMP", primary_path.name + ".xmp", primary_path.name + ".XMP"]:
        if (folder / xmp_name).exists():
            sidecars["has_xmp"] = True
            sidecars["sidecar_count"] += 1
            break

    # Check for ON1 sidecar
    for on1_name in [stem + ".on1", primary_path.name + ".on1"]:
        if (folder / on1_name).exists():
            sidecars["has_on1"] = True
            sidecars["sidecar_count"] += 1
            break

    # Check for Radiant sidecar
    for rad_name in [stem + ".radiant", primary_path.name + ".radiant", stem + ".JPG.radiant", stem + ".jpg.radiant"]:
        if (folder / rad_name).exists():
            sidecars["has_radiant"] = True
            sidecars["sidecar_count"] += 1
            break

    sidecars["edited_anywhere"] = sidecars["has_xmp"] or sidecars["has_on1"] or sidecars["has_radiant"]

    return sidecars


def is_orphan_jpeg(primary_path):
    """Check if a JPEG has no RAW sibling (phone shot or export)."""
    if primary_path.suffix.lower() not in JPEG_EXTENSIONS:
        return False
    folder = primary_path.parent
    stem = primary_path.stem
    for rext in RAW_EXTENSIONS:
        for case in [rext, rext.upper()]:
            if (folder / (stem + case)).exists():
                return False
    return True


# ============================================================
# EXIF EXTRACTION
# ============================================================


def extract_exif_batch(file_paths):
    """Call exiftool once for a batch of files, return dict keyed by path."""
    if not file_paths:
        return {}

    cmd = [
        "exiftool",
        "-json",
        "-n",  # -n = numeric values (no formatting)
        "-charset",
        "filename=utf8",
    ]
    cmd.extend(EXIF_TAGS)
    cmd.extend(str(p) for p in file_paths)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode not in (0, 1):  # 1 = minor warnings OK
            print(f"  exiftool warning: {result.stderr[:200]}")
        data = json.loads(result.stdout)
        # Key by SourceFile path
        return {item.get("SourceFile", ""): item for item in data}
    except subprocess.TimeoutExpired:
        print(f"  exiftool TIMEOUT on batch of {len(file_paths)} files")
        return {}
    except json.JSONDecodeError as e:
        print(f"  exiftool JSON parse error: {e}")
        return {}


# ============================================================
# DERIVED FIELDS
# ============================================================


def compute_time_of_day(hour):
    """Map hour (0-23) to time-of-day bucket."""
    if hour is None:
        return None
    if 5 <= hour < 7:
        return "dawn"
    elif 7 <= hour < 11:
        return "morning"
    elif 11 <= hour < 14:
        return "midday"
    elif 14 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 19:
        return "golden"
    elif 19 <= hour < 22:
        return "evening"
    else:
        return "night"


def compute_season(month):
    """Map month (1-12) to season (Finnish latitude)."""
    if month is None:
        return None
    if month in (12, 1, 2):
        return "winter"
    elif month in (3, 4, 5):
        return "spring"
    elif month in (6, 7, 8):
        return "summer"
    else:
        return "autumn"


def get_camera_short(model):
    """Map camera model string to friendly short name."""
    if not model:
        return None
    # Try exact match first
    if model in CAMERA_SHORT_MAP:
        return CAMERA_SHORT_MAP[model]
    # Try partial match (e.g., model string contains the key)
    for key, short in CAMERA_SHORT_MAP.items():
        if key in model:
            return short
    return model  # fallback: return original


def get_mount(camera_short):
    """Map camera short name to mount system."""
    if not camera_short:
        return None
    return MOUNT_MAP.get(camera_short)


def parse_volume(file_path):
    """Extract volume name from path like /Volumes/Kuvia1/..."""
    parts = Path(file_path).parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "Volumes":
        return parts[2]
    return None


def parse_date_folder(file_path):
    """Extract YYYY-MM-DD folder name if present in path."""
    for part in Path(file_path).parts:
        if len(part) == 10 and part[4] == "-" and part[7] == "-":
            try:
                datetime.strptime(part, "%Y-%m-%d")
                return part
            except ValueError:
                pass
    return None


def parse_date_taken(exif):
    """Parse DateTimeOriginal from exif dict."""
    dto = exif.get("DateTimeOriginal")
    if not dto:
        return None, None, None
    try:
        # exiftool -n gives "2025:12:15 14:23:07" format
        dt = datetime.strptime(str(dto), "%Y:%m:%d %H:%M:%S")
        return dt.isoformat(), dt.hour, dt.month
    except (ValueError, TypeError):
        return str(dto), None, None


def format_shutter_speed(val):
    """Convert numeric ExposureTime (e.g. 0.004) to fraction string (1/250)."""
    if val is None:
        return None
    try:
        val = float(val)
        if val <= 0:
            return None
        if val >= 1:
            return f"{val:.1f}s"
        reciprocal = round(1.0 / val)
        return f"1/{reciprocal}"
    except (ValueError, TypeError):
        return str(val)


def safe_float(val):
    """Convert exif value to float or None."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def safe_int(val):
    """Convert exif value to int or None."""
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


# ============================================================
# BUILD ROW
# ============================================================


def build_row(file_path, exif, sidecars):
    """Build a dict of all fields for one image row."""
    fpath = Path(file_path)
    date_taken, hour, month = parse_date_taken(exif)
    camera_model = exif.get("Model")
    cam_short = get_camera_short(camera_model)

    return {
        "file_path": str(fpath),
        "file_name": fpath.name,
        "file_type": fpath.suffix.lstrip(".").upper(),
        "file_size": fpath.stat().st_size if fpath.exists() else None,
        "volume": parse_volume(str(fpath)),
        "date_folder": parse_date_folder(str(fpath)),
        "camera_make": exif.get("Make"),
        "camera_model": camera_model,
        "camera_serial": exif.get("SerialNumber"),
        "camera_short": cam_short,
        "mount": get_mount(cam_short),
        "lens_model": exif.get("LensModel"),
        "lens_serial": exif.get("LensSerialNumber"),
        "date_taken": date_taken,
        "aperture": safe_float(exif.get("FNumber")),
        "shutter_speed": format_shutter_speed(exif.get("ExposureTime")),
        "iso": safe_int(exif.get("ISO")),
        "focal_length": safe_float(exif.get("FocalLength")),
        "focal_length_35eq": safe_float(exif.get("FocalLengthIn35mmFormat")),
        "exposure_comp": safe_float(exif.get("ExposureCompensation")),
        "metering_mode": exif.get("MeteringMode"),
        "white_balance": exif.get("WhiteBalance"),
        "flash": exif.get("Flash"),
        "width": safe_int(exif.get("ImageWidth")),
        "height": safe_int(exif.get("ImageHeight")),
        "orientation": exif.get("Orientation"),
        "color_space": exif.get("ColorSpace"),
        "bit_depth": safe_int(exif.get("BitsPerSample")),
        "gps_lat": safe_float(exif.get("GPSLatitude")),
        "gps_lon": safe_float(exif.get("GPSLongitude")),
        "gps_alt": safe_float(exif.get("GPSAltitude")),
        "time_of_day": compute_time_of_day(hour),
        "season": compute_season(month),
        "has_jpeg": sidecars["has_jpeg"],
        "has_xmp": sidecars["has_xmp"],
        "has_on1": sidecars["has_on1"],
        "has_radiant": sidecars["has_radiant"],
        "sidecar_count": sidecars["sidecar_count"],
        "edited_anywhere": sidecars["edited_anywhere"],
        "orphan_jpeg": is_orphan_jpeg(fpath),
    }


# ============================================================
# INSERT / UPSERT
# ============================================================

INSERT_SQL = """
INSERT INTO images (
    file_path, file_name, file_type, file_size, volume, date_folder,
    camera_make, camera_model, camera_serial, camera_short, mount,
    lens_model, lens_serial,
    date_taken, aperture, shutter_speed, iso,
    focal_length, focal_length_35eq, exposure_comp,
    metering_mode, white_balance, flash,
    width, height, orientation, color_space, bit_depth,
    gps_lat, gps_lon, gps_alt,
    time_of_day, season,
    has_jpeg, has_xmp, has_on1, has_radiant,
    sidecar_count, edited_anywhere, orphan_jpeg
) VALUES (
    :file_path, :file_name, :file_type, :file_size, :volume, :date_folder,
    :camera_make, :camera_model, :camera_serial, :camera_short, :mount,
    :lens_model, :lens_serial,
    :date_taken, :aperture, :shutter_speed, :iso,
    :focal_length, :focal_length_35eq, :exposure_comp,
    :metering_mode, :white_balance, :flash,
    :width, :height, :orientation, :color_space, :bit_depth,
    :gps_lat, :gps_lon, :gps_alt,
    :time_of_day, :season,
    :has_jpeg, :has_xmp, :has_on1, :has_radiant,
    :sidecar_count, :edited_anywhere, :orphan_jpeg
)
ON CONFLICT(file_path) DO UPDATE SET
    file_size=excluded.file_size,
    camera_make=excluded.camera_make, camera_model=excluded.camera_model,
    camera_serial=excluded.camera_serial, camera_short=excluded.camera_short,
    mount=excluded.mount, lens_model=excluded.lens_model,
    lens_serial=excluded.lens_serial, date_taken=excluded.date_taken,
    aperture=excluded.aperture, shutter_speed=excluded.shutter_speed,
    iso=excluded.iso, focal_length=excluded.focal_length,
    focal_length_35eq=excluded.focal_length_35eq,
    exposure_comp=excluded.exposure_comp, metering_mode=excluded.metering_mode,
    white_balance=excluded.white_balance, flash=excluded.flash,
    width=excluded.width, height=excluded.height,
    orientation=excluded.orientation, color_space=excluded.color_space,
    bit_depth=excluded.bit_depth,
    gps_lat=excluded.gps_lat, gps_lon=excluded.gps_lon, gps_alt=excluded.gps_alt,
    time_of_day=excluded.time_of_day, season=excluded.season,
    has_jpeg=excluded.has_jpeg, has_xmp=excluded.has_xmp,
    has_on1=excluded.has_on1, has_radiant=excluded.has_radiant,
    sidecar_count=excluded.sidecar_count, edited_anywhere=excluded.edited_anywhere,
    orphan_jpeg=excluded.orphan_jpeg,
    updated_at=CURRENT_TIMESTAMP
"""


# ============================================================
# THUMBNAIL EXTRACTION
# ============================================================


def _resize_thumbnail(thumb_path, max_dim=300):
    """Resize thumbnail to max_dim on longest side. Uses sips on macOS, Pillow elsewhere."""
    if platform.system() == "Darwin":
        subprocess.run(["sips", "-Z", str(max_dim), str(thumb_path)], capture_output=True, timeout=10)
    else:
        try:
            from PIL import Image

            img = Image.open(thumb_path)
            img.thumbnail((max_dim, max_dim))
            img.save(thumb_path)
        except ImportError:
            pass  # no resize available — thumbnail will be full size


def extract_thumbnail_file_only(file_path, image_id):
    """Extract and resize thumbnail to disk only. No DB writes — safe to run in threads.
    Returns (image_id, thumb_path_str) on success, (image_id, None) on failure.

    Supports both RAW files (exiftool extraction) and JPEG files (direct resize).
    """
    fpath = Path(file_path)
    ext = fpath.suffix.lower()
    thumb_path = THUMB_DIR / f"{image_id}.jpg"

    if thumb_path.exists():
        return image_id, str(thumb_path)  # Already on disk

    if not fpath.exists():
        return image_id, None

    try:
        if ext in RAW_EXTENSIONS:
            # RAW: extract embedded JPEG via exiftool, then resize
            for tag in ["-JpgFromRaw", "-PreviewImage"]:
                result = subprocess.run(["exiftool", "-b", tag, str(fpath)], capture_output=True, timeout=10)
                if result.stdout and len(result.stdout) > 1000:
                    thumb_path.write_bytes(result.stdout)
                    _resize_thumbnail(thumb_path)
                    return image_id, str(thumb_path)
        elif ext in (".jpg", ".jpeg"):
            # JPEG: copy and resize directly
            shutil.copy2(str(fpath), str(thumb_path))
            _resize_thumbnail(thumb_path)
            return image_id, str(thumb_path)
    except (subprocess.TimeoutExpired, Exception):
        pass
    return image_id, None


def extract_thumbnail(file_path, image_id, conn):
    """Single-threaded wrapper — used during normal scan passes."""
    image_id, thumb_path = extract_thumbnail_file_only(file_path, image_id)
    if thumb_path:
        conn.execute(
            """INSERT OR REPLACE INTO thumbnails
               (image_id, thumb_path, generated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)""",
            (image_id, thumb_path),
        )


# ============================================================
# CONCURRENT THUMBNAIL PASS
# ============================================================


def _run_thumbnail_pass(conn):
    """Generate missing thumbnails using ThreadPoolExecutor.
    File I/O runs in parallel. DB writes happen sequentially in main thread.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cursor = conn.execute(
        """SELECT id, file_path FROM images
           WHERE id NOT IN (SELECT image_id FROM thumbnails)
           AND file_type IN ('RW2', 'NEF', 'RAF', 'ARW', 'CR3', 'DNG', 'ORF',
                             'JPG', 'JPEG')"""
    )
    rows = cursor.fetchall()
    total = len(rows)

    if total == 0:
        print("  No thumbnails to generate.")
        return

    print(f"\n[4/4] Extracting thumbnails ({total:,} files, {THUMB_WORKERS} workers)...")
    thumb_start = time.time()
    thumb_count = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=THUMB_WORKERS) as executor:
        future_to_row = {
            executor.submit(extract_thumbnail_file_only, file_path, image_id): (image_id, file_path)
            for image_id, file_path in rows
        }
        for future in as_completed(future_to_row):
            try:
                image_id, thumb_path = future.result()
                if thumb_path:
                    conn.execute(
                        """INSERT OR REPLACE INTO thumbnails
                           (image_id, thumb_path, generated_at)
                           VALUES (?, ?, CURRENT_TIMESTAMP)""",
                        (image_id, thumb_path),
                    )
                    thumb_count += 1
                else:
                    errors += 1
            except Exception:
                errors += 1

            if (thumb_count + errors) % 500 == 0:
                conn.commit()
                elapsed = time.time() - thumb_start
                rate = (thumb_count + errors) / elapsed if elapsed > 0 else 0
                remaining = (total - thumb_count - errors) / rate if rate > 0 else 0
                print(f"  [{thumb_count:,}/{total:,}] {rate:.0f}/sec ~{remaining:.0f}s remaining")

    conn.commit()
    elapsed = time.time() - thumb_start
    print(f"  Done: {thumb_count:,} thumbnails, {errors:,} errors in {elapsed:.1f}s")


# ============================================================
# MAIN SCAN
# ============================================================


def get_indexed_paths(conn):
    """Return set of all file_paths already in DB."""
    cursor = conn.execute("SELECT file_path FROM images")
    return {row[0] for row in cursor.fetchall()}


def show_stats(conn):
    """Print database statistics."""
    print("\n=== DAM Database Stats ===\n")

    total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    print(f"Total images indexed: {total:,}")

    if total == 0:
        return

    print("\nBy volume:")
    for row in conn.execute("SELECT volume, COUNT(*) c FROM images GROUP BY volume ORDER BY c DESC"):
        print(f"  {row[0]}: {row[1]:,}")

    print("\nBy camera:")
    for row in conn.execute("SELECT camera_short, COUNT(*) c FROM images GROUP BY camera_short ORDER BY c DESC"):
        print(f"  {row[0] or '(unknown)'}: {row[1]:,}")

    print("\nBy file type:")
    for row in conn.execute("SELECT file_type, COUNT(*) c FROM images GROUP BY file_type ORDER BY c DESC"):
        print(f"  {row[0]}: {row[1]:,}")

    print("\nSidecar coverage:")
    # Safety: field names are hardcoded string literals in the list above,
    # never derived from user input.
    for field in ["has_xmp", "has_on1", "has_radiant", "edited_anywhere"]:
        count = conn.execute(f"SELECT COUNT(*) FROM images WHERE {field}=1").fetchone()[0]
        pct = (count / total * 100) if total else 0
        print(f"  {field}: {count:,} ({pct:.1f}%)")

    orphans = conn.execute("SELECT COUNT(*) FROM images WHERE orphan_jpeg=1").fetchone()[0]
    print(f"\nOrphan JPEGs (no RAW): {orphans:,}")

    thumbs = conn.execute("SELECT COUNT(*) FROM thumbnails").fetchone()[0]
    print(f"Thumbnails cached: {thumbs:,}")

    print("\nEdit status:")
    for row in conn.execute("SELECT edit_status, COUNT(*) c FROM images GROUP BY edit_status ORDER BY c DESC"):
        print(f"  {row[0]}: {row[1]:,}")


def scan(volumes, rescan=False, dry_run=False, extract_thumbs=True):
    """Main scan entry point."""
    conn = init_db()

    print("=" * 60)
    print("DAM Scanner — Phase 1")
    print(f"DB: {DB_PATH}")
    print(f"Volumes: {', '.join(str(v) for v in volumes)}")
    print(f"Mode: {'DRY RUN' if dry_run else 'RESCAN' if rescan else 'INCREMENTAL'}")
    print("=" * 60)

    # Step 1: Discover files
    print("\n[1/4] Discovering primary files...")
    all_files = discover_primary_files(volumes)
    print(f"  Total primary files: {len(all_files):,}")

    if not all_files:
        print("Nothing to scan.")
        conn.close()
        return

    # Step 1b: Filter out JPEGs that have RAW siblings (they're sidecars, not primaries)
    before_filter = len(all_files)
    all_files = [f for f in all_files if f.suffix.lower() not in JPEG_EXTENSIONS or is_orphan_jpeg(f)]
    jpeg_sidecars = before_filter - len(all_files)
    if jpeg_sidecars:
        print(f"  Filtered {jpeg_sidecars:,} JPEG sidecars (have RAW siblings)")
    print(f"  Indexable primaries: {len(all_files):,}")

    # Step 2: Filter already-indexed (unless rescan)
    if rescan:
        to_scan = all_files
        print(f"\n[2/4] Rescan mode — processing all {len(to_scan):,} files")
    else:
        indexed = get_indexed_paths(conn)
        to_scan = [f for f in all_files if str(f) not in indexed]
        print(f"\n[2/4] Already indexed: {len(indexed):,}, new: {len(to_scan):,}")

    if not to_scan:
        print("Everything is already indexed. Use --rescan to force.")
        show_stats(conn)
        conn.close()
        return

    if dry_run:
        print(f"\n[DRY RUN] Would process {len(to_scan):,} files. Exiting.")
        conn.close()
        return

    # Step 3: Process in batches
    print(f"\n[3/4] Extracting EXIF and indexing ({BATCH_SIZE} files/batch)...")
    start_time = time.time()
    processed = 0
    errors = 0
    batch_num = 0

    for i in range(0, len(to_scan), BATCH_SIZE):
        batch = to_scan[i : i + BATCH_SIZE]
        batch_num += 1

        # Batch exiftool call
        exif_data = extract_exif_batch(batch)

        for fpath in batch:
            try:
                exif = exif_data.get(str(fpath), {})
                sidecars = detect_sidecars(fpath)
                row = build_row(fpath, exif, sidecars)
                conn.execute(INSERT_SQL, row)
                processed += 1
            except Exception as e:
                print(f"  ERROR: {fpath.name} — {e}")
                errors += 1

        conn.commit()

        # Progress report every 10 batches
        if batch_num % 10 == 0:
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            remaining = (len(to_scan) - processed) / rate if rate > 0 else 0
            print(f"  [{processed:,}/{len(to_scan):,}] {rate:.0f} files/sec, ~{remaining:.0f}s remaining")

    elapsed = time.time() - start_time

    print(f"\n  Done: {processed:,} indexed, {errors:,} errors in {elapsed:.1f}s")

    # Step 4: Thumbnail extraction
    if extract_thumbs:
        _run_thumbnail_pass(conn)

    # Show final stats
    show_stats(conn)
    conn.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    args = sys.argv[1:]
    flags = {a for a in args if a.startswith("--")}
    paths = [a for a in args if not a.startswith("--")]

    if "--stats" in flags:
        conn = init_db()
        show_stats(conn)
        conn.close()
        sys.exit(0)

    volumes = [Path(p) for p in paths] if paths else DEFAULT_VOLUMES

    # --no-scan: skip file discovery and indexing, only generate thumbnails
    if "--no-scan" in flags:
        conn = init_db()
        print("[Thumbnails only mode]")
        _run_thumbnail_pass(conn)
        conn.close()
        sys.exit(0)

    scan(
        volumes=volumes,
        rescan="--rescan" in flags,
        dry_run="--dry-run" in flags,
        extract_thumbs="--no-thumbs" not in flags,
    )
