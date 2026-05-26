#!/usr/bin/env python3
"""Build draft closed vocabulary for SigLIP zero-shot classifier.

v0.2: Fixed false positives (the -ence suffix dropped 'fence', etc.).
      Capped from_existing_keywords to top 250 by frequency.
      Whitespace-normalized to prevent dedupe leaks.

Strategy:
  1. Load top-frequency keywords from prior LLaVA+LoRA tagger output.
  2. Drop ONLY explicit projected-mood words (no suffix heuristic).
  3. Cap to top 250 to reduce noise.
  4. Merge in technical photographic terms.
  5. Merge in CONCRETE Triptych themes.
  6. Add common visual categories not well-represented in prior data.
  7. Whitespace-normalize and lowercase for clean dedupe.
"""
import sqlite3
import json
from pathlib import Path

DB = "/Users/janinieminen/Documents/dam/dam.db"
OUT = Path("/Users/janinieminen/Documents/dam/dam_vocabulary.json")

# ── Projected moods (the hallucination set) — explicit blacklist, no suffix heuristic
PROJECTED_MOODS = {
    "serenity", "serene", "tranquil", "tranquility", "melancholy",
    "contemplation", "contemplative", "warmth", "isolation", "solitude",
    "joy", "stillness", "quietness", "nostalgia", "intimacy", "tension",
    "calm", "calmness", "peaceful", "peacefulness", "moody",
    "tender", "tenderness", "playful", "playfulness",
    "desolate", "vulnerability", "innocence", "happiness", "domesticity",
    "engagement", "curiosity", "protection", "nurturing", "emptiness",
    "dignity", "grief", "waiting", "seclusion", "quietude",
    "wonder", "delight", "concentration", "anticipation",
    "exhaustion", "fatigue", "relaxation", "love", "bonding",
    "comfort", "discomfort", "patience", "hope", "fear",
    "sadness", "loneliness", "togetherness", "harmony",
    "balance", "imbalance", "stagnation",
    "passage of time", "remembrance", "forgetfulness",
    "neutrality", "ambiguity", "wholesomeness", "mystery", "mysteriousness",
    "casualness", "informality", "formality", "presence", "absence",
    "freshness", "ordinariness", "naturalness", "spontaneity",
    "simplicity", "complexity", "abstraction",
    # Action-shaped abstractions
    "togetherness", "exploration", "discovery", "observation",
    # Frequent generic-mood words from prior tagger
    "moodiness", "moroseness", "weariness", "weirdness", "uneasiness",
    "everyday", "ordinary", "quietude",
}

# ── Technical photographic terms (visually detectable)
TECHNICAL = {
    "backlit", "silhouette",
    "high contrast", "low contrast",
    "shallow depth of field", "deep focus",
    "motion blur", "sharp focus",
    "long exposure",
    "soft lighting", "natural light", "artificial lighting",
    "high-key lighting", "low light",
    "macro photography", "close-up", "wide shot",
    "diffused light", "soft shadows", "even lighting", "harsh light",
    "candlelight", "lamp light", "window light",
    "golden hour", "blue hour",
    "black and white", "monochrome", "desaturated",
    "film grain", "vintage",
}

# ── Concrete Triptych themes
TRIPTYCH_CONCRETE = {
    "elderly", "hospital", "care facility", "wheelchair",
    "medication", "medical equipment",
}

# ── Additions to fill gaps in prior tagger's vocabulary
ADDITIONS = {
    "single person", "two people", "group of people", "crowd", "self-portrait",
    "text visible", "sign", "writing on wall",
    "eating", "drinking", "sleeping", "reading", "writing",
    "walking", "running", "sitting", "standing", "lying down",
    "playing", "working", "cooking",
    "face", "hands", "feet", "eyes closed", "smiling",
    "kitchen", "bathroom", "bedroom", "living room", "office",
    "garden", "park", "forest", "beach", "mountain", "lake", "river",
    "street", "sidewalk", "shop", "restaurant", "cafe",
    "school", "playground", "stairs", "hallway",
    "sunny", "overcast", "foggy", "rainy", "snowy", "stormy", "clear sky",
    "daytime", "nighttime", "twilight", "indoor scene", "outdoor scene",
    "documentary", "candid", "posed portrait", "environmental portrait",
    "still life", "architecture", "interior",
}


def normalize(kw: str) -> str:
    """Lowercase + collapse whitespace, for clean dedupe."""
    return " ".join(kw.strip().lower().split())


def load_existing_keywords(min_count: int = 50):
    """Frequency-rank existing keywords from prior tagging."""
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        f"""
        SELECT k.keyword, COUNT(*) AS cnt
        FROM image_keywords ik
        JOIN keywords k ON ik.keyword_id = k.id
        GROUP BY k.keyword
        HAVING cnt >= {min_count}
        ORDER BY cnt DESC
        """
    ).fetchall()
    conn.close()
    return rows


def is_concrete(kw: str) -> bool:
    """Drop ONLY explicit mood/abstract words from the blacklist.
    No fragile suffix heuristic — the blacklist is comprehensive.
    """
    return normalize(kw) not in {normalize(m) for m in PROJECTED_MOODS}


def main():
    raw = load_existing_keywords(min_count=50)
    print(f"Loaded {len(raw)} keywords with cnt >= 50 from prior tagging")

    # Keep concrete ones only, top 250 by frequency
    concrete = [(normalize(k), c) for k, c in raw if is_concrete(k)]
    capped = concrete[:250]
    dropped = [k for k, _ in raw if not is_concrete(k)]
    overflow = [k for k, _ in concrete[250:]]

    print(f"  kept as concrete:           {len(concrete)}")
    print(f"  dropped as mood/abstract:   {len(dropped)}")
    print(f"  capped at top 250 by freq:  {len(capped)} (overflow {len(overflow)} dropped)")

    vocab = {
        "_meta": {
            "version": "0.2-draft",
            "purpose": "SigLIP zero-shot classification closed vocabulary",
            "notes": "Tags are flat — categories are organizational only. The 'all' list is what the classifier uses.",
        },
        "technical": sorted(normalize(t) for t in TECHNICAL),
        "triptych_concrete": sorted(normalize(t) for t in TRIPTYCH_CONCRETE),
        "additions_uncategorized": sorted(normalize(t) for t in ADDITIONS),
        "from_existing_keywords_top_250": [k for k, _ in capped],
        "_dropped_as_mood_or_abstract": sorted(set(dropped))[:50],
        "_overflow_dropped_low_freq": sorted(set(overflow))[:30],
    }

    # Flat dedup set for the classifier
    all_set = set()
    for k, v in vocab.items():
        if k.startswith("_"):
            continue
        for tag in v:
            all_set.add(normalize(tag))
    vocab["all"] = sorted(all_set)
    vocab["_meta"]["total_tags"] = len(vocab["all"])

    OUT.write_text(json.dumps(vocab, indent=2, ensure_ascii=False))
    print(f"\nDraft v0.2 written: {OUT}")
    print(f"Total unique tags in flat 'all': {len(vocab['all'])}")


if __name__ == "__main__":
    main()
