# Ingest Monitor — Design Spec

**Date:** 2026-04-10  
**Status:** Approved  
**Author:** viilu + Claude  

---

## Overview

Replace the three bare `osascript` notifications (card detected, ingest done, ingest failed) with a rich, persistent progress window that covers the full ingest pipeline — file copy through AI tagging. The user sees one window per card insertion, stays open until manually dismissed, and always knows exactly where the pipeline is and where to find the logs.

---

## Goals

- Show real-time progress (count, phase, progress bar) for both copy and tagging phases
- Display the actual JPEG being processed as a live preview thumbnail
- Surface the most recent AI keywords as they are written
- Show the log file path and make it one click to open
- Work on macOS natively; degrade gracefully on Windows
- Mirror the same information in the existing web UI

---

## Architecture

Four layers, each with a single responsibility:

| Layer | What | Where |
|---|---|---|
| Tagger status file | `dam_tagger.py` writes `tagger_status.json` per image | Python backend |
| Native monitor window | `ingest_monitor.py` — PySide6 floating panel | New Python script |
| Platform abstraction | `platform_utils.launch_ingest_monitor()` | `platform_utils.py` |
| Web UI banner | `IngestMonitor.tsx` — collapsible banner in React app | Frontend |

All components are read-only consumers of two JSON status files. No IPC, no sockets.

---

## Layer 1: Tagger Status File

### New file: `tagger_status.json`

Written by `dam_tagger.py` after every completed image. Lives at `DAM_ROOT / "tagger_status.json"`.

```json
{
  "status": "tagging",
  "current": 142,
  "total": 387,
  "current_path": "2026-04-07/DSCF2601.JPG",
  "last_keywords": ["coastal", "fog", "lone figure", "documentary"],
  "timestamp": "2026-04-10T08:14:22.441"
}
```

**`status` values:** `idle` | `tagging` | `done` | `error`

- Written `tagging` after each image completes
- Written `done` on clean exit
- Written `error` on unhandled exception
- `last_keywords` is the keyword list from the most recently tagged image only (not cumulative)
- `current_path` uses the same relative format as `last_ingest.json` (`YYYY-MM-DD/FILENAME.JPG`)

### New config constant

```python
# dam_config.py
TAGGER_STATUS_FILE = DAM_ROOT / "tagger_status.json"
```

### `dam_tagger.py` changes

- Import `TAGGER_STATUS_FILE`
- Write status at the start of a run (`status: tagging, current: 0, total: N`)
- Write status after each image completes (current path + keywords)
- Write `done` on clean exit, `error` in the exception handler
- Write is non-fatal (wrapped in `try/except OSError`)

---

## Layer 2: Ingest Status File — Additions

### `ingest_status.json` gains `current_path` and `dest_root`

`card_ingest.py`'s `_update_ingest_status()` adds two fields:
- `current_path` — relative path of the file currently being copied
- `dest_root` — absolute path of the destination volume (written from the first status update onward)

```json
{
  "status": "copying",
  "current": 47,
  "total": 387,
  "current_path": "2026-04-07/DSCF2536.JPG",
  "dest_root": "/Volumes/Photos2",
  "timestamp": "2026-04-10T07:58:12.001"
}
```

`current_path` is omitted during `scanning` phase. `dest_root` is present in every write after the destination is chosen.

### `dam_scanner.py` writes phase status

`dam_scanner.py` gains two `_update_ingest_status()` calls (imported from `card_ingest` or extracted to a shared helper in `dam_config`):
- On scan start: `{"status": "scanning_db", ...}`
- On thumbnail generation start: `{"status": "thumbs", ...}`

This closes the gap where the Scan and Thumbs phases were invisible to the monitor.

---

## Layer 3: Native Monitor Window (`ingest_monitor.py`)

### Framework

**PySide6** — cross-platform (macOS + Windows), smooth animations via `QPropertyAnimation`. Added to `requirements.txt` and `pyproject.toml`.

### Invocation

Launched by `card_watcher.py` via `platform_utils.launch_ingest_monitor()` as a background subprocess. Only `vol_name` is passed — `dest_root` is not known at card-detection time and is read from `ingest_status.json` once ingest starts writing it.

```bash
python3 ingest_monitor.py --vol "Archive 2"
```

The script runs its own `QApplication` event loop, independent of the watcher process. On first few polls before `ingest_status.json` exists, the window shows "Starting..." with an indeterminate progress bar.

### Window

A `QDialog` with `Qt.WindowStaysOnTopHint` — floats above other windows. Fixed width ~420px, height auto. Not resizable.

