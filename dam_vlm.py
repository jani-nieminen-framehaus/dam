#!/usr/bin/env python3
"""
dam_vlm.py — Qwen 2.5 VL wrapper for image description (CUDA + transformers).

Replaces the prior MLX-only Mac path. Default model is Qwen2.5-VL-32B-Instruct
in bnb-NF4 (matches Mac MLX 4-bit quality baseline); 7B-fp16 is a one-line
variant flip for ~3x throughput at slightly lower quality.

Design:
  - Module-level lazy singleton: model loads on first use, stays in memory.
  - CUDA-only. Hard-pinned to cuda:1 to leave cuda:0 free for SigLIP
    (~3.3 GB resident). Falls back to cuda:0 on single-GPU hosts.
  - Image input always a path; processor + qwen_vl_utils handle preprocessing.
  - Per-image inference, ~10 s on Turing (sm_75) at NF4 / fp16-compute.
  - DB writes are atomic per image. Caller manages transaction + commit.
  - ~17 GB resident for 32B-NF4.

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

# Variant switch. Flip MODEL_VARIANT to change defaults; both code paths stay live.
#   "32B-bnb4" — Qwen/Qwen2.5-VL-32B-Instruct in bnb NF4. ~17 GB. ~10 s/img on RTX 6000.
#                Matches the Mac MLX 4-bit quality baseline.
#   "7B-fp16"  — Qwen/Qwen2.5-VL-7B-Instruct fp16. ~16 GB. ~3 s/img. Lower quality.
MODEL_VARIANT = "32B-bnb4"

MODEL_IDS = {
    "7B-fp16":  "Qwen/Qwen2.5-VL-7B-Instruct",
    "32B-bnb4": "Qwen/Qwen2.5-VL-32B-Instruct",
}
MODEL_ID = MODEL_IDS[MODEL_VARIANT]

# Hard pin: cuda:1 is the "describe" GPU. cuda:0 hosts SigLIP (~3.3 GB resident).
# device_map="auto" was rejected — it spills weights onto cuda:0 and OOMs
# whenever SigLIP runs a search in parallel with a describe step.
VLM_DEVICE = "cuda:1"

# Qwen2.5-VL pixel budget. Defaults in qwen-vl-utils are 4..16384 visual tokens;
# we clamp tighter because our inputs are already 2048-px previews / 300-px thumbs.
# Do NOT pass image_patch_size=16 to process_vision_info — that's Qwen3-VL.
# Qwen2.5-VL uses patch_size=14 and qwen-vl-utils' defaults are correct for it.
MIN_PIXELS = 256 * 28 * 28
MAX_PIXELS = 1280 * 28 * 28

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

# Input source priority — 2048-px preview first, 300-px thumb fallback.
# Same cross-platform pattern as the dam_siglip.load_vocabulary patch:
# resolve via dam_config when importable; fall back to the original Mac
# defaults so this module remains usable standalone.
try:
    from dam_config import DAM_ROOT
    PREVIEW_DIR = DAM_ROOT / "previews"
    THUMB_DIR = DAM_ROOT / "thumbs"
except Exception:
    PREVIEW_DIR = Path(os.path.expanduser("~/Documents/dam/previews"))
    THUMB_DIR = Path(os.path.expanduser("~/Documents/dam/thumbs"))


# ── Lazy model singleton ──────────────────────────────────────────────────────

_model = None
_processor = None
_device: str | None = None


def get_model():
    """Load and return (model, processor, device). Cached after first call.
    First load is ~30-60 s for 7B fp16, ~90-180 s for 32B-NF4 (one-shot
    on-load quantization).

    Note: the third tuple element used to be `config` (mlx-vlm's load_config
    object). In the CUDA rewrite it's the device string. No external caller
    in this repo unpacks all three elements (describe_all.py only uses
    pick_input, describe_image_to_db, get_model() for warm-up).
    """
    global _model, _processor, _device
    if _model is not None:
        return _model, _processor, _device

    import torch
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    if not torch.cuda.is_available():
        raise RuntimeError("dam_vlm requires CUDA. Use the MLX branch on Mac.")
    # Pin to cuda:1 if available so cuda:0 stays free for SigLIP.
    # Single-GPU hosts (e.g. a CachyOS laptop dev box) fall back to cuda:0 —
    # SigLIP will share the card; on a 24 GB card the combined footprint is
    # ~21 GB for 7B-fp16 + SigLIP, tolerable but tight.
    if torch.cuda.device_count() >= 2:
        device = VLM_DEVICE
    else:
        device = "cuda:0"
    _device = device

    t0 = time.time()
    if MODEL_VARIANT == "32B-bnb4":
        from transformers import BitsAndBytesConfig
        # IMPORTANT: compute_dtype=torch.float16 on Turing (sm_75).
        # bf16 MMA requires sm_80+ (Ampere). Using bf16 here silently emulates
        # in fp32 and tanks throughput. Do NOT "fix" this back to bf16 by
        # copying it from a Qwen blog post — those assume Ampere+.
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            MODEL_ID,
            quantization_config=bnb,
            device_map={"": device},
            attn_implementation="sdpa",  # flash-attn 2 requires sm_80+; not available on Turing
            torch_dtype=torch.float16,
        )
    else:  # 7B-fp16
        _model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            MODEL_ID,
            torch_dtype=torch.float16,
            device_map={"": device},
            attn_implementation="sdpa",
        )

    _model.eval()
    _processor = AutoProcessor.from_pretrained(
        MODEL_ID,
        min_pixels=MIN_PIXELS,
        max_pixels=MAX_PIXELS,
    )
    print(f"[vlm] loaded {MODEL_ID} on {device} ({MODEL_VARIANT}) in {time.time()-t0:.1f}s")
    return _model, _processor, _device


def is_loaded() -> bool:
    """Cheap check whether the model is in memory. Useful for runners that
    want to print a one-time banner only on first iteration."""
    return _model is not None


# ── Input source selection ────────────────────────────────────────────────────


def pick_input(image_id: int) -> Path | None:
    """Prefer 2048-px preview, fall back to 300-px thumbnail. Returns None if
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
    import torch
    from qwen_vl_utils import process_vision_info

    model, processor, device = get_model()
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"input image missing: {image_path}")

    messages = [{
        "role": "user",
        "content": [
            {"type": "image", "image": f"file://{image_path.as_posix()}"},
            {"type": "text", "text": DESCRIPTION_PROMPT},
        ],
    }]

    image_inputs, video_inputs = process_vision_info(messages)
    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    ).to(device)

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            do_sample=False,        # deterministic — re-runs yield the same description
            temperature=None,       # avoid the "do_sample=False but temperature set" warning
            top_p=None,
            top_k=None,
            repetition_penalty=1.0,
            pad_token_id=processor.tokenizer.eos_token_id,
        )

    trimmed = [
        out[len(inp):] for inp, out in zip(inputs.input_ids, output_ids)
    ]
    text_out = processor.batch_decode(
        trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=True
    )[0].strip()
    if not text_out:
        raise RuntimeError("vlm returned empty description")
    return text_out


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
    """Proof-of-life: load model, describe 5 newest pending images, compare
    side-by-side with prior ai_description (will be null on a fresh Windows
    DB). Read-only on dam.db. NO writes.

    Test IDs are picked dynamically because the legacy [6210, 280, 160, 2, 11]
    aren't present in the current Windows DB.
    """
    import sqlite3
    try:
        from dam_config import DB_PATH as _db
        db_path = _db
    except Exception:
        db_path = Path(os.path.expanduser("~/.dam/dam.db"))

    conn = sqlite3.connect(str(db_path))
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

    pairs = []
    for r in rows:
        inp = pick_input(r["id"])
        if inp:
            pairs.append((r, inp))
        else:
            print(f"[smoke] skip id={r['id']} (no preview/thumb)")
    conn.close()

    if not pairs:
        print("[smoke] no images with input files; nothing to do.")
        return

    times = []
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
            times.append(elapsed)
            print(f"new ({elapsed:.1f}s): {text}")
        except Exception as e:
            print(f"FAIL: {e}")

    if times:
        avg = sum(times) / len(times)
        print(f"\n{'='*70}\n[smoke] {len(times)} ok, avg {avg:.2f}s/img")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        _smoke()
    else:
        print("usage: python3 dam_vlm.py smoke")
        print("(this module is normally imported, not run directly)")
