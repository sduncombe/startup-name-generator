"""Naming philosophies — distinct strategies, not tweaks on one algorithm.

API values: invented | real_word | compound | descriptive
Legacy: brandable→invented, balanced→invented
"""

from __future__ import annotations

# User-facing philosophies → local method quotas.
STYLE_WEIGHTS: dict[str, dict[str, float]] = {
    # Purpose-built brands that still feel natural (Figma / Canva / Houzz).
    "invented": {
        "invented": 0.38,
        "evocative": 0.42,
        "compound": 0.12,
        "suggestive": 0.08,
    },
    # Existing words as brands (Stripe / Cursor / Ramp / Atlas).
    "real_word": {
        "real_word": 1.0,
    },
    # Two familiar concepts joined (Basecamp / Mailchimp / DigitalOcean / GitHub).
    "compound": {
        "compound": 1.0,
    },
    # Names that say what you do (SurveyMonkey / PayPal energy — still ownable).
    "descriptive": {
        "descriptive": 0.45,
        "suggestive": 0.30,
        "compound": 0.20,
        "evocative": 0.05,
    },
}

VALID_STYLES = frozenset(STYLE_WEIGHTS)

LEGACY_STYLES = {
    "brandable": "invented",
    "balanced": "invented",
}

STYLE_LABELS = {
    "invented": "Invented",
    "real_word": "Real Words",
    "compound": "Compound",
    "descriptive": "Descriptive",
}


def normalize_naming_style(value: str | None) -> str:
    style = (value or "invented").strip().lower().replace("-", "_").replace(" ", "_")
    style = LEGACY_STYLES.get(style, style)
    # Friendly aliases
    if style in {"familiar", "real", "realwords", "real_words"}:
        style = "real_word"
    if style in {"invent", "brandable_invented"}:
        style = "invented"
    return style if style in VALID_STYLES else "invented"
