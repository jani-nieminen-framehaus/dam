#!/opt/homebrew/bin/python3
"""
Quick A/B comparison: LLaVA 34B vs Qwen2.5-VL 72B on known-bad images.
Run after pulling qwen2.5vl:72b into Ollama.

Usage:
    python3 test_vlm_compare.py
    python3 test_vlm_compare.py --ids 6210 160 2 10
"""

import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

OLLAMA_BASE = "http://localhost:11434"
THUMB_DIR = Path.home() / "Documents/dam/thumbs"

MODELS = ["llava:34b", "qwen2.5vl:72b"]

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

# Known problem images
DEFAULT_IDS = [
    6210,   # Zalando box misread as Samsung
    160,    # Dark hallway (isolation keyword)
    2,      # Child with toy car
    10,     # Toddler on floor
    11,     # Woman with child reading
    280,    # Another Samsung misread
]


def ollama_generate(model, image_b64, prompt):
    """Run vision model on image, return description."""
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_b64],
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 200,
            "num_ctx": 4096,
        },
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode())
            return result.get("response", "").strip()
    except Exception as e:
        return f"ERROR: {e}"


def main():
    ids = DEFAULT_IDS
    if "--ids" in sys.argv:
        idx = sys.argv.index("--ids")
        ids = [int(x) for x in sys.argv[idx + 1:]]

    # Check which models are available
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=5) as resp:
            available = {m["name"] for m in json.loads(resp.read().decode()).get("models", [])}
    except Exception as e:
        print(f"Cannot reach Ollama: {e}")
        sys.exit(1)

    active_models = []
    for m in MODELS:
        if any(m in a for a in available):
            active_models.append(m)
        else:
            print(f"  SKIP {m} — not installed")

    if not active_models:
        print("No test models available!")
        sys.exit(1)

    print(f"\nComparing: {', '.join(active_models)}")
    print(f"Test images: {ids}")
    print("=" * 70)

    for img_id in ids:
        thumb_path = THUMB_DIR / f"{img_id}.jpg"
        if not thumb_path.exists():
            print(f"\n[{img_id}] Thumbnail not found: {thumb_path}")
            continue

        image_b64 = base64.b64encode(thumb_path.read_bytes()).decode()

        print(f"\n{'=' * 70}")
        print(f"IMAGE {img_id} ({thumb_path.name})")
        print(f"{'=' * 70}")

        for model in active_models:
            print(f"\n  [{model}]")
            t0 = time.time()
            desc = ollama_generate(model, image_b64, PROMPT)
            elapsed = time.time() - t0
            print(f"  Time: {elapsed:.1f}s")
            print(f"  Description: {desc}")

    print(f"\n{'=' * 70}")
    print("Done.")


if __name__ == "__main__":
    main()
