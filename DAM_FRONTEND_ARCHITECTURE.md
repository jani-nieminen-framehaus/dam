# DAM Frontend Architecture — Draft

**Date:** 2026-04-09
**Status:** Weekends 1–5 complete. Sprint 4 (list view + audit fixes) next.
**Stack:** TypeScript + React + Tailwind CSS v4
**IDE:** WebStorm (JetBrains, licensed)
**Backend:** Flask API at `localhost:5001` (port 5000 blocked by macOS AirPlay)

---

## Development Setup

```bash
# Start the API (from project root)
cd ~/Documents/dam
/opt/homebrew/bin/gunicorn -w 2 -b 0.0.0.0:5001 dam_api:app

# Start frontend dev server with hot reload (from frontend/)
cd ~/Documents/dam/frontend
NODE_ENV=development npm install   # NODE_ENV=production is set globally, must override
NODE_ENV=development npm run dev   # Vite dev server at localhost:5173, proxies /api/* to :5001

# Production build (outputs to ../static/, served by Flask)
NODE_ENV=development npm run build
```

**Python:** `/opt/homebrew/bin/python3` (3.14). Flask/gunicorn in homebrew, not venv.
**Node:** v25.6.1, npm 11.9.0 (`/opt/homebrew/bin/node`)
**Tests:** `/opt/homebrew/bin/pytest tests/` — 120/120 passing

---

## Philosophy

The DAM frontend serves one user on one machine. No auth flows, no user management, no responsive mobile layout. It's a desktop-first power tool for photo culling, tagging, and search. Every design decision optimizes for speed-of-interaction over prettiness.

The backend is finished. Every endpoint exists. The frontend's job is to put buttons on those endpoints and get out of the way.

---

## Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language | TypeScript | Type safety catches API contract drift early |
| UI framework | React 18+ | Component model fits the panel layout |
| Styling | Tailwind CSS | Utility-first, dark mode trivial |
| Data fetching | TanStack Query | Server state, caching, pagination, background refetch |
| UI state | Zustand | Lightbox open/closed, selection, sidebar — pure UI state only |
| Build | Vite | Fast HMR, TypeScript native, outputs to `static/` |
| Icons | Lucide React | Clean, MIT licensed |
| Keyboard shortcuts | react-hotkeys-hook | Culling must be keyboard-driven |
| Virtualization | @tanstack/react-virtual | 50k thumbnails need windowed rendering |

