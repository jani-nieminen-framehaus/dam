#!/usr/bin/env python3
"""Download Qwen 2.5 VL 32B 4-bit MLX. Background-safe."""
import sys
from huggingface_hub import snapshot_download

try:
    path = snapshot_download(
        repo_id="mlx-community/Qwen2.5-VL-32B-Instruct-4bit",
        # MLX needs the full snapshot — config, tokenizer, safetensors shards
        allow_patterns=["*.json", "*.txt", "*.safetensors", "*.py", "tokenizer*", "spiece*", "merges.txt", "vocab.json"],
    )
    print(f"OK Qwen2.5VL-32B-4bit -> {path}")
except Exception as e:
    print(f"FAIL Qwen: {e}", file=sys.stderr)
    sys.exit(1)
