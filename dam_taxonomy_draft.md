# DAM Taxonomy Design — Draft v0.1
# March 9, 2026

## THE PROBLEM

100k+ images across 8 drives, 4 camera systems, 4 sidecar formats,
inconsistent naming, and a multi-year documentary project with no
way to search "show me every frame of Jorma from the Nikon, December 2025."

## CORE CONCEPT: THE IMAGE GROUP

One photograph = one group. The group contains:
- 1 primary file (the RAW: .RW2, .NEF, .RAF)
- 0-1 JPEG pair (camera-generated)
- 0-N sidecars (.xmp, .on1, .radiant, .RW2.xmp)

The DAM indexes groups, not individual files. When you search,
you find images. The sidecars follow silently.

### Group detection logic:
```
Given: DC-S1M2ES - P1055133.RW2

Related files (same stem):
  DC-S1M2ES - P1055133.xmp          → XMP sidecar
  DC-S1M2ES - P1055133.RW2.xmp      → alt XMP sidecar
  DC-S1M2ES - P1055133.on1          → ON1 sidecar
  DC-S1M2ES - P1055133.RW2.radiant  → Radiant sidecar
  DC-S1M2ES - P1055133.JPG.radiant  → Radiant JPEG sidecar

Group key: folder_path + base_stem (strip all extensions)
```

Collision handling: DSCF0350 from X-T30 vs X-Pro3 in same folder
→ Already resolved by camera prefix in filename
→ EXIF SerialNumber is the authoritative disambiguator

---

## LAYER 1: AUTO-EXTRACTED (exiftool, zero human input)

These fields are populated on first scan. Never needs manual entry.

### File identity
| Field | Source | Example |
|-------|--------|---------|
| file_path | filesystem | /Volumes/Kuvia1/2025-12-15/DC-S1M2ES - P1055133.RW2 |
| file_name | filesystem | DC-S1M2ES - P1055133.RW2 |
| file_size | filesystem | 32,456,789 |
| file_type | extension | RW2 |
| volume | parsed from path | Kuvia1 |
| date_folder | parsed from path | 2025-12-15 |

### Camera & lens
| Field | EXIF tag | Example |
|-------|----------|---------|
| camera_make | Make | Panasonic |
| camera_model | Model | DC-S1M2ES |
| camera_serial | SerialNumber | WH2AA... |
| lens_model | LensModel | LUMIX S 50/F1.8 |
| lens_serial | LensSerialNumber | ... |

### Exposure
| Field | EXIF tag | Example |
|-------|----------|---------|
| date_taken | DateTimeOriginal | 2025-12-15 14:23:07 |
| aperture | FNumber | 1.8 |
| shutter_speed | ExposureTime | 1/250 |
| iso | ISO | 800 |
| focal_length | FocalLength | 50 |
| focal_length_35eq | FocalLengthIn35mmFormat | 50 |
| exposure_comp | ExposureCompensation | -0.3 |
| metering_mode | MeteringMode | Multi-segment |
| white_balance | WhiteBalance | Auto |
| flash | Flash | No Flash |

### Image properties
| Field | EXIF tag | Example |
|-------|----------|---------|
| width | ImageWidth | 6000 |
| height | ImageHeight | 4000 |
| orientation | Orientation | Horizontal |
| color_space | ColorSpace | sRGB |
| bit_depth | BitsPerSample | 14 |

### GPS (when available)
| Field | EXIF tag |
|-------|----------|
| gps_lat | GPSLatitude |
| gps_lon | GPSLongitude |
| gps_alt | GPSAltitude |

### Sidecar inventory
| Field | Type | Note |
|-------|------|------|
| has_jpeg | bool | camera-generated JPEG pair exists |
| has_xmp | bool | .xmp sidecar exists |
| has_xmp_alt | bool | .RW2.xmp / .RAF.xmp variant exists |
| has_on1 | bool | ON1 Photo RAW sidecar |
| has_radiant | bool | Radiant Photo sidecar |
| sidecar_count | int | total sidecar files |

---

## LAYER 2: AUTO-DERIVED (computed, no human input)

| Field | Logic | Use |
|-------|-------|-----|
| time_of_day | hour bucket: dawn(5-7), morning(7-11), midday(11-14), afternoon(14-17), golden(17-19), evening(19-22), night(22-5) | "show me all night shots" |
| season | month-based: winter(12-2), spring(3-5), summer(6-8), autumn(9-11) | seasonal filtering |
| camera_short | map model → friendly name: DC-S1M2ES→"S1IIE", Z f→"Zf", X-T30→"XT30", X-H2→"XH2" | quick filtering |
| mount | derived from camera: S1IIE→L-mount, Zf→Z-mount, XT30/XH2→X-mount | lens ecosystem queries |
| edited_anywhere | has_xmp OR has_on1 OR has_radiant | "what have I touched?" |
| orphan_jpeg | has no RAW sibling, is JPEG only | identify phone shots or exports |

---

## LAYER 3: MANUAL TAGS (human input — this is the value)

