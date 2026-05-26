#!/usr/bin/env python3
"""Smoke test: Qwen 2.5 VL 32B 4-bit via mlx-vlm.

Validates:
  - Model loads on Apple Silicon (MLX)
  - Generates a description on one DAM thumbnail
  - Throughput is in expected range (~6-15s per image at 32B-4bit)

Compares output side-by-side with LLaVA's prior description from DB.
Read-only on dam.db. NO bulk processing.
"""
import sqlite3
import time
from pathlib import Path

DB = Path("/Users/janinieminen/.dam/dam.db")
THUMB_DIR = Path("/Users/janinieminen/Documents/dam/thumbs")
PREVIEW_DIR = Path("/Users/janinieminen/Documents/dam/previews")

MODEL = "mlx-community/Qwen2.5-VL-32B-Instruct-4bit"

# Same prompt as production VISION_PROMPT in dam_tagger.py (for apples-to-apples)
PROMPT = (
    "You are writing catalog entries for a documentary photography archive. "
    "Describe what is in this photograph in 2-4 short, factual sentences. "
    "Name specific subjects, objects, settings, and actions. "
    "If there is text visible in the image, transcribe it exactly. "
    "Mention light quality only if distinctive. "
    "Do NOT start with 'The photograph', 'In the image', 'The image captures', "
    "'This photograph' or similar. Start directly with the subject. "
    "Do NOT use phrases like 'adding to the sense of', 'suggesting a', "
    "'serves to highlight', 'drawing the viewer's eye'. Be concrete, not interpretive."
)

# Test on the known-problem images from test_vlm_compare.py
TEST_IDS = [6210, 280, 160, 2, 11]


def pick_input(image_id: int) -> Path | None:
    """Prefer 2048px preview, fall back to 300px thumbnail."""
    for d in (PREVIEW_DIR, THUMB_DIR):
        p = d / f"{image_id}.jpg"
        if p.exists():
            return p
    return None


def main():
    from mlx_vlm import load, generate
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_config

    print(f"Loading {MODEL} ...")
    t0 = time.time()
    model, processor = load(MODEL)
    config = load_config(MODEL)
    print(f"  loaded in {time.time()-t0:.1f}s")

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    for img_id in TEST_IDS:
        inp = pick_input(img_id)
        row = conn.execute("SELECT id, file_name, ai_description FROM images WHERE id = ?", (img_id,)).fetchone()
        if not inp or not row:
            print(f"  skip id={img_id} (no thumb/preview or DB row)")
            continue

        print(f"\n{'='*70}")
        print(f"id={img_id}  file={row['file_name']}")
        print(f"input: {inp.name} ({inp.parent.name})")
        print(f"LLaVA prior: {(row['ai_description'] or '(none)')[:200]}")

        messages = [{"role": "user", "content": PROMPT}]
        formatted = apply_chat_template(processor, config, messages, num_images=1)

        t0 = time.time()
        result = generate(
            model,
            processor,
            formatted,
            image=[str(inp)],
            max_tokens=200,
            verbose=False,
        )
        elapsed = time.time() - t0

        # mlx-vlm generate returns either a string or a GenerationResult object
        if hasattr(result, "text"):
            text = result.text
        else:
            text = str(result)

        print(f"Qwen 32B-4bit ({elapsed:.1f}s): {text.strip()}")

    conn.close()
    print(f"\n{'='*70}\nDone.")


if __name__ == "__main__":
    main()
