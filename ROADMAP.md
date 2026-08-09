# DAM Project Roadmap

**Project:** Personal Digital Asset Management System with Semantic Search
**Last Updated:** 2026-04-06
**Status:** Active Development

---

## Overview

The DAM is a personal photo Digital Asset Management system built on Python/Flask/SQLite with AI-powered tagging (LLaVA 34b → dam-tagger Mistral 7B LoRA → nomic-embed-text embeddings), burst stacking, card ingestion with checksum verification, and semantic search via sqlite-vec.

**Current State:**
- ~4,100 Python lines (11 modules) + ~1,200 lines tests
- Backend: Flask API with SQLite + sqlite-vec
- Frontend: TypeScript + React + Tailwind CSS v4 (in development)
- AI Stack: Ollama-based vision (llava:34b), text (dam-tagger), embeddings (nomic-embed-text)
- Platform: Cross-platform (macOS primary, Linux supported)

---

## Vision & Goals

### North Star
Build a personal DAM that enables instant semantic search across 100k+ images with zero manual tagging overhead, while providing professional-grade culling and organization tools.

### Core Principles
1. **Zero-friction ingest:** Card insertion → automatic copy → scan → thumbnail → AI tagging
2. **Semantic-first:** Find any image by describing what's in it
3. **Desktop-first:** Optimized for dual 34" 4K panels, keyboard-driven workflow
4. **Offline-capable:** All AI runs locally via Ollama
5. **Minimal ceremony:** No auth, no user management, no mobile layout

---

## Roadmap Timeline

### Phase 0: Foundation (COMPLETE)

**Duration:** Pre-2026-04-06
**Status:** ✅ Production-ready

| Milestone | Description | Status |
|-----------|-------------|--------|
| M0.1 | Core database schema (images, projects, subjects, keywords) | ✅ |
| M0.2 | Card ingestion pipeline with checksum verification | ✅ |
| M0.3 | File scanner with EXIF extraction | ✅ |
| M0.4 | Thumbnail generation | ✅ |
| M0.5 | AI tagging with LLaVA + dam-tagger LoRA | ✅ |
| M0.6 | Semantic search with sqlite-vec + nomic-embed-text | ✅ |
| M0.7 | Flask REST API (CRUD, search, filters) | ✅ |
| M0.8 | Card watcher (macOS LaunchAgent, Linux systemd) | ✅ |
| M0.9 | Burst stacking support | ✅ |

**Deliverables:**
- `dam.py` CLI with ingest, scan, thumbs, stats, tag, search commands
- `dam_api.py` Flask API with 44+ endpoints
- `dam_scanner.py` with EXIF extraction and thumbnail generation
- `dam_tagger.py` with AI-powered description and keyword extraction
- SQLite database with sqlite-vec extension for vector search

---

### Phase 1: Critical Fixes & Stability (PRIORITY)

**Duration:** 2026-04-06 to 2026-04-13 (1 week)
**Status:** 🟡 In Progress
**Priority:** P0 - Blocking issues that affect production use

| Milestone | Description | Effort | Status | Dependencies |
|-----------|-------------|--------|--------|--------------|
| M1.1 | Fix route parameter bug in dam_api.py | 2 min | ❌ | None |
| M1.2 | Add connection context manager to dam_db.py | 30 min | ❌ | None |
| M1.3 | Schema version check with PRAGMA user_version | 15 min | ❌ | M1.2 |
| M1.4 | Move duplicate `serialize_vector` to shared module | 5 min | ❌ | None |
| M1.5 | Add partial index for untagged images | 2 min | ❌ | None |
| M1.6 | WAL checkpoint management after bulk ops | 10 min | ❌ | None |
| M1.7 | Add Sony A7C II camera mapping | 2 min | ❌ | None |
| M1.8 | Add recovery path for stuck ingests | 15 min | ❌ | None |
| M1.9 | Swap MD5 to SHA256 for checksums | 5 min | ❌ | None |

