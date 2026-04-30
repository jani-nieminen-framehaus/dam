# Preview Pipeline Design

**Date:** 2026-04-30
**Status:** Approved
**Goal:** Serve 2048px lightbox previews instead of 300px grid thumbnails for culling workflow.

## Context

The DAM currently has a single thumbnail tier: 300px JPEGs generated at scan time, stored in `thumbs/{id}.jpg`. The lightbox serves these same 300px images, making cull decisions impossible. A 1600px on-demand preview endpoint was added in Phase 1 but has only 3 cached files — most images still show the grid thumbnail.

**53,038 images. Mac Studio M3 Ultra. Internal SSD.**

## Architecture

### Two-Tier System

| Tier | Max dim | Location | Generated when | Purpose |
|------|---------|----------|----------------|---------|
| Grid thumb | 300px | `thumbs/{id}.jpg` | Scan time (unchanged) | Grid browsing |
| Lightbox preview | 2048px | `previews/{id}.jpg` | On-demand + backfill | Culling / detail |

### No Schema Changes

The `thumbnails` table stays as-is — it tracks grid thumbs only. Previews are a pure file cache keyed by `{image_id}.jpg`. The filesystem is the index: file exists and passes JPEG header check → serve it. Otherwise → generate.

### Estimated Disk

At 2048px long side, compressed JPEG: **~200-700 KB per image** depending on content. 53k images → **~15-35 GB**. Internal SSD has headroom.

## Generation Pipeline

Same for on-demand and backfill:

1. Look up image in DB → `file_path`, `volume`, `relative_path`
2. `resolve_archive_file()` → resolve to mounted path
3. **RAW files** (.arw, .cr2, .cr3, .nef, .orf, .raf, .rw2, .dng, .pef, .srw):
   - `exiftool -b -JpgFromRaw <file>` → extract embedded JPEG
   - Fallback: `exiftool -b -PreviewImage <file>`
   - Minimum output: 1000 bytes
4. **JPEG files**: `shutil.copy2()` to preview path
5. `sips -Z 2048 <preview_path>` → resize to 2048px long side
6. Validate: file ≥ 32 bytes, starts with `\xff\xd8\xff`

**Tools:** exiftool (extraction), sips (resize). No new dependencies.

## On-Demand Endpoint

Existing route: `GET /api/previews/<int:image_id>.jpg`

Changes:
- Bump `_PREVIEW_MAX_DIM` from 1600 to 2048
- Generation logic extracted to a shared function used by both on-demand and backfill
- Broad exception handler (already in place from Phase 1) ensures thumbnail fallback

## Backfill CLI

New command: `python3 dam.py previews`

- Queries all image IDs from DB
- Filters to those missing a valid file in `previews/`
- Generates via `ThreadPoolExecutor(max_workers=THUMB_WORKERS)` (default 8)
- Progress: `tqdm` progress bar with count/total
- Skips images whose source volume isn't mounted (warning, not error)
- Idempotent: re-run skips existing valid previews
- Prints summary: generated / skipped / failed / total time

## Ingest Integration

After `dam ingest` completes its existing pipeline (copy → scan → thumbs), a **previews pass** runs for newly ingested images only. Same threading model as the thumbnail pass. This ensures freshly ingested images are immediately ready for lightbox culling without on-demand delay.

## Shared Generation Function

Extract a single function used by three call sites:

```
generate_preview(image_id, file_path, volume, relative_path, preview_dir, max_dim=2048) -> Path | None
```

- Returns the path to the generated preview, or None if generation failed
- Handles RAW extraction, JPEG copy, resize, validation
- Called by: on-demand endpoint, backfill CLI, ingest pipeline

Location: `dam_scanner.py` alongside existing `extract_thumbnail_file_only()`.

## Frontend

No frontend changes. The lightbox already requests `/api/previews/{id}.jpg` and has an `onError` fallback to the grid thumbnail. The only visible change is that previews will be 2048px instead of 1600px (or 300px fallback).

## Testing

1. **Shared function test**: Call `generate_preview()` with a real JPEG file (no exiftool needed for JPEG path). Verify output is valid JPEG ≤ 2048px.
2. **API test**: Existing `test_preview_invalid_cache_falls_back_to_thumbnail` already covers fallback. Add test for successful preview serve from cache.
3. **Backfill test**: Mock DB query + filesystem. Verify: skips existing, generates missing, handles unmounted volumes gracefully.
4. **Ingest integration test**: Verify preview pass runs after thumbnail pass in the ingest pipeline.

## Out of Scope

- Grid thumb changes (stays 300px)
- Schema changes
- Configurable preview directory (future, if disk pressure)
- pyvips / libvips dependency
- Pixel-peep tier (on-demand from RAW, future)
- Tagger or AI pipeline changes
- Cull-before-ingest GUI
