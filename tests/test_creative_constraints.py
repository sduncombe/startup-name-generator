from __future__ import annotations

from app.services.brief import compose_brand_brief
from app.services.llm import _build_prompt
from app.services.naming_entity import get_naming_entity
from app.services.preferences import build_preference_profile, preference_penalty


def test_prompt_is_opinionated_with_positive_and_negative_examples():
    prompt = _build_prompt(
        category="furniture visualization",
        keywords=["furniture", "home"],
        tone="Modern",
        brand_brief="Problem: visualize furniture before buying.",
        max_length=12,
        count=36,
        naming_style="real_word",
        entity=get_naming_entity("software_company"),
        liked_brands="Stripe, Cursor, Figma, Houzz, Notion, Linear",
        avoid="Invented words, AI-sounding, -ly, -ify, Vision, Home, Furniture",
    )
    assert "opinionated brand strategist" in prompt.lower() or "opinionated" in prompt
    assert "Roomly" in prompt and "Bapaen" in prompt
    assert "Stripe" in prompt and "Cursor" in prompt
    assert "inevitable rather than invented" in prompt
    assert "USER AVOID LIST" in prompt
    assert "Home" in prompt and "Furniture" in prompt
    assert "Learn naming PATTERNS" in prompt
    assert "do NOT imitate" in prompt or "Never copy" in prompt
    assert "That's actually a really good name" in prompt


def test_brief_explains_liked_brand_patterns():
    brief = compose_brand_brief(
        problem="People can't visualize furniture before buying.",
        naming_entity="software_company",
        liked_brands="Stripe, Cursor, Linear",
        avoid="AI, Vision, -ly",
    )
    assert "extract patterns" in brief.lower() or "naming style we admire" in brief.lower()
    assert "Hard avoid" in brief
    assert "commercially believable" in brief


def test_avoid_tokens_include_short_roots_and_suffixes():
    prefs = build_preference_profile(
        avoid="Invented words, AI-sounding, -ly, -ify, Vision, Home, Furniture, VR"
    )
    tokens = set(prefs.avoid_tokens)
    assert "vision" in tokens
    assert "home" in tokens
    assert "furniture" in tokens
    assert "ly" in tokens or "startup_suffix" in prefs.avoid_traits
    assert "tech_ai" in prefs.avoid_traits or "vision" in tokens

    pen, notes = preference_penalty("HomeVision", prefs)
    assert pen >= 22
    assert notes

    pen_ly, _ = preference_penalty("Roomly", prefs)
    assert pen_ly >= 22
