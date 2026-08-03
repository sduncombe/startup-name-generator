from __future__ import annotations

from collections import Counter

from app.services.brand_quality import brand_quality_ok, credibility_score
from app.services.filter import filter_name
from app.services.generator import NameGenerator
from app.services.scorer import score_candidate


def test_rejects_gibberish_examples():
    for name in ("Bapaen", "Booflar", "Brathu", "Breduora", "Orionan", "Sonosis", "Puke", "Stuha"):
        ok, reason = brand_quality_ok(name, method="invented", min_score=68)
        assert not ok, f"{name} should fail credibility ({reason})"


def test_accepts_real_brand_shapes():
    # Pattern references (scoring only — generator should not emit these brands).
    for name in ("Stripe", "Linear", "Vercel", "Slack", "Lyra", "Vera", "Nova", "Prism", "Lumina", "Atlas"):
        score = credibility_score(name, method="evocative")
        assert score >= 60, f"{name} scored {score}"


def test_brandable_batch_avoids_known_junk():
    gen = NameGenerator(seed=99)
    names = gen.generate(
        category="furniture visualization",
        keywords=["furniture", "home", "visualize"],
        tone="Warm, modern",
        max_length=12,
        count=60,
        naming_style="invented",
    )
    keys = {c.name.lower() for c in names}
    for junk in ("bapaen", "booflar", "brathu", "breduora"):
        assert junk not in keys
    # Prefer quality over padding — may be slightly under quota under hard gate
    assert len(names) >= 25
    # Most should look brand-like
    high = sum(1 for c in names if credibility_score(c.name, method=c.method) >= 64)
    assert high >= len(names) * 0.8


def test_brandable_mix_still_non_descriptive():
    gen = NameGenerator(seed=42)
    names = gen.generate(
        category="furniture visualization",
        keywords=["furniture", "home"],
        tone="Friendly",
        max_length=12,
        count=80,
        naming_style="invented",
    )
    counts = Counter(c.method for c in names)
    descriptive = counts.get("descriptive", 0)
    brandableish = sum(counts[m] for m in ("invented", "evocative", "compound", "suggestive"))
    assert brandableish > descriptive * 2


def test_credible_invented_beats_junk_in_scoring():
    good = score_candidate(
        "Lumina",
        method="invented",
        category="furniture",
        keywords=["furniture", "home"],
        tone="Modern",
        naming_style="invented",
    )
    junk = score_candidate(
        "Booflar",
        method="invented",
        category="furniture",
        keywords=["furniture", "home"],
        tone="Modern",
        naming_style="invented",
    )
    assert good["total_score"] > junk["total_score"]
    assert good["scores"]["brand_credibility"] > junk["scores"]["brand_credibility"]
