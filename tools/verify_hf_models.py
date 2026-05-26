#!/usr/bin/env python3
"""Verify HF model names exist before kicking off downloads."""
import urllib.request, json

REPOS = [
    'google/siglip-so400m-patch14-384',
    'mlx-community/Qwen2.5-VL-32B-Instruct-4bit',
]

for repo in REPOS:
    try:
        with urllib.request.urlopen(f'https://huggingface.co/api/models/{repo}', timeout=10) as r:
            d = json.loads(r.read())
            print(f'OK   {repo}')
            # Show total size if available
            for sib in d.get('siblings', [])[:3]:
                print(f'       {sib.get("rfilename")}')
    except Exception as e:
        print(f'MISS {repo}: {e}')
