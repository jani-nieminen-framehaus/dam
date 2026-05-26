#!/usr/bin/env python3
"""Smoke test: SigLIP image + text encoding.

Validates: model loads, image -> 1152-dim vector, text -> 1152-dim vector,
matched pairs score higher than unmatched.
"""
import sqlite3
import time
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

DB = "/Users/janinieminen/Documents/dam/dam.db"
THUMB_DIR = Path("/Users/janinieminen/Documents/dam/thumbs")

device = "mps" if torch.backends.mps.is_available() else "cpu"
print(f"device: {device}")

t0 = time.time()
model = AutoModel.from_pretrained("google/siglip-so400m-patch14-384").to(device).eval()
processor = AutoProcessor.from_pretrained("google/siglip-so400m-patch14-384")
print(f"load: {time.time()-t0:.1f}s")


def encode_images(pil_images):
    inp = processor(images=pil_images, return_tensors="pt").to(device)
    with torch.no_grad():
        out = model.get_image_features(**inp)
    # transformers 5.x can return either a tensor or an output object
    emb = out if isinstance(out, torch.Tensor) else out.pooler_output if hasattr(out, "pooler_output") else out.last_hidden_state[:, 0]
    emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb


def encode_texts(texts):
    inp = processor(text=texts, return_tensors="pt", padding="max_length", truncation=True).to(device)
    with torch.no_grad():
        out = model.get_text_features(**inp)
    emb = out if isinstance(out, torch.Tensor) else out.pooler_output if hasattr(out, "pooler_output") else out.last_hidden_state[:, 0]
    emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb


conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
ids = [6210, 160, 2, 10, 11, 280]
rows = []
for i in ids:
    r = conn.execute("SELECT id, file_name, ai_description FROM images WHERE id=?", (i,)).fetchone()
    p = THUMB_DIR / f"{i}.jpg"
    if r and p.exists():
        rows.append((dict(r), p))
conn.close()

if not rows:
    print("No matching thumbnails — aborting")
    raise SystemExit(1)

print(f"Loaded {len(rows)} test images")

imgs = [Image.open(p).convert("RGB") for _, p in rows]
t0 = time.time()
img_embeds = encode_images(imgs)
img_t = time.time() - t0
print(f"image encode ({len(imgs)} imgs): {img_t*1000:.0f}ms total, {img_t/len(imgs)*1000:.0f}ms/img, dim={img_embeds.shape[-1]}")

queries = [
    "a photo of a child",
    "a photo of an empty hallway",
    "a photo of a Samsung box",
    "a photo of a person reading",
    "a photo of a beach",
    "a photo of snow",
]
t0 = time.time()
txt_embeds = encode_texts(queries)
print(f"text encode ({len(queries)} q): {(time.time()-t0)*1000:.0f}ms total, dim={txt_embeds.shape[-1]}")

sims = (img_embeds @ txt_embeds.T).cpu().numpy()
print("\nsimilarity matrix (rows=images, cols=queries):")
print("        " + "    ".join(f"q{i}" for i in range(len(queries))))
for (r, _), row in zip(rows, sims):
    desc = (r["ai_description"] or "")[:60]
    line = "  ".join(f"{s:+.3f}" for s in row)
    print(f"  {r['id']:>5}  {line}  | {desc}")
print("\nqueries:")
for i, q in enumerate(queries):
    print(f"  q{i}: {q}")
