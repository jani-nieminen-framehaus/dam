"""
DAM Schema — database schema definition and initialisation.

Contains the canonical SQLite schema for the DAM database, plus init_db()
which creates the database and loads the sqlite-vec extension.

Usage:
    from dam_schema import init_db
    conn = init_db()
"""

import dam_config
from dam_db import get_db
from storage_utils import derive_legacy_identity

# ============================================================
# DATABASE SCHEMA
# ============================================================

SCHEMA_SQL = """
-- Core image table (one row per image GROUP)
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
    file_path TEXT UNIQUE NOT NULL,
    file_name TEXT NOT NULL,
    file_type TEXT,
    file_size INTEGER,
    volume TEXT,
    relative_path TEXT,
    date_folder TEXT,

    -- EXIF: camera
    camera_make TEXT,
    camera_model TEXT,
    camera_serial TEXT,
    camera_short TEXT,
    mount TEXT,

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
    orphan_jpeg BOOLEAN DEFAULT 0,

    -- Manual: workflow (defaults only — populated in Phase 2 UI)
    rating INTEGER DEFAULT 0,
    pick TEXT DEFAULT 'unmarked',
    edit_status TEXT DEFAULT 'unculled',
    color_label TEXT DEFAULT 'none',
    is_selkie BOOLEAN DEFAULT 0,
    notes TEXT,

    -- AI tagging
    ai_description TEXT,
    ai_tagged_at TIMESTAMP,

    -- Triptych-specific
    triptych_leg TEXT,
    narrative_arc TEXT,
    location_type TEXT,

    -- Timestamps
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Many-to-many: images <-> projects
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS image_projects (
    image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    PRIMARY KEY (image_id, project_id)
);

-- Many-to-many: images <-> subjects
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS image_subjects (
    image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
    subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE,
    PRIMARY KEY (image_id, subject_id)
);

-- Many-to-many: images <-> keywords
CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY,
    keyword TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS image_keywords (
    image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
    keyword_id INTEGER REFERENCES keywords(id) ON DELETE CASCADE,
    PRIMARY KEY (image_id, keyword_id)
);

-- Thumbnail cache reference
CREATE TABLE IF NOT EXISTS thumbnails (
    image_id INTEGER PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
    thumb_path TEXT,
    thumb_width INTEGER,
    thumb_height INTEGER,
    generated_at TIMESTAMP
);

-- AI embedding vectors (sqlite-vec)
CREATE VIRTUAL TABLE IF NOT EXISTS image_embeddings USING vec0(
    image_id INTEGER PRIMARY KEY,
    embedding float[768]
);

-- Indexes for fast queries
CREATE INDEX IF NOT EXISTS idx_date_taken ON images(date_taken);
CREATE INDEX IF NOT EXISTS idx_camera_short ON images(camera_short);
CREATE INDEX IF NOT EXISTS idx_volume ON images(volume);
CREATE INDEX IF NOT EXISTS idx_rating ON images(rating);
CREATE INDEX IF NOT EXISTS idx_pick ON images(pick);
CREATE INDEX IF NOT EXISTS idx_edit_status ON images(edit_status);
CREATE INDEX IF NOT EXISTS idx_triptych_leg ON images(triptych_leg);
CREATE INDEX IF NOT EXISTS idx_is_selkie ON images(is_selkie);
CREATE INDEX IF NOT EXISTS idx_date_folder ON images(date_folder);
CREATE INDEX IF NOT EXISTS idx_file_type ON images(file_type);

-- Flat view: normalized tables collapsed to JSON arrays per image
-- Flask queries this instead of writing multi-join queries manually
CREATE VIEW IF NOT EXISTS images_flat AS
SELECT
    i.*,
    COALESCE(json_group_array(DISTINCT p.name)
        FILTER (WHERE p.name IS NOT NULL), '[]') AS projects,
    COALESCE(json_group_array(DISTINCT s.name)
        FILTER (WHERE s.name IS NOT NULL), '[]') AS subjects,
    COALESCE(json_group_array(DISTINCT k.keyword)
        FILTER (WHERE k.keyword IS NOT NULL), '[]') AS keywords
FROM images i
LEFT JOIN image_projects ip ON i.id = ip.image_id
LEFT JOIN projects p      ON ip.project_id = p.id
LEFT JOIN image_subjects isubj ON i.id = isubj.image_id
LEFT JOIN subjects s      ON isubj.subject_id = s.id
LEFT JOIN image_keywords ik ON i.id = ik.image_id
LEFT JOIN keywords k      ON ik.keyword_id = k.id
GROUP BY i.id;

-- Seed default projects
INSERT OR IGNORE INTO projects (name, description) VALUES
    ('triptych', 'Documentary triptych project'),
    ('evidence', 'Legal/dispute documentation'),
    ('street', 'Street photography'),
    ('personal', 'Family snapshots, non-project'),
    ('test', 'Gear testing, calibration'),
    ('client', 'Work for others');
"""


def init_db():
    """Create database and tables if they don't exist.

    Returns an open sqlite3 connection with sqlite-vec loaded.
    """
    dam_config.DAM_ROOT.mkdir(parents=True, exist_ok=True)
    dam_config.THUMB_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript(SCHEMA_SQL)
    _migrate_storage_identity(conn)
    conn.commit()
    return conn


def _migrate_storage_identity(conn):
    """Backfill logical volume identity for existing rows on older schemas."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(images)")}
    if "relative_path" not in columns:
        conn.execute("ALTER TABLE images ADD COLUMN relative_path TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_relative_path ON images(relative_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_volume_relative_path ON images(volume, relative_path)")

    rows = conn.execute("SELECT id, file_path, volume, relative_path FROM images").fetchall()
    updates = []
    for row in rows:
        logical_volume, relative_path = derive_legacy_identity(row["file_path"], dam_config.VOLUME_ALIASES)
        if logical_volume is None and row["volume"] is not None:
            logical_volume = row["volume"]
        if logical_volume == row["volume"] and relative_path == row["relative_path"]:
            continue
        updates.append((logical_volume, relative_path, row["id"]))

    if updates:
        conn.executemany("UPDATE images SET volume = ?, relative_path = ? WHERE id = ?", updates)
