from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import blocklist_config, syllables_config
from app.services.pronunciation import consecutive_consonants, syllable_count

AMBIGUOUS_DEFAULT = {
    "xq", "qv", "qz", "zx", "gx", "cx", "pq", "nstl", "rnx", "yy", "uu", "iii", "aaa", "ooo", "eee",
}


@dataclass
class FilterResult:
    ok: bool
    reason: str = ""


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z ]", "", name).strip()


def compact_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def filter_name(name: str, *, max_length: int = 12) -> FilterResult:
    cfg = syllables_config()
    block = blocklist_config()
    exact_reject = {str(x).lower() for x in block.get("exact_reject", []) if x}
    confusing = {str(x).lower() for x in block.get("confusing_terms", []) if x}
    ambiguous = {str(x).lower() for x in (cfg.get("ambiguous_clusters") or []) if x} | AMBIGUOUS_DEFAULT
    max_cons = int(cfg.get("max_consecutive_consonants", 3))

    cleaned = normalize_name(name)
    if not cleaned:
        return FilterResult(False, "empty")
    if cleaned != name.strip():
        # numbers / punctuation / hyphens present
        if re.search(r"[0-9]", name):
            return FilterResult(False, "contains numbers")
        if re.search(r"[-_'/\\.]", name):
            return FilterResult(False, "contains punctuation")
        if re.search(r"[^a-zA-Z ]", name):
            return FilterResult(False, "uncommon characters")

    key = compact_key(cleaned)
    display_len = len(key)
    if display_len < 4:
        return FilterResult(False, "too short")
    if display_len > max_length:
        return FilterResult(False, "too long")

    if key in exact_reject:
        return FilterResult(False, "exact brand blocklist")
    for term in confusing:
        if term and term in key:
            return FilterResult(False, "confusing term")

    if consecutive_consonants(key) > max_cons:
        return FilterResult(False, "too many consecutive consonants")

    for cluster in ambiguous:
        if cluster and cluster in key:
            return FilterResult(False, f"ambiguous cluster: {cluster}")

    # Accidental repeated letters (aaa, bbbb) — allow common doubles like ll, ss, ee
    if re.search(r"(.)\1\1", key):
        return FilterResult(False, "accidental repeated letters")

    syll = syllable_count(key)
    if syll > 3:
        return FilterResult(False, "more than three syllables")
    if syll < 1:
        return FilterResult(False, "unpronounceable")

    # Hard letter pairs for FR/EN (q without u, naked x mid-word starts)
    if re.search(r"q(?!u)", key):
        return FilterResult(False, "difficult q spelling")
    if key.startswith("x") or "xx" in key:
        return FilterResult(False, "difficult x spelling")

    # Must contain at least one vowel
    if not re.search(r"[aeiouy]", key):
        return FilterResult(False, "no vowels")

    return FilterResult(True)
