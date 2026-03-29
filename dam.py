#!/opt/homebrew/bin/python3
# NOTE: Always invoke with /opt/homebrew/bin/python3 or via shebang.
# System python3 resolves to /Library/Frameworks/Python.framework which
# lacks sqlite_vec and other DAM dependencies.
"""
DAM Orchestrator — unified entry point for the photo DAM system.

Usage:
    python3 dam.py ingest               # detect card, copy, scan, thumbnail
    python3 dam.py ingest /path/card    # specify card path
    python3 dam.py ingest --dry-run     # preview ingest without copying
    python3 dam.py scan                 # incremental scan of default volumes
    python3 dam.py scan --rescan        # force rescan everything
    python3 dam.py thumbs               # generate missing thumbnails
    python3 dam.py stats                # show DB statistics
"""

import os
import subprocess
import sys
from pathlib import Path

# Guard: ensure we're running under a Python that has sqlite_vec (skip when frozen — bundle has deps)
if (
    sys.platform == "darwin"
    and not getattr(sys, "frozen", False)
    and "homebrew" not in sys.executable
    and "/opt/" not in sys.executable
):
    print(f"ERROR: Running under {sys.executable}")
    print("DAM requires homebrew python: /opt/homebrew/bin/python3 dam.py")
    sys.exit(1)

from dam_config import DAM_ROOT, DB_PATH, DEFAULT_VOLUMES, GUNICORN_WORKERS, IGNORE_VOLUMES, PORT, VOLUME_ALIASES, WINDOW_SIZE, cmd_config
from platform_utils import spawn_background_process
from storage_utils import resolve_archive_file

INGEST_SCRIPT = DAM_ROOT / "card_ingest.py"
SCANNER_SCRIPT = DAM_ROOT / "dam_scanner.py"
TAGGER_SCRIPT = DAM_ROOT / "dam_tagger.py"


def run(cmd, description):
    print(f"\nDAM ── {description}\n" + "-" * 50)
    result = subprocess.run(cmd)
    return result.returncode


def cmd_ingest(args):
    dry_run = "--dry-run" in args
    card_args = [a for a in args if not a.startswith("--")]

    ingest_cmd = [sys.executable, str(INGEST_SCRIPT)]
    if card_args:
        ingest_cmd.extend(card_args)
    if dry_run:
        ingest_cmd.append("--dry-run")

    rc = run(ingest_cmd, "STEP 1/4 — Card Ingest")
    if rc != 0:
        print(f"\nIngest failed (exit {rc}). Aborting.")
        sys.exit(rc)

    if dry_run:
        print("\nDry run complete. No DB changes made.")
        return

    rc = run([sys.executable, str(SCANNER_SCRIPT), "--no-thumbs"], "STEP 2/4 — Scanning New Files")
    if rc != 0:
        print(f"\nScan failed (exit {rc}). Thumbnails skipped.")
        sys.exit(rc)

    run([sys.executable, str(SCANNER_SCRIPT), "--no-scan"], "STEP 3/4 — Generating Thumbnails for New Files")

    # Step 4: AI tagging in background (takes minutes/hours, don't block)
    no_tag = "--no-tag" in args
    if no_tag:
        print("\nIngest complete (AI tagging skipped).")
    else:
        print("\nDAM ── STEP 4/4 — AI Tagging (background)\n" + "-" * 50)
        tag_log = DAM_ROOT / "tagger_run.log"
        spawn_background_process([sys.executable, str(TAGGER_SCRIPT)], tag_log, cwd=DAM_ROOT)
        print(f"  Tagger launched in background. Monitor: tail -f {tag_log}")
        print("\nIngest complete. AI tagging running in background.")


def cmd_scan(args):
    scan_cmd = [sys.executable, str(SCANNER_SCRIPT)]
    if "--rescan" in args:
        scan_cmd.append("--rescan")
    paths = [a for a in args if not a.startswith("--")]
    scan_cmd.extend(paths)
    sys.exit(run(scan_cmd, "Scanning volumes"))


def cmd_thumbs(_args):
    sys.exit(run([sys.executable, str(SCANNER_SCRIPT), "--no-scan"], "Generating missing thumbnails"))


def cmd_stats(_args):
    sys.exit(run([sys.executable, str(SCANNER_SCRIPT), "--stats"], "DAM Stats"))


def cmd_tag(args):
    tag_cmd = [sys.executable, str(TAGGER_SCRIPT), *args]
    sys.exit(run(tag_cmd, "AI Tagging"))


def cmd_search(args):
    if not args:
        print('Usage: dam search "your query"')
        sys.exit(1)
    search_cmd = [sys.executable, str(TAGGER_SCRIPT), "--search", *args]
    sys.exit(run(search_cmd, "Semantic Search"))


