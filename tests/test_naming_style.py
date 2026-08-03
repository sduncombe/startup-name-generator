from __future__ import annotations

from collections import Counter

from app.services.generator import NameGenerator, STYLE_WEIGHTS, normalize_naming_style
from app.services.scorer import score_candidate


def test_normalize_naming_style_philosophies():
    assert normalize_naming_style(None) == "invented"
    assert normalize_naming_style("") == "invented"
    assert normalize_naming_style("weird") == "invented"
    assert normalize_naming_style("brandable") == "invented"
    assert normalize_naming_style("balanced") == "invented"
    assert normalize_naming_style("Familiar") == "real_word"
    assert normalize_naming_style("compound") == "compound"
    assert normalize_naming_style("Descriptive") == "descriptive"


def test_invented_mix_favors_non_descriptive():
    gen = NameGenerator(seed=42)
    names = gen.generate(
        category="furniture visualization",
        keywords=["furniture", "home", "visualize"],
        tone="Friendly, Warm",
        max_length=12,
        count=80,
        naming_style="invented",
    )
    counts = Counter(c.method for c in names)
    descriptive = counts.get("descriptive", 0)
    inventedish = (
        counts.get("invented", 0)
        + counts.get("evocative", 0)
        + counts.get("compound", 0)
        + counts.get("suggestive", 0)
    )
    assert inventedish > descriptive * 3


def test_descriptive_style_increases_descriptive_share():
    invented = NameGenerator(seed=7).generate(
        category="furniture",
        keywords=["furniture", "home"],
        tone="Friendly",
        max_length=12,
        count=80,
        naming_style="invented",
    )
    descriptive = NameGenerator(seed=7).generate(
        category="furniture",
        keywords=["furniture", "home"],
        tone="Friendly",
        max_length=12,
        count=80,
        naming_style="descriptive",
    )
    i_desc = sum(1 for c in invented if c.method == "descriptive")
    d_desc = sum(1 for c in descriptive if c.method == "descriptive")
    assert d_desc > i_desc


def test_compound_style_produces_two_part_names():
    names = NameGenerator(seed=11).generate(
        category="project tools",
        keywords=["project", "team"],
        tone="Modern",
        max_length=14,
        count=40,
        naming_style="compound",
    )
    assert len(names) >= 15
    assert all(c.method == "compound" for c in names)
    # Most should be longer joins (Basecamp energy), not 4-letter singles.
    longish = sum(1 for c in names if len(c.name) >= 7)
    assert longish >= len(names) * 0.7


def test_invented_scoring_does_not_reward_keyword_stuffing():
    stuffed = score_candidate(
        "HomeFurniture",
        method="descriptive",
        category="furniture",
        keywords=["furniture", "home"],
        tone="Friendly",
        naming_style="invented",
    )
    coined = score_candidate(
        "Lumina",
        method="invented",
        category="furniture",
        keywords=["furniture", "home"],
        tone="Friendly",
        naming_style="invented",
    )
    assert coined["total_score"] >= stuffed["total_score"]


def test_descriptive_scoring_rewards_keyword_relevance():
    stuffed = score_candidate(
        "HomeFurniture",
        method="descriptive",
        category="furniture",
        keywords=["furniture", "home"],
        tone="Friendly",
        naming_style="descriptive",
    )
    coined = score_candidate(
        "Lumina",
        method="invented",
        category="furniture",
        keywords=["furniture", "home"],
        tone="Friendly",
        naming_style="descriptive",
    )
    assert stuffed["scores"]["category_relevance"] > coined["scores"]["category_relevance"]


def test_style_weight_tables_are_valid():
    assert set(STYLE_WEIGHTS) == {"invented", "real_word", "compound", "descriptive"}
    for style, weights in STYLE_WEIGHTS.items():
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        assert all(w > 0 for w in weights.values())
