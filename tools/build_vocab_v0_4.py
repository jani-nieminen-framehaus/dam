#!/usr/bin/env python3
"""Build closed vocabulary v0.4 — production-test-driven cleanup.

Changes from v0.3:
  - Expanded blacklist with leaks seen in real classifier output:
    concern, excitement, joy, disorganization, lens diffusion,
    + descriptive phrases that aren't atomic tags.
  - Expanded synonym map for setting near-duplicates: indoor space/setting/
    lighting/room/settings all -> indoor scene; nighttime photography ->
    night; etc.
  - NEW: drop any tag longer than 4 words (descriptive phrases like
    "calming influence of nature (soft & scattered lights"). These aren't
    classifier targets — they're free-form fragments from prior LLM output.
  - NEW: drop tags containing parentheses, slashes, or '&' (phrase
    fragments).
"""
import sqlite3
import json
from pathlib import Path
from collections import defaultdict

DB = "/Users/janinieminen/.dam/dam.db"
OUT = Path("/Users/janinieminen/Documents/dam/dam_vocabulary.json")

# Mood / abstract projections — v0.4 expanded
PROJECTED_MOODS = {
    # v0.3 set
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
    "neglect", "coziness", "orderliness", "messiness",
    "child-friendly environment", "domestic setting", "domestic interior",
    "indoor environment",
    "child-friendliness", "child-friendly",
    "coolness",
    "stagedness",
    "atmospheric", "atmospheric lighting",
    "casual moment", "intimate moment", "candid moment",
    "story", "narrative",
    "personality", "character",
    "expression", "expressiveness",
    "interaction", "connection",
    "everyday life", "daily life", "domestic life",

    # v0.4 ADDITIONS — seen leaking in real production output
    "concern", "excitement", "disorganization", "lens diffusion",
    "calming influence", "gentle lighting",
    "direct gaze",  # judgmentally interpretive — looking-at-camera is fine but this is loaded
    "introspection", "reflection",  # ambiguous: water-reflection ok, but the LoRA used both senses
    "absentmindedness", "alertness",
    "amusement", "pride", "shame", "disgust",
    "surprise", "boredom",
    "calm focus", "deep focus state",
    "engaged play", "active play", "creative play",
    "still life arrangement",
    "quiet moment", "loud moment",
    "personal space", "shared space",
    "soft atmosphere",
    # v0.5 ADDITIONS — leakers seen in lightbox after v0.4 deployed
    "distress", "cozy", "drama", "dramatic",
    "tiredness", "weariness", "alert", "alertness",
    "attentiveness", "inattentiveness",
    "trust", "mistrust", "suspicion",
    "frustration", "satisfaction", "dissatisfaction",
    "anger", "tranquillity",
    "interest", "disinterest",
    "well-being", "wellbeing",
    "atmosphere",  # too vague on its own
    "feeling", "feel",
    "vibe", "ambience", "ambiance",
}

# Synonym merge map — v0.4 expanded for setting and lighting duplicates
SYNONYMS = {
    # v0.3 (kept)
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
    "siting": "sitting",
    "standin": "standing",
    "playin": "playing",
    "babies": "baby",
    "children": "child",
    "kids": "child",
    "kid": "child",
    "toddlers": "toddler",
    "women": "woman",
    "men": "man",
    "people": "person",
    "persons": "person",
    "hands": "hand",
    "indoors": "indoor scene",
    "outdoors": "outdoor scene",
    "indoor": "indoor scene",
    "outdoor": "outdoor scene",
    "interior": "indoor scene",
    "exterior": "outdoor scene",

    # v0.4 ADDITIONS — collapse the "indoor X" family
    "indoor setting": "indoor scene",
    "indoor settings": "indoor scene",
    "indoor space": "indoor scene",
    "indoor room": "indoor scene",
    "indoor lighting": "indoor scene",  # was loose; reclassify as a scene
    "outdoor setting": "outdoor scene",
    "outdoor settings": "outdoor scene",
    "outdoor space": "outdoor scene",
    "outdoor area": "outdoor scene",
    # Night family
    "nighttime": "night",
    "night scene": "night",
    "nighttime photography": "night",
    "night photography": "night",
    "nighttime image": "night",
    # Toys family
    "toys": "toy",
    # Cameras / lenses to singular
    "cameras": "camera",
    "lenses": "lens",
    "camera lenses": "lens",
    # Misc duplicates
    "low-key lighting": "low light",
    "high-key lighting": "high-key light",
    "warm-toned light": "warm light",
    "cool-toned light": "cool light",
    "soft shadow": "soft shadows",
    # Plurals
    "toy cars": "toy car",
    "streetlights": "streetlight",
    "lights": "light",
    "shadows": "shadow",
}