def cmd_serve(args):
    """Start the web API (and SPA). Prefers gunicorn; falls back to Flask dev server."""
    port = str(PORT)
    for i, a in enumerate(args):
        if a in ("-p", "--port") and i + 1 < len(args):
            port = args[i + 1]
            break
        if a.startswith("--port="):
            port = a.split("=", 1)[1]
            break
    env = os.environ.copy()
    env["PYTHONPATH"] = str(DAM_ROOT)
    api_module = "dam_api"
    bind = f"0.0.0.0:{port}"
    try:
        import gunicorn
    except ModuleNotFoundError:
        gunicorn = None

    if gunicorn is not None and "--window" not in args:
        print("DAM ── Web server (gunicorn)\n" + "-" * 50)
        if getattr(sys, "frozen", False):
            # When frozen, sys.executable is this DAM binary, not python; run gunicorn in-process.
            try:
                from gunicorn.app.base import BaseApplication

                sys.path.insert(0, str(DAM_ROOT))
                from dam_api import app as flask_app

                class _GunicornApp(BaseApplication):
                    def __init__(self, app, options=None):
                        self._app = app
                        self._options = options or {}
                        super().__init__()

                    def load_config(self):
                        for k, v in self._options.items():
                            if k in self.cfg.settings and v is not None:
                                self.cfg.set(k.lower(), v)

                    def load(self):
                        return self._app

                options = {
                    "bind": bind,
                    "workers": GUNICORN_WORKERS,
                    "accesslog": "-",
                    "errorlog": "-",
                }
                _GunicornApp(flask_app, options).run()
                return
            except Exception as e:
                print(f"Gunicorn failed to start: {e}")
                sys.exit(1)

        rc = subprocess.run(
            [sys.executable, "-m", "gunicorn", "-w", str(GUNICORN_WORKERS), "-b", bind, f"{api_module}:app"],
            cwd=str(DAM_ROOT),
            env=env,
        ).returncode
        sys.exit(rc)

    use_window = "--window" in args

    if use_window:
        print("DAM ── Desktop application\n" + "-" * 50)
        import socket
        import threading
        import time

        try:
            import webview
        except ImportError:
            print("ERROR: pywebview is not installed.")
            print("Install it: pip install pywebview")
            sys.exit(1)

        from dam_api import app as flask_app

        # Pick a free port if the default is busy
        int_port = int(port)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", int_port)) == 0:
                # Port is taken — find a free one
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
                    s2.bind(("127.0.0.1", 0))
                    int_port = s2.getsockname()[1]
                print(f"  Port {port} busy, using {int_port}")

        server_ready = threading.Event()

        def start_server():
            # Signal ready once the first request can be served
            import werkzeug.serving

            original_inner = werkzeug.serving.make_server

            def patched_make_server(*a, **kw):
                srv = original_inner(*a, **kw)
                server_ready.set()
                return srv

            werkzeug.serving.make_server = patched_make_server
            flask_app.run(host="127.0.0.1", port=int_port, debug=False, use_reloader=False)

        t = threading.Thread(target=start_server, daemon=True)
        t.start()

        # Wait for server to actually bind (up to 5s)
        if not server_ready.wait(timeout=5.0):
            # Fallback: just give it a bit more time
            time.sleep(0.5)

        url = f"http://127.0.0.1:{int_port}"
        print(f"  Server: {url}")
        print(f"  Window: {WINDOW_SIZE[0]}x{WINDOW_SIZE[1]}")

        webview.create_window("DAM", url, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1])

        # Fix macOS Dock showing "Python" instead of "DAM"
        import platform

        if platform.system() == "Darwin":
            try:
                from Foundation import NSBundle

                bundle = NSBundle.mainBundle()
                info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
                if info:
                    info["CFBundleName"] = "DAM"
            except ImportError:
                pass  # PyObjC not available — Dock will show "Python"

        webview.start()
        return

    print("DAM ── Web server (Flask dev)\n" + "-" * 50)
    print("Install gunicorn for production: pip install gunicorn")

    if getattr(sys, "frozen", False):
        sys.path.insert(0, str(DAM_ROOT))
        from dam_api import app as flask_app

        flask_app.run(host="0.0.0.0", port=int(port))
        return
    subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, {str(DAM_ROOT)!r}); from dam_api import app; app.run(host='0.0.0.0', port={int(port)})",
        ],
        env=env,
    )


