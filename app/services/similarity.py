"""Deterministic string and phonetic similarity. No AI, no network."""

from __future__ import annotations

import re


def normalize(name: str) -> str:
    """Lowercase alphanumeric form used for all comparisons."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def levenshtein(a: str, b: str) -> int:
    """Classic edit distance (insert / delete / substitute)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def jaro(a: str, b: str) -> float:
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    window = max(la, lb) // 2 - 1
    if window < 0:
        window = 0
    a_flags = [False] * la
    b_flags = [False] * lb

    matches = 0
    for i in range(la):
        lo = max(0, i - window)
        hi = min(lb, i + window + 1)
        for j in range(lo, hi):
            if not b_flags[j] and a[i] == b[j]:
                a_flags[i] = b_flags[j] = True
                matches += 1
                break
    if not matches:
        return 0.0

    transpositions = 0
    j = 0
    for i in range(la):
        if a_flags[i]:
            while not b_flags[j]:
                j += 1
            if a[i] != b[j]:
                transpositions += 1
            j += 1
    transpositions //= 2

    m = float(matches)
    return (m / la + m / lb + (m - transpositions) / m) / 3.0


def jaro_winkler(a: str, b: str, *, prefix_weight: float = 0.1) -> float:
    """Jaro similarity boosted for a shared prefix (up to 4 chars)."""
    base = jaro(a, b)
    if base <= 0.7:
        return base
    prefix = 0
    for ca, cb in zip(a[:4], b[:4]):
        if ca != cb:
            break
        prefix += 1
    return base + prefix * prefix_weight * (1.0 - base)


_SOUNDEX_CODES = {
    "b": "1", "f": "1", "p": "1", "v": "1",
    "c": "2", "g": "2", "j": "2", "k": "2", "q": "2", "s": "2", "x": "2", "z": "2",
    "d": "3", "t": "3",
    "l": "4",
    "m": "5", "n": "5",
    "r": "6",
}


def soundex(name: str) -> str:
    """American Soundex, 4 characters (e.g. 'Homio' and 'Homeo' both H500)."""
    s = normalize(name)
    s = re.sub(r"[^a-z]", "", s)
    if not s:
        return ""
    first = s[0]
    encoded = [first.upper()]
    prev = _SOUNDEX_CODES.get(first, "")
    for ch in s[1:]:
        code = _SOUNDEX_CODES.get(ch, "")
        if code and code != prev:
            encoded.append(code)
            if len(encoded) == 4:
                break
        # h/w do not reset the previous code; vowels do
        if ch not in "hw":
            prev = code
    return "".join(encoded).ljust(4, "0")


def phonetic_key(name: str) -> str:
    """
    Aggressive phonetic normalization for wordmark comparison.
    Collapses common sound-alike spellings, then strips interior vowels.
    """
    s = normalize(name)
    s = re.sub(r"[^a-z]", "", s)
    if not s:
        return ""
    subs = [
        ("ough", "o"), ("augh", "a"),
        ("ph", "f"), ("gh", "g"), ("ck", "k"), ("sch", "sk"), ("sh", "x"),
        ("ch", "x"), ("th", "t"), ("wh", "w"), ("wr", "r"), ("kn", "n"),
        ("qu", "kw"), ("x", "ks"), ("z", "s"), ("c", "k"), ("y", "i"),
    ]
    for old, new in subs:
        s = s.replace(old, new)
    s = re.sub(r"(.)\1+", r"\1", s)  # collapse doubles
    head, tail = s[0], s[1:]
    tail = re.sub(r"[aeiou]", "", tail)
    return head + tail
