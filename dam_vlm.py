#!/usr/bin/env python3
"""
dam_vlm.py — Qwen 2.5 VL 32B 4-bit (MLX) wrapper for image description.

Replaces (in the new pipeline):
  - dam_tagger.py's LLaVA-via-Ollama description path

Design:
  - Module-level lazy singleton: model loads on first use, stays in memory.
  - MLX-only (Apple Silicon). No CUDA/CPU fallback for the VLM — this model
    is mac-only here. Use a different module if you want portability.
  - Image input always a path; mlx_vlm handles open + resize internally.
  - Per-image inference, ~10-20s on M3 Ultra at 4-bit quant.
  - DB writes are atomic per image. Caller manages transaction + commit.
  - 22 GB resident during inference, drops to ~6 GB between images.

Depends on schema v3 (description_prompt_version column on images).
Run tools/migrate_v3_prompt_version.py before any DB writes.

This module is import-safe — loading the module does NOT load the model.
The model loads on the first call to describe_image / get_model.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

MODEL_ID = "mlx-community/Qwen2.5-VL-32B-Instruct-4bit"

# Prompt version stamped on every description this module writes.
# Bump this constant + write a new migration if you change DESCRIPTION_PROMPT.
PROMPT_VERSION = 1

# Derived from tools/smoke_qwen.py PROMPT, tightened after v1 smoke revealed
# Qwen wrapping descriptions with trailing mood projections ("creating a calm
# and intimate atmosphere", "cozy", "highlighting"). v2 changes: explicit
# mood-word ban, concrete lighting examples.
#
# Note: v3 attempted a shape-attack (banned final-sentence opening phrases) but
# was rolled back. Pushing the prompt that hard suppressed Qwen's natural
# wrap-up pattern in ways that risked confabulated content filling the space
# (third box appearing on id=280, additional objects on id=6210). Factual
# wrap-up sentences ("The walls are plain, and the floor is light-colored
# wood") are kept because they are searchable observations, not mood projections.
DESCRIPTION_PROMPT = (
    "You are writing catalog entries for a documentary photography archive. "
    "Describe what is in this photograph in 2-4 short, factual sentences. "
    "Name specific subjects, objects, settings, and actions. "
    "If there is text visible in the image, transcribe it exactly. "
    "Do NOT start with 'The photograph', 'In the image', 'The image captures', "
    "'This photograph' or similar. Start directly with the subject. "
    "Do NOT use phrases like 'adding to the sense of', 'suggesting a', "
    "'serves to highlight', 'drawing the viewer's eye', 'highlighting'. "
    "Do NOT project mood or atmosphere. Banned words: cozy, intimate, calm, "
    "peaceful, serene, warm (as feeling), vibrant, dramatic, captures the essence. "
    "Mention light only if it is genuinely unusual (e.g. shaft of window light, "
    "single candle, hard side-light, neon, mixed-temperature sources). "
    "Do not describe ordinary indoor lighting such as 'soft', 'even', 'subdued', "
    "or 'dim' in a trailing sentence. If the description already implies the "
    "lighting (e.g. 'dimly lit room'), do not restate it. "
    "End after the last concrete observation. Do not add a closing summary "
    "sentence about lighting, mood, atmosphere, or setting."
)

MAX_TOKENS = 200

# Input source priority — 2048px preview first, 300px thumb as fallback
PREVIEW_DIR = Path(os.path.expanduser("~/Documents/dam/previews"))
THUMB_DIR = Path(os.path.expanduser("~/Documents/dam/thumbs"))


# ── Lazy model singleton ──────────────────────────────────────────────────────

_model = None
_processor = None
_config = None


def get_model():
    """Load and return (model, processor, config). Cached after first call.
    First load is ~60-120s; subsequent calls are free."""
    global _model, _processor, _config
    if _model is None:
        from mlx_vlm import load
        from mlx_vlm.utils import load_config
        t0 = time.time()
        _model, _processor = load(MODEL_ID)
        _config = load_config(MODEL_ID)
        print(f"[vlm] loaded {MODEL_ID} in {time.time()-t0:.1f}s")
    return _model, _processor, _config


def is_loaded() -> bool:
    """Cheap check whether the model is in memory. Useful for runners that
    want to print a one-time banner only on first iteration."""
    return _model is not None


# ── Input source selection ────────────────────────────────────────────────────


def pick_input(image_id: int) -> Path | None:
    """Prefer 2048px preview, fall back to 300px thumbnail. Returns None if
    neither exists (e.g. RAF stragglers without previews — should be filtered
    out by the runner's queue query, not handled here)."""
    for d in (PREVIEW_DIR, THUMB_DIR):
        p = d / f"{image_id}.jpg"
        if p.exists():
            return p
    return None


# ── Description ───────────────────────────────────────────────────────────────


def describe_image(image_path: Path | str, *, max_tokens: int = MAX_TOKENS) -> str:
    """Generate a description for a single image. Returns stripped text.

    Raises on missing input, model failure, or empty output. Caller decides
    whether to skip + log or abort.
    """
    from mlx_vlm import generate
    from mlx_vlm.prompt_utils import apply_chat_template

    model, processor, config = get_model()
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"input image missing: {image_path}")

    messages = [{"role": "user", "content": DESCRIPTION_PROMPT}]
    formatted = apply_chat_template(processor, config, messages, num_images=1)

    result = generate(
        model,
        processor,
        formatted,
        image=[str(image_path)],
        max_tokens=max_tokens,
        verbose=False,
    )

    # mlx-vlm generate returns either a string or a GenerationResult object
    text = result.text if hasattr(result, "text") else str(result)
    text = text.strip()
    if not text:
        raise RuntimeError("vlm returned empty description")
    return text