**Success Criteria:**
- All 120+ tests pass
- No 500 errors on API endpoints
- Migration runs only once on startup
- WAL file doesn't grow unbounded

**Risk:** Low - All are isolated, small changes

---

### Phase 2: Preview Pipeline (ACTIVE)

**Duration:** 2026-04-10 to 2026-04-30 (3 weeks)
**Status:** 🟡 In Progress
**Priority:** P1 - Required for lightbox culling workflow

| Milestone | Description | Effort | Status | Dependencies |
|-----------|-------------|--------|--------|--------------|
| M2.1 | Shared `generate_preview()` function in dam_scanner.py | 1 day | 🟡 | None |
| M2.2 | Rewire on-demand API endpoint to use generate_preview() | 1 day | ❌ | M2.1 |
| M2.3 | `dam previews` backfill CLI command | 1 day | ❌ | M2.1 |
| M2.4 | Integrate preview generation into ingest pipeline | 1 day | ❌ | M2.3 |
| M2.5 | Clean up old constants, rebuild frontend | 1 day | ❌ | M2.4 |
| M2.6 | End-to-end verification | 1 day | ❌ | M2.5 |

**Details:**
- Generate 2048px lightbox previews for culling decisions
- Shared function used by: API endpoint, CLI backfill, ingest pipeline
- Filesystem-based cache (previews/ directory)
- ThreadPoolExecutor with 8 workers for parallel generation
- Fallback to thumbnail if preview generation fails

**Success Criteria:**
- Lightbox shows sharp 2048px previews
- `dam previews` command generates missing previews
- Ingest pipeline automatically generates previews for new images
- All tests pass (137+ expected)

**Risk:** Medium - Requires exiftool for RAW extraction

---

### Phase 3: Ingest Monitor (NEXT)

**Duration:** 2026-05-01 to 2026-05-15 (2 weeks)
**Status:** ⏳ Planned
**Priority:** P1 - Improves user experience during long operations

| Milestone | Description | Effort | Status | Dependencies |
|-----------|-------------|--------|--------|--------------|
| M3.1 | Add TAGGER_STATUS_FILE to dam_config.py | 5 min | ❌ | None |
| M3.2 | Add current_path + dest_root to ingest status writes | 30 min | ❌ | M3.1 |
| M3.3 | Add scanning_db and thumbs phase statuses | 30 min | ❌ | M3.1 |
| M3.4 | Add tagger_status.json writes in dam_tagger.py | 1 hour | ❌ | M3.1 |
| M3.5 | Add /api/tagger/status + /api/ingest/preview endpoints | 1 hour | ❌ | M3.2 |
| M3.6 | Create ingest_monitor.py (PySide6 floating window) | 2 days | ❌ | M3.5 |
| M3.7 | Add launch_ingest_monitor() to platform_utils.py | 30 min | ❌ | M3.6 |
| M3.8 | Replace osascript notifications in card_watcher.py | 30 min | ❌ | M3.7 |
| M3.9 | Frontend: Add IngestMonitor.tsx React banner | 2 days | ❌ | M3.5 |
| M3.10 | Frontend: Update useUIStore.ts with ingest state | 1 hour | ❌ | M3.9 |
| M3.11 | Frontend: Mount IngestMonitor in App.tsx | 30 min | ❌ | M3.10 |
| M3.12 | Backend tests for status endpoints | 1 day | ❌ | M3.5 |

**Details:**
- Two JSON status files: `ingest_status.json`, `tagger_status.json`
- PySide6 floating progress window for desktop
- React banner in web UI
- Both poll status files independently
- Shows progress through all 5 ingest phases

**Success Criteria:**
- Native window launches on card insert
- Web banner shows progress when app is open
- Status files are single source of truth
- All tests pass

**Risk:** Medium - PySide6 dependency, cross-platform UI considerations

---

### Phase 4: Frontend Completion

