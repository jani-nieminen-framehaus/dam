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

from dam_config import (
    DAM_ROOT,
    DB_PATH,
    DEFAULT_VOLUMES,
    GUNICORN_WORKERS,
    IGNORE_VOLUMES,
    PORT,
    VOLUME_ALIASES,
    WINDOW_SIZE,
    cmd_config,
)
from ingest_pipeline import SCANNER_SCRIPT, TAGGER_SCRIPT, run_ingest_pipeline
from platform_utils import open_path_external
from storage_utils import resolve_archive_file


def run(cmd, description):
    print(f"\nDAM ── {description}\n" + "-" * 50)
    result = subprocess.run(cmd)
    return result.returncode


def cmd_ingest(args):
    dry_run = "--dry-run" in args
    no_tag = "--no-tag" in args
    card_args = [a for a in args if not a.startswith("--")]
    result = run_ingest_pipeline(card_args, dry_run=dry_run, no_tag=no_tag)
    if result.returncode != 0:
        sys.exit(result.returncode)


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


def _parse_port(args):
    """Extract port from args, defaulting to configured PORT."""
    for i, a in enumerate(args):
        if a in ("-p", "--port") and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--port="):
            return a.split("=", 1)[1]
    return str(PORT)


def _serve_gunicorn(bind, env):
    """Start gunicorn — in-process when frozen, subprocess otherwise."""
    print("DAM ── Web server (gunicorn)\n" + "-" * 50)
    if getattr(sys, "frozen", False):
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

            _GunicornApp(flask_app, {"bind": bind, "workers": GUNICORN_WORKERS, "accesslog": "-", "errorlog": "-"}).run()
            return
        except Exception as e:
            print(f"Gunicorn failed to start: {e}")
            sys.exit(1)

    rc = subprocess.run(
        [sys.executable, "-m", "gunicorn", "-w", str(GUNICORN_WORKERS), "-b", bind, "dam_api:app"],
        cwd=str(DAM_ROOT),
        env=env,
    ).returncode
    sys.exit(rc)


class _DamBridge:
    """JS ↔ Python bridge exposed as `window.pywebview.api` in the frontend."""

    def __init__(self, win_ref):
        self._win_ref = win_ref

    def set_title(self, title):
        """Called from JS to update the window title."""
        w = self._win_ref()
        if w:
            w.set_title(title or "DAM")

    def start_ingest(self, card_path=None):
        """Trigger card ingest pipeline in a background thread."""
        import threading

        def _run():
            run_ingest_pipeline([card_path] if card_path else [], dry_run=False, no_tag=False)

        threading.Thread(target=_run, daemon=True).start()
        return {"status": "started"}

    def open_path(self, path):
        """Open a file or reveal its parent folder via the native shell."""
        target = Path(path).expanduser()
        if target.is_file() or (target.suffix and not target.is_dir()):
            target = target.parent
        open_path_external(target)
        return {"status": "opened"}

    def pick_folder(self):
        """Open a native folder picker dialog."""
        w = self._win_ref()
        if w:
            result = w.create_file_dialog(
                dialog_type=20,  # FOLDER_DIALOG
            )
            if result and len(result) > 0:
                return result[0]
        return None


