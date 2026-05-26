#!/usr/bin/env python3
"""Build closed vocabulary v0.3 — smoke-test-driven cleanup.

Changes from v0.2:
  - Expanded PROJECTED_MOODS blacklist with words that leaked through:
    neglect, coziness, orderliness, intimacy variants, "child-friendly
    environment", "domestic setting", "domestic interior" (interpretive),
    "indoor environment" (duplicate of indoor scene).
  - Synonym merge map collapses no-space variants and near-duplicates:
    youngchild->young child, livingroom->living room, etc.
  - Lighting term deduplication (diffused light/lighting, soft light/lighting).

Backup: /Users/janinieminen/Documents/dam/dam_vocabulary.v0.2.backup.json
Output: /Users/janinieminen/Documents/dam/dam_vocabulary.json (overwrites v0.2)
"""
import sqlite3
import json
from pathlib import Path

DB = "/Users/janinieminen/Documents/dam/dam.db"
OUT = Path("/Users/janinieminen/Documents/dam/dam_vocabulary.json")

# ── Expanded projected-moods blacklist
PROJECTED_MOODS = {
    # v0.2 set (unchanged)
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
    "exploration", "discovery", "observation",
    "moodiness", "moroseness", "weariness", "weirdness", "uneasiness",
    "everyday", "ordinary",

    # v0.3 ADDITIONS — caught in smoke test output as projection
    "neglect", "coziness", "orderliness", "messiness",
    "child-friendly environment", "domestic setting", "domestic interior",
    "indoor environment",  # duplicates indoor scene, also vague
    "child-friendliness", "child-friendly",
    "warmth", "coolness",  # subjective temperature
    "stagedness", "naturalness",
    "atmospheric", "atmospheric lighting",
    "casual moment", "intimate moment", "candid moment",
    "story", "narrative",
    "personality", "character",
    "expression", "expressiveness",
    "interaction", "connection",
    "everyday life", "daily life", "domestic life",
}

# ── Synonym / variant merge: source -> canonical
SYNONYMS = {
    # No-space variants from prior tagger inconsistency
    "youngchild": "young child",
    "youngchildren": "young child",
    "livingroom": "living room",
    "diningroom": "dining room",
    "diningarea": "dining area",
    "bedroomscene": "bedroom",
    "kitchenscene": "kitchen",
    "carseat": "car seat",
    "highchair": "high chair",
    "tabletop": "table",
    # Lighting near-duplicates
    "soft lighting": "soft light",
    "diffused lighting": "diffused light",
    "ambient lighting": "ambient light",
    "natural lighting": "natural light",
    "warm lighting": "warm light",
    "harsh lighting": "harsh light",
    "even lighting": "even light",
    "dim lighting": "dim light",
    "low lighting": "low light",
    "artificial lighting": "artificial light",
    "back lighting": "backlit",
    "backlighting": "backlit",
    "window lighting": "window light",
    "candlelighting": "candlelight",
    # Action variants
    "siting": "sitting",
    "standin": "standing",
    "playin": "playing",
    # Plural collapse for common subjects
    "babies": "baby",
    "children": "child",
    "kids": "child",
    "kid": "child",
    "toddlers": "toddler",
    "women": "woman",
    "men": "man",
    "people": "person",
    "persons": "person",
    "hands": "hand",  # keep both? prior tagger has both. canonicalize singular
    # Setting near-duplicates
    "indoors": "indoor scene",
    "outdoors": "outdoor scene",
    "indoor": "indoor scene",
    "outdoor": "outdoor scene",
    "interior": "indoor scene",  # too vague otherwise
    "exterior": "outdoor scene",
}

# ── Technical photographic terms (canonical forms)
TECHNICAL = {
    "backlit", "silhouette",
    "high contrast", "low contrast",
    "shallow depth of field", "deep focus",
    "motion blur", "sharp focus",
    "long exposure",
    "soft light", "natural light", "artificial light",
    "high-key lighting", "low light",
    "macro photography", "close-up", "wide shot",
    "diffused light", "soft shadows", "even light", "harsh light",
    "candlelight", "lamp light", "window light",
    "golden hour", "blue hour",
    "black and white", "monochrome", "desaturated",
    "film grain", "vintage",
}

