# Ingest Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace bare osascript notifications with a persistent PySide6 progress window and a web UI banner covering the full ingest pipeline — copy through AI tagging.

**Architecture:** Two JSON status files (`ingest_status.json`, `tagger_status.json`) act as the shared source of truth. A PySide6 floating window (`ingest_monitor.py`) and a React banner (`IngestMonitor.tsx`) both poll these files independently. The native window is launched as a subprocess by `card_watcher.py`; the web banner runs whenever the app is open.

**Tech Stack:** Python 3.14, PySide6 ≥ 6.6, React 18 + TypeScript + Tailwind CSS v4, TanStack Query, Zustand, pytest, Flask

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `dam_config.py` | Modify | Add `TAGGER_STATUS_FILE` constant |
| `card_ingest.py` | Modify | Add `current_path` + `dest_root` to `_update_ingest_status()` |
| `dam_scanner.py` | Modify | Write `scanning_db` and `thumbs` phase statuses |
| `dam_tagger.py` | Modify | Write `tagger_status.json` per image; add `relative_path` + `id` to SELECT |
| `dam_api.py` | Modify | Add `/api/tagger/status` + `/api/ingest/preview` endpoints |
| `ingest_monitor.py` | **Create** | PySide6 floating progress window |
| `platform_utils.py` | Modify | Add `launch_ingest_monitor()` |
| `card_watcher.py` | Modify | Replace 3 notify calls with `launch_ingest_monitor()` |
| `requirements.txt` | Modify | Add `PySide6>=6.6` |
| `pyproject.toml` | Modify | Add `PySide6>=6.6` to dependencies |
| `frontend/src/api/ingest.ts` | Modify | Fix `IngestStatus` type; add `TaggerStatus` + `useTagStatus` |
| `frontend/src/stores/useUIStore.ts` | Modify | Add `ingestMonitorCollapsed` boolean + toggle |
| `frontend/src/components/layout/IngestMonitor.tsx` | **Create** | Collapsible React banner |
| `frontend/src/components/layout/StatusBar.tsx` | Modify | Remove existing ingest progress strip |
| `frontend/src/App.tsx` | Modify | Mount `<IngestMonitor>` between toolbar and grid |
| `tests/test_ingest_monitor_backend.py` | **Create** | Tests for status file writes + Flask endpoints |

---

## Task 1: Add `TAGGER_STATUS_FILE` to `dam_config.py`

**Files:**
- Modify: `dam_config.py:157-158`

- [ ] **Step 1: Add the constant**

Open `dam_config.py`. After line 158 (`LAST_INGEST_FILE = DAM_ROOT / "last_ingest.json"`), add:

```python
TAGGER_STATUS_FILE = DAM_ROOT / "tagger_status.json"
```

- [ ] **Step 2: Verify**

```bash
cd ~/Documents/dam
python3 -c "from dam_config import TAGGER_STATUS_FILE; print(TAGGER_STATUS_FILE)"
```
Expected output: `/Users/<you>/Documents/dam/tagger_status.json`

- [ ] **Step 3: Commit**

```bash
git add dam_config.py
git commit -m "feat: add TAGGER_STATUS_FILE config constant"
```

---

## Task 2: Add `current_path` + `dest_root` to ingest status writes

**Files:**
- Modify: `card_ingest.py:130-237`
- Test: `tests/test_ingest_monitor_backend.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingest_monitor_backend.py`:

```python
"""Tests for ingest monitor — status file writes and Flask endpoints."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_update_ingest_status_includes_current_path_and_dest_root(tmp_path):
    """_update_ingest_status writes current_path and dest_root to JSON."""
    import dam_config
    orig = dam_config.INGEST_STATUS_FILE
    dam_config.INGEST_STATUS_FILE = tmp_path / "ingest_status.json"

    try:
        from card_ingest import _update_ingest_status
        _update_ingest_status(
            dam_config.INGEST_STATUS_FILE,
            "copying",
            current=5,
            total=100,
            current_path="2026-04-07/DSCF2601.JPG",
            dest_root="/Volumes/Photos2",
        )
        data = json.loads(dam_config.INGEST_STATUS_FILE.read_text())
        assert data["current_path"] == "2026-04-07/DSCF2601.JPG"
        assert data["dest_root"] == "/Volumes/Photos2"
        assert data["status"] == "copying"
        assert data["current"] == 5
        assert data["total"] == 100
    finally:
        dam_config.INGEST_STATUS_FILE = orig


def test_update_ingest_status_current_path_defaults_to_none(tmp_path):
    """current_path absent from JSON when not provided."""
    import dam_config
    orig = dam_config.INGEST_STATUS_FILE
    dam_config.INGEST_STATUS_FILE = tmp_path / "ingest_status.json"

    try:
        from card_ingest import _update_ingest_status
        _update_ingest_status(dam_config.INGEST_STATUS_FILE, "scanning")
        data = json.loads(dam_config.INGEST_STATUS_FILE.read_text())
        assert data.get("current_path") is None
    finally:
        dam_config.INGEST_STATUS_FILE = orig
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd ~/Documents/dam
/opt/homebrew/bin/pytest tests/test_ingest_monitor_backend.py::test_update_ingest_status_includes_current_path_and_dest_root -v
```
Expected: FAIL — `TypeError: _update_ingest_status() got unexpected keyword argument 'current_path'`

- [ ] **Step 3: Update `_update_ingest_status` in `card_ingest.py`**

Replace the function at line 130 (current signature ends at line ~137):