# ── DB write ──────────────────────────────────────────────────────────────────


def write_image_description(
    conn,
    image_id: int,
    description: str,
    *,
    prompt_version: int = PROMPT_VERSION,
) -> None:
    """Idempotent UPDATE: stamps ai_description, described_at, and
    description_prompt_version. Caller manages transaction + commit.

    Overwrites any prior description (legacy LLaVA or earlier Qwen passes).
    """
    conn.execute(
        """UPDATE images
              SET ai_description = ?,
                  described_at = CURRENT_TIMESTAMP,
                  description_prompt_version = ?
            WHERE id = ?""",
        (description, prompt_version, image_id),
    )


def describe_image_to_db(conn, image_id: int, image_path: Path | str) -> str:
    """Convenience: describe + write in one call. Returns the description.
    Caller still manages commit."""
    text = describe_image(image_path)
    write_image_description(conn, image_id, text)
    return text


# ── Smoke / CLI ───────────────────────────────────────────────────────────────


def _smoke():
    """Proof-of-life: load model, describe 5 known images, compare side-by-side
    with prior ai_description (legacy LLaVA or earlier Qwen). Read-only on
    dam.db. NO writes. Uses same test_ids as tools/smoke_qwen.py for direct
    comparability."""
    import sqlite3
    DB = Path(os.path.expanduser("~/.dam/dam.db"))

    test_ids = [6210, 280, 160, 2, 11]
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    pairs = []
    for i in test_ids:
        inp = pick_input(i)
        row = conn.execute(
            "SELECT id, file_name, ai_description FROM images WHERE id = ?",
            (i,),
        ).fetchone()
        if inp and row:
            pairs.append((row, inp))
        else:
            print(f"[smoke] skip id={i} (no input or DB row)")
    conn.close()

    for row, inp in pairs:
        print(f"\n{'='*70}")
        print(f"id={row['id']}  file={row['file_name']}")
        print(f"input: {inp.name} ({inp.parent.name})")
        prior = (row["ai_description"] or "(none)")[:200]
        print(f"prior: {prior}")
        t0 = time.time()
        try:
            text = describe_image(inp)
            elapsed = time.time() - t0
            print(f"new ({elapsed:.1f}s): {text}")
        except Exception as e:
            print(f"FAIL: {e}")

    print(f"\n{'='*70}\n[smoke] done.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        _smoke()
    else:
        print("usage: python3 dam_vlm.py smoke")
        print("(this module is normally imported, not run directly)")