### 3a. Project assignment (many-to-many)

An image can belong to multiple projects.

| Project | Description |
|---------|-------------|
| triptych | The documentary triptych project |
| evidence | Legal/dispute documentation (Jimms, Rajala, Fortum, etc.) |
| street | Street photography |
| personal | Family snapshots, non-project |
| test | Gear testing, calibration |
| client | Work for others (if applicable) |

### 3b. Triptych-specific tags (only for project=triptych)

| Field | Values | Note |
|-------|--------|------|
| triptych_leg | color_doc / bw_portrait / abstract | The three visual languages |
| subject | free-text, multi-value | Jorma, Heidi, Eemil, self, environment, hands, objects... |
| location_type | home / care_facility / hospital / outdoors / transit | Where |
| narrative_arc | beginning / middle / current | Rough chronological position in the story |

### 3c. Universal manual tags (any image)

| Field | Values | Note |
|-------|--------|------|
| rating | 0-5 | Standard star rating |
| pick | pick / reject / unmarked | Quick cull flag |
| edit_status | unculled / rejected / selected / developed / printed / exhibited | Workflow stage |
| color_label | red / yellow / green / blue / purple / none | Flexible flag |
| keywords | free-text, multi-value | General keywords |
| notes | free-text | Anything |
| is_selkie | bool | "The one." Portfolio-grade select |

---

## DESIGN DECISIONS

### 1. DB-only tags. Never write back to XMP.
The sidecar situation is already a mess (4 formats, inconsistent presence).
Adding another writer makes it worse. The SQLite DB IS the organizational
layer. XMP/on1/radiant remain as-is for their respective editors.

Exception: If you later want C1/darktable to read your ratings, we can
do a one-way EXPORT from DB → XMP. But never bidirectional sync.

### 2. Additive tagging, not hierarchical categories.
Don't force images into a single bucket. An image of Jorma's hands
at the care facility is simultaneously:
- project: triptych
- triptych_leg: abstract (or color_doc, depending on treatment)
- subject: Jorma, hands
- location_type: care_facility
- rating: 4
- edit_status: developed

### 3. Keyboard-driven workflow for tagging.
ADHD brain needs: see image → press key → next image.
Not: see image → right-click → navigate menu → select tag → confirm.
The UI must support single-keystroke rating and flagging.

### 4. The "where is everything" problem.
Images live on multiple drives. Drives aren't always mounted.
The DB stores the full path AND the volume name separately.
If Kuvia1 isn't mounted, you still see the metadata and embedded
thumbnail. You just can't open the RAW until you plug it in.

### 5. Embedded JPEG thumbnails cached in DB.
On first scan, extract the embedded JPEG preview from each RAW
(rawpy.extract_thumb or exiftool -b -JpgFromRaw).
Store as blob or in a thumbnail cache directory.
This is how you get Photo Mechanic-speed browsing.

---

## SCHEMA SKETCH (SQLite)

```sql
-- Core image table (one row per image GROUP)
CREATE TABLE images (
    id INTEGER PRIMARY KEY,
    file_path TEXT UNIQUE NOT NULL,
    file_name TEXT NOT NULL,
    file_type TEXT,
    file_size INTEGER,
    volume TEXT,
    date_folder TEXT,

    -- EXIF: camera
    camera_make TEXT,
    camera_model TEXT,
    camera_serial TEXT,
    camera_short TEXT,  -- derived friendly name
    mount TEXT,         -- derived

    -- EXIF: lens
    lens_model TEXT,
    lens_serial TEXT,

    -- EXIF: exposure
    date_taken TIMESTAMP,
    aperture REAL,
    shutter_speed TEXT,
    iso INTEGER,
    focal_length REAL,
    focal_length_35eq REAL,
    exposure_comp REAL,
    metering_mode TEXT,
    white_balance TEXT,
    flash TEXT,

    -- EXIF: image
    width INTEGER,
    height INTEGER,
    orientation TEXT,
    color_space TEXT,
    bit_depth INTEGER,

    -- GPS
    gps_lat REAL,
    gps_lon REAL,
    gps_alt REAL,

    -- Derived
    time_of_day TEXT,
    season TEXT,

    -- Sidecars
    has_jpeg BOOLEAN DEFAULT 0,
    has_xmp BOOLEAN DEFAULT 0,
    has_on1 BOOLEAN DEFAULT 0,
    has_radiant BOOLEAN DEFAULT 0,
    sidecar_count INTEGER DEFAULT 0,
    edited_anywhere BOOLEAN DEFAULT 0,

    -- Manual: workflow
    rating INTEGER DEFAULT 0,
    pick TEXT DEFAULT 'unmarked',  -- pick/reject/unmarked
    edit_status TEXT DEFAULT 'unculled',
    color_label TEXT DEFAULT 'none',
    is_selkie BOOLEAN DEFAULT 0,
    notes TEXT,

    -- Triptych-specific
    triptych_leg TEXT,  -- color_doc/bw_portrait/abstract/NULL
    narrative_arc TEXT,  -- beginning/middle/current/NULL
    location_type TEXT,

    -- Timestamps
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Many-to-many: images ↔ projects
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT
);

CREATE TABLE image_projects (
    image_id INTEGER REFERENCES images(id),
    project_id INTEGER REFERENCES projects(id),
    PRIMARY KEY (image_id, project_id)
);

-- Many-to-many: images ↔ subjects
CREATE TABLE subjects (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE image_subjects (
    image_id INTEGER REFERENCES images(id),
    subject_id INTEGER REFERENCES subjects(id),
    PRIMARY KEY (image_id, subject_id)
);

-- Many-to-many: images ↔ keywords
CREATE TABLE keywords (
    id INTEGER PRIMARY KEY,
    keyword TEXT UNIQUE NOT NULL
);

CREATE TABLE image_keywords (
    image_id INTEGER REFERENCES images(id),
    keyword_id INTEGER REFERENCES keywords(id),
    PRIMARY KEY (image_id, keyword_id)
);

-- Thumbnail cache reference
CREATE TABLE thumbnails (
    image_id INTEGER PRIMARY KEY REFERENCES images(id),
    thumb_path TEXT,       -- path to cached JPEG
    thumb_width INTEGER,
    thumb_height INTEGER,
    generated_at TIMESTAMP
);

-- Indexes for fast queries
CREATE INDEX idx_date_taken ON images(date_taken);
CREATE INDEX idx_camera_short ON images(camera_short);
CREATE INDEX idx_volume ON images(volume);
CREATE INDEX idx_rating ON images(rating);
CREATE INDEX idx_pick ON images(pick);
CREATE INDEX idx_edit_status ON images(edit_status);
CREATE INDEX idx_triptych_leg ON images(triptych_leg);
CREATE INDEX idx_is_selkie ON images(is_selkie);
```

