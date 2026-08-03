from __future__ import annotations

from app.services.brand_quality import brand_quality_ok, credibility_score
from app.services.generator import NameGenerator
from app.services.soft_invented import is_soft_invented


def test_flags_known_soft_inventeds():
    for name in ("Velora", "Norva", "Roomly", "Bruksen", "Vexora", "Solin"):
        assert is_soft_invented(name), name


def test_allows_real_and_classical_words():
    for name in ("Stripe", "Harbor", "Prism", "Atlas", "Nova", "Lumina", "Vera", "Aura"):
        assert not is_soft_invented(name), name


def test_gate_rejects_soft_inventeds():
    ok, reason = brand_quality_ok("Velora", method="invented", min_score=60)
    assert not ok
    assert "soft" in reason or "AI" in reason


def test_brandable_batch_excludes_purged_soft_inventeds():
    names = NameGenerator(seed=21).generate(
        category="design tools",
        keywords=["design", "canvas"],
        tone="Modern",
        max_length=12,
        count=60,
        naming_style="invented",
    )
    keys = {c.name.lower() for c in names}
    banned = {"velora", "norva", "solin", "belva", "kova", "corda", "pella", "arvo"}
    assert not (keys & banned)
    # Soft inventeds should score poorly even if somehow scored.
    assert credibility_score("Velora", method="invented") < 55