```python
def _update_ingest_status(progress_file, status, current=0, total=0, current_path=None, dest_root=None):
    """Write ingest progress to status file (non-fatal on error)."""
    try:
        with open(progress_file, "w") as f:
            json.dump(
                {
                    "status": status,
                    "current": current,
                    "total": total,
                    "current_path": current_path,
                    "dest_root": dest_root,
                    "timestamp": datetime.now().isoformat(),
                },
                f,
            )
    except OSError:
        pass
```

- [ ] **Step 4: Thread `dest_root` through `ingest()` and `current_path` through `_copy_date_group()`**

In `ingest()` (around line 247), update the status write at scan start:

```python
_update_ingest_status(progress_file, "scanning", 0, 0, dest_root=str(dest_root))
```

In `ingest()` (around line 275), update the idle/done write:

```python
_update_ingest_status(progress_file, "idle", total, total, dest_root=str(dest_root))
```

In `_copy_date_group()` (around line 213), update the per-file write inside the `for fpath, fname in iterator` loop:

```python
_update_ingest_status(
    progress_file, "copying",
    sum(counters.values()), total,
    current_path=f"{date}/{fname}",
    dest_root=str(dest_root),
)
```

- [ ] **Step 5: Run tests**

```bash
/opt/homebrew/bin/pytest tests/test_ingest_monitor_backend.py -v
```
Expected: 2 PASS

- [ ] **Step 6: Run full test suite**

```bash
/opt/homebrew/bin/pytest tests/ -q
```
Expected: all 120+ tests pass

- [ ] **Step 7: Commit**

```bash
git add card_ingest.py tests/test_ingest_monitor_backend.py
git commit -m "feat: add current_path and dest_root to ingest status writes"
```

---

## Task 3: Add phase status writes to `dam_scanner.py`

**Files:**
- Modify: `dam_scanner.py:35` (imports) and `dam_scanner.py:855-858` (scan body)
- Test: `tests/test_ingest_monitor_backend.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingest_monitor_backend.py`:

```python
def test_write_ingest_phase_writes_status(tmp_path):
    """_write_ingest_phase writes the given status string to INGEST_STATUS_FILE."""
    import dam_config
    orig = dam_config.INGEST_STATUS_FILE
    dam_config.INGEST_STATUS_FILE = tmp_path / "ingest_status.json"

    try:
        from dam_scanner import _write_ingest_phase
        _write_ingest_phase("scanning_db")
        data = json.loads(dam_config.INGEST_STATUS_FILE.read_text())
        assert data["status"] == "scanning_db"
        assert "timestamp" in data
    finally:
        dam_config.INGEST_STATUS_FILE = orig
```

- [ ] **Step 2: Run to confirm failure**

```bash
/opt/homebrew/bin/pytest tests/test_ingest_monitor_backend.py::test_write_ingest_phase_writes_status -v
```
Expected: FAIL — `ImportError: cannot import name '_write_ingest_phase'`

- [ ] **Step 3: Add import and helper to `dam_scanner.py`**

At line 35, add `INGEST_STATUS_FILE` to the `dam_config` import:

```python
from dam_config import BATCH_SIZE, DB_PATH, DEFAULT_VOLUMES, IGNORE_VOLUMES, INGEST_STATUS_FILE, THUMB_DIR, THUMB_WORKERS, VOLUME_ALIASES
```

Add this helper function after the imports block (before `CAMERA_SHORT_MAP`, around line 55):

```python
def _write_ingest_phase(status: str) -> None:
    """Write a pipeline phase marker to ingest_status.json (best effort)."""
    import json as _json
    from datetime import datetime
    try:
        with open(INGEST_STATUS_FILE, "w") as f:
            _json.dump({"status": status, "timestamp": datetime.now().isoformat()}, f)
    except OSError:
        pass
```

- [ ] **Step 4: Call `_write_ingest_phase` in `scan()`**

In `scan()` at line 855, add calls around `_index_batches` and `_run_thumbnail_pass`:

```python
    _write_ingest_phase("scanning_db")
    _index_batches(conn, to_scan, volumes)

    if extract_thumbs:
        _write_ingest_phase("thumbs")
        _run_thumbnail_pass(conn)
```

- [ ] **Step 5: Run tests**

```bash
/opt/homebrew/bin/pytest tests/test_ingest_monitor_backend.py -v
```
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add dam_scanner.py tests/test_ingest_monitor_backend.py
git commit -m "feat: write scanning_db and thumbs phase status from dam_scanner"
```

---

## Task 4: Add `tagger_status.json` writes to `dam_tagger.py`

**Files:**
- Modify: `dam_tagger.py:36-50` (imports), `dam_tagger.py:356-364` (SELECT), `dam_tagger.py:512-617` (loops), `dam_tagger.py:620-654` (tag_images)
- Test: `tests/test_ingest_monitor_backend.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingest_monitor_backend.py`:

```python
def test_write_tagger_status_includes_all_fields(tmp_path):
    """_write_tagger_status writes all expected fields to TAGGER_STATUS_FILE."""
    import dam_config
    orig = dam_config.TAGGER_STATUS_FILE
    dam_config.TAGGER_STATUS_FILE = tmp_path / "tagger_status.json"

    try:
        from dam_tagger import _write_tagger_status
        _write_tagger_status(
            status="tagging",
            current=3,
            total=50,
            current_path="2026-04-07/DSCF2601.JPG",
            current_id=42,
            last_keywords=["coastal", "fog"],
        )
        data = json.loads(dam_config.TAGGER_STATUS_FILE.read_text())
        assert data["status"] == "tagging"
        assert data["current"] == 3
        assert data["total"] == 50
        assert data["current_path"] == "2026-04-07/DSCF2601.JPG"
        assert data["current_id"] == 42
        assert data["last_keywords"] == ["coastal", "fog"]
        assert "timestamp" in data
    finally:
        dam_config.TAGGER_STATUS_FILE = orig
