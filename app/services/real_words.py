"""Curated real-word brand lexicon — Stripe / Linear / Cursor energy."""

from __future__ import annotations

from functools import lru_cache

from app.config import load_yaml


@lru_cache
def real_word_lexicon() -> dict:
    return load_yaml("real_word_lexicon.yaml")


@lru_cache
def real_word_set() -> frozenset[str]:
    """Flattened curated real-word brand lexicon."""
    data = real_word_lexicon()
    words: set[str] = set()
    for _key, values in data.items():
        for w in values or []:
            s = str(w).strip().lower()
            if s and s.isalpha() and 3 <= len(s) <= 12:
                words.add(s)
    return frozenset(words)


def is_real_word_candidate(key: str, known: frozenset[str] | None = None) -> bool:
    """True if name is an intact lexicon word or a join of two lexicon words."""
    known = known if known is not None else real_word_set()
    if not key or not key.isalpha():
        return False
    if key in known:
        return True
    if len(key) < 6:
        return False
    for i in range(3, len(key) - 2):
        left, right = key[:i], key[i:]
        if left in known and right in known:
            return True
    return False
