#!/usr/bin/env python3
"""Reclassify all SigLIP-embedded images against the current vocabulary.

Use case: vocabulary updated, embeddings unchanged. Re-run only the cheap
classification step (no re-encoding of images).

Strategy:
  - Wipe ALL classifier-assigned tags (rows where confidence IS NOT NULL).
  - Keep legacy LLaVA-era tags untouched (confidence IS NULL).
  - Read each image's stored 1152-dim SigLIP embedding from the vec0 table.
  - Classify against the current vocabulary.
  - Write new tags with confidence.

Why this approach rather than just running bootstrap_siglip.py --classify:
The classify-only mode in bootstrap re-encodes the image (because reading
raw vec0 blobs by primary key is awkward through stock sqlite-vec). This
script reads the stored embeddings directly via the vec0 query interface,
making reclassify properly cheap.

Run (from the project root):
  uv run python tools/reclassify.py

Idempotent. Safe to interrupt and resume (per-batch commits, although the
ALL-or-nothing wipe at the start means you should NOT interrupt during the
first ~5 seconds when the wipe happens).
"""
import sys, os, time, sqlite3, struct
from pathlib import Path

import sqlite_vec
import torch

sys.path.insert(0, "/Users/janinieminen/Documents/dam")
import dam_siglip

DB = Path(os.path.expanduser("~/.dam/dam.db"))
OUTER_CHUNK = 2000  # how many images per DB commit
CONFIDENCE_THRESHOLD = 0.10
MAX_TAGS_PER_IMAGE = 12


def open_db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def main():
    conn = open_db()

    n_before = conn.execute(
        "SELECT COUNT(*) FROM image_keywords WHERE confidence IS NOT NULL"
    ).fetchone()[0]
    n_legacy = conn.execute(
        "SELECT COUNT(*) FROM image_keywords WHERE confidence IS NULL"
    ).fetchone()[0]
    print(f"current state: {n_before} classifier rows, {n_legacy} legacy rows")

    print("WIPING all classifier-assigned tags (confidence IS NOT NULL)...")
    cur = conn.execute("DELETE FROM image_keywords WHERE confidence IS NOT NULL")
    print(f"  deleted {cur.rowcount} rows")
    # Also reset classified_at so it reflects this fresh pass
    conn.execute("UPDATE images SET classified_at = NULL WHERE classified_at IS NOT NULL")
    conn.commit()

    # Load vocabulary and precompute its text embeddings
    tags = dam_siglip.load_vocabulary()
    print(f"vocabulary: {len(tags)} tags")
    vocab_emb = dam_siglip.precompute_vocab_embeddings(tags)

    # Get all (image_id, embedding) — read raw float blobs back from vec0
    # sqlite-vec stores embedding as a float blob; we read it back as-is.
    print("loading all stored SigLIP embeddings...")
    t0 = time.time()
    rows = conn.execute(
        "SELECT image_id, embedding FROM image_embeddings_siglip ORDER BY image_id"
    ).fetchall()
    print(f"  loaded {len(rows)} embeddings in {time.time()-t0:.1f}s")

    EMBED_DIM = 1152
    EMBED_BYTES = EMBED_DIM * 4

    def deserialize(blob):
        return struct.unpack(f"{EMBED_DIM}f", blob)

    t0 = time.time()
    classified = 0
    failed = 0

    for chunk_start in range(0, len(rows), OUTER_CHUNK):
        chunk = rows[chunk_start : chunk_start + OUTER_CHUNK]
        # Build a tensor of (chunk_size, 1152) for batched matrix multiply
        try:
            mat = torch.tensor(
                [deserialize(r["embedding"]) for r in chunk]
            )  # (B, 1152)
        except Exception as e:
            print(f"  CHUNK DESERIALIZE FAIL at {chunk_start}: {e}")
            failed += len(chunk)
            continue

        # Similarity matrix: (B, V) — rows are images, cols are tags
        sims = (mat @ vocab_emb.T).numpy()

        for i, row in enumerate(chunk):
            row_sims = sims[i]
            scored = [
                (tags[j], float(s))
                for j, s in enumerate(row_sims)
                if s >= CONFIDENCE_THRESHOLD
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            scored = scored[:MAX_TAGS_PER_IMAGE]

            try:
                dam_siglip.write_classifier_tags(conn, row["image_id"], scored)
                classified += 1
            except Exception as e:
                print(f"  WRITE FAIL id={row['image_id']}: {e}")
                failed += 1

        conn.commit()

        elapsed = time.time() - t0
        rate = classified / elapsed if elapsed > 0 else 0
        eta = (len(rows) - classified) / rate / 60 if rate > 0 else 0
        print(
            f"  {classified}/{len(rows)} ({100*classified/len(rows):.1f}%) "
            f"| {rate:.0f} img/s | elapsed {elapsed:.1f}s | ETA {eta:.1f}min"
        )

    conn.commit()

    n_after = conn.execute(
        "SELECT COUNT(*) FROM image_keywords WHERE confidence IS NOT NULL"
    ).fetchone()[0]
    print(
        f"\nDONE: {classified} classified, {failed} failed, "
        f"{n_after} new tag rows (was {n_before}), elapsed {(time.time()-t0)/60:.1f}min"
    )
    conn.close()


if __name__ == "__main__":
    main()