```

- [ ] **Step 2: Run to confirm failure**

```bash
/opt/homebrew/bin/pytest tests/test_ingest_monitor_backend.py::test_write_tagger_status_includes_all_fields -v
```
Expected: FAIL — `ImportError: cannot import name '_write_tagger_status'`

- [ ] **Step 3: Add `TAGGER_STATUS_FILE` to `dam_tagger.py` imports** (around line 36)

```python
from dam_config import (
    BURST_GAP_SECONDS,
    BURST_MIN_SIZE,
    EMBED_MODEL,
    MODEL_CTX,
    OLLAMA_BASE,
    OLLAMA_BASE_EMBED,
    OLLAMA_BASE_TEXT,
    OLLAMA_BASE_VISION,
    SKIP_PATH_PATTERNS,
    TAGGER_STATUS_FILE,
    TAGGER_WORKERS,
    TEXT_MODEL,
    THUMB_DIR,
    VISION_MODEL,
)
```

- [ ] **Step 4: Add `_write_tagger_status()` after `write_keywords()` (after line ~306)**

```python
def _write_tagger_status(status, current=0, total=0, current_path=None, current_id=None, last_keywords=None):
    """Write tagger progress to tagger_status.json (non-fatal on error)."""
    try:
        with open(TAGGER_STATUS_FILE, "w") as f:
            json.dump(
                {
                    "status": status,
                    "current": current,
                    "total": total,
                    "current_path": current_path,
                    "current_id": current_id,
                    "last_keywords": last_keywords or [],
                    "timestamp": datetime.now().isoformat(),
                },
                f,
            )
    except OSError:
        pass
```

- [ ] **Step 5: Add `relative_path` to the SELECT in `select_candidate_rows()` (line 356)**

```python
    sql = f"""
        SELECT i.id, i.file_name, i.date_taken, i.camera_short,
               i.file_path, i.triptych_leg, i.relative_path
        FROM images i
        {where}
        {order}
        {lim_clause}
    """
```

- [ ] **Step 6: Write initial status in `tag_images()` after `total = len(rows)` (around line 629)**

```python
    total = len(rows)
    _write_tagger_status("tagging", current=0, total=total)
```

- [ ] **Step 7: Write per-image status in `_tag_loop_sequential()` after `tagged += 1` (around line 529)**

```python
            tagged += 1
            all_kws = (
                kw_dict.get("factual", []) + kw_dict.get("mood", []) + kw_dict.get("technical", [])
            )
            _write_tagger_status(
                "tagging",
                current=tagged,
                total=total,
                current_path=row.get("relative_path"),
                current_id=row["id"],
                last_keywords=all_kws[:6],
            )
```

- [ ] **Step 8: Write per-image status in `_tag_loop_parallel()` after `tagged += 1` (around line 590)**

```python
                tagged += 1
                all_kws = (
                    kw_dict.get("factual", []) + kw_dict.get("mood", []) + kw_dict.get("technical", [])
                )
                _write_tagger_status(
                    "tagging",
                    current=tagged,
                    total=len(work),
                    current_path=row.get("relative_path"),
                    current_id=image_id,
                    last_keywords=all_kws[:6],
                )
```

- [ ] **Step 9: Write `done`/`error` states in `tag_images()`**

Wrap the `_tag_loop` call and update the end of `tag_images()`:

```python
    try:
        tagged, errors = _tag_loop(conn, rows, burst_map, opts["verbose"], workers=opts["workers"])
    except Exception:
        _write_tagger_status("error", current=0, total=total)
        raise

    elapsed = time.time() - start
    # ... existing print statements ...
    conn.close()
    wal_checkpoint()
    _write_tagger_status("done", current=tagged, total=total)
```

- [ ] **Step 10: Run tests**

```bash
/opt/homebrew/bin/pytest tests/test_ingest_monitor_backend.py -v
```
Expected: 4 PASS

- [ ] **Step 11: Run full suite**

```bash
/opt/homebrew/bin/pytest tests/ -q
```
Expected: all tests pass

- [ ] **Step 12: Commit**

```bash
git add dam_tagger.py tests/test_ingest_monitor_backend.py
git commit -m "feat: write tagger_status.json per image with keywords and path"
```

---

## Task 5: Add `/api/tagger/status` and `/api/ingest/preview` to Flask

**Files:**
- Modify: `dam_api.py:38-42` (imports) and after line 225
- Test: `tests/test_ingest_monitor_backend.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ingest_monitor_backend.py`:

```python
def test_tagger_status_returns_idle_when_no_file(tmp_dam_root, app_client):
    """GET /api/tagger/status returns {status: idle} when tagger_status.json absent."""
    import dam_config
    dam_config.TAGGER_STATUS_FILE.unlink(missing_ok=True)
    resp = app_client.get("/api/tagger/status")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "idle"


