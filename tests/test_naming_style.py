from __future__ import annotations

from collections import Counter

from app.services.generator import NameGenerator, STYLE_WEIGHTS, normalize_naming_style
from app.services.scorer import score_candidate


def test_normalize_naming_style_defaults_to_brandable():
    assert normalize_naming_style(None) == "brandable"
    assert normalize_naming_style("") == "brandable"
    assert normalize_naming_style("weird") == "brandable"
    assert normalize_naming_style("Descriptive") == "descriptive"


def test_brandable_mix_favors_non_descriptive():
    gen = NameGenerator(seed=42)
    names = gen.generate(
        category="furniture visualization",
        keywords=["furniture", "home", "visualize"],
        tone="Friendly, Warm",
        max_length=12,
        count=200,
        naming_style="brandable",
    )
    counts = Counter(c.method for c in names)
    descriptive = counts.get("descriptive", 0)
    brandableish = (
        counts.get("invented", 0)
        + counts.get("evocative", 0)
        + counts.get("compound", 0)
        + counts.get("suggestive", 0)
    )
    assert brandableish > descriptive * 3
    assert counts.get("invented", 0) + counts.get("evocative", 0) >= counts.get("descriptive", 0)


def test_descriptive_style_increases_descriptive_share():
    brandable = NameGenerator(seed=7).generate(
        category="furniture",
        keywords=["furniture", "home"],
        tone="Friendly",
        max_length=12,
        count=160,
        naming_style="brandable",
    )
    descriptive = NameGenerator(seed=7).generate(
        category="furniture",
        keywords=["furniture", "home"],
        tone="Friendly",
        max_length=12,
        count=160,
        naming_style="descriptive",
    )
    b_desc = sum(1 for c in brandable if c.method == "descriptive")
    d_desc = sum(1 for c in descriptive if c.method == "descriptive")
    assert d_desc > b_desc


def test_brandable_scoring_does_not_reward_keyword_stuffing():
    stuffed = score_candidate(
        "HomeFurniture",
        method="descriptive",
        category="furniture",
        keywords=["furniture", "home"],
        tone="Friendly",
        naming_style="brandable",
    )
    invented = score_candidate(
        "Vexora",
        method="invented",
        category="furniture",
        keywords=["furniture", "home"],
        tone="Friendly",
        naming_style="brandable",
    )
    assert invented["total_score"] >= stuffed["total_score"]


def test_descriptive_scoring_rewards_keyword_relevance():
    stuffed = score_candidate(
        "HomeFurniture",
        method="descriptive",
        category="furniture",
        keywords=["furniture", "home"],
        tone="Friendly",
        naming_style="descriptive",
    )
    invented = score_candidate(
        "Vexora",
        method="invented",
        category="furniture",
        keywords=["furniture", "home"],
        tone="Friendly",
        naming_style="descriptive",
    )
    assert stuffed["scores"]["category_relevance"] > invented["scores"]["category_relevance"]


def test_style_weight_tables_cover_all_methods():
    methods = {"invented", "evocative", "compound", "suggestive", "descriptive"}
    for style, weights in STYLE_WEIGHTS.items():
        assert set(weights) == methods
        assert abs(sum(weights.values()) - 1.0) < 1e-6
