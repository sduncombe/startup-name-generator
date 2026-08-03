from __future__ import annotations

from dataclasses import dataclass

from app.config import blocklist_config
from app.services.filter import compact_key


@dataclass
class ConflictResult:
    level: str
    notes: str


def check_conflict(name: str, *, category: str = "") -> ConflictResult:
    """
    Preliminary conflict scan against local brand/block lists.
    Not a legal trademark opinion; no live web search in V1.
    """
    block = blocklist_config()
    key = compact_key(name)
    exact = {x.lower() for x in block.get("exact_reject", [])}
    stems = [s.lower() for s in block.get("brand_stems", [])]

    if key in exact:
        return ConflictResult(
            "High apparent conflict",
            f"Exact match against known major brand/term '{key}'",
        )

    hits: list[str] = []
    for stem in stems:
        if not stem:
            continue
        if key == stem:
            hits.append(stem)
        elif len(stem) >= 4 and (key.startswith(stem) or key.endswith(stem) or stem in key):
            hits.append(stem)

    if hits:
        # Nest / sofa etc. often appear as stems; treat as possible unless exact brand
        major = {"ikea", "wayfair", "houzz", "google", "amazon", "apple", "homesense", "airbnb", "zillow"}
        if any(h in major for h in hits):
            return ConflictResult(
                "High apparent conflict",
                f"Close match to major brand stem(s): {', '.join(sorted(set(hits)))}",
            )
        return ConflictResult(
            "Possible conflict",
            f"Contains brand-adjacent stem(s): {', '.join(sorted(set(hits)))}",
        )

    return ConflictResult(
        "Low apparent conflict",
        "No obvious exact match found in local brand list",
    )
