"""
DAM Config — centralised configuration for the photo DAM system.

Loads settings from ~/.dam/config.json with sensible defaults.
Auto-creates the config file on first run.

Usage from other modules:
    from dam_config import DB_PATH, THUMB_DIR, OLLAMA_BASE, ...
"""

import json
import os
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".dam"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "dam_root": str(Path.home() / "Documents" / "dam"),
    "db_path": None,  # derived: dam_root/dam.db
    "thumb_dir": None,  # derived: dam_root/thumbs
    "dest_root": "/Volumes/kuvia2",
    "default_volumes": ["/Volumes/Kuvia1", "/Volumes/kuvia2"],
    "ignore_volumes": [
        "Macintosh HD",
        "Macintosh HD - Data",
        "Preboot",
        "Recovery",
        "Kuvia1",
        "kuvia2",
        "Arkisto",
        "Kaikki kata",
        "T7",
        "Nuked one",
        "Dumppaus ko",
        "kv2",
        "com.apple.TimeMachine.localsnapshots",
    ],
    "ollama_base": "http://localhost:11434",
    "ollama_base_embed": None,
    "ollama_base_vision": None,
    "ollama_base_text": None,
    "vision_model": "llava:34b",
    "text_model": "llama3.1:70b",
    "embed_model": "nomic-embed-text",
    "embed_dim": 768,
    "model_ctx": 2048,
    "thumb_workers": 8,
    "batch_size": 100,
    "burst_gap_seconds": 2.0,
    "burst_min_size": 3,
    "port": 5000,
    "gunicorn_workers": 4,
    "page_size": 50,
    "window_size": [1200, 800],
    "poll_interval": 3,
    "ingest_timeout": 7200,
    "skip_path_patterns": [
        "/[Developed]/",
        "_proxy.",
        "_desktop_salvage_",
    ],
}


def _load_config():
    """Read config JSON, merge over defaults, derive paths."""
    cfg = dict(DEFAULTS)

    # Read user config if it exists
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                user = json.load(f)
            cfg.update(user)
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: Could not read {CONFIG_FILE}: {e}")
    else:
        # Auto-create config dir and file with defaults on first run
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump(DEFAULTS, f, indent=2)
        except OSError:
            pass  # non-fatal: defaults still work

    # Frozen binary override: PyInstaller sets dam_root to executable dir
    if getattr(sys, "frozen", False):
        cfg["dam_root"] = str(Path(sys.executable).resolve().parent)

    # Convert dam_root to Path and derive dependent paths
    cfg["dam_root"] = Path(cfg["dam_root"])
    if cfg["db_path"] is None:
        cfg["db_path"] = cfg["dam_root"] / "dam.db"
    else:
        cfg["db_path"] = Path(cfg["db_path"])
    if cfg["thumb_dir"] is None:
        cfg["thumb_dir"] = cfg["dam_root"] / "thumbs"
    else:
        cfg["thumb_dir"] = Path(cfg["thumb_dir"])

    cfg["dest_root"] = Path(cfg["dest_root"])
    cfg["default_volumes"] = [Path(v) for v in cfg["default_volumes"]]
    cfg["ignore_volumes"] = set(cfg["ignore_volumes"])

    return cfg


# Load once at import time — every module that imports dam_config gets these
_cfg = _load_config()

DAM_ROOT = _cfg["dam_root"]
DB_PATH = _cfg["db_path"]
THUMB_DIR = _cfg["thumb_dir"]
SPA_DIR = DAM_ROOT / "static"
DEST_ROOT = _cfg["dest_root"]
DEFAULT_VOLUMES = _cfg["default_volumes"]
IGNORE_VOLUMES = _cfg["ignore_volumes"]

OLLAMA_BASE = _cfg["ollama_base"]
OLLAMA_BASE_EMBED = _cfg.get("ollama_base_embed") or OLLAMA_BASE
OLLAMA_BASE_VISION = _cfg.get("ollama_base_vision") or OLLAMA_BASE
OLLAMA_BASE_TEXT = _cfg.get("ollama_base_text") or OLLAMA_BASE
VISION_MODEL = _cfg["vision_model"]
TEXT_MODEL = _cfg["text_model"]
EMBED_MODEL = _cfg["embed_model"]
EMBED_DIM = _cfg["embed_dim"]
MODEL_CTX = _cfg["model_ctx"]

THUMB_WORKERS = _cfg["thumb_workers"]
BATCH_SIZE = _cfg["batch_size"]
BURST_GAP_SECONDS = _cfg["burst_gap_seconds"]
BURST_MIN_SIZE = _cfg["burst_min_size"]

PORT = _cfg["port"]
GUNICORN_WORKERS = _cfg["gunicorn_workers"]
PAGE_SIZE = _cfg["page_size"]
WINDOW_SIZE = _cfg["window_size"]

POLL_INTERVAL = _cfg["poll_interval"]
INGEST_TIMEOUT = _cfg["ingest_timeout"]
SKIP_PATH_PATTERNS = _cfg["skip_path_patterns"]

# Progress file path (derived, used by card_ingest and dam_api)
INGEST_STATUS_FILE = DAM_ROOT / "ingest_status.json"


def cmd_config(args):
    """Print current config, open in editor, or show config path."""
    if "--path" in args:
        print(CONFIG_FILE)
        return

    if "--edit" in args:
        editor = os.environ.get("EDITOR", "nano")
        os.execvp(editor, [editor, str(CONFIG_FILE)])
        return

    # Default: pretty-print merged config
    out = {}
    for k, v in _cfg.items():
        if isinstance(v, Path):
            out[k] = str(v)
        elif isinstance(v, set):
            out[k] = sorted(v)
        elif isinstance(v, list) and v and isinstance(v[0], Path):
            out[k] = [str(p) for p in v]
        else:
            out[k] = v
    print(json.dumps(out, indent=2))
