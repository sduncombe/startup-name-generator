from __future__ import annotations

from collections import Counter

from app.services.generator import NameGenerator
from app.services.preferences import (
    build_preference_profile,
    language_display,
    normalize_language,
    preference_penalty,
)
from app.services.scorer import score_candidate


def test_normalize_language_defaults():
    assert normalize_language(None) == ("en-global", "")
    assert language_display("fr") == "French"
    assert language_display("other", "Dutch") == "Dutch"


def test_liked_brands_infer_traits_not_names():
    prefs = build_preference_profile(liked_brands="Notion, Stripe, Linear")
    assert "abstract" in prefs.traits or "minimal" in prefs.traits or "short" in prefs.traits
    assert "premium" in prefs.traits or "minimal" in prefs.traits


def test_audience_shapes_traits():
    prefs = build_preference_profile(audience="Busy parents with young kids")
    assert "friendly" in prefs.traits or "warm" in prefs.traits or "playful" in prefs.traits


def test_avoid_penalizes_matching_names():
    prefs = build_preference_profile(avoid="AI-sounding, enterprise, hard to pronounce")
    pen, notes = preference_penalty("CloudAICorp", prefs)
    assert pen >= 18
    assert notes


def test_japanese_generation_prefers_open_syllables():
    gen = NameGenerator(seed=21)
    names = gen.generate(
        category="learning app",
        keywords=["learn", "language"],
        tone="Friendly",
        max_length=10,
        count=80,
        naming_style="invented",
        primary_language="ja",
    )
    keys = ["".join(ch for ch in n.name.lower() if ch.isalpha()) for n in names]
    # Most names should end in a vowel for Japanese phonotactics
    vowel_end = sum(1 for k in keys if k and k[-1] in "aeiou")
    assert vowel_end >= len(keys) * 0.55


def test_avoid_and_liked_change_ranking():
    avoid_prefs = build_preference_profile(avoid="AI-sounding, enterprise")
    liked_prefs = build_preference_profile(liked_brands="Notion, Stripe")

    ai_name = score_candidate(
        "NeuralBot",
        method="invented",
        category="software",
        keywords=["software"],
        tone="Modern",
        naming_style="invented",
        preferences=avoid_prefs,
    )
    clean = score_candidate(
        "Vera",
        method="invented",
        category="software",
        keywords=["software"],
        tone="Modern",
        naming_style="invented",
        preferences=liked_prefs,
    )
    assert clean["total_score"] > ai_name["total_score"]


def test_liked_brands_shift_method_mix():
    abstract = NameGenerator(seed=3).generate(
        category="tools",
        keywords=["tool"],
        tone="Minimal",
        max_length=10,
        count=120,
        naming_style="invented",
        liked_brands="Notion, Stripe, Linear",
    )
    counts = Counter(c.method for c in abstract)
    assert counts["invented"] + counts["evocative"] > counts["descriptive"]
