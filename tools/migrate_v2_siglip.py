#!/usr/bin/env python3
"""Phase 1: SigLIP schema migration — additive only.

Adds:
  - image_embeddings_siglip (vec0 virtual table, 1152-dim) — parallel to existing
    768-dim image_embeddings. Old table untouched.
  - images.siglip_embedded_at TIMESTAMP — per-stage marker for SigLIP pass
  - images.classified_at TIMESTAMP — per-stage marker for classifier pass
  - images.described_at TIMESTAMP — per-stage marker for new VLM description pass
    (alias-friendly with existing ai_tagged_at; new pipeline uses described_at)
  - image_keywords.confidence REAL — classifier confidence per tag, NULL for
    human-added or legacy-LLaVA keywords
  - idx_siglip_pending, idx_classify_pending, idx_describe_pending partial indexes

Touches NO existing data. Old 768-dim image_embeddings stays in place. Old
columns stay in place. The new pipeline writes to the new columns/tables;
the old pipeline (if anyone ever runs it again) continues to write to old.

Bumps user_version from 1 -> 2. Idempotent — safe to run twice (uses IF NOT
EXISTS everywhere). Wrapped in transaction. Aborts if user_version != 1.
"""
import os
import sqlite3
import sys
import sqlite_vec
from pathlib import Path

# Resolve through symlink — the real DB is at ~/.dam/dam.db
DB_PATH = Path(os.path.expanduser("~/.dam/dam.db"))
assert DB_PATH.exists(), f"DB not found at {DB_PATH}"

EXPECTED_VERSION_BEFORE = 1
NEW_VERSION = 2


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # sqlite-vec is needed to create vec0 virtual tables
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    current = conn.execute("PRAGMA user_version").fetchone()[0]
    print(f"current user_version: {current}")

    if current >= NEW_VERSION:
        print(f"  already at version {current} >= {NEW_VERSION} — nothing to do")
        conn.close()
        return

    if current != EXPECTED_VERSION_BEFORE:
        print(f"  ERROR: expected user_version {EXPECTED_VERSION_BEFORE}, got {current}")
        print(f"  refusing to migrate from unexpected version")
        conn.close()
        sys.exit(1)

    # Pre-migration counts for verification
    n_images = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    n_embeddings_768 = conn.execute("SELECT COUNT(*) FROM image_embeddings").fetchone()[0]
    n_keywords = conn.execute("SELECT COUNT(*) FROM image_keywords").fetchone()[0]
    print(f"\npre-migration:")
    print(f"  images:                {n_images}")
    print(f"  image_embeddings (768): {n_embeddings_768}")
    print(f"  image_keywords:        {n_keywords}")

    print(f"\nrunning migration -> version {NEW_VERSION}...")

    try:
        conn.execute("BEGIN")

        # ── New 1152-dim vec0 table, parallel to old 768-dim ──
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS image_embeddings_siglip USING vec0(
                image_id INTEGER PRIMARY KEY,
                embedding float[1152]
            )
        """)
        print("  + image_embeddings_siglip (vec0, 1152-dim)")

        # ── Per-stage timestamps on images table ──
        # SQLite ALTER TABLE ADD COLUMN doesn't support IF NOT EXISTS,
        # so check pragma_table_info first.
        existing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(images)").fetchall()}

        for col in ("siglip_embedded_at", "classified_at", "described_at"):
            if col in existing_cols:
                print(f"  = images.{col} already exists, skip")
            else:
                conn.execute(f"ALTER TABLE images ADD COLUMN {col} TIMESTAMP")
                print(f"  + images.{col}")

        # ── Confidence column on image_keywords (multi-label classifier prob) ──
        ik_cols = {r["name"] for r in conn.execute("PRAGMA table_info(image_keywords)").fetchall()}
        if "confidence" in ik_cols:
            print("  = image_keywords.confidence already exists, skip")
        else:
            conn.execute("ALTER TABLE image_keywords ADD COLUMN confidence REAL")
            print("  + image_keywords.confidence (NULL for human/legacy entries)")

        # ── Partial indexes for the new pipeline's queue queries ──
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_siglip_pending
            ON images(id) WHERE siglip_embedded_at IS NULL
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_classify_pending
            ON images(id) WHERE classified_at IS NULL
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_describe_pending
            ON images(id) WHERE described_at IS NULL
        """)
        print("  + idx_siglip_pending, idx_classify_pending, idx_describe_pending")

        # ── Bump version ──
        conn.execute(f"PRAGMA user_version = {NEW_VERSION}")

        conn.execute("COMMIT")
        print(f"\nCOMMIT user_version -> {NEW_VERSION}")

    except Exception as e:
        conn.execute("ROLLBACK")
        print(f"\nROLLBACK due to: {e}")
        conn.close()
        sys.exit(1)

    # Post-migration verification
    n_images_after = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    n_embeddings_768_after = conn.execute("SELECT COUNT(*) FROM image_embeddings").fetchone()[0]
    n_keywords_after = conn.execute("SELECT COUNT(*) FROM image_keywords").fetchone()[0]
    n_siglip = conn.execute("SELECT COUNT(*) FROM image_embeddings_siglip").fetchone()[0]
    new_ver = conn.execute("PRAGMA user_version").fetchone()[0]

    print(f"\npost-migration:")
    print(f"  user_version:               {new_ver}")
    print(f"  images:                     {n_images_after}  (was {n_images})")
    print(f"  image_embeddings (768):     {n_embeddings_768_after}  (was {n_embeddings_768})")
    print(f"  image_embeddings_siglip:    {n_siglip}  (empty, ready for pass)")
    print(f"  image_keywords:             {n_keywords_after}  (was {n_keywords})")

    # Sanity: did we lose data?
    if n_images_after != n_images:
        print(f"\n  WARNING: image count changed unexpectedly")
        sys.exit(2)
    if n_embeddings_768_after != n_embeddings_768:
        print(f"\n  WARNING: old embedding count changed unexpectedly")
        sys.exit(2)
    if n_keywords_after != n_keywords:
        print(f"\n  WARNING: keyword count changed unexpectedly")
        sys.exit(2)

    print("\nOK")
    conn.close()


if __name__ == "__main__":
    main()
