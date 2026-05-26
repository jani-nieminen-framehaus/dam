#!/usr/bin/env python3
"""Download SigLIP-So400m via huggingface_hub.snapshot_download. Background-safe."""
import sys
from huggingface_hub import snapshot_download

try:
    path = snapshot_download(
        repo_id="google/siglip-so400m-patch14-384",
        # Skip GGUF/MLX-incompatible variants if any — just the standard files
        allow_patterns=["*.json", "*.txt", "*.safetensors", "*.model", "tokenizer*", "spiece*", "*.bin"],
    )
    print(f"OK SigLIP -> {path}")
except Exception as e:
    print(f"FAIL SigLIP: {e}", file=sys.stderr)
    sys.exit(1)
