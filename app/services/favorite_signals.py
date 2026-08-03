"""Learn from names founders actually keep (stars / shortlist).

Signals are anonymized patterns — length, shape, philosophy — not private brief text.
Used as a soft bonus in scoring so future runs lean toward what humans choose.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app.services.filter import compact_key
from app.services.real_words import is_real_word_candidate


def classify_shape(name: str) -> str:
    key = compact_key(name)
    if not key:
        return "empty"
    # Prefer compound when both halves are authentic words (Basecamp).
    for i in range(3, min(9, len(key) - 2)):
        left, right = key[:i], key[i:]
        if 3 <= len(right) <= 8 and is_real_word_candidate(left) and is_real_word_candidate(right):
            return "compound"
    if is_real_word_candidate(key):
        return "real_word"
    if re.search(r"[A-Z][a-z]+[A-Z]", name or ""):
        return "compound"
    return "invented"


def signal_from_name(
    name: str,
    *,
    method: str = "",
    naming_style: str = "",
) -> dict[str, Any]:
    key = compact_key(name)
    shape = classify_shape(name)
    return {
        "key": key,
        "length": len(key),
        "shape": shape,
        "method": method or "",
        "naming_style": naming_style or "",
        "ends_vowel": bool(key and key[-1] in "aeiouy"),
        "syllableish": 1 + sum(1 for i in range(1, len(key)) if key[i] in "aeiou" and key[i - 1] not in "aeiou"),
    }


@lru_cache(maxsize=1)
def _empty_profile() -> dict[str, Any]:
    return {
        "count": 0,
        "shapes": {},
        "avg_length": 0.0,
        "vowel_end_rate": 0.0,
    }


def profile_from_signals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return dict(_empty_profile())
    shapes: dict[str, int] = {}
    lengths: list[int] = []
    vowel_ends = 0
    for row in rows:
        shape = str(row.get("shape") or "invented")
        shapes[shape] = shapes.get(shape, 0) + 1
        lengths.append(int(row.get("length") or 0))
        if row.get("ends_vowel"):
            vowel_ends += 1
    return {
        "count": len(rows),
        "shapes": shapes,
        "avg_length": sum(lengths) / max(1, len(lengths)),
        "vowel_end_rate": vowel_ends / max(1, len(rows)),
    }


def favorite_affinity_bonus(name: str, profile: dict[str, Any] | None) -> float:
    """Soft 0–8 bonus when a candidate matches historically favorited patterns."""
    if not profile or int(profile.get("count") or 0) < 3:
        return 0.0
    key = compact_key(name)
    if not key:
        return 0.0
    shape = classify_shape(name)
    shapes = profile.get("shapes") or {}
    total = float(profile["count"])
    shape_share = float(shapes.get(shape, 0)) / total
    bonus = 0.0
    if shape_share >= 0.35:
        bonus += 4.0 * shape_share
    avg_len = float(profile.get("avg_length") or 0)
    if avg_len and abs(len(key) - avg_len) <= 1.5:
        bonus += 2.0
    if profile.get("vowel_end_rate", 0) >= 0.5 and key[-1:] in "aeiouy":
        bonus += 1.5
    return min(8.0, bonus)
