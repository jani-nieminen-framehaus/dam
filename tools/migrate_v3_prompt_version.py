#!/usr/bin/env python3
"""Phase 7: VLM prompt-versioning column — additive only.

Adds:
  - images.description_prompt_version INTEGER — stamped on every row written
    by dam_vlm.write_image_description(). Lets us target re-describes by
    prompt version if we ever revise. NULL = legacy LLaVA / Qwen smoke test /
    unknown source.

Bumps user_version 2 -> 3. Idempotent. Wrapped in transaction. Aborts if
user_version != 2.

Does NOT backfill description_prompt_version on existing rows. Legacy
descriptions stay NULL; new Qwen pass stamps 1.
"""
import os
import sqlite3
import sys
from pathlib import Path

# Use dam_config so this works cross-platform (was hardcoded ~/.dam/dam.db).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dam_config import DB_PATH

assert DB_PATH.exists(), f"DB not found at {DB_PATH}"

EXPECTED_VERSION_BEFORE = 2
NEW_VERSION = 3


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

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

    n_images = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    n_described = conn.execute(
        "SELECT COUNT(*) FROM images WHERE described_at IS NOT NULL"
    ).fetchone()[0]
    print(f"\npre-migration:")
    print(f"  images:                {n_images}")
    print(f"  with described_at:     {n_described}")

    print(f"\nrunning migration -> version {NEW_VERSION}...")

    try:
        conn.execute("BEGIN")

        existing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(images)").fetchall()}
        if "description_prompt_version" in existing_cols:
            print("  = images.description_prompt_version already exists, skip")
        else:
            conn.execute("ALTER TABLE images ADD COLUMN description_prompt_version INTEGER")
            print("  + images.description_prompt_version (NULL for legacy entries)")

        conn.execute(f"PRAGMA user_version = {NEW_VERSION}")
        conn.execute("COMMIT")
        print(f"\n  user_version: {current} -> {NEW_VERSION}")

    except Exception as e:
        conn.execute("ROLLBACK")
        print(f"\nMIGRATION FAILED, rolled back: {e}")
        conn.close()
        sys.exit(1)

    # Post-migration verification
    print(f"\npost-migration:")
    final_version = conn.execute("PRAGMA user_version").fetchone()[0]
    print(f"  user_version:          {final_version}")
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(images)").fetchall()]
    print(f"  description_prompt_version present: {'description_prompt_version' in cols}")
    n_stamped = conn.execute(
        "SELECT COUNT(*) FROM images WHERE description_prompt_version IS NOT NULL"
    ).fetchone()[0]
    print(f"  rows with non-NULL stamp: {n_stamped} (expected 0 — no backfill)")

    conn.close()
    print("\nOK.")


if __name__ == "__main__":
    main()
