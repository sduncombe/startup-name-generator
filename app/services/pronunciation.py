from __future__ import annotations

import re

VOWELS = set("aeiouy")


def syllable_count(name: str) -> int:
    """Rough English syllable estimate."""
    word = re.sub(r"[^a-z]", "", name.lower())
    if not word:
        return 0
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and count > 1 and not word.endswith(("le", "ye")):
        count -= 1
    return max(1, count)


def consecutive_consonants(name: str) -> int:
    word = re.sub(r"[^a-z]", "", name.lower())
    best = 0
    run = 0
    for ch in word:
        if ch not in VOWELS:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def pronounce_guide(name: str) -> str:
    """
    Lightweight pronunciation hint for the results table.
    Not IPA — intended as a quick human cue.
    """
    raw = name.strip()
    if not raw:
        return ""

    # Preserve known compound splits
    for sep in (" ", "-"):
        if sep in raw:
            parts = [p for p in raw.split(sep) if p]
            return sep.join(_syllable_hint(p) for p in parts)

    # CamelCase / TitleCase compounds
    pieces = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", raw)
    if len(pieces) > 1:
        return "-".join(_syllable_hint(p) for p in pieces)

    return _syllable_hint(raw)


def _syllable_hint(token: str) -> str:
    word = token.lower()
    # Split into vowel groups with surrounding consonants
    parts = re.findall(r"[^aeiouy]*[aeiouy]+(?:[^aeiouy]*(?=$|[^aeiouy][aeiouy]))?", word)
    if not parts:
        return word
    # Capitals for stress on the last full syllable for brandy feel
    out: list[str] = []
    for i, part in enumerate(parts):
        if i == len(parts) - 1 and len(parts) > 1:
            out.append(part.upper())
        else:
            out.append(part)
    return "-".join(out)
