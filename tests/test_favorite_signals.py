from __future__ import annotations

from app.services.favorite_signals import (
    classify_shape,
    favorite_affinity_bonus,
    profile_from_signals,
    signal_from_name,
)


def test_classify_shapes():
    assert classify_shape("Harbor") == "real_word"
    assert classify_shape("Basecamp") == "compound"
    assert classify_shape("Velora") == "invented"


def test_affinity_bonus_needs_enough_signal():
    weak = profile_from_signals(
        [signal_from_name("Harbor"), signal_from_name("Vault")]
    )
    assert favorite_affinity_bonus("Prism", weak) == 0.0

    rows = [signal_from_name(n) for n in ("Harbor", "Vault", "Prism", "Atlas", "Beacon")]
    profile = profile_from_signals(rows)
    assert profile["count"] == 5
    bonus = favorite_affinity_bonus("Cedar", profile)
    assert bonus > 0