**Duration:** 2026-05-16 to 2026-06-15 (4 weeks)
**Status:** ⏳ Planned
**Priority:** P2 - Required for full user experience

| Milestone | Description | Effort | Status | Dependencies |
|-----------|-------------|--------|--------|--------------|
| M4.1 | Complete toolbar (Search, Filters, Sort, View toggle, Stats) | 3 days | ❌ | Phase 3 |
| M4.2 | Sidebar filters (Camera, Volume, Date, Rating, Pick, Status, Project, Keyword) | 5 days | ❌ | M4.1 |
| M4.3 | Virtualized thumbnail grid with infinite scroll | 5 days | ❌ | M4.2 |
| M4.4 | Lightbox with EXIF panel, AI tags, workflow controls | 5 days | ❌ | M4.3, Phase 2 |
| M4.5 | Keyboard shortcuts (culling: P/X for pick/reject, 1-5 for rating, arrows for navigation) | 3 days | ❌ | M4.4 |
| M4.6 | Auto-advance after pick/reject (Lightroom-style) | 1 day | ❌ | M4.5 |
| M4.7 | Project assigner, keyword editor in lightbox | 2 days | ❌ | M4.4 |
| M4.8 | Open in external app (Capture One, etc.) | 1 day | ❌ | M4.4 |
| M4.9 | Status bar with image count and filter info | 1 day | ❌ | M4.1 |
| M4.10 | Dark mode styling with Tailwind CSS v4 | 2 days | ❌ | M4.1 |

**Details:**
- TypeScript + React 18+
- TanStack Query for server state
- Zustand for UI state (lightbox, selection, sidebar)
- @tanstack/react-virtual for 50k+ thumbnail rendering
- Lucide React for icons
- react-hotkeys-hook for keyboard shortcuts

**Success Criteria:**
- Full culling workflow works with keyboard
- Filters work and update grid in real-time
- Lightbox shows all metadata and allows editing
- Smooth performance with 50k+ images

**Risk:** High - Complex UI with many edge cases

---

### Phase 5: Taxonomy & Organization

**Duration:** 2026-06-16 to 2026-06-30 (2 weeks)
**Status:** ⏳ Planned
**Priority:** P2 - Improves long-term organization

| Milestone | Description | Effort | Status | Dependencies |
|-----------|-------------|--------|--------|--------------|
| M5.1 | Implement image grouping (RAW + JPEG + sidecars as one group) | 3 days | ❌ | Phase 0 |
| M5.2 | Add sidecar inventory tracking (XMP, ON1, Radiant) | 2 days | ❌ | M5.1 |
| M5.3 | Implement collision handling with EXIF SerialNumber | 2 days | ❌ | M5.1 |
| M5.4 | Add camera/lens auto-extraction to all images | 1 day | ❌ | M5.1 |
| M5.5 | Add exposure metadata extraction | 2 days | ❌ | M5.1 |
| M5.6 | Add GPS metadata extraction and display | 2 days | ❌ | M5.1 |
| M5.7 | Frontend: Group view toggle | 1 day | ❌ | M5.1, Phase 4 |
| M5.8 | Frontend: Sidecar indicators in grid | 1 day | ❌ | M5.2, Phase 4 |

**Details:**
- Group key: folder_path + base_stem (strip all extensions)
- Authoritative disambiguation via EXIF SerialNumber
- Track has_jpeg, has_xmp, has_xmp_alt, has_on1, has_radiant
- All Layer 1 fields from taxonomy spec

**Success Criteria:**
- Images are grouped correctly
- Sidecar presence is tracked
- All metadata is searchable

**Risk:** Medium - Schema changes, data migration

---

### Phase 6: Performance & Scale

**Duration:** 2026-07-01 to 2026-07-15 (2 weeks)
**Status:** ⏳ Planned
**Priority:** P3 - Required for 100k+ image libraries