---

## EXAMPLE QUERIES

```sql
-- "Every frame of Jorma from the Nikon in December 2025"
SELECT i.* FROM images i
JOIN image_subjects isub ON i.id = isub.image_id
JOIN subjects s ON isub.subject_id = s.id
WHERE s.name = 'Jorma'
  AND i.camera_short = 'Zf'
  AND i.date_taken BETWEEN '2025-12-01' AND '2025-12-31';

-- "All triptych selects, abstract leg, rated 4+"
SELECT * FROM images
WHERE triptych_leg = 'abstract'
  AND rating >= 4
  AND is_selkie = 1;

-- "What have I never culled?"
SELECT * FROM images
WHERE edit_status = 'unculled'
ORDER BY date_taken DESC;

-- "Everything shot on vintage glass" (manual focus lenses)
SELECT * FROM images
WHERE lens_model LIKE '%TTArtisan%'
   OR lens_model LIKE '%Voigtlander%'
   OR lens_model LIKE '%Helios%';

-- "How many images per camera?"
SELECT camera_short, COUNT(*) FROM images
GROUP BY camera_short;

-- "Unedited picks from the triptych"
SELECT * FROM images
WHERE pick = 'pick'
  AND edit_status = 'selected'
  AND triptych_leg IS NOT NULL;
```

---

## WHAT THIS DOES NOT DO

- No RAW rendering (use FRV or darktable for that)
- No pixel editing
- No sync with C1/LR catalogs (one-way export possible later)
- No cloud anything

## WHAT THIS DOES DO

- Find any image in your archive in under a second
- Track the triptych project across cameras, drives, and years
- Know what you've culled and what you haven't
- Know what's been edited and in which tool
- Work when drives are offline (metadata + thumbnails cached)
- AI auto-tagging with local models (LLaVA 34b + Llama 3.1 70b + nomic-embed-text via Ollama)
- Semantic search across your entire archive ("man standing by window")
- Full keyboard-driven culling and tagging workflow
- Bulk operations: multi-select, batch rating/pick/status/delete
- Zero subscription cost
- You built it, you own it, you understand it

---

## IMPLEMENTATION STATUS (March 2026)

All three layers of the taxonomy are fully implemented:

- **Layer 1** (Auto-extracted): 30+ EXIF fields via exiftool, sidecar inventory
- **Layer 2** (Auto-derived): time_of_day, season, camera_short, mount, edited_anywhere, orphan_jpeg
- **Layer 3** (Manual tags): All fields editable in UI — rating, pick, edit_status, color_label,
  is_selkie, notes, triptych_leg, narrative_arc, location_type, projects (m2m),
  subjects (m2m), keywords (m2m)
- **AI tagging**: Vision descriptions, structured keyword extraction, 768-dim embeddings,
  burst detection (saves ~150 hours on a 35k image archive)
- **Filtering**: All manual tag fields are filterable in the SPA filter panel,
  including project and subject (many-to-many)
- **Bulk ops**: Multi-select in grid, bulk pick/reject/rate/status/delete
- **Delete**: Single and bulk delete from DB (files on disk untouched)
