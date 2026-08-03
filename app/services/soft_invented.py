"""Detect soft-invented / AI-brand morphology.

These pass phonotactic filters but fail the commercial test:
"We use ____ at work every day" should sound natural — Velora/Roomly do not.
"""

from __future__ import annotations

import re

from app.services.filter import compact_key
from app.services.real_words import real_word_set

# Exact soft inventeds previously curated into the brand lexicon by mistake.
BANNED_SOFT_INVENTEDS = frozenset(
    {
        "velora",
        "norva",
        "solin",
        "belva",
        "kova",
        "corda",
        "pella",
        "arvo",
        "toru",
        "mina",
        "vela",
        "sora",
        "quayle",
        "bruksen",
        "roomly",
        "vexora",
        "bram",
        "dorr",
        "noll",
        "pram",
        "quin",
    }
)

# Product-y / SaaS inventeds that sound generated.
_PRODUCT_INVENTED = re.compile(
    r"(ly|ify|sy|io|hq|ai|bot|ify|soft|ware)$"
)

# Soft Latinate coinage tails that dominate AI naming sludge.
_SOFT_COINAGE_TAIL = re.compile(r"(ora|ura|iva|uva|eva|ova)$")


def is_soft_invented(name: str) -> bool:
    """True when the name looks like an AI soft-invented brandable."""
    key = compact_key(name)
    if not key or len(key) < 4:
        return False
    if key in BANNED_SOFT_INVENTEDS:
        return True
    # Real curated words are never soft inventeds.
    if key in real_word_set():
        return False
    # *ly product inventeds that aren't common English adverbs used as brands.
    if key.endswith("ly") and len(key) >= 6 and key not in {"only", "early", "clearly"}:
        # Allow short brand-like ly when the stem is a known real word (rarely).
        stem = key[:-2]
        if stem not in real_word_set():
            return True
    if _PRODUCT_INVENTED.search(key) and key.endswith(("ify", "sy", "bot", "hq")):
        return True
    # Two-syllable-ish soft coinages ending in ora/iva/ova that aren't lexicon roots.
    if len(key) >= 5 and _SOFT_COINAGE_TAIL.search(key):
        # Keep classical/real: aurora, terra, vera, aura, flora (if present)
        if key in {"aurora", "terra", "vera", "aura", "flora", "agora", "corona"}:
            return False
        return True
    return False
