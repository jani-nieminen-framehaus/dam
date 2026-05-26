#!/usr/bin/env python3
"""
dam_siglip.py — SigLIP-So400m wrapper for image embedding, text embedding,
and zero-shot multi-label classification against a closed vocabulary.

Replaces (in the new pipeline):
  - dam_tagger.embed_text       (nomic-embed via Ollama)
  - dam_tagger.text_extract_keywords (Mistral LoRA generative tagger)
  - dam_api.get_embedding       (Ollama HTTP retry helper)

Design:
  - Module-level lazy singleton: model loads on first use, stays in memory.
  - MPS on Mac, CUDA when present, CPU fallback.
  - Vocabulary text embeddings cached on disk (~/.dam/siglip_vocab_cache.pt)
    keyed by hash of the vocab list -> instant warm-start on subsequent runs.
  - Image input always a path; module doesn't care RAW vs JPEG vs preview.
  - Pipeline functions handle batched ingest with progress reporting.
  - DB write functions are atomic per image, idempotent (DELETE+INSERT on
    vec0 because virtual tables don't support UPSERT).

This module is import-safe — loading the module does NOT load the model.
The model loads on the first call to encode_image / encode_text / get_model.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import time
from pathlib import Path
from typing import Iterable

import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

# ── Constants ─────────────────────────────────────────────────────────────────

MODEL_ID = "google/siglip-so400m-patch14-384"
EMBED_DIM = 1152
ZERO_SHOT_PROMPT = "a photo of {tag}"

# Default classifier behavior
DEFAULT_CONFIDENCE_THRESHOLD = 0.10  # Cosine similarity floor for tag emission
DEFAULT_MAX_TAGS_PER_IMAGE = 12       # Hard cap regardless of threshold

# Cache for precomputed vocabulary text embeddings
_VOCAB_CACHE_PATH = Path(os.path.expanduser("~/.dam/siglip_vocab_cache.pt"))


# ── Device ────────────────────────────────────────────────────────────────────


def _pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# ── Lazy model singleton ──────────────────────────────────────────────────────

_model = None
_processor = None
_device: str | None = None


def get_model():
    """Load and return (model, processor, device). Cached after first call."""
    global _model, _processor, _device
    if _model is None:
        _device = _pick_device()
        t0 = time.time()
        _model = AutoModel.from_pretrained(MODEL_ID).to(_device).eval()
        _processor = AutoProcessor.from_pretrained(MODEL_ID)
        # silence the noisy unauthenticated-requests warning on subsequent calls
        # (the warning is harmless; HF anonymous access works fine here)
        print(f"[siglip] loaded on {_device} in {time.time()-t0:.1f}s")
    return _model, _processor, _device


def _extract_features(output) -> torch.Tensor:
    """Handle transformers 5.x return-type quirks for get_image_features /
    get_text_features. Always returns a tensor."""
    if isinstance(output, torch.Tensor):
        return output
    if hasattr(output, "pooler_output") and output.pooler_output is not None:
        return output.pooler_output
    if hasattr(output, "last_hidden_state"):
        # mean-pool as last resort (shouldn't be needed for SigLIP)
        return output.last_hidden_state[:, 0]
    raise RuntimeError(f"Unexpected output type from SigLIP: {type(output)}")


def _normalize(t: torch.Tensor) -> torch.Tensor:
    return t / t.norm(dim=-1, keepdim=True).clamp(min=1e-9)


# ── Encoding ──────────────────────────────────────────────────────────────────


def encode_images(paths: Iterable[Path | str], batch_size: int = 32) -> list[list[float]]:
    """Encode N images, return list of L2-normalized 1152-dim vectors.
    Skips images that fail to load; the returned list has the same length as
    successfully-loaded inputs (caller pairs by input order from successes).

    Returns a list of (path, embedding) tuples for clarity.
    """
    raise NotImplementedError(
        "Use encode_images_with_paths() — it returns paired (path, embedding) "
        "so caller can write to DB by image_id without ambiguity."
    )


def encode_images_with_paths(
    paths: Iterable[Path | str],
    batch_size: int = 32,
    on_progress=None,
) -> list[tuple[Path, list[float]]]:
    """Encode N images. Returns list of (path, embedding) for successful loads.
    Failed loads are silently skipped (logged to stderr).

    on_progress(done, total) called once per batch.
    """
    model, processor, device = get_model()
    paths = [Path(p) for p in paths]
    total = len(paths)
    results: list[tuple[Path, list[float]]] = []

    for i in range(0, total, batch_size):
        batch_paths = paths[i : i + batch_size]
        loaded: list[tuple[Path, Image.Image]] = []
        for p in batch_paths:
            try:
                loaded.append((p, Image.open(p).convert("RGB")))
            except Exception as e:
                print(f"[siglip] WARN skip {p}: {e}")

        if not loaded:
            if on_progress:
                on_progress(min(i + batch_size, total), total)
            continue

        imgs = [img for _, img in loaded]
        inp = processor(images=imgs, return_tensors="pt").to(device)
        with torch.no_grad():
            out = model.get_image_features(**inp)
        emb = _normalize(_extract_features(out)).cpu()

        for (p, _), vec in zip(loaded, emb):
            results.append((p, vec.tolist()))

        # Free PIL handles
        for _, img in loaded:
            img.close()

        if on_progress:
            on_progress(min(i + batch_size, total), total)

    return results


def encode_text(text: str) -> list[float]:
    """Encode a single query string into a 1152-dim vector. Convenience for /api/search."""
    return encode_texts([text])[0]


def encode_texts(texts: list[str]) -> list[list[float]]:
    """Encode multiple texts. Returns L2-normalized 1152-dim vectors."""
    model, processor, device = get_model()
    inp = processor(text=texts, return_tensors="pt", padding="max_length", truncation=True).to(device)
    with torch.no_grad():
        out = model.get_text_features(**inp)
    emb = _normalize(_extract_features(out)).cpu()
    return emb.tolist()


# ── Vocabulary embeddings (cached on disk) ────────────────────────────────────


def _vocab_hash(tags: list[str]) -> str:
    return hashlib.sha256("\n".join(tags).encode()).hexdigest()[:16]


def precompute_vocab_embeddings(
    tags: list[str],
    *,
    use_cache: bool = True,
    prompt_template: str = ZERO_SHOT_PROMPT,
) -> torch.Tensor:
    """Compute (or load from cache) a (N, 1152) tensor of text embeddings,
    one row per tag in input order. Cached on disk keyed by hash of (tags +
    prompt_template) so changes invalidate automatically.
    """
    cache_key = _vocab_hash([prompt_template] + tags)
    cache_path = _VOCAB_CACHE_PATH.with_name(f"siglip_vocab_{cache_key}.pt")

    if use_cache and cache_path.exists():
        try:
            cached = torch.load(cache_path, weights_only=True, map_location="cpu")
            if cached.shape == (len(tags), EMBED_DIM):
                print(f"[siglip] vocab cache hit ({len(tags)} tags) -> {cache_path.name}")
                return cached
        except Exception as e:
            print(f"[siglip] vocab cache load failed, recomputing: {e}")

    prompts = [prompt_template.format(tag=t) for t in tags]
    t0 = time.time()
    emb = torch.tensor(encode_texts(prompts))
    print(f"[siglip] vocab encoded ({len(tags)} tags) in {time.time()-t0:.1f}s")

    if use_cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(emb, cache_path)
        print(f"[siglip] vocab cached -> {cache_path.name}")
    return emb


# ── Classification ────────────────────────────────────────────────────────────


def classify_image(
    image_embedding: list[float] | torch.Tensor,
    vocab_embeddings: torch.Tensor,
    tags: list[str],
    *,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    max_tags: int = DEFAULT_MAX_TAGS_PER_IMAGE,
) -> list[tuple[str, float]]:
    """Given an image embedding and a vocab embedding matrix, return tags
    whose cosine similarity exceeds threshold, capped at max_tags, sorted
    by similarity descending.
    """
    if not isinstance(image_embedding, torch.Tensor):
        image_embedding = torch.tensor(image_embedding)
    sims = (vocab_embeddings @ image_embedding).tolist()
    scored = [(tags[i], float(s)) for i, s in enumerate(sims) if s >= threshold]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:max_tags]


# ── Vocabulary file loader ────────────────────────────────────────────────────


def load_vocabulary(path: Path | str | None = None) -> list[str]:
    """Load the 'all' flat list from dam_vocabulary.json."""
    if path is None:
        path = Path(os.path.expanduser("~/Documents/dam/dam_vocabulary.json"))
    path = Path(path)
    with path.open() as f:
        data = json.load(f)
    if "all" not in data:
        raise ValueError(f"{path} missing required 'all' key")
    return data["all"]


# ── Embedding serialization (for sqlite-vec writes) ───────────────────────────


def serialize_embedding(emb: list[float]) -> bytes:
    """Pack a 1152-dim float32 list into bytes for sqlite-vec insertion.

    Validates dimension to prevent shape mismatches between the new SigLIP
    table (1152) and the old nomic table (768).
    """
    if len(emb) != EMBED_DIM:
        raise ValueError(f"expected {EMBED_DIM}-dim embedding, got {len(emb)}")
    return struct.pack(f"{EMBED_DIM}f", *emb)


# ── DB writes ─────────────────────────────────────────────────────────────────


def write_image_embedding(conn, image_id: int, embedding: list[float]) -> None:
    """Idempotent upsert into image_embeddings_siglip + bump timestamp.
    Caller manages transaction + commit."""
    blob = serialize_embedding(embedding)
    conn.execute("DELETE FROM image_embeddings_siglip WHERE image_id = ?", (image_id,))
    conn.execute(
        "INSERT INTO image_embeddings_siglip (image_id, embedding) VALUES (?, ?)",
        (image_id, blob),
    )
    conn.execute(
        "UPDATE images SET siglip_embedded_at = CURRENT_TIMESTAMP WHERE id = ?",
        (image_id,),
    )


def write_classifier_tags(
    conn,
    image_id: int,
    scored_tags: list[tuple[str, float]],
    *,
    replace_classifier_tags: bool = True,
) -> int:
    """Write classifier-assigned tags to image_keywords with confidence scores.

    If replace_classifier_tags=True (default), removes existing rows for this
    image that have non-NULL confidence (i.e. previously classifier-assigned),
    while preserving human-added or legacy-LLaVA keywords (confidence IS NULL).

    Returns count of new keyword rows inserted.
    """
    if replace_classifier_tags:
        conn.execute(
            "DELETE FROM image_keywords WHERE image_id = ? AND confidence IS NOT NULL",
            (image_id,),
        )

    inserted = 0
    for tag, score in scored_tags:
        # Ensure keyword exists in keywords table
        conn.execute("INSERT OR IGNORE INTO keywords (keyword) VALUES (?)", (tag,))
        row = conn.execute("SELECT id FROM keywords WHERE keyword = ?", (tag,)).fetchone()
        if row is None:
            continue
        keyword_id = row[0]

        # Insert junction with confidence (ignore if human already added this tag)
        cur = conn.execute(
            """INSERT OR IGNORE INTO image_keywords (image_id, keyword_id, confidence)
               VALUES (?, ?, ?)""",
            (image_id, keyword_id, score),
        )
        inserted += cur.rowcount

    conn.execute(
        "UPDATE images SET classified_at = CURRENT_TIMESTAMP WHERE id = ?",
        (image_id,),
    )
    return inserted


# ── Smoke / CLI ───────────────────────────────────────────────────────────────


def _smoke():
    """Quick end-to-end smoke: load vocab, encode it, encode 3 known images,
    classify each. No DB writes. Read-only."""
    import sqlite3
    DB = Path(os.path.expanduser("~/.dam/dam.db"))
    THUMB_DIR = Path(os.path.expanduser("~/Documents/dam/thumbs"))

    tags = load_vocabulary()
    print(f"[smoke] vocab: {len(tags)} tags")

    vocab_emb = precompute_vocab_embeddings(tags)

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    test_ids = [2, 10, 11, 160, 6210, 280]
    pairs = []
    for i in test_ids:
        p = THUMB_DIR / f"{i}.jpg"
        r = conn.execute("SELECT id, ai_description FROM images WHERE id = ?", (i,)).fetchone()
        if r and p.exists():
            pairs.append((dict(r), p))
    conn.close()

    embs = encode_images_with_paths([p for _, p in pairs])
    print(f"\n[smoke] classifier output:\n")
    for (r, _), (_, emb) in zip(pairs, embs):
        scored = classify_image(emb, vocab_emb, tags, threshold=0.08, max_tags=10)
        tags_str = ", ".join(f"{t}({s:.2f})" for t, s in scored)
        desc = (r["ai_description"] or "")[:60]
        print(f"  id={r['id']:>5} | LLaVA: {desc}")
        print(f"         SigLIP: {tags_str}")
        print()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "smoke":
        _smoke()
    else:
        print("usage: python3 dam_siglip.py smoke")
        print("(this module is normally imported, not run directly)")
