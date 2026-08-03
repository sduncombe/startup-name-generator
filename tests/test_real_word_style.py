from __future__ import annotations

from collections import Counter

from app.services.brand_quality import brand_quality_ok
from app.services.filter import compact_key
from app.services.generator import NameGenerator, STYLE_WEIGHTS, normalize_naming_style
from app.services.llm import _STYLE_GUIDANCE, _build_prompt
from app.services.real_words import is_real_word_candidate, real_word_set
from app.services.scorer import score_candidate


def test_normalize_accepts_real_word():
    assert normalize_naming_style("real_word") == "real_word"
    assert normalize_naming_style("Real_Word") == "real_word"


def test_real_word_style_uses_only_real_word_method():
    assert set(STYLE_WEIGHTS["real_word"]) == {"real_word"}
    assert STYLE_WEIGHTS["real_word"]["real_word"] == 1.0


def test_real_word_generation_produces_lexicon_words():
    gen = NameGenerator(seed=11)
    names = gen.generate(
        category="furniture visualization",
        keywords=["furniture", "home", "visualize"],
        tone="Modern, Premium",
        max_length=12,
        count=80,
        naming_style="real_word",
    )
    assert len(names) >= 40
    known = real_word_set()
    methods = Counter(c.method for c in names)
    assert methods.get("real_word", 0) == len(names)
    assert methods.get("invented", 0) == 0
    for cand in names:
        key = compact_key(cand.name)
        assert is_real_word_candidate(key, known), cand.name
        # Must not look like soft inventeds
        assert key not in {"velora", "norva", "solin", "belva", "kova"}


def test_real_word_differs_from_invented():
    invented = {
        compact_key(c.name)
        for c in NameGenerator(seed=3).generate(
            category="payments",
            keywords=["payments", "money"],
            tone="Modern",
            max_length=12,
            count=60,
            naming_style="invented",
        )
    }
    real = {
        compact_key(c.name)
        for c in NameGenerator(seed=3).generate(
            category="payments",
            keywords=["payments", "money"],
            tone="Modern",
            max_length=12,
            count=60,
            naming_style="real_word",
        )
    }
    # Strategies should diverge — some overlap is fine (shared roots like vault).
    assert len(real - invented) >= 15
    inventedish = {"velora", "norva", "solin", "belva", "kova", "pella"}
    assert not (real & inventedish)


def test_brand_quality_gate_for_real_word():
    ok, _ = brand_quality_ok("Harbor", method="real_word", min_score=60)
    assert ok
    ok, reason = brand_quality_ok("Velora", method="real_word", min_score=60)
    assert not ok
    assert "soft" in reason or "real word" in reason
    ok, reason = brand_quality_ok("Bruksen", method="real_word", min_score=60)
    assert not ok


def test_real_word_scoring_rewards_lexicon_membership():
    real = score_candidate(
        "Prism",
        method="real_word",
        category="design tools",
        keywords=["design", "canvas"],
        tone="Modern",
        naming_style="real_word",
    )
    junk = score_candidate(
        "Bruksen",
        method="invented",
        category="design tools",
        keywords=["design", "canvas"],
        tone="Modern",
        naming_style="real_word",
    )
    assert real["total_score"] > junk["total_score"]
    assert real["scores"]["category_relevance"] > junk["scores"]["category_relevance"]


def test_llm_prompt_real_word_forbids_inventeds():
    assert "real_word" in _STYLE_GUIDANCE
    prompt = _build_prompt(
        category="saas",
        keywords=["workflow"],
        tone="Modern",
        brand_brief="People need a clearer way to manage work.",
        max_length=12,
        count=40,
        naming_style="real_word",
    )
    assert "REAL WORDS" in prompt or "existing English words" in prompt.lower()
    assert "Roomly" in prompt or "invent" in prompt.lower()