TRIPTYCH_CONCRETE = {
    "elderly", "hospital", "care facility", "wheelchair",
    "medication", "medical equipment",
}

ADDITIONS = {
    "single person", "two people", "group of people", "crowd", "self-portrait",
    "text visible", "sign", "writing on wall",
    "eating", "drinking", "sleeping", "reading", "writing",
    "walking", "running", "sitting", "standing", "lying down",
    "playing", "working", "cooking",
    "face", "hand", "feet", "eyes closed", "smiling",
    "kitchen", "bathroom", "bedroom", "living room", "office",
    "garden", "park", "forest", "beach", "mountain", "lake", "river",
    "street", "sidewalk", "shop", "restaurant", "cafe",
    "school", "playground", "stairs", "hallway",
    "sunny", "overcast", "foggy", "rainy", "snowy", "stormy", "clear sky",
    "daytime", "nighttime", "twilight", "indoor scene", "outdoor scene",
    "documentary", "candid", "posed portrait", "environmental portrait",
    "still life", "architecture",
}


def normalize(kw: str) -> str:
    return " ".join(kw.strip().lower().split())


def apply_synonym(kw: str) -> str:
    n = normalize(kw)
    return SYNONYMS.get(n, n)


def load_existing_keywords(min_count: int = 50):
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
    return normalize(kw) not in {normalize(m) for m in PROJECTED_MOODS}


def main():
    raw = load_existing_keywords(min_count=50)
    print(f"Loaded {len(raw)} keywords with cnt >= 50 from prior tagging")

    # Filter mood + apply synonym merging; aggregate counts when synonyms collapse
    from collections import defaultdict
    merged_counts = defaultdict(int)
    dropped = []
    for kw, cnt in raw:
        if not is_concrete(kw):
            dropped.append(kw)
            continue
        canonical = apply_synonym(kw)
        merged_counts[canonical] += cnt

    sorted_merged = sorted(merged_counts.items(), key=lambda x: x[1], reverse=True)
    print(f"  after mood filter + synonym merge: {len(sorted_merged)} unique tags")
    print(f"  dropped as mood/abstract:          {len(dropped)}")

    # Top 250 by (now-merged) frequency
    capped = sorted_merged[:250]
    overflow = sorted_merged[250:]

    vocab = {
        "_meta": {
            "version": "0.3-draft",
            "purpose": "SigLIP zero-shot classification closed vocabulary",
            "notes": "v0.3 cleanup: expanded mood blacklist + synonym merging + variant dedup based on smoke-test feedback.",
            "previous_version_backup": "dam_vocabulary.v0.2.backup.json",
        },
        "technical": sorted(normalize(t) for t in TECHNICAL),
        "triptych_concrete": sorted(normalize(t) for t in TRIPTYCH_CONCRETE),
        "additions_uncategorized": sorted(normalize(t) for t in ADDITIONS),
        "from_existing_keywords_top_250_merged": [k for k, _ in capped],
        "_dropped_as_mood_or_abstract": sorted(set(dropped))[:80],
        "_overflow_dropped_low_freq": [k for k, _ in overflow[:30]],
        "_synonyms_applied": dict(sorted(SYNONYMS.items())),
    }

    # Flat dedup set
    all_set = set()
    for k, v in vocab.items():
        if k.startswith("_"):
            continue
        for tag in v:
            all_set.add(normalize(tag))
    vocab["all"] = sorted(all_set)
    vocab["_meta"]["total_tags"] = len(vocab["all"])

    OUT.write_text(json.dumps(vocab, indent=2, ensure_ascii=False))
    print(f"\nDraft v0.3 written: {OUT}")
    print(f"Total unique tags in flat 'all': {len(vocab['all'])}")
    print(f"Backup of v0.2 preserved: dam_vocabulary.v0.2.backup.json")


if __name__ == "__main__":
    main()
