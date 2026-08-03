from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.config import blocklist_config, syllables_config
from app.services.pronunciation import consecutive_consonants, syllable_count

if TYPE_CHECKING:
    from app.services.naming_entity import NamingEntity

AMBIGUOUS_DEFAULT = {
    "xq", "qv", "qz", "zx", "gx", "cx", "pq", "nstl", "rnx", "yy", "uu", "iii", "aaa", "ooo", "eee",
}


@dataclass
class FilterResult:
    ok: bool
    reason: str = ""


def normalize_name(name: str, *, allow_ampersand: bool = False) -> str:
    if allow_ampersand:
        cleaned = re.sub(r"[^a-zA-Z &]", "", name)
        cleaned = re.sub(r"\s*&\s*", " & ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip(" &")
    return re.sub(r"[^a-zA-Z ]", "", name).strip()


def compact_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def filter_name(
    name: str,
    *,
    max_length: int = 12,
    entity: NamingEntity | None = None,
) -> FilterResult:
    cfg = syllables_config()
    block = blocklist_config()
    exact_reject = {str(x).lower() for x in block.get("exact_reject", []) if x}
    confusing = {str(x).lower() for x in block.get("confusing_terms", []) if x}
    ambiguous = {str(x).lower() for x in (cfg.get("ambiguous_clusters") or []) if x} | AMBIGUOUS_DEFAULT
    max_cons = int(cfg.get("max_consecutive_consonants", 3))

    allow_amp = bool(entity and entity.allow_ampersand)
    allow_spaces = bool(entity and entity.allow_spaces)
    eff_max = max(max_length, entity.max_length) if entity else max_length

    cleaned = normalize_name(name, allow_ampersand=allow_amp)
    if not cleaned:
        return FilterResult(False, "empty")
    if cleaned != name.strip():
        if re.search(r"[0-9]", name):
            return FilterResult(False, "contains numbers")
        if re.search(r"[-_'/\\.]", name):
            return FilterResult(False, "contains punctuation")
        if allow_amp:
            if re.search(r"[^a-zA-Z &]", name):
                return FilterResult(False, "uncommon characters")
        elif re.search(r"[^a-zA-Z ]", name):
            return FilterResult(False, "uncommon characters")

    key = compact_key(cleaned)
    display_len = len(cleaned) if (allow_spaces or allow_amp) else len(key)
    if len(key) < 4:
        return FilterResult(False, "too short")
    if display_len > eff_max:
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

    if re.search(r"(.)\1\1", key):
        return FilterResult(False, "accidental repeated letters")

    syll = syllable_count(key)
    # Multi-word local names can exceed 3 syllables naturally.
    syll_limit = 8 if (allow_spaces or allow_amp) else 3
    if syll > syll_limit:
        return FilterResult(False, "too many syllables")
    if syll < 1:
        return FilterResult(False, "unpronounceable")

    if re.search(r"q(?!u)", key):
        return FilterResult(False, "difficult q spelling")
    if key.startswith("x") or "xx" in key:
        return FilterResult(False, "difficult x spelling")

    if not re.search(r"[aeiouy]", key):
        return FilterResult(False, "no vowels")

    # Gibberish junctions matter most for inventeds, not local phrases.
    if not (allow_spaces or allow_amp):
        if re.search(r"(?:ae|ao|uu|iii|flar|oofl|apaen|duora)", key):
            return FilterResult(False, "awkward invented pattern")

    return FilterResult(True)