def test_tagger_status_returns_file_contents(tmp_dam_root, app_client):
    """GET /api/tagger/status returns tagger_status.json contents when present."""
    import dam_config
    dam_config.TAGGER_STATUS_FILE.write_text(
        '{"status":"tagging","current":5,"total":100,"last_keywords":["fog"]}'
    )
    resp = app_client.get("/api/tagger/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "tagging"
    assert data["last_keywords"] == ["fog"]


def test_ingest_preview_returns_204_when_no_current_path(tmp_dam_root, app_client):
    """GET /api/ingest/preview returns 204 when ingest_status.json has no current_path."""
    import dam_config
    dam_config.INGEST_STATUS_FILE.write_text('{"status":"copying","current_path":null}')
    resp = app_client.get("/api/ingest/preview")
    assert resp.status_code == 204
```

- [ ] **Step 2: Run to confirm failure**

```bash
/opt/homebrew/bin/pytest tests/test_ingest_monitor_backend.py::test_tagger_status_returns_idle_when_no_file -v
```
Expected: FAIL — 404

- [ ] **Step 3: Add `TAGGER_STATUS_FILE` to `dam_api.py` imports** (around line 40)

```python
    INGEST_STATUS_FILE,
    TAGGER_STATUS_FILE,
```

Verify `Path` and `send_file` are already imported; add `from pathlib import Path` at the top if not present.

- [ ] **Step 4: Add two new endpoints to `dam_api.py` after the existing `/api/ingest/status` route (after line 225)**

```python
@app.route("/api/tagger/status", methods=["GET"])
def tagger_status():
    f = TAGGER_STATUS_FILE
    if not f.exists():
        return jsonify({"status": "idle"})
    try:
        with open(f) as fh:
            return jsonify(json.load(fh))
    except Exception:
        return jsonify({"status": "idle"})


@app.route("/api/ingest/preview", methods=["GET"])
def ingest_preview():
    """Serve the JPEG currently being copied as a raw image (copy-phase live preview)."""
    try:
        with open(INGEST_STATUS_FILE) as fh:
            data = json.load(fh)
        current_path = data.get("current_path")
        dest_root = data.get("dest_root")
        if not current_path or not dest_root:
            return ("", 204)
        path = Path(dest_root) / current_path
        if not path.exists() or path.suffix.lower() not in (".jpg", ".jpeg"):
            return ("", 204)
        return send_file(str(path), mimetype="image/jpeg")
    except Exception:
        return ("", 204)
```

- [ ] **Step 5: Run tests**

```bash
/opt/homebrew/bin/pytest tests/test_ingest_monitor_backend.py -v
```
Expected: 7 PASS

- [ ] **Step 6: Commit**

```bash
git add dam_api.py tests/test_ingest_monitor_backend.py
git commit -m "feat: add /api/tagger/status and /api/ingest/preview endpoints"
```

---

## Task 6: Fix `ingest.ts` types and add `useTagStatus`

**Files:**
- Modify: `frontend/src/api/ingest.ts`

- [ ] **Step 1: Replace the entire file**

```typescript
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from './client'
import { useEffect, useRef } from 'react'

export interface IngestStatus {
  status: 'idle' | 'scanning' | 'scanning_db' | 'thumbs' | 'copying' | 'error'
  current?: number
  total?: number
  current_path?: string
  dest_root?: string
  timestamp?: string
}

export interface TaggerStatus {
  status: 'idle' | 'tagging' | 'done' | 'error'
  current?: number
  total?: number
  current_path?: string
  current_id?: number
  last_keywords?: string[]
  timestamp?: string
}

export function useIngestStatus() {
  const qc = useQueryClient()
  const wasIngesting = useRef(false)

  const query = useQuery({
    queryKey: ['ingest-status'],
    queryFn: () => apiFetch<IngestStatus>('/ingest/status'),
    refetchInterval: 3000,
  })

  useEffect(() => {
    if (query.data?.status !== 'idle') {
      wasIngesting.current = true
    } else if (wasIngesting.current && query.data?.status === 'idle') {
      wasIngesting.current = false
      qc.invalidateQueries({ queryKey: ['images'] })
      qc.invalidateQueries({ queryKey: ['filters'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    }
  }, [query.data?.status, qc])

  return query
}

export function useTagStatus() {
  const qc = useQueryClient()
  const wasTagging = useRef(false)

  const query = useQuery({
    queryKey: ['tagger-status'],
    queryFn: () => apiFetch<TaggerStatus>('/tagger/status'),
    refetchInterval: 3000,
  })

  useEffect(() => {
    if (query.data?.status === 'tagging') {
      wasTagging.current = true
    } else if (wasTagging.current && query.data?.status === 'done') {
      wasTagging.current = false
      qc.invalidateQueries({ queryKey: ['images'] })
      qc.invalidateQueries({ queryKey: ['filters'] })
    }
  }, [query.data?.status, qc])

  return query
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ~/Documents/dam/frontend
NODE_ENV=development npm run build 2>&1 | tail -20
```
Expected: no TypeScript errors

- [ ] **Step 3: Commit**

```bash
cd ~/Documents/dam
git add frontend/src/api/ingest.ts
git commit -m "feat: fix IngestStatus type, add TaggerStatus and useTagStatus hook"
```

---

## Task 7: Add `ingestMonitorCollapsed` to Zustand store

**Files:**
- Modify: `frontend/src/stores/useUIStore.ts`

- [ ] **Step 1: Add to the `UIState` interface** (after `setThumbSize` line ~68)

```typescript
  // Ingest monitor
  ingestMonitorCollapsed: boolean
  toggleIngestMonitor: () => void
```

- [ ] **Step 2: Add initial value and action to the `create` body** (after `setThumbSize` line ~144)

```typescript
  ingestMonitorCollapsed: false,
  toggleIngestMonitor: () => set((s) => ({ ingestMonitorCollapsed: !s.ingestMonitorCollapsed })),
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd ~/Documents/dam/frontend
NODE_ENV=development npm run build 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```bash
cd ~/Documents/dam
git add frontend/src/stores/useUIStore.ts
git commit -m "feat: add ingestMonitorCollapsed state to UIStore"
```

---

## Task 8: Build `IngestMonitor.tsx`

**Files:**
- Create: `frontend/src/components/layout/IngestMonitor.tsx`

- [ ] **Step 1: Create the component**

```typescript
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useIngestStatus, useTagStatus } from '../../api/ingest'
import { useUIStore } from '../../stores/useUIStore'

const PHASES = ['Copy', 'Scan', 'Thumbs', 'Tag'] as const

function phaseIndex(ingestStatus: string, taggerStatus: string): number {
  if (taggerStatus === 'tagging') return 3
  if (ingestStatus === 'thumbs') return 2
  if (ingestStatus === 'scanning_db') return 1
  if (ingestStatus === 'copying') return 0
  return -1
}

function PhasePill({ label, state }: { label: string; state: 'done' | 'active' | 'pending' }) {
  const base = 'px-2 py-0.5 rounded text-[10px] font-medium'
  if (state === 'active') return <span className={`${base} bg-[var(--accent)] text-black`}>{label}</span>
  if (state === 'done') return <span className={`${base} bg-[var(--bg3)] text-[var(--accent)]`}>{label}</span>
  return <span className={`${base} bg-[var(--bg3)] text-[var(--text-dim)]`}>{label}</span>
}

export function IngestMonitor() {
  const { data: ingest } = useIngestStatus()
  const { data: tagger } = useTagStatus()
  const { ingestMonitorCollapsed, toggleIngestMonitor, addToast } = useUIStore()

  const ingestS = ingest?.status ?? 'idle'
  const taggerS = tagger?.status ?? 'idle'

  const isActive = ingestS !== 'idle' || taggerS === 'tagging'
  if (!isActive) return null

  const active = phaseIndex(ingestS, taggerS)
  const current = taggerS === 'tagging' ? (tagger?.current ?? 0) : (ingest?.current ?? 0)
  const total = taggerS === 'tagging' ? (tagger?.total ?? 0) : (ingest?.total ?? 0)
  const pct = total > 0 ? Math.round((current / total) * 100) : 0
  const keywords = tagger?.last_keywords ?? []
  const logPath = '~/Documents/dam/card_watcher.log'

  const thumbSrc = (() => {
    if (taggerS === 'tagging' && tagger?.current_id) return `/api/thumbs/${tagger.current_id}.jpg`
    if (ingestS === 'copying') return '/api/ingest/preview'
    return null
  })()

  const handleLogClick = () => {
    try {
      ;(window as any).pywebview?.api?.open_path?.(logPath)
    } catch {
      navigator.clipboard.writeText(logPath)
      addToast('Log path copied to clipboard', 'info')
    }
  }

  return (
    <div className="border-b border-[var(--border)] bg-[var(--bg2)] shrink-0">
      {ingestMonitorCollapsed ? (
        <div
          className="flex items-center gap-3 px-3 h-7 cursor-pointer hover:bg-[var(--bg3)]"
          onClick={toggleIngestMonitor}
        >
          <span className="text-[11px] text-[var(--text-mid)]">
            {active >= 0 ? PHASES[active] : 'Starting'}
          </span>
          <div className="flex-1 h-1 rounded bg-[var(--bg)] overflow-hidden">
            <div
              className="h-full bg-[var(--accent)] transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-[11px] text-[var(--text-dim)]">{current}/{total}</span>
          <ChevronDown size={12} className="text-[var(--text-dim)]" />
        </div>
      ) : (
        <div className="px-3 py-2 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {PHASES.map((label, i) => (
                <PhasePill
                  key={label}
                  label={label}
                  state={i === active ? 'active' : i < active ? 'done' : 'pending'}
                />
              ))}
            </div>
            <button onClick={toggleIngestMonitor} className="text-[var(--text-dim)] hover:text-[var(--text)]">
              <ChevronUp size={14} />
            </button>
          </div>

          <div className="flex items-start gap-3">
            {thumbSrc && (
              <img
                key={thumbSrc === '/api/ingest/preview' ? ingest?.current_path : tagger?.current_id}
                src={thumbSrc}
                alt=""
                className="w-20 h-[54px] object-cover rounded bg-[var(--bg3)] shrink-0"
              />
            )}
            <div className="flex-1 min-w-0">
              <p className="text-[12px] text-[var(--text)]">
                {total > 0 ? `${current} / ${total} photos` : 'Starting…'}
              </p>
              {keywords.length > 0 && (
                <p className="text-[11px] text-[var(--text-dim)] truncate mt-0.5">
                  {keywords.join(' · ')}
                </p>
              )}
            </div>
          </div>

          <div className="h-1.5 rounded bg-[var(--bg)] overflow-hidden">
            <div
              className="h-full bg-[var(--accent)] transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[10px] text-[var(--text-dim)]">{logPath}</span>
            <button
              onClick={handleLogClick}
              className="text-[10px] text-[var(--accent)] hover:underline"
            >
              {(window as any).pywebview ? 'Open in Finder' : 'Copy path'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd ~/Documents/dam/frontend
NODE_ENV=development npm run build 2>&1 | tail -20
```
Expected: no TypeScript errors

- [ ] **Step 3: Commit**

```bash
cd ~/Documents/dam
git add frontend/src/components/layout/IngestMonitor.tsx
git commit -m "feat: add IngestMonitor React component"
```

---

## Task 9: Wire `IngestMonitor` into `App.tsx`; remove strip from `StatusBar.tsx`

**Files:**
- Modify: `frontend/src/App.tsx:70-80`
- Modify: `frontend/src/components/layout/StatusBar.tsx:1-89`

- [ ] **Step 1: Add import to `App.tsx`**

At the top of `App.tsx` alongside other layout imports:

```typescript
import { IngestMonitor } from './components/layout/IngestMonitor'
```

- [ ] **Step 2: Mount `<IngestMonitor />` between `<Toolbar>` and the flex row** (around line 74)

```tsx
    <div className="h-full flex flex-col">
      <Toolbar totalFiltered={totalFiltered} />
      <IngestMonitor />

      <div className="flex flex-1 min-h-0">
```

- [ ] **Step 3: Remove the ingest progress block from `StatusBar.tsx`**

Delete lines 73–86 (the `{/* Ingest progress */}` block):

```tsx
      {/* DELETE — replaced by IngestMonitor component: */}
      {ingest?.status === 'ingesting' && ingest.total && (
        <div className="flex items-center gap-2">
          ...
        </div>
      )}
```

Also remove the `useIngestStatus` import and the `const { data: ingest } = useIngestStatus()` line from `StatusBar.tsx` (lines 3 and 14) since they are no longer used.

- [ ] **Step 4: Build and verify**

```bash
cd ~/Documents/dam/frontend
NODE_ENV=development npm run build 2>&1 | tail -20
```
Expected: clean build, zero TypeScript errors

- [ ] **Step 5: Commit**

```bash
cd ~/Documents/dam
git add frontend/src/App.tsx frontend/src/components/layout/StatusBar.tsx
git commit -m "feat: mount IngestMonitor in App, remove status strip from StatusBar"
```

---

## Task 10: Add PySide6 dependency

**Files:**
- Modify: `requirements.txt` (after line 9, after `tqdm`)
- Modify: `pyproject.toml` (in `dependencies` list)

- [ ] **Step 1: Add to `requirements.txt`**

```
PySide6>=6.6
```

- [ ] **Step 2: Add to `pyproject.toml` dependencies list**

```toml
    "PySide6>=6.6",
```

- [ ] **Step 3: Install**

```bash
cd ~/Documents/dam
pip install "PySide6>=6.6"
```

- [ ] **Step 4: Verify**

```bash
python3 -c "from PySide6.QtWidgets import QApplication; print('PySide6 OK')"
```
Expected: `PySide6 OK`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt pyproject.toml
git commit -m "feat: add PySide6 dependency for native ingest monitor window"
```

---

## Task 11: Create `ingest_monitor.py` — PySide6 floating window

**Files:**
- Create: `ingest_monitor.py`

**Note:** The Qt event loop is started with `QApplication.exec()` (PySide6 spelling). This is the Qt event loop, not a shell command.

- [ ] **Step 1: Create the script**

```python
#!/opt/homebrew/bin/python3
"""
DAM Ingest Monitor — PySide6 floating progress window.

Launched by card_watcher as a detached subprocess when a card is inserted.
Polls ingest_status.json + tagger_status.json every 2s. Stays open until
manually closed — does not auto-close on completion.

Usage:
    python3 ingest_monitor.py --vol "Archive 2"
"""
import argparse
import json
import sys
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from dam_config import DAM_ROOT, INGEST_STATUS_FILE, TAGGER_STATUS_FILE, THUMB_DIR

ACCENT = "#c8a96e"
REJECT = "#e05555"
BG = "#0e0e0e"
BG3 = "#1f1f1f"
BORDER = "#2a2a2a"
TEXT = "#d4d4d4"
TEXT_DIM = "#666666"

PHASE_LABELS = ["Copy", "Scan", "Thumbs", "Tag"]
LOG_FILE = DAM_ROOT / "card_watcher.log"


class PhaseDot(QLabel):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self.set_pending()

    def set_active(self):
        self.setText(f"● {self._label}")
        self.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-weight: bold;")

    def set_done(self):
        self.setText(f"● {self._label}")
        self.setStyleSheet(f"color: {ACCENT}; font-size: 12px;")

    def set_pending(self):
        self.setText(f"○ {self._label}")
        self.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")


class IngestMonitorWindow(QDialog):
    def __init__(self, vol_name: str):
        super().__init__()
        self.vol_name = vol_name
        self.dest_root: str | None = None
        self._last_thumb_path: Path | None = None
        self._progress_anim: QPropertyAnimation | None = None
        self._opacity_anim: QPropertyAnimation | None = None
        self._opacity_anim_in: QPropertyAnimation | None = None

        self._build_ui()
        self._apply_styles()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(2000)
        self._poll()

    def _build_ui(self):
        self.setWindowTitle(f"DAM — {self.vol_name}")
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.setFixedWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        # Phase dots
        phase_row = QHBoxLayout()
        phase_row.setSpacing(16)
        self.phase_dots = [PhaseDot(label) for label in PHASE_LABELS]
        for dot in self.phase_dots:
            phase_row.addWidget(dot)
        phase_row.addStretch()
        root.addLayout(phase_row)

        # Thumbnail + counter/keywords
        info_row = QHBoxLayout()
        info_row.setSpacing(12)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(QSize(140, 93))
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet(
            f"background: {BG3}; border: 1px solid {BORDER}; border-radius: 3px;"
        )
        self._opacity_effect = QGraphicsOpacityEffect(self.thumb_label)
        self._opacity_effect.setOpacity(1.0)
        self.thumb_label.setGraphicsEffect(self._opacity_effect)
        info_row.addWidget(self.thumb_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        self.counter_label = QLabel("Starting…")
        self.counter_label.setStyleSheet(f"color: {TEXT}; font-size: 13px;")
        text_col.addWidget(self.counter_label)
        self.keywords_label = QLabel("")
        self.keywords_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        self.keywords_label.setWordWrap(True)
        self.keywords_label.setVisible(False)
        text_col.addWidget(self.keywords_label)
        text_col.addStretch()
        info_row.addLayout(text_col)
        root.addLayout(info_row)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        root.addWidget(self.progress_bar)

        # Log row
        log_row = QHBoxLayout()
        log_label = QLabel(str(LOG_FILE).replace(str(Path.home()), "~"))
        log_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 10px;")
        log_row.addWidget(log_label)
        log_row.addStretch()
        log_btn = QPushButton("Open in Finder")
        log_btn.setStyleSheet(
            f"QPushButton {{ color: {ACCENT}; background: transparent; border: none;"
            f" font-size: 10px; text-decoration: underline; }}"
            f"QPushButton:hover {{ color: {TEXT}; }}"
        )
        log_btn.setCursor(Qt.PointingHandCursor)
        log_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE.parent)))
        )
        log_row.addWidget(log_btn)
        root.addLayout(log_row)

    def _apply_styles(self):
        self.setStyleSheet(
            f"QDialog {{ background: {BG}; color: {TEXT}; }}"
            f"QProgressBar {{ background: {BG3}; border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}"
        )

    def _read_status(self, path: Path) -> dict:
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {}

    def _animate_progress(self, new_val: int):
        if self._progress_anim and self._progress_anim.state() == QPropertyAnimation.Running:
            self._progress_anim.stop()
        self._progress_anim = QPropertyAnimation(self.progress_bar, b"value")
        self._progress_anim.setDuration(300)
        self._progress_anim.setStartValue(self.progress_bar.value())
        self._progress_anim.setEndValue(new_val)
        self._progress_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._progress_anim.start()

    def _load_thumbnail(self, path: Path):
        if path == self._last_thumb_path or not path.exists():
            return
        self._last_thumb_path = path

        if self._opacity_anim and self._opacity_anim.state() == QPropertyAnimation.Running:
            self._opacity_anim.stop()

        fade_out = QPropertyAnimation(self._opacity_effect, b"opacity")
        fade_out.setDuration(200)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._opacity_anim = fade_out

        captured = path

        def _swap():
            pix = QPixmap(str(captured))
            if not pix.isNull():
                self.thumb_label.setPixmap(
                    pix.scaled(self.thumb_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            fade_in = QPropertyAnimation(self._opacity_effect, b"opacity")
            fade_in.setDuration(200)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
            fade_in.start()
            self._opacity_anim_in = fade_in

        fade_out.finished.connect(_swap)
        fade_out.start()

    def _update_phase_dots(self, ingest_s: str, tagger_s: str):
        all_done = ingest_s == "idle" and tagger_s == "done"
        if tagger_s == "tagging":
            active = 3
        elif ingest_s == "thumbs":
            active = 2
        elif ingest_s == "scanning_db":
            active = 1
        elif ingest_s == "copying":
            active = 0
        else:
            active = -1

        for i, dot in enumerate(self.phase_dots):
            if all_done:
                dot.set_done()
            elif i == active:
                dot.set_active()
            elif i < active:
                dot.set_done()
            else:
                dot.set_pending()

    def _poll(self):
        ingest = self._read_status(INGEST_STATUS_FILE)
        tagger = self._read_status(TAGGER_STATUS_FILE)
        ingest_s = ingest.get("status", "")
        tagger_s = tagger.get("status", "")

        if not self.dest_root and ingest.get("dest_root"):
            self.dest_root = ingest["dest_root"]

        if ingest_s == "idle" and tagger_s == "done":
            self.setWindowTitle(f"DAM — Done ✓  ({self.vol_name})")
        elif ingest_s == "error" or tagger_s == "error":
            self.setWindowTitle(f"DAM — Failed  ({self.vol_name})")

        self._update_phase_dots(ingest_s, tagger_s)

        is_tagging = tagger_s == "tagging"
        current = tagger.get("current") if is_tagging else ingest.get("current")
        total = tagger.get("total") if is_tagging else ingest.get("total")

        if total and total > 0:
            pct = min(100, int(round((current or 0) / total * 100)))
            if pct != self.progress_bar.value():
                self._animate_progress(pct)
            self.counter_label.setText(f"{current or 0} of {total} photos")
        else:
            self.counter_label.setText("Starting…")

        if ingest_s == "idle" and tagger_s == "done":
            if self.progress_bar.value() < 100:
                self._animate_progress(100)
            self.counter_label.setText(f"Complete — {total or '?'} photos tagged")

        keywords = tagger.get("last_keywords") or []
        if is_tagging and keywords:
            self.keywords_label.setText(" · ".join(keywords))
            self.keywords_label.setVisible(True)
        else:
            self.keywords_label.setVisible(False)

        if is_tagging and tagger.get("current_id"):
            self._load_thumbnail(THUMB_DIR / f"{tagger['current_id']}.jpg")
        elif ingest_s == "copying" and ingest.get("current_path") and self.dest_root:
            candidate = Path(self.dest_root) / ingest["current_path"]
            if candidate.suffix.lower() in (".jpg", ".jpeg"):
                self._load_thumbnail(candidate)


def main():
    parser = argparse.ArgumentParser(description="DAM Ingest Monitor")
    parser.add_argument("--vol", default="Card", help="Volume label for window title")
    args = parser.parse_args()

    qt_app = QApplication(sys.argv)
    window = IngestMonitorWindow(args.vol)
    window.show()
    # Start the Qt event loop (PySide6: QApplication.exec())
    raise SystemExit(qt_app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the window opens**

```bash
cd ~/Documents/dam
python3 ingest_monitor.py --vol "Test Card"
# Window should appear. Close it manually to exit.
```
Expected: floating dark window appears, no tracebacks

- [ ] **Step 3: Commit**

```bash
git add ingest_monitor.py
git commit -m "feat: add PySide6 ingest monitor floating window"
```

---

## Task 12: Add `launch_ingest_monitor()` to `platform_utils.py`; update `card_watcher.py`

**Files:**
- Modify: `platform_utils.py` (after `notify_desktop`, around line 133)
- Modify: `card_watcher.py:20` (imports), `card_watcher.py:53-56` (notify fn), `card_watcher.py:59-107` (run_ingest)

- [ ] **Step 1: Add helper to `platform_utils.py`**

Add after `notify_desktop()`:

```python
def launch_ingest_monitor(vol_name: str) -> None:
    """Launch the PySide6 ingest monitor as a detached background subprocess.

    dest_root is NOT passed here — the monitor reads it from ingest_status.json
    once card_ingest.py starts writing it. No-op on Linux or if script is absent.
    """
    if sys.platform not in ("darwin", "win32"):
        return
    monitor_script = Path(__file__).parent / "ingest_monitor.py"
    if not monitor_script.exists():
        return
    with contextlib.suppress(Exception):
        subprocess.Popen(
            [sys.executable, str(monitor_script), "--vol", vol_name],
            start_new_session=True,
        )
```

Ensure `contextlib` is imported at the top of `platform_utils.py`; add it if missing.

- [ ] **Step 2: Update `card_watcher.py` import line**

Replace:
```python
from platform_utils import find_dcim_mounts, notify_desktop, volume_label
```
With:
```python
from platform_utils import find_dcim_mounts, launch_ingest_monitor, volume_label
```

- [ ] **Step 3: Remove `notify()` helper; update `run_ingest()`**

Delete the `notify()` function (lines 53–56).

Replace `run_ingest()` with:

```python
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
        else:
            log.error(f"Ingest FAILED (exit {result.returncode})")
            log.error(result.stderr[-500:] if result.stderr else "no stderr")

        if result.stdout:
            for line in result.stdout.strip().split("\n")[-20:]:
                log.info(f"  {line}")

        return result.returncode == 0

    except subprocess.TimeoutExpired:
        log.error("Ingest TIMED OUT after 2 hours")
        return False
    except Exception as e:
        log.error(f"Ingest error: {e}")
        return False
```

Remove `contextlib` from `card_watcher.py` imports if it was only used by the now-deleted `notify()` function.

- [ ] **Step 4: Run full test suite**

```bash
cd ~/Documents/dam
/opt/homebrew/bin/pytest tests/ -q
```
Expected: all tests pass

- [ ] **Step 5: Smoke-test the launch path**

```bash
python3 -c "
import sys, time
sys.argv = ['x']
from platform_utils import launch_ingest_monitor
launch_ingest_monitor('Smoke Test')
time.sleep(4)
print('No errors — monitor launched OK')
"
```
Expected: monitor window appears, prints `No errors — monitor launched OK`

- [ ] **Step 6: Commit**

```bash
git add platform_utils.py card_watcher.py
git commit -m "feat: launch PySide6 monitor on card detection, remove bare osascript notify calls"
```

---

## Self-Review Checklist

| Spec Requirement | Task |
|---|---|
| `tagger_status.json` with all fields | Task 4 |
| `done` and `error` written by tagger | Task 4, step 9 |
| `TAGGER_STATUS_FILE` config constant | Task 1 |
| `current_path` + `dest_root` in `ingest_status.json` | Task 2 |
| `scanning_db` + `thumbs` phase writes from scanner | Task 3 |
| `/api/tagger/status` endpoint | Task 5 |
| `/api/ingest/preview` endpoint | Task 5 |
| `IngestStatus` type corrected in `ingest.ts` | Task 6 |
| `useTagStatus` hook with invalidate-on-done | Task 6 |
| `ingestMonitorCollapsed` in Zustand | Task 7 |
| `IngestMonitor.tsx` — phases, thumbnail, keywords, log path | Task 8 |
| Mounted in `App.tsx` between toolbar and grid | Task 9 |
| Old ingest strip removed from `StatusBar` | Task 9 |
| PySide6 dependency added | Task 10 |
| `ingest_monitor.py` — QPropertyAnimation on progress (300ms OutCubic) | Task 11 |
| Thumbnail crossfade via opacity QPropertyAnimation (200ms) | Task 11 |
| Phase dots light up progressively | Task 11 |
| Window stays open until manually closed | Task 11 |
| Done state: 100% fill + all dots lit | Task 11 |
| `platform_utils.launch_ingest_monitor()` | Task 12 |
| `card_watcher` replaces 3 notify calls with launch | Task 12 |
| `dest_root` read from status file (not CLI arg) | Task 11 — polls from `ingest_status.json` |