| Milestone | Description | Effort | Status | Dependencies |
|-----------|-------------|--------|--------|--------------|
| M6.1 | Drop images_flat view (join bomb) | 2 hours | ❌ | Phase 0 |
| M6.2 | Create helper function _image_detail_query() | 2 hours | ❌ | M6.1 |
| M6.3 | Add keyset pagination for infinite scroll | 3 days | ❌ | Phase 4 |
| M6.4 | Implement thumbnail lifecycle management | 2 days | ❌ | Phase 2 |
| M6.5 | Add `dam cleanup` command for orphaned thumbs | 1 day | ❌ | M6.4 |
| M6.6 | Optimize sqlite-vec index for 100k+ vectors | 2 days | ❌ | Phase 0 |
| M6.7 | Add vector index HNSW configuration | 1 day | ❌ | M6.6 |
| M6.8 | Implement query caching for common searches | 2 days | ❌ | Phase 0 |

**Details:**
- Replace images_flat view with inline joins
- Keyset pagination: WHERE id > last_seen_id ORDER BY id LIMIT N
- HNSW index for faster vector search
- Cache frequent queries (top cameras, recent dates, etc.)

**Success Criteria:**
- Grid loads in <500ms with 50k images
- Search returns results in <200ms
- Memory usage stable with large libraries

**Risk:** Medium - Performance tuning is iterative

---

### Phase 7: Polish & Production

**Duration:** 2026-07-16 to 2026-07-31 (2 weeks)
**Status:** ⏳ Planned
**Priority:** P3 - Final touches before v1.0

| Milestone | Description | Effort | Status | Dependencies |
|-----------|-------------|--------|--------|--------------|
| M7.1 | Replace print() with logging module throughout | 3 days | ❌ | All phases |
| M7.2 | Add API write protection (simple API key check) | 1 day | ❌ | Phase 0 |
| M7.3 | Linux desktop integration (make install) | 2 days | ❌ | Phase 0 |
| M7.4 | macOS app bundle with PyInstaller | 2 days | ❌ | Phase 4 |
| M7.5 | Standalone bundle packaging | 2 days | ❌ | M7.4 |
| M7.6 | Comprehensive error handling in frontend | 3 days | ❌ | Phase 4 |
| M7.7 | Graceful degradation when Ollama offline | 1 day | ❌ | Phase 4 |
| M7.8 | Volume unmounted handling (open external) | 1 day | ❌ | Phase 4 |
| M7.9 | Final test suite expansion (200+ tests) | 3 days | ❌ | All phases |

**Details:**
- Proper logging with configurable levels
- API key in ~/.dam/config.json for write operations
- .desktop entry and PATH integration for Linux
- PyInstaller bundle for macOS (.app) and Linux (directory)
- Toast notifications for errors
- Search degrades to keyword-only when embeddings unavailable

**Success Criteria:**
- All 200+ tests pass
- App can be installed and run as standalone bundle
- Error handling is comprehensive and user-friendly

**Risk:** Low - Mostly isolated improvements

---

### Phase 8: Advanced Features (v2.0+)

**Duration:** 2026-08+ (Ongoing)
**Status:** ⏳ Future
**Priority:** P4 - Nice-to-have enhancements

| Milestone | Description | Effort | Status | Dependencies |
|-----------|-------------|--------|--------|--------------|
| M8.1 | Face detection and clustering | 1 week | ❌ | Phase 0 |
| M8.2 | Object detection (YOLO or similar) | 1 week | ❌ | Phase 0 |
| M8.3 | Smart collections (saved searches) | 3 days | ❌ | Phase 4 |
| M8.4 | Export presets (sizing, naming, metadata) | 3 days | ❌ | Phase 0 |
| M8.5 | Batch operations (rating, pick, keyword) | 3 days | ❌ | Phase 4 |
| M8.6 | Duplicate detection (perceptual hash) | 3 days | ❌ | Phase 0 |
| M8.7 | Multi-volume search (federated query) | 5 days | ❌ | Phase 0 |
| M8.8 | Backup verification and integrity checks | 3 days | ❌ | Phase 0 |
| M8.9 | Custom metadata fields (user-defined) | 5 days | ❌ | Phase 5 |
| M8.10 | Plugin system for custom processors | 1 week | ❌ | Phase 0 |

