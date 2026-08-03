"""
Brand preferences that materially change generation and scoring.

Every UI preference should map to concrete generator / scorer behavior:
- naming_style → strategy quotas (handled in generator)
- primary_language → syllable inventory, endings, phonetic penalties
- audience → tone / sophistication vocabulary bias
- liked_brands → trait inference (never copy names)
- avoid → active penalties for matching traits / substrings
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LANGUAGE_LABELS = {
    "en-global": "English (Global)",
    "en-us": "English (US)",
    "en-uk": "English (UK)",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "other": "Other",
}

# Phonotactic / scoring knobs per language. Invented names stay Latin-script
# brandables, tuned for speakers of that language.
LANGUAGE_PROFILES: dict[str, dict] = {
    "en-global": {
        "prefer_vowel_endings": False,
        "max_onset_cluster": 2,
        "avoid_clusters": ("sch", "tch", "x", "q"),
        "soft_endings": ("a", "o", "y", "ly", "en", "el", "ora"),
        "hard_letters_penalty": "xqz",
        "open_syllable_bias": 0.35,
    },
    "en-us": {
        "prefer_vowel_endings": False,
        "max_onset_cluster": 2,
        "avoid_clusters": ("sch", "tch"),
        "soft_endings": ("a", "o", "y", "ly", "en", "el", "ora"),
        "hard_letters_penalty": "xqz",
        "open_syllable_bias": 0.3,
    },
    "en-uk": {
        "prefer_vowel_endings": False,
        "max_onset_cluster": 2,
        "avoid_clusters": ("ize",),  # prefer -ise feel via softer endings
        "soft_endings": ("a", "o", "y", "ly", "our", "ise", "en"),
        "hard_letters_penalty": "xqz",
        "open_syllable_bias": 0.35,
    },
    "fr": {
        "prefer_vowel_endings": True,
        "max_onset_cluster": 1,
        "avoid_clusters": ("th", "wh", "ck", "gh"),
        "soft_endings": ("e", "é", "ette", "eau", "elle", "ine", "on", "a", "o"),
        "hard_letters_penalty": "kwxqz",
        "open_syllable_bias": 0.7,
        "onset_prefer": ("b", "c", "d", "f", "l", "m", "n", "p", "r", "s", "t", "v"),
        "nucleus_prefer": ("a", "e", "i", "o", "u", "ou", "ai", "eau"),
    },
    "de": {
        "prefer_vowel_endings": False,
        "max_onset_cluster": 2,
        "avoid_clusters": ("th", "wh"),
        "soft_endings": ("er", "el", "en", "ung", "a", "o"),
        "hard_letters_penalty": "xqj",
        "open_syllable_bias": 0.25,
        "onset_prefer": ("b", "d", "f", "g", "h", "k", "l", "m", "n", "p", "r", "s", "st", "t", "v", "w", "z"),
    },
    "es": {
        "prefer_vowel_endings": True,
        "max_onset_cluster": 1,
        "avoid_clusters": ("th", "wh", "ck", "sh", "ph"),
        "soft_endings": ("a", "o", "e", "ia", "io", "ito", "ita"),
        "hard_letters_penalty": "kwxqz",
        "open_syllable_bias": 0.8,
        "onset_prefer": ("b", "c", "d", "f", "g", "l", "m", "n", "p", "r", "s", "t", "v"),
        "nucleus_prefer": ("a", "e", "i", "o", "u"),
    },
    "it": {
        "prefer_vowel_endings": True,
        "max_onset_cluster": 1,
        "avoid_clusters": ("th", "wh", "ck", "sh", "ph", "x"),
        "soft_endings": ("a", "o", "e", "i", "ina", "ino", "etta"),
        "hard_letters_penalty": "kwxqzjy",
        "open_syllable_bias": 0.85,
        "onset_prefer": ("b", "c", "d", "f", "g", "l", "m", "n", "p", "r", "s", "t", "v"),
        "nucleus_prefer": ("a", "e", "i", "o", "u"),
    },
    "pt": {
        "prefer_vowel_endings": True,
        "max_onset_cluster": 1,
        "avoid_clusters": ("th", "wh", "ck", "sh"),
        "soft_endings": ("a", "o", "e", "ao", "inha", "inho"),
        "hard_letters_penalty": "kwxqz",
        "open_syllable_bias": 0.8,
        "onset_prefer": ("b", "c", "d", "f", "g", "l", "m", "n", "p", "r", "s", "t", "v"),
        "nucleus_prefer": ("a", "e", "i", "o", "u"),
    },
    "ja": {
        "prefer_vowel_endings": True,
        "max_onset_cluster": 0,
        "avoid_clusters": ("th", "wh", "ck", "sh", "ch", "ph", "st", "tr", "br", "pl", "cl", "fl"),
        "soft_endings": ("a", "i", "u", "o", "e", "ko", "mi", "ra", "ri", "to", "na"),
        "hard_letters_penalty": "lrvwxqzf",
        "open_syllable_bias": 1.0,
        "onset_prefer": ("k", "m", "n", "h", "t", "s", "y", "r", "b", "p", "d", "g"),
        "nucleus_prefer": ("a", "i", "u", "e", "o"),
        "forbid_coda": True,
    },
    "ko": {
        "prefer_vowel_endings": True,
        "max_onset_cluster": 0,
        "avoid_clusters": ("th", "wh", "ck", "st", "tr", "br", "pl"),
        "soft_endings": ("a", "i", "o", "u", "e", "mi", "na", "ra", "so"),
        "hard_letters_penalty": "fvxqz",
        "open_syllable_bias": 0.95,
        "onset_prefer": ("k", "m", "n", "h", "t", "s", "y", "r", "b", "p", "d", "g", "j"),
        "nucleus_prefer": ("a", "i", "u", "e", "o"),
        "forbid_coda": True,
    },
    "zh": {
        "prefer_vowel_endings": True,
        "max_onset_cluster": 0,
        "avoid_clusters": ("th", "wh", "ck", "st", "tr", "br", "pl", "dr", "str"),
        "soft_endings": ("a", "i", "o", "u", "an", "en", "ing", "ao", "ei"),
        "hard_letters_penalty": "rvxqz",
        "open_syllable_bias": 0.9,
        "onset_prefer": ("b", "d", "f", "g", "h", "j", "k", "l", "m", "n", "p", "s", "t", "w", "y", "z"),
        "nucleus_prefer": ("a", "e", "i", "o", "u", "ai", "ao", "ei"),
        "forbid_coda": True,
    },
    "other": {
        "prefer_vowel_endings": False,
        "max_onset_cluster": 2,
        "avoid_clusters": ("sch", "tch"),
        "soft_endings": ("a", "o", "y", "ly", "en", "el"),
        "hard_letters_penalty": "xqz",
        "open_syllable_bias": 0.4,
    },
}

# Liked brands → traits we want to echo (never copy the names).
BRAND_TRAITS: dict[str, set[str]] = {
    "notion": {"short", "minimal", "abstract", "calm"},
    "stripe": {"short", "abstract", "premium", "clear"},
    "airbnb": {"friendly", "warm", "approachable"},
    "slack": {"friendly", "playful", "short"},
    "figma": {"short", "abstract", "creative", "modern"},
    "canva": {"friendly", "playful", "approachable"},
    "linear": {"short", "minimal", "premium", "precise"},
    "spotify": {"bold", "cultural", "expressive"},
    "apple": {"short", "minimal", "premium", "abstract"},
    "google": {"friendly", "playful", "approachable"},
    "uber": {"short", "bold", "abstract"},
    "reddit": {"playful", "casual"},
    "asana": {"calm", "soft", "abstract"},
    "sonos": {"short", "premium", "abstract"},
    "oculus": {"abstract", "tech"},
    "roblox": {"playful", "youthful"},
    "houzz": {"home", "visual"},
    "nike": {"bold", "energetic", "short"},
    "mercury": {"premium", "minimal", "clear"},
    "vercel": {"short", "tech", "minimal"},
    "duolingo": {"playful", "friendly"},
    "headspace": {"calm", "soft", "friendly"},
    "peloton": {"bold", "energetic"},
}

AUDIENCE_TRAITS: dict[str, set[str]] = {
    "parent": {"friendly", "warm", "approachable", "soft"},
    "parents": {"friendly", "warm", "approachable", "soft"},
    "kid": {"playful", "friendly", "soft"},
    "kids": {"playful", "friendly", "soft"},
    "child": {"playful", "friendly", "soft"},
    "teen": {"playful", "bold", "short"},
    "student": {"friendly", "approachable", "clear"},
    "lawyer": {"sophisticated", "clear", "premium"},
    "attorney": {"sophisticated", "clear", "premium"},
    "enterprise": {"clear", "sophisticated", "premium"},
    "business": {"clear", "sophisticated"},
    "smb": {"approachable", "clear", "friendly"},
    "small business": {"approachable", "clear", "friendly"},
    "founder": {"modern", "bold", "short"},
    "developer": {"minimal", "tech", "short"},
    "designer": {"minimal", "creative", "premium"},
    "luxury": {"premium", "short", "sophisticated"},
    "premium": {"premium", "short", "sophisticated"},
    "consumer": {"friendly", "approachable", "clear"},
    "homeowner": {"warm", "approachable", "clear"},
    "homeowners": {"warm", "approachable", "clear"},
    "professional": {"clear", "sophisticated"},
    "creator": {"creative", "bold", "modern"},
    "nonprofit": {"warm", "friendly", "approachable"},
}

AVOID_TRAIT_MAP: dict[str, set[str]] = {
    "ai": {"tech_ai"},
    "artificial": {"tech_ai"},
    "gpt": {"tech_ai"},
    "llm": {"tech_ai"},
    "vr": {"tech_ai"},
    "xr": {"tech_ai"},
    "vision": {"tech_ai"},
    "enterprise": {"enterprise", "sophisticated"},
    "corporate": {"enterprise", "sophisticated"},
    "b2b": {"enterprise"},
    "luxury": {"premium", "sophisticated"},
    "premium": {"premium"},
    "cheap": {"playful"},
    "cute": {"playful", "soft"},
    "playful": {"playful"},
    "childish": {"playful", "youthful"},
    "hard to pronounce": {"hard_pronounce"},
    "hard-to-pronounce": {"hard_pronounce"},
    "difficult to pronounce": {"hard_pronounce"},
    "unpronounceable": {"hard_pronounce"},
    "long": {"long"},
    "complicated": {"hard_pronounce", "long"},
    "jargon": {"enterprise", "tech"},
    "techy": {"tech"},
    "geeky": {"tech"},
    "invented": {"invented_words"},
    "invented words": {"invented_words"},
    "syllable": {"invented_words"},
    "ai-sounding": {"invented_words", "tech_ai"},
    "ai sounding": {"invented_words", "tech_ai"},
    "-ly": {"startup_suffix"},
    "ly": {"startup_suffix"},
    "-ify": {"startup_suffix"},
    "ify": {"startup_suffix"},
    "-io": {"startup_suffix"},
    "io": {"startup_suffix"},
}


@dataclass
class PreferenceProfile:
    language: str = "en-global"
    language_other: str = ""
    language_label: str = "English (Global)"
    traits: set[str] = field(default_factory=set)
    avoid_traits: set[str] = field(default_factory=set)
    avoid_tokens: list[str] = field(default_factory=list)
    audience_tokens: list[str] = field(default_factory=list)
    style_bias: dict[str, float] = field(default_factory=dict)


def normalize_language(value: str | None, other: str = "") -> tuple[str, str]:
    code = (value or "en-global").strip().lower().replace("_", "-")
    aliases = {
        "english": "en-global",
        "en": "en-global",
        "english-global": "en-global",
        "english-us": "en-us",
        "english-uk": "en-uk",
        "french": "fr",
        "german": "de",
        "spanish": "es",
        "italian": "it",
        "portuguese": "pt",
        "japanese": "ja",
        "korean": "ko",
        "chinese": "zh",
        "mandarin": "zh",
    }
    code = aliases.get(code, code)
    if code not in LANGUAGE_LABELS:
        code = "en-global"
    other_text = (other or "").strip() if code == "other" else ""
    return code, other_text


def language_display(code: str, other: str = "") -> str:
    code, other = normalize_language(code, other)
    if code == "other" and other:
        return other
    return LANGUAGE_LABELS[code]


def language_profile(code: str) -> dict:
    code, _ = normalize_language(code)
    return dict(LANGUAGE_PROFILES.get(code) or LANGUAGE_PROFILES["en-global"])


def _infer_liked_traits(liked_brands: str) -> set[str]:
    traits: set[str] = set()
    for brand in re.split(r"[,;/]| and ", liked_brands or ""):
        key = brand.strip().lower()
        if not key:
            continue
        if key in BRAND_TRAITS:
            traits |= BRAND_TRAITS[key]
            continue
        # Fuzzy: substring match known brands
        for known, vals in BRAND_TRAITS.items():
            if known in key or key in known:
                traits |= vals
    return traits


def _infer_audience_traits(audience: str) -> tuple[set[str], list[str]]:
    text = (audience or "").lower()
    traits: set[str] = set()
    tokens: list[str] = []
    for needle, vals in AUDIENCE_TRAITS.items():
        if needle in text:
            traits |= vals
            tokens.append(needle)
    # Generic sophistication cues
    if any(w in text for w in ("executive", "c-suite", "fortune", "enterprise")):
        traits |= {"sophisticated", "premium", "clear"}
    if any(w in text for w in ("fun", "casual", "everyday", "family")):
        traits |= {"friendly", "approachable", "playful"}
    return traits, tokens


def _infer_avoid(avoid: str) -> tuple[set[str], list[str]]:
    text = (avoid or "").lower()
    traits: set[str] = set()
    tokens: list[str] = []
    for needle, vals in AVOID_TRAIT_MAP.items():
        if needle in text:
            traits |= vals
    # Free-form tokens to ban as substrings (skip ultra-short noise / meta words)
    skip = {
        "and",
        "the",
        "for",
        "with",
        "names",
        "name",
        "sounding",
        "sound",
        "words",
        "word",
        "random",
        "combinations",
        "combination",
        "generic",
        "startup",
        "suffixes",
        "suffix",
        "like",
        "difficult",
        "pronounce",
        "invented",
    }
    for tok in re.findall(r"[a-z][a-z0-9-]{1,}", text):
        if tok in skip or len(tok) < 2:
            continue
        # Keep short banned roots (ai, vr, xr, ly, io) and longer words.
        if len(tok) <= 2 and tok not in {"ai", "vr", "xr", "ly", "io"}:
            continue
        if tok not in tokens:
            tokens.append(tok)
        if tok in AVOID_TRAIT_MAP:
            traits |= AVOID_TRAIT_MAP[tok]
    return traits, tokens


def style_bias_from_traits(traits: set[str]) -> dict[str, float]:
    """Multipliers on generator strategy weights (relative)."""
    bias = {
        "invented": 1.0,
        "evocative": 1.0,
        "compound": 1.0,
        "suggestive": 1.0,
        "descriptive": 1.0,
        "real_word": 1.0,
    }
    if "abstract" in traits or "minimal" in traits:
        bias["invented"] += 0.35
        bias["evocative"] += 0.25
        bias["descriptive"] -= 0.25
    if "short" in traits:
        bias["invented"] += 0.15
        bias["compound"] -= 0.1
    if "playful" in traits or "friendly" in traits:
        bias["evocative"] += 0.2
        bias["compound"] += 0.15
    if "premium" in traits or "sophisticated" in traits:
        bias["invented"] += 0.2
        bias["evocative"] += 0.15
        bias["descriptive"] -= 0.2
        bias["compound"] -= 0.1
    if "warm" in traits or "approachable" in traits:
        bias["compound"] += 0.15
        bias["suggestive"] += 0.1
    if "tech" in traits:
        bias["invented"] += 0.15
        bias["suggestive"] += 0.1
    return {k: max(0.05, v) for k, v in bias.items()}


def build_preference_profile(
    *,
    primary_language: str = "en-global",
    primary_language_other: str = "",
    audience: str = "",
    liked_brands: str = "",
    avoid: str = "",
) -> PreferenceProfile:
    lang, lang_other = normalize_language(primary_language, primary_language_other)
    traits = _infer_liked_traits(liked_brands)
    aud_traits, aud_tokens = _infer_audience_traits(audience)
    traits |= aud_traits
    avoid_traits, avoid_tokens = _infer_avoid(avoid)
    return PreferenceProfile(
        language=lang,
        language_other=lang_other,
        language_label=language_display(lang, lang_other),
        traits=traits,
        avoid_traits=avoid_traits,
        avoid_tokens=avoid_tokens,
        audience_tokens=aud_tokens,
        style_bias=style_bias_from_traits(traits),
    )


def preference_penalty(name: str, profile: PreferenceProfile) -> tuple[float, list[str]]:
    """Deterministic score penalty from avoid list + trait conflicts."""
    key = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    penalty = 0.0
    notes: list[str] = []

    for tok in profile.avoid_tokens:
        # Exact short bans (ai/vr/xr/ly/io) or substring for longer tokens.
        if len(tok) <= 2:
            if key == tok or key.endswith(tok) or key.startswith(tok):
                penalty += 28
                notes.append(f"contains avoided '{tok}'")
        elif tok in key:
            penalty += 22
            notes.append(f"contains avoided '{tok}'")

    # Trait-based heuristics on the name itself
    if "tech_ai" in profile.avoid_traits:
        if any(s in key for s in ("ai", "gpt", "neural", "bot", "llm", "intel", "vision", "vr", "xr")):
            penalty += 28
            notes.append("AI-coded")
    if "startup_suffix" in profile.avoid_traits:
        if key.endswith(("ly", "ify", "io")) and len(key) >= 5:
            penalty += 30
            notes.append("startup suffix")
    if "invented_words" in profile.avoid_traits:
        # Soft inventeds / syllable soup — scoring layer; generator also gates these.
        if key.endswith(("ora", "ura", "iva", "ova", "ly", "ify")) and len(key) >= 6:
            penalty += 26
            notes.append("invented / AI-sounding")
    if "enterprise" in profile.avoid_traits:
        if any(s in key for s in ("corp", "sys", "soft", "data", "logic", "stack", "cloud")):
            penalty += 14
            notes.append("enterprise-coded")
    if "long" in profile.avoid_traits and len(key) > 10:
        penalty += 12
        notes.append("longer than preferred")
    if "hard_pronounce" in profile.avoid_traits:
        if re.search(r"[bcdfghjklmnpqrstvwxyz]{3,}", key) or re.search(r"[aeiou]{3,}", key):
            penalty += 16
            notes.append("harder to pronounce")
    if "playful" in profile.avoid_traits:
        if any(s in key for s in ("zz", "oo", "ify", "ly", "y")) and key.endswith(("y", "ie", "ify")):
            penalty += 10
            notes.append("playful tone")
    if "premium" in profile.avoid_traits:
        if any(s in key for s in ("lux", "elite", "prime", "royal", "gold")):
            penalty += 16
            notes.append("premium-coded")

    # Language fitness penalties
    lang = language_profile(profile.language)
    for cluster in lang.get("avoid_clusters") or ():
        if cluster and cluster in key:
            penalty += 10
            notes.append(f"awkward in {profile.language_label}")
            break
    hard = lang.get("hard_letters_penalty") or ""
    hard_hits = sum(1 for ch in key if ch in hard)
    if hard_hits >= 2:
        penalty += 8
        notes.append("hard letters for language")
    if lang.get("prefer_vowel_endings") and key and key[-1] not in "aeiouy":
        penalty += 6
        notes.append("consonant ending for language")
    if lang.get("forbid_coda") and re.search(r"[bcdfghjklmnpqrstvwxyz]{2}", key):
        penalty += 12
        notes.append("cluster-heavy for language")

    return penalty, notes


def preference_bonus(name: str, profile: PreferenceProfile) -> tuple[float, list[str]]:
    """Small rewards when a name fits requested traits / language."""
    key = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    bonus = 0.0
    notes: list[str] = []
    if "short" in profile.traits and 4 <= len(key) <= 7:
        bonus += 6
        notes.append("short")
    if "minimal" in profile.traits and len(key) <= 8 and key.isalpha():
        bonus += 4
    if "soft" in profile.traits or "calm" in profile.traits:
        if key.endswith(("a", "o", "e", "y", "en", "el", "ora")):
            bonus += 4
    if "bold" in profile.traits and key and key[0] in "bdfgkptvz":
        bonus += 3
    lang = language_profile(profile.language)
    if lang.get("prefer_vowel_endings") and key and key[-1] in "aeiou":
        bonus += 5
        notes.append("open ending")
    return bonus, notes