### Layout (top to bottom)

```
┌─ DAM — Archive 2 ────────────────────────────────────────────┐
│                                                               │
│  ● Copy   ○ Scan   ○ Thumbs   ○ Tag                          │
│                                                               │
│  ┌────────────────────┐   142 of 387 photos                  │
│  │                    │                                       │
│  │   [JPEG preview]   │   coastal · fog · lone figure        │
│  │                    │   (tagging phase only)                │
│  └────────────────────┘                                       │
│                                                               │
│  ████████████████░░░░░░░░░░░░  (progress bar)                │
│                                                               │
│  ~/Documents/dam/card_watcher.log        [Open in Finder]    │
└───────────────────────────────────────────────────────────────┘
```

### Animations

All animations use `QPropertyAnimation` with `OutCubic` easing:

| Element | Animation | Duration |
|---|---|---|
| Progress bar | `value` property, old → new | 300ms |
| Thumbnail | Opacity fade out → swap image → fade in | 200ms each |
| Phase dot | Custom `color` property, grey → gold | 200ms |

Animation objects stored as instance attributes to prevent GC mid-animation.

### Phase dots

Four dots: Copy → Scan → Thumbs → Tag. Each lights up (grey → `#c8a96e`, matching the app accent) when its phase becomes active. Completed phases stay lit.

Phase is derived from the `status` field in `ingest_status.json`:
- `copying` → Copy dot lit
- `scanning_db` → Copy done, Scan dot lit
- `thumbs` → Copy + Scan done, Thumbs dot lit
- `idle` on ingest + `tagging` in `tagger_status.json` → all three done, Tag dot lit

### Thumbnail

`QLabel` with `setPixmap`, 280×186px. During copy phase: reads the file at `dest_root / current_path` directly from disk. During tagging phase: resolves `THUMB_DIR / current_path` (replacing extension with `.jpg`). Falls back to a grey placeholder if file not found yet.

### Keywords line

Visible only during tagging phase. Shows `last_keywords` from `tagger_status.json` joined with ` · `. Hidden (zero height) during copy/scan/thumb phases.

### Log path

Small dim text at the bottom. `QPushButton` styled as a link: "Open in Finder" calls `QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir))`.

### Error state

If either status file shows `error`, the title bar background turns red (`#e05555`) and text reads "Ingest failed — see log". Progress bar stops animating. Window stays open.

### Polling

`QTimer` fires every 2 seconds on the main thread. Reads both JSON files. Only triggers animations when values actually change (compare new vs current before animating).

### Done state

When `ingest_status.json` shows `idle` AND `tagger_status.json` shows `done`, the progress bar fills to 100% (animated), all phase dots light up, and the title changes to "DAM — Done". Window stays open until user closes it. No auto-close.

---

## Layer 4: Platform Abstraction

### `platform_utils.py` addition

```python
def launch_ingest_monitor(vol_name: str, dest_root: str) -> None:
    """Launch the ingest monitor window as a background subprocess (macOS + Windows)."""
    if not is_macos() and sys.platform != 'win32':
        return  # Linux/other: no GUI, rely on terminal logs
    monitor_script = Path(__file__).parent / "ingest_monitor.py"
    if not monitor_script.exists():
        return
    subprocess.Popen(
        [sys.executable, str(monitor_script), "--vol", vol_name, "--dest-root", dest_root],
        start_new_session=True,
    )
```

### `card_watcher.py` changes

Replace the three `notify()` calls with one `launch_ingest_monitor()` call at card detection. The bare osascript notifications are removed entirely. On error/timeout, `ingest_monitor.py` detects the error state from the status file — no separate notification needed.

```python
# card_watcher.py — run_ingest()
from platform_utils import launch_ingest_monitor

def run_ingest(card_path):
    vol_name = Path(card_path).name
    dest_root = choose_ingest_destination(...)  # already called inside dam.py, but vol can be derived
    launch_ingest_monitor(vol_name, str(dest_root))
    # ... rest unchanged
```

`vol_name` and `dest_root` are passed as strings. The monitor reads the status files itself — the watcher doesn't need to send any further signals.

---

## Layer 5: Web UI

### Backend — new endpoint

```python
# dam_api.py
@app.route("/api/tagger/status", methods=["GET"])
def tagger_status():
    f = TAGGER_STATUS_FILE
    if not f.exists():
        return jsonify({"status": "idle"})
    try:
        return jsonify(json.load(open(f)))
    except Exception:
        return jsonify({"status": "idle"})

@app.route("/api/ingest/preview")
def ingest_preview():
    """Serve the current file being ingested as an image (copy phase live preview)."""
    try:
        data = json.load(open(INGEST_STATUS_FILE))
        if not data.get("current_path") or not data.get("dest_root"):
            return ("", 204)
        path = Path(data["dest_root"]) / data["current_path"]
        if not path.exists():
            return ("", 204)
        return send_file(path, mimetype="image/jpeg")
    except Exception:
        return ("", 204)
```