def cmd_export(args):
    """Export picked/rated images to a destination folder."""
    import shutil
    import sqlite3

    dest = None
    rating_min = None
    pick = None
    edit_status = None
    fmt = "both"
    dry_run = "--dry-run" in args

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--dest" and i + 1 < len(args):
            dest = args[i + 1]
            i += 2
        elif a == "--rating" and i + 1 < len(args):
            rating_min = int(args[i + 1])
            i += 2
        elif a == "--pick" and i + 1 < len(args):
            pick = args[i + 1]
            i += 2
        elif a == "--edit-status" and i + 1 < len(args):
            edit_status = args[i + 1]
            i += 2
        elif a == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
            i += 2
        elif a == "--dry-run":
            i += 1
        else:
            i += 1

    if not dest:
        print("ERROR: --dest is required")
        print("Usage: dam export --dest ~/Export [--rating N] [--pick yes] [--format raw|jpeg|both] [--dry-run]")
        sys.exit(1)

    if fmt not in ("raw", "jpeg", "both"):
        print(f"ERROR: --format must be raw, jpeg, or both (got: {fmt})")
        sys.exit(1)

    dest = Path(dest).expanduser().resolve()
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    # Build query
    clauses, params = [], []
    if rating_min is not None:
        clauses.append("rating >= ?")
        params.append(rating_min)
    if pick:
        clauses.append("pick = ?")
        params.append(pick)
    if edit_status:
        clauses.append("edit_status = ?")
        params.append(edit_status)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        "SELECT id, file_path, file_name, volume, relative_path, date_folder, has_jpeg, orphan_jpeg "
        f"FROM images {where} ORDER BY date_taken DESC"
    )

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    if not rows:
        print("No images match the given filters.")
        return

    exported = 0
    skipped_exists = 0
    skipped_missing = 0
    total_bytes = 0

    def _jpeg_path_for(raw_path):
        """Derive JPEG sidecar path from RAW path."""
        p = Path(raw_path)
        for ext in (".JPG", ".jpg", ".JPEG", ".jpeg"):
            candidate = p.with_suffix(ext)
            if candidate.exists():
                return candidate
        return None

    def _copy_file(src, dest_dir, dry_run):
        nonlocal exported, skipped_exists, skipped_missing, total_bytes
        src = Path(src)
        if not src.exists():
            skipped_missing += 1
            if dry_run:
                print(f"  SKIP (not mounted): {src.name}")
            return
        target = dest_dir / src.name
        if target.exists():
            skipped_exists += 1
            return
        size = src.stat().st_size
        if dry_run:
            print(f"  WOULD COPY: {src.name} ({size / (1024 * 1024):.1f} MB)")
        else:
            shutil.copy2(str(src), str(target))
        exported += 1
        total_bytes += size

    mode = "DRY RUN" if dry_run else "EXPORT"
    print(f"DAM Export — {mode}")
    print(f"Destination: {dest}")
    print(f"Format: {fmt}")
    if rating_min:
        print(f"Rating >= {rating_min}")
    if pick:
        print(f"Pick = {pick}")
    if edit_status:
        print(f"Edit status = {edit_status}")
    print(f"Matching images: {len(rows)}")
    print("-" * 50)

    for row in rows:
        resolved = resolve_archive_file(
            row["file_path"], row["volume"], row["relative_path"], DEFAULT_VOLUMES, IGNORE_VOLUMES, VOLUME_ALIASES
        )
        file_path = str(resolved) if resolved else row["file_path"]
        date_folder = row["date_folder"] or "undated"
        is_orphan = row["orphan_jpeg"]

        date_dir = dest / date_folder
        if not dry_run:
            date_dir.mkdir(parents=True, exist_ok=True)

        if is_orphan:
            # Primary file IS the JPEG
            if fmt in ("jpeg", "both"):
                _copy_file(file_path, date_dir, dry_run)
            elif fmt == "raw":
                pass  # orphan JPEG has no RAW
        else:
            # Primary file is RAW
            if fmt in ("raw", "both"):
                _copy_file(file_path, date_dir, dry_run)
            if fmt in ("jpeg", "both") and row["has_jpeg"]:
                jpeg = _jpeg_path_for(file_path)
                if jpeg:
                    _copy_file(jpeg, date_dir, dry_run)

    print(f"\n{'=' * 50}")
    print(f"{'Would export' if dry_run else 'Exported'}: {exported} files ({total_bytes / (1024 * 1024):.1f} MB)")
    if skipped_exists:
        print(f"Skipped (already exists): {skipped_exists}")
    if skipped_missing:
        print(f"Skipped (volume not mounted): {skipped_missing}")


COMMANDS = {
    "ingest": cmd_ingest,
    "scan": cmd_scan,
    "thumbs": cmd_thumbs,
    "stats": cmd_stats,
    "tag": cmd_tag,
    "search": cmd_search,
    "serve": cmd_serve,
    "export": cmd_export,
    "config": cmd_config,
}

HELP = """
DAM Orchestrator

Commands:
  ingest [path] [--dry-run] [--no-tag] Copy card, scan, thumbnails, AI tag
  scan [path] [--rescan]               Scan volumes (incremental by default)
  thumbs                               Generate missing thumbnails
  stats                                Show database statistics
  tag [--sample N] [--limit N]         AI tag images (burst stacking ON by default)
  search "query"                       Semantic search across tagged images
  serve [--port 5000] [--window]       Start web API & open local desktop window
  export --dest PATH [--rating N]     Export picks to folder (--pick, --edit-status, --format, --dry-run)
  config [--edit] [--path]             Show, edit, or locate config file
"""

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(HELP)
        sys.exit(0)
    command = args[0]
    if command not in COMMANDS:
        print(f"Unknown command: {command}")
        print(HELP)
        sys.exit(1)
    COMMANDS[command](args[1:])