**Not using:** Next.js (overkill), Redux (ceremony), Electron (browser tab on dual 34" 4K panels is effectively a desktop app).

**State boundary:** TanStack Query owns all server data (images, filters, stats). Zustand owns only ephemeral UI state (which image is selected, lightbox visibility, multi-select range, sidebar collapsed). Never duplicate server data in Zustand — use TanStack Query's `useMutation` with `onMutate` for optimistic updates during culling.

**Error handling:** Every API consumer wraps errors. Ollama offline → search gracefully degrades. Volume unmounted → "open external" shows toast, not crash. TanStack Query's `onError` callbacks surface issues in a non-blocking toast/notification component.

---

## Layout

```
┌─────────────────────────────────────────────────────────┐
│  Toolbar                                                │
│  [Search] [Filters] [Sort] [View: Grid|List] [Stats]   │
├────────────┬────────────────────────────────────────────┤
│  Sidebar   │  Main Panel                                │
│            │                                            │
│  Filters   │  Thumbnail Grid (virtualized)              │
│  - Camera  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐        │
│  - Volume  │  │thumb│ │thumb│ │thumb│ │thumb│        │
│  - Date    │  │ ★★★ │ │ ★   │ │     │ │ ★★  │        │
│  - Rating  │  └─────┘ └─────┘ └─────┘ └─────┘        │
│  - Pick    │                                            │
│  - Status  │  infinite scroll (keyset pagination)       │
│  - Project │                                            │
│  - Keyword │                                            │
├────────────┴────────────────────────────────────────────┤
│  Status Bar: 50,877 images | Filter: S1IIE | 3 selected │
└─────────────────────────────────────────────────────────┘
```

### Lightbox (overlay on image click or Enter)

- Full preview (JPEG sidecar or high-res thumb)
- EXIF panel: camera, lens, exposure, GPS
- AI tags: description, keywords (editable)
- Workflow controls: pick/reject, rating stars, edit status
- Project assigner, keyword editor
- Open in external app (Capture One, etc.)
- Arrow keys navigate, Esc closes
- **Auto-advance after pick/reject** (Lightroom-style culling)

---

## Component Tree

```
App
├── Toolbar
│   ├── SearchBar              → GET /api/search?q=...
│   ├── FilterDropdowns        → reads from GET /api/filters
│   ├── SortSelector           → date_taken, rating, camera
│   ├── ViewToggle             → grid / list
│   └── StatsButton            → modal with GET /api/stats
├── Sidebar
│   └── FilterPanel
│       ├── CameraFilter, VolumeFilter, DateRangeFilter
│       ├── RatingFilter, PickFilter, EditStatusFilter
│       ├── ProjectFilter, KeywordFilter
│       └── ActiveFilters      → chips, click to remove
├── MainPanel
│   ├── ImageGrid              → GET /api/images (virtualized, infinite scroll)
│   │   └── ImageCard (×N)     → thumbnail + rating/pick/status overlays
│   └── ImageList              → table view alternative
├── Lightbox (portal overlay)
│   ├── ImagePreview, ExifPanel, AiTagPanel
│   ├── WorkflowControls      → pick/reject, rating, status
│   ├── KeywordEditor, ProjectAssigner
│   └── ExternalOpener         → POST /api/images/:id/open_external
├── StatusBar
│   ├── TotalCount, FilterSummary, SelectionCount
│   └── IngestProgress         → polls GET /api/ingest/status
└── Modals
    ├── StatsModal, BulkEditModal, KeyboardShortcutsHelp
```

---

## Keyboard Shortcuts (Culling Workflow)

| Key | Action | API Call |
|-----|--------|---------|
| `→` / `←` | Next / previous image (lightbox) | — |
| `Enter` | Open lightbox | — |
| `Esc` | Close lightbox | — |
| `P` | Pick | PATCH /api/images/:id |
| `R` | Reject | PATCH /api/images/:id |
| `U` | Unmarked | PATCH /api/images/:id |
| `1`–`5` | Set rating | PATCH /api/images/:id |
| `0` | Clear rating | PATCH /api/images/:id |
| `D` | Status → developed | PATCH /api/images/:id |
| `S` | Status → selected | PATCH /api/images/:id |
| `O` | Open in Capture One | POST /api/images/:id/open_external |
| `J` | Open JPEG sidecar | POST /api/images/:id/open_jpeg |
| `Cmd+A` | Select all visible | — |
| `Shift+Click` | Range select | — |
| `Cmd+Shift+P` | Bulk pick selected | PATCH /api/images/bulk |

---

## Performance: Thumbnail Virtualization

50k+ thumbnails = mandatory virtualization. Only visible thumbnails exist in the DOM.

Use `@tanstack/react-virtual` with a `FixedSizeGrid`. Thumbnail size ~200px adjustable. Combined with keyset pagination from the API, this gives infinite scroll without memory issues.

Thumbnail loading: `loading="lazy"` on img tags. Thumbs are 300px max, served from `/api/thumbs/:id.jpg`.

---

## Project Structure

```
dam/
├── static/                    ← Vite build output (served by Flask)
│   ├── index.html
│   └── assets/
├── frontend/                  ← Source code (not served)
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts         ← proxies /api/* to Flask :5000
│   ├── tailwind.config.ts
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── types.ts           ← Image, FilterState, Cursor types
│       ├── api/               ← TanStack Query hooks
│       │   ├── client.ts, images.ts, search.ts, filters.ts, stats.ts
│       ├── stores/            ← Zustand (UI state only, never server data)
│       │   └── useUIStore.ts  ← lightbox, selection, sidebar, view mode
│       ├── components/
│       │   ├── layout/        ← Toolbar, Sidebar, MainPanel, StatusBar
│       │   ├── grid/          ← ImageGrid, ImageCard, ImageList
│       │   ├── lightbox/      ← Lightbox, ExifPanel, WorkflowControls
│       │   ├── filters/       ← FilterPanel, CameraFilter, etc.
│       │   ├── search/        ← SearchBar
│       │   └── shared/        ← StarRating, PickBadge, Modal
│       └── hooks/
│           ├── useKeyboardShortcuts.ts
│           ├── useInfiniteScroll.ts
│           └── useDebounce.ts
```

---

## Milestones

### Weekend 1: Grid + Thumbnails — ✅ COMPLETE (2026-04-07)
- ✅ Vite + React + Tailwind CSS v4 project setup (`frontend/`)
- ✅ TanStack Query wired to `GET /api/images` with keyset pagination
- ✅ TanStack Virtual grid (50k+ thumbnails, windowed rendering)
- ✅ Infinite scroll (fetches next page when near bottom)
- ✅ Filter sidebar: camera, volume, pick, edit status, project, color, min rating
- ✅ Toolbar with thumbnail size slider and image count
- ✅ Status bar with counts, active filters, selection count
- ✅ Zustand UI store (selection, sidebar, filters, thumb size)
- ✅ Flask routes for `/assets/` and `/favicon.svg` (Vite build output)
- ✅ Production build outputs to `static/`, served by Flask on port 5001
- ⚠️ Note: `NODE_ENV=development` required for `npm install` (system has NODE_ENV=production)
- ⚠️ Note: Port 5000 blocked by macOS AirPlay Receiver — use 5001

### Weekend 2: Lightbox + Culling — ✅ COMPLETE (2026-04-07)
- ✅ Lightbox overlay (double-click thumbnail to open)
- ✅ Keyboard shortcuts: P/R/U pick/reject, 1-5 rating, 0 clear, arrows navigate, Esc close
- ✅ Optimistic PATCH mutations via TanStack Query `useMutation` + `onMutate`
- ✅ Auto-advance after pick/reject (80ms delay for visual feedback)
- ✅ EXIF line at bottom (camera · lens · focal · aperture · shutter · ISO)
- ✅ AI description and keyword tags displayed when available
- ✅ N+1 image preloading for fast culling speed
- ✅ Clickable star rating and pick/reject buttons in lightbox top bar

### Weekend 3: Search + Tags — ✅ COMPLETE (2026-04-09)
- ✅ Semantic search bar (debounced, wired to `GET /api/search?q=`)
- ✅ Search replaces grid results, clear button returns to filtered view
- ✅ AI tag display in lightbox (editable)
- ✅ Keyword add/remove in lightbox (`POST/DELETE /api/images/:id/keywords`)
- ✅ Project assignment in lightbox (`POST/DELETE /api/images/:id/projects`)
- ✅ "Open in external app" split button with configurable default + browsable app list
- ✅ "Open JPEG sidecar" button (`O`/`J` keys)

### Weekend 4: Bulk Operations + Polish — ✅ COMPLETE (2026-04-09)
- ✅ Multi-select: Shift+Click range select, Cmd+A select all visible
- ✅ Bulk pick/reject/rate (`PATCH /api/images/bulk`)
- ✅ Bulk delete (`DELETE /api/images/bulk`)
- ✅ Ingest progress indicator (polls `GET /api/ingest/status`)
- ✅ Sort selector (date_taken, rating, file_name, camera) + direction toggle
- ✅ Date range filter UI wired to date_from/date_to
- ✅ Keyboard shortcuts help overlay (`?` key)
- 🔲 Global error toast/notification component (Sprint 4)
- ✅ Dark mode default throughout

### Weekend 5: Desktop Polish — ✅ COMPLETE (2026-04-09)
- ✅ pywebview native macOS window with JS bridge + native menu bar
- ✅ Window title with filter/count (via `pywebview.api.set_title()`)
- ✅ PyInstaller one-directory `.app` bundle (`dam.spec`) with sqlite_vec.dylib
- ✅ Custom gold aperture icon (`assets/icon.icns`)
- ✅ Makefile: `make build`, `make run`, `make test`, `make clean`
- ✅ PACKAGING.md updated
- 🔲 ImageList (table view) as alternative to grid — Sprint 4

### Sprint 4: List View + Stability — 🔲 IN PROGRESS
- 🔲 Fix route param bug: `<n>` → `<name>` in projects/subjects DELETE endpoints
- 🔲 Backend audit fixes: schema version guard, connection context manager, serialize_vector dedup, partial index, WAL checkpoint, A7C II camera mapping
- 🔲 Global error toast system (bottom-right, auto-dismiss, wire to all failure paths)
- 🔲 `components/shared/StarRating.tsx` — extracted, reused in lightbox + list rows
- 🔲 `components/list/ImageList.tsx` — virtual rows: thumb + filename + date + camera + stars + pick badge + keywords
- 🔲 Toolbar grid/list toggle (LayoutGrid / List icons)

---

## Notes

- API is source of truth. Frontend state is a cache. TanStack Query handles invalidation.
- Optimistic updates essential for culling feel. Rating/pick must feel instant.
- Dark mode by default. Photographers work in dark environments.
- No Electron. pywebview already in the stack. Don't add 200MB of Chromium.
- A browser tab on dual 34" 4K panels is effectively a desktop app.
- Search and filters are mutually exclusive (search overrides filters).
- JPEG sidecar preview in lightbox — don't try to serve 35GB ProRes through the browser.
- Lightbox must preload N+1 and N-1 images for fast culling at speed.
- Thumbnail grid uses `object-cover` on fixed squares — mixed aspect ratios (3:2, 4:3, 16:9) crop to fit.