### Frontend — `ingest.ts` fixes

- `IngestStatus.status` type corrected: `'idle' | 'scanning' | 'copying' | 'error'`
- `IngestStatus` gains `current_path?: string`
- New `TaggerStatus` interface and `useTagStatus()` hook, identical structure to `useIngestStatus()`, polling `/api/tagger/status`
- `useTagStatus()` includes the same "was tagging → now done → invalidate grid" side effect

### Frontend — `StatusBar.tsx`

Remove the existing ingest progress bar and text from `StatusBar`. It is replaced by the new `IngestMonitor` component.

### Frontend — `IngestMonitor.tsx`

New file at `frontend/src/components/layout/IngestMonitor.tsx`.

**Visibility:** rendered in `App.tsx` between `<Toolbar>` and the sidebar/grid flex row. Visible when `ingestStatus.status !== 'idle'` OR `tagStatus.status === 'tagging'`.

**Collapsed state:** stored in Zustand (`ingestMonitorCollapsed: boolean`). When collapsed, only a single-line strip is shown: phase pill + thin progress bar + counter. Click anywhere on the strip to expand.

**Expanded layout:**

```
┌─ DAM — Ingesting Archive 2 ─────────────────────────── ∨ ──┐
│  [Copy ●]  [Scan ○]  [Thumbs ○]  [Tag ○]                   │
│                                                              │
│  [thumb 80×54]  142 / 387  ·  coastal · fog · lone figure   │
│                                                              │
│  ████████████████████░░░░░░░░░░  (Tailwind transition-all)  │
│                                                              │
│  ~/Documents/dam/card_watcher.log          [copy path]      │
└──────────────────────────────────────────────────────────────┘
```

**Thumbnail source:**
- Copy phase: `<img src="/api/ingest/preview" key={ingestStatus.current_path} />` — `key` change forces re-render on new file
- Tagging phase: `<img src={`/api/thumbs/${tagStatus.current_path}`} />`

**Progress bar:** CSS `transition-all duration-300` on the `width` style property — smooth fill without JS animation library.

**Phase pills:** four inline badges. Active phase gets `bg-[var(--accent)] text-black`, completed phases `bg-[var(--bg3)] text-[var(--accent)]`, pending phases `bg-[var(--bg3)] text-[var(--text-dim)]`.

**Keywords:** `tagStatus.last_keywords?.join(' · ')` — rendered only during tagging phase alongside the thumbnail.

**Log path:** `onClick` calls `window.pywebview?.api?.open_path(logPath)` if in the desktop wrapper; otherwise `navigator.clipboard.writeText(logPath)` with a "Copied" toast.

---

## Files Changed / Created

| File | Change |
|---|---|
| `dam_config.py` | Add `TAGGER_STATUS_FILE` constant |
| `dam_tagger.py` | Write `tagger_status.json` per image |
| `card_ingest.py` | Add `current_path` + `dest_root` to `_update_ingest_status()` |
| `dam_scanner.py` | Write `scanning_db` and `thumbs` phase statuses |
| `card_watcher.py` | Replace 3 notify calls with `launch_ingest_monitor()` |
| `platform_utils.py` | Add `launch_ingest_monitor()` function |
| `dam_api.py` | Add `/api/tagger/status` and `/api/ingest/preview` endpoints |
| `ingest_monitor.py` | **New** — PySide6 floating panel |
| `requirements.txt` | Add `PySide6>=6.6` |
| `pyproject.toml` | Add `PySide6>=6.6` to dependencies |
| `frontend/src/api/ingest.ts` | Fix types, add `useTagStatus` hook |
| `frontend/src/components/layout/IngestMonitor.tsx` | **New** — React banner component |
| `frontend/src/components/layout/StatusBar.tsx` | Remove ingest progress strip |
| `frontend/src/App.tsx` | Mount `<IngestMonitor>` between toolbar and grid |
| `frontend/src/stores/useUIStore.ts` | Add `ingestMonitorCollapsed` state |

---

## Out of Scope

- Persistent log of all historical ingests (separate feature)
- Tagger progress per-worker (workers complete out of order; current/total is sufficient)
- Linux desktop notifications
- Sound effects on completion