def _serve_window(port):
    """Start Flask in a thread and open a pywebview desktop window."""
    print("DAM ── Desktop application\n" + "-" * 50)
    import socket
    import threading
    import time
    import weakref

    try:
        import webview
    except ImportError:
        print("ERROR: pywebview is not installed.")
        print("Install it: pip install pywebview")
        sys.exit(1)

    from dam_api import app as flask_app

    int_port = int(port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", int_port)) == 0:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
                s2.bind(("127.0.0.1", 0))
                int_port = s2.getsockname()[1]
            print(f"  Port {port} busy, using {int_port}")

    server_ready = threading.Event()

    def start_server():
        import werkzeug.serving

        original_inner = werkzeug.serving.make_server

        def patched_make_server(*a, **kw):
            srv = original_inner(*a, **kw)
            server_ready.set()
            return srv

        werkzeug.serving.make_server = patched_make_server
        flask_app.run(host="127.0.0.1", port=int_port, debug=False, use_reloader=False)

    threading.Thread(target=start_server, daemon=True).start()
    if not server_ready.wait(timeout=5.0):
        time.sleep(0.5)

    url = f"http://127.0.0.1:{int_port}"
    print(f"  Server: {url}")

    # -- Native menu bar --
    menu_items = [
        webview.menu.Menu(
            "File",
            [
                webview.menu.MenuAction("Ingest from Card...", lambda: _menu_ingest(win_ref)),
                webview.menu.MenuSeparator(),
                webview.menu.MenuAction("Close Window", lambda: _menu_close(win_ref)),
            ],
        ),
        webview.menu.Menu(
            "View",
            [
                webview.menu.MenuAction("Toggle Sidebar", lambda: _menu_js(win_ref, "document.querySelector('[data-sidebar-toggle]')?.click()")),
                webview.menu.MenuSeparator(),
                webview.menu.MenuAction("Zoom In", lambda: _menu_js(win_ref, "document.body.style.zoom = (parseFloat(document.body.style.zoom || 1) + 0.1).toString()")),
                webview.menu.MenuAction("Zoom Out", lambda: _menu_js(win_ref, "document.body.style.zoom = (Math.max(0.5, parseFloat(document.body.style.zoom || 1) - 0.1)).toString()")),
                webview.menu.MenuAction("Reset Zoom", lambda: _menu_js(win_ref, "document.body.style.zoom = '1'")),
            ],
        ),
    ]

    # Create window — start maximized for dual-monitor studio setup
    window = webview.create_window(
        "DAM",
        url,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=(800, 600),
    )

    win_ref = weakref.ref(window)
    bridge = _DamBridge(win_ref)
    window.expose(bridge.set_title, bridge.start_ingest, bridge.open_path, bridge.pick_folder)

    import platform

    if platform.system() == "Darwin":
        try:
            from Foundation import NSBundle

            bundle = NSBundle.mainBundle()
            info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
            if info:
                info["CFBundleName"] = "DAM"
        except ImportError:
            pass

    def _on_loaded():
        """Maximize window after first page load."""
        w = win_ref()
        if w:
            w.maximize()

    window.events.loaded += _on_loaded
    webview.start(menu=menu_items)


def _menu_ingest(win_ref):
    """Menu: trigger ingest."""
    w = win_ref()
    if w:
        w.evaluate_js("window.pywebview?.api?.start_ingest()")


def _menu_close(win_ref):
    """Menu: close the window."""
    w = win_ref()
    if w:
        w.destroy()


def _menu_js(win_ref, js):
    """Menu: run arbitrary JS in the window."""
    w = win_ref()
    if w:
        w.evaluate_js(js)


def _serve_flask_dev(port, env):
    """Start Flask dev server (fallback when gunicorn unavailable)."""
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


def cmd_serve(args):
    """Start the web API (and SPA). Prefers gunicorn; falls back to Flask dev server."""
    port = _parse_port(args)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(DAM_ROOT)

    try:
        import gunicorn  # noqa: F401
        has_gunicorn = True
    except ModuleNotFoundError:
        has_gunicorn = False

    if "--window" in args:
        _serve_window(port)
    elif has_gunicorn:
        _serve_gunicorn(f"0.0.0.0:{port}", env)
    else:
        _serve_flask_dev(port, env)


def _parse_export_args(args):
    """Parse export CLI arguments into a dict."""
    opts = {"dest": None, "rating_min": None, "pick": None, "edit_status": None, "format": "both", "dry_run": "--dry-run" in args}
    valued_flags = {"--dest": "dest", "--rating": "rating_min", "--pick": "pick", "--edit-status": "edit_status", "--format": "format"}
    i = 0
    while i < len(args):
        flag = valued_flags.get(args[i])
        if flag and i + 1 < len(args):
            opts[flag] = int(args[i + 1]) if flag == "rating_min" else args[i + 1]
            i += 2
        else:
            i += 1
    return opts


def _find_jpeg_sidecar(raw_path):
    """Derive JPEG sidecar path from RAW path."""
    p = Path(raw_path)
    for ext in (".JPG", ".jpg", ".JPEG", ".jpeg"):
        candidate = p.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


def _select_export_files(file_path, row, want_raw, want_jpeg):
    """Determine which files to export for a given image row."""
    files = []
    if row["orphan_jpeg"]:
        if want_jpeg:
            files.append(file_path)
    else:
        if want_raw:
            files.append(file_path)
        if want_jpeg and row["has_jpeg"]:
            jpeg = _find_jpeg_sidecar(file_path)
            if jpeg:
                files.append(jpeg)
    return files


def _export_file(src, dest_dir, dry_run, counters):
    """Copy a single file to dest_dir, updating counters dict in place."""
    import shutil

    src = Path(src)
    if not src.exists():
        counters["missing"] += 1
        if dry_run:
            print(f"  SKIP (not mounted): {src.name}")
        return
    target = dest_dir / src.name
    if target.exists():
        counters["exists"] += 1
        return
    size = src.stat().st_size
    if dry_run:
        print(f"  WOULD COPY: {src.name} ({size / (1024 * 1024):.1f} MB)")
    else:
        shutil.copy2(str(src), str(target))
    counters["exported"] += 1
    counters["bytes"] += size


def _validate_export_opts(opts):
    """Validate export options, exit on error. Returns (dest, fmt, dry_run)."""
    if not opts["dest"]:
        print("ERROR: --dest is required")
        print("Usage: dam export --dest ~/Export [--rating N] [--pick yes] [--format raw|jpeg|both] [--dry-run]")
        sys.exit(1)
    fmt = opts["format"]
    if fmt not in ("raw", "jpeg", "both"):
        print(f"ERROR: --format must be raw, jpeg, or both (got: {fmt})")
        sys.exit(1)
    return Path(opts["dest"]).expanduser().resolve(), fmt, opts["dry_run"]


def _query_export_rows(opts):
    """Query DB for images matching export filters."""
    import sqlite3

    clauses, params = [], []
    for field, col in [("rating_min", "rating >= ?"), ("pick", "pick = ?"), ("edit_status", "edit_status = ?")]:
        if opts[field] is not None:
            clauses.append(col)
            params.append(opts[field])

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT id, file_path, file_name, volume, relative_path, date_folder, has_jpeg, orphan_jpeg FROM images {where} ORDER BY date_taken DESC"

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def cmd_export(args):
    """Export picked/rated images to a destination folder."""
    opts = _parse_export_args(args)
    dest, fmt, dry_run = _validate_export_opts(opts)
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    rows = _query_export_rows(opts)
    if not rows:
        print("No images match the given filters.")
        return

    print(f"DAM Export — {'DRY RUN' if dry_run else 'EXPORT'}")
    print(f"Destination: {dest}")
    print(f"Format: {fmt}")
    print(f"Matching images: {len(rows)}")
    print("-" * 50)

    counters = {"exported": 0, "exists": 0, "missing": 0, "bytes": 0}
    want_raw = fmt in ("raw", "both")
    want_jpeg = fmt in ("jpeg", "both")

    for row in rows:
        resolved = resolve_archive_file(
            row["file_path"], row["volume"], row["relative_path"], DEFAULT_VOLUMES, IGNORE_VOLUMES, VOLUME_ALIASES
        )
        file_path = str(resolved) if resolved else row["file_path"]
        date_dir = dest / (row["date_folder"] or "undated")
        if not dry_run:
            date_dir.mkdir(parents=True, exist_ok=True)

        for f in _select_export_files(file_path, row, want_raw, want_jpeg):
            _export_file(f, date_dir, dry_run, counters)

    print(f"\n{'=' * 50}")
    print(f"{'Would export' if dry_run else 'Exported'}: {counters['exported']} files ({counters['bytes'] / (1024 * 1024):.1f} MB)")
    if counters["exists"]:
        print(f"Skipped (already exists): {counters['exists']}")
    if counters["missing"]:
        print(f"Skipped (volume not mounted): {counters['missing']}")


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
  serve [--port 5001] [--window]       Start web API & open local desktop window
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