---

## Release Plan

| Version | Date | Scope | Status |
|---------|------|-------|--------|
| v0.9.0 | 2026-04-06 | Current state (pre-audit) | ✅ Released |
| v0.9.1 | 2026-04-13 | Phase 1: Critical fixes | ⏳ |
| v0.9.2 | 2026-04-30 | Phase 2: Preview pipeline | ⏳ |
| v0.9.3 | 2026-05-15 | Phase 3: Ingest monitor | ⏳ |
| v1.0.0 | 2026-06-15 | Phase 4: Frontend complete | ⏳ |
| v1.1.0 | 2026-06-30 | Phase 5: Taxonomy | ⏳ |
| v1.2.0 | 2026-07-15 | Phase 6: Performance | ⏳ |
| v1.3.0 | 2026-07-31 | Phase 7: Polish | ⏳ |
| v2.0.0 | 2026-08+ | Phase 8: Advanced features | ⏳ |

---

## Resource Requirements

### Dependencies (Current)

| Category | Dependency | Purpose |
|----------|------------|---------|
| Python | Flask | Web API |
| Python | sqlite-vec | Vector search |
| Python | Pillow | Image processing |
| Python | pyheif | HEIF support |
| Python | Ollama | AI inference |
| Python | PySide6 | Native UI (future) |
| System | exiftool | EXIF extraction |
| System | sips | Image resizing (macOS) |
| Frontend | TypeScript | Type safety |
| Frontend | React | UI framework |
| Frontend | Tailwind CSS | Styling |
| Frontend | TanStack Query | Server state |
| Frontend | Zustand | UI state |
| Frontend | Vite | Build tool |

### New Dependencies (Planned)

| Phase | Dependency | Purpose |
|-------|------------|---------|
| Phase 3 | PySide6>=6.6 | Ingest monitor window |
| Phase 8 | opencv-python | Face/object detection |
| Phase 8 | imagehash | Duplicate detection |

---

## Testing Strategy

### Test Coverage Goals

| Phase | Current | Target | Status |
|-------|---------|--------|--------|
| Phase 0 | 120 tests | 120 tests | ✅ |
| Phase 1 | 120 tests | 120 tests | ⏳ |
| Phase 2 | 120 tests | 137+ tests | ⏳ |
| Phase 3 | 137 tests | 150+ tests | ⏳ |
| Phase 4 | 150 tests | 180+ tests | ⏳ |
| Phase 5 | 180 tests | 200+ tests | ⏳ |
| Phase 6+ | 200 tests | 250+ tests | ⏳ |

### Test Types
- Unit tests: Individual functions (pytest)
- Integration tests: Module interactions
- API tests: Flask endpoints (pytest with test client)
- Frontend tests: Component tests (Vitest, future)
- E2E tests: Full workflow validation (manual + automated)

---

## Risk Register

| Risk | Probability | Impact | Mitigation | Owner |
|------|-------------|--------|------------|-------|
| PySide6 compatibility issues | Medium | High | Test on both macOS and Linux early | Dev |
| Performance degradation at scale | Medium | High | Load test with 100k images before v1.0 | Dev |
| Ollama API changes | Low | Medium | Version pinning, abstraction layer | Dev |
| exiftool missing on user systems | Medium | Medium | Clear error messages, installation docs | Docs |
| SQLite vector search limitations | Low | Medium | Evaluate alternatives (Qdrant, Weaviate) for v2.0 | Dev |
| Frontend complexity | High | Medium | Modular component design, incremental delivery | Dev |

---

## Success Metrics

