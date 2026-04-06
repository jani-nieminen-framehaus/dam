# DAM Frontend Architecture — Draft

**Date:** 2026-04-06
**Status:** Planning
**Stack:** TypeScript + React + Tailwind CSS
**IDE:** WebStorm (JetBrains, licensed through 2028)
**Backend:** Existing Flask API at `localhost:5000`

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
| State | Zustand | Minimal boilerplate, no Redux ceremony |
| Data fetching | TanStack Query | Caching, pagination, background refetch |
| Build | Vite | Fast HMR, TypeScript native, outputs to `static/` |
| Icons | Lucide React | Clean, MIT licensed |
| Keyboard shortcuts | react-hotkeys-hook | Culling must be keyboard-driven |
| Virtualization | @tanstack/react-virtual | 50k thumbnails need windowed rendering |

**Not using:** Next.js (overkill), Redux (ceremony), Electron (pywebview handles desktop window).

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
│       ├── stores/            ← Zustand stores
│       │   ├── useImageStore.ts, useCullingStore.ts
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

### M1: Grid + Thumbnails (Weekend 1)
- Vite + React + Tailwind scaffolding
- Fetch `/api/images`, render thumbnail grid with virtualization
- Infinite scroll with keyset pagination
- Basic filter sidebar (camera, volume)

### M2: Lightbox + Culling (Weekend 2)
- Lightbox overlay with EXIF panel
- Keyboard shortcuts: P/R/U, 1-5, arrows
- Optimistic PATCH updates (instant UI, async persist)
- Auto-advance after pick/reject

### M3: Search + Tags (Weekend 3)
- Semantic search bar (debounced, replaces grid results)
- AI tag display in lightbox
- Keyword add/remove
- Project assignment

### M4: Bulk Operations + Polish (Weekend 4)
- Multi-select: Shift+Click, Cmd+A
- Bulk pick/reject/rate
- Status bar with counts
- Ingest progress indicator
- Dark mode default (Tailwind `dark:` classes)

### M5: Desktop Window (Weekend 5)
- pywebview integration (`dam serve --window`)
- Menu bar, window title with filter/count
- macOS native feel refinements

---

## Notes

- API is source of truth. Frontend state is a cache. TanStack Query handles invalidation.
- Optimistic updates essential for culling feel. Rating/pick must feel instant.
- Dark mode by default. Photographers work in dark environments.
- No Electron. pywebview already in the stack. Don't add 200MB of Chromium.
- Search and filters are mutually exclusive (search overrides filters).
- JPEG sidecar preview in lightbox — don't try to serve 35GB ProRes through the browser.