# Technical photographic terms
TECHNICAL = {
    "backlit", "silhouette",
    "high contrast", "low contrast",
    "shallow depth of field", "deep focus",
    "motion blur", "sharp focus",
    "long exposure",
    "soft light", "natural light", "artificial light",
    "high-key light", "low light",
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
    "daytime", "night", "twilight", "indoor scene", "outdoor scene",
    "documentary", "candid", "posed portrait", "environmental portrait",
    "still life", "architecture",
}


def normalize(kw: str) -> str:
    return " ".join(kw.strip().lower().split())


def is_phrase_fragment(kw: str) -> bool:
    """Detect free-form descriptive phrases (not atomic tags)."""
    if any(c in kw for c in "()/&"):
        return True
    if len(kw.split()) > 4:
        return True
    return False


def apply_synonym(kw: str) -> str:
    n = normalize(kw)
    return SYNONYMS.get(n, n)


def is_concrete(kw: str) -> bool:
    n = normalize(kw)
    if n in {normalize(m) for m in PROJECTED_MOODS}:
        return False
    if is_phrase_fragment(n):
        return False
    return True


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


def main():
    raw = load_existing_keywords(min_count=50)
    print(f"Loaded {len(raw)} keywords with cnt >= 50 from prior tagging")

    merged_counts = defaultdict(int)
    dropped_mood = []
    dropped_phrase = []
    for kw, cnt in raw:
        n = normalize(kw)
        if n in {normalize(m) for m in PROJECTED_MOODS}:
            dropped_mood.append(kw)
            continue
        if is_phrase_fragment(n):
            dropped_phrase.append(kw)
            continue
        canonical = apply_synonym(kw)
        merged_counts[canonical] += cnt

    sorted_merged = sorted(merged_counts.items(), key=lambda x: x[1], reverse=True)
    print(f"  after mood filter + phrase filter + synonym merge: {len(sorted_merged)} unique tags")
    print(f"  dropped as mood/abstract:  {len(dropped_mood)}")
    print(f"  dropped as phrase fragment: {len(dropped_phrase)}")

    capped = sorted_merged[:250]
    overflow = sorted_merged[250:]

    vocab = {
        "_meta": {
            "version": "0.5-draft",
            "purpose": "SigLIP zero-shot classification closed vocabulary",
            "notes": "v0.5: added distress, cozy, drama and related emotion/abstract leakers seen in production lightbox.",
        },
        "technical": sorted(normalize(t) for t in TECHNICAL),
        "triptych_concrete": sorted(normalize(t) for t in TRIPTYCH_CONCRETE),
        "additions_uncategorized": sorted(normalize(t) for t in ADDITIONS),
        "from_existing_keywords_top_250_merged": [k for k, _ in capped],
        "_dropped_as_mood_or_abstract": sorted(set(dropped_mood))[:80],
        "_dropped_as_phrase_fragment": sorted(set(dropped_phrase))[:40],
        "_overflow_dropped_low_freq": [k for k, _ in overflow[:30]],
        "_synonyms_applied": dict(sorted(SYNONYMS.items())),
    }

    all_set = set()
    for k, v in vocab.items():
        if k.startswith("_"):
            continue
        for tag in v:
            all_set.add(normalize(tag))
    vocab["all"] = sorted(all_set)
    vocab["_meta"]["total_tags"] = len(vocab["all"])

    OUT.write_text(json.dumps(vocab, indent=2, ensure_ascii=False))
    print(f"\nDraft v0.4 written: {OUT}")
    print(f"Total unique tags in flat 'all': {len(vocab['all'])}")


if __name__ == "__main__":
    main()