### Functional
- [ ] All API endpoints return correct responses
- [ ] Ingest pipeline completes without errors
- [ ] Semantic search returns relevant results
- [ ] Frontend provides full culling workflow

### Performance
- [ ] API response time <200ms for search queries
- [ ] Grid rendering <500ms with 50k images
- [ ] Ingest pipeline <2min for 1000 images (copy + scan + thumbs + previews)
- [ ] AI tagging <10s per image (llava:34b on local GPU)

### Quality
- [ ] 200+ passing tests
- [ ] Zero critical bugs (P0/P1)
- [ ] <5 minor bugs (P3/P4)
- [ ] Documentation complete for all features

### User Experience
- [ ] Keyboard-driven culling workflow
- [ ] Clear progress indicators for long operations
- [ ] Graceful error handling
- [ ] Responsive UI with 50k+ images

---

## Open Questions

1. **Vector search scale:** At what point does sqlite-vec become a bottleneck? (Estimate: ~500k vectors)
2. **Multi-GPU support:** How to utilize multiple GPUs for parallel AI tagging?
3. **Cloud sync:** Should we support syncing metadata to cloud for multi-machine access?
4. **Mobile companion:** Is a mobile viewer app valuable for field use?
5. **Video support:** Should we extend to video files (MP4, MOV)?

---

## Appendix

### File Structure

```
dam/
├── dam.py                 # CLI entry point
├── dam_api.py             # Flask REST API
├── dam_config.py          # Centralized configuration
├── dam_db.py              # Database schema and utilities
├── dam_scanner.py         # File scanning and thumbnail generation
├── dam_tagger.py          # AI-powered tagging
├── dam_schema.py          # Database schema definitions
├── card_ingest.py         # Card ingestion pipeline
├── card_watcher.py        # Card insertion detection
├── ingest_pipeline.py     # Unified ingest orchestration
├── ingest_monitor.py      # Progress monitoring UI (future)
├── platform_utils.py      # Platform-specific utilities
├── storage_utils.py       # File system utilities
├── dam_vlm.py             # Vision language model utilities
├── dam_vocabulary.json    # Tagging vocabulary
├── frontend/              # React frontend
│   ├── src/
│   │   ├── App.tsx        # Main app component
│   │   ├── api/           # API client
│   │   ├── components/    # React components
│   │   ├── stores/        # Zustand stores
│   │   └── types.ts       # TypeScript types
│   └── ...
├── docs/                  # Documentation
│   └── superpowers/       # Implementation plans and specs
├── tests/                 # Test suite
└── static/                # Built frontend assets
```

### Key Configuration Files

- `~/.dam/config.json` - User configuration (volumes, models, paths)
- `dam.db` - SQLite database (images, metadata, vectors)
- `ingest_status.json` - Current ingest progress
- `tagger_status.json` - Current tagging progress (future)

### Environment Requirements

- Python 3.12+ (3.14 recommended)
- Node.js 20+ (for frontend development)
- macOS or Linux (Windows experimental)
- GPU for AI inference (optional but recommended)

---

## Links

- [DAM Audit 2026-04-06](DAM_AUDIT_2026-04-06.md) - Detailed code audit findings
- [Frontend Architecture](DAM_FRONTEND_ARCHITECTURE.md) - Frontend design document
- [Taxonomy Draft](dam_taxonomy_draft.md) - Metadata and grouping design
- [Packaging Guide](PACKAGING.md) - Installation and packaging instructions
- [Preview Pipeline Plan](docs/superpowers/plans/2026-04-30-preview-pipeline.md)
- [Ingest Monitor Plan](docs/superpowers/plans/2026-04-10-ingest-monitor.md)
- [Preview Pipeline Design](docs/superpowers/specs/2026-04-30-preview-pipeline-design.md)
- [Ingest Monitor Design](docs/superpowers/specs/2026-04-10-ingest-monitor-design.md)
