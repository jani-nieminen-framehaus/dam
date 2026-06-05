#!/usr/bin/env python3
"""Smoke test: Qwen 2.5 VL via transformers on CUDA.

Validates:
  - Model loads (defaults to MODEL_VARIANT in dam_vlm.py — currently 32B-bnb4)
  - Generates descriptions on a handful of DAM thumbnails/previews
  - Throughput is in the expected range (~10 s/img for 32B-bnb4 on Turing, ~3 s for 7B-fp16)

Picks 5 newest images that lack a description (described_at IS NULL), falling
back to plain newest if all rows are described. Read-only on dam.db. NO writes.

Was previously an MLX-only script; now delegates to dam_vlm (CUDA + transformers).
"""
import sys
import time
from pathlib import Path

# Make the repo root importable so dam_config / dam_vlm resolve from here.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dam_config import DB_PATH
from dam_vlm import (
    describe_image,
    get_model,
    pick_input,
    MODEL_ID,
    MODEL_VARIANT,
)


def main():
    import sqlite3

    print(f"Loading {MODEL_ID}  (variant={MODEL_VARIANT}) ...")
    t0 = time.time()
    get_model()
    print(f"  loaded in {time.time()-t0:.1f}s")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, file_name, ai_description FROM images "
        "WHERE described_at IS NULL ORDER BY id DESC LIMIT 5"
    ).fetchall()
    if not rows:
        rows = conn.execute(
            "SELECT id, file_name, ai_description FROM images "
            "ORDER BY id DESC LIMIT 5"
        ).fetchall()
    conn.close()

    times = []
    for row in rows:
        inp = pick_input(row["id"])
        if not inp:
            print(f"  skip id={row['id']} (no preview/thumb)")
            continue

        print(f"\n{'='*70}")
        print(f"id={row['id']}  file={row['file_name']}")
        print(f"input: {inp.name} ({inp.parent.name})")
        prior = (row["ai_description"] or "(none)")[:200]
        print(f"prior: {prior}")

        t0 = time.time()
        try:
            text = describe_image(inp)
            elapsed = time.time() - t0
            times.append(elapsed)
            print(f"new ({elapsed:.1f}s): {text}")
        except Exception as e:
            print(f"FAIL: {e}")

    if times:
        avg = sum(times) / len(times)
        print(f"\n{'='*70}\n{len(times)} ok, avg {avg:.2f}s/img  (target: 32B-bnb4 ~=10s, 7B-fp16 ~=3s)")
    else:
        print("\nNo successful runs.")


if __name__ == "__main__":
    main()
