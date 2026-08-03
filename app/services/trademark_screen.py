"""
Deterministic trademark screening.

Screens candidate names against a dataset of registered US wordmarks using
exact, edit-distance (Levenshtein / Jaro-Winkler), and phonetic (Soundex /
phonetic key) matching, weighted by Nice class relevance.

No AI, no scraping. The engine is data-source agnostic: it consumes any
YAML or JSON dataset with a `marks` list (and optional `meta`). Out of the
box it loads a tiny SAMPLE dataset (config/trademarks.sample.yaml) meant
only for development and demos. For production-quality screening, build a
dataset from the official USPTO bulk data with tools/import_uspto.py and
point TRADEMARK_DATA_PATH at it. This is an early-warning screen, not
legal advice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import CONFIG_DIR, get_settings
from app.services.similarity import jaro_winkler, levenshtein, normalize, phonetic_key, soundex

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"


@dataclass(frozen=True)
class MarkRecord:
    mark: str
    norm: str
    status: str  # live | pending | dead
    classes: tuple[int, ...]
    owner: str = ""
    sdx: str = ""
    pkey: str = ""


@dataclass
class TmMatch:
    mark: str
    status: str
    classes: tuple[int, ...]
    owner: str
    kind: str  # exact | spelling | phonetic
    similarity: float
    same_industry: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "mark": self.mark,
            "status": self.status,
            "classes": list(self.classes),
            "owner": self.owner,
            "kind": self.kind,
            "similarity": round(self.similarity, 3),
            "same_industry": self.same_industry,
        }


@dataclass
class ScreenResult:
    risk: str
    summary: str
    reason: str
    matches: list[TmMatch] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk": self.risk,
            "summary": self.summary,
            "reason": self.reason,
            "matches": [m.to_dict() for m in self.matches],
        }


@lru_cache
def _dataset() -> dict[str, Any]:
    settings = get_settings()
    override = (getattr(settings, "trademark_data_path", "") or "").strip()
    path = Path(override) if override else CONFIG_DIR / "trademarks.sample.yaml"
    with path.open(encoding="utf-8") as f:
        if path.suffix.lower() == ".json":
            data = json.load(f) or {}
        else:
            data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("Trademark dataset must be a mapping")
    return data


def dataset_info() -> dict[str, Any]:
    """Metadata about the active dataset, so the UI can flag sample data."""
    meta = _dataset().get("meta") or {}
    return {
        "name": str(meta.get("name") or "Custom dataset"),
        "sample": bool(meta.get("sample", False)),
        "source": str(meta.get("source") or ""),
        "marks": len(load_marks()),
    }


def clear_dataset_cache() -> None:
    _dataset.cache_clear()
    load_marks.cache_clear()


@lru_cache
def load_marks() -> tuple[MarkRecord, ...]:
    records: list[MarkRecord] = []
    for item in _dataset().get("marks") or []:
        mark = str(item.get("mark") or "").strip()
        if not mark:
            continue
        norm = normalize(mark)
        records.append(
            MarkRecord(
                mark=mark,
                norm=norm,
                status=str(item.get("status") or "live").lower(),
                classes=tuple(int(c) for c in (item.get("classes") or [])),
                owner=str(item.get("owner") or ""),
                sdx=soundex(mark),
                pkey=phonetic_key(mark),
            )
        )
    return tuple(records)


@lru_cache
def _class_hints() -> dict[str, tuple[int, ...]]:
    with (CONFIG_DIR / "trademark_classes.yaml").open(encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    hints = {}
    for word, classes in (config.get("class_hints") or {}).items():
        hints[str(word).lower()] = tuple(int(c) for c in classes)
    return hints


def infer_classes(category: str, keywords: list[str]) -> set[int]:
    """Guess the user's likely Nice classes from their brief. Deterministic."""
    text_words = set(normalize_words(category)) | {normalize(k) for k in keywords}
    classes: set[int] = set()
    for word, cls in _class_hints().items():
        if word in text_words:
            classes.update(cls)
    return classes


def normalize_words(text: str) -> list[str]:
    return [normalize(w) for w in (text or "").split() if normalize(w)]


def _spelling_threshold(length: int) -> int:
    return 1 if length <= 5 else 2


def screen_name(
    name: str,
    *,
    category: str = "",
    keywords: list[str] | None = None,
    marks: tuple[MarkRecord, ...] | None = None,
) -> ScreenResult:
    """Screen one name. Returns risk (low/medium/high), summary, reason, matches."""
    n = normalize(name)
    if not n:
        return ScreenResult(RISK_LOW, "None found", "Empty name.", [])

    marks = marks if marks is not None else load_marks()
    user_classes = infer_classes(category, keywords or [])
    n_sdx = soundex(n)
    n_pkey = phonetic_key(n)

    matches: list[TmMatch] = []
    for rec in marks:
        if abs(len(rec.norm) - len(n)) > 3:
            continue
        # Industry overlap; if we can't infer the user's classes, be conservative.
        same_industry = bool(user_classes & set(rec.classes)) if user_classes else True

        if n == rec.norm:
            matches.append(
                TmMatch(rec.mark, rec.status, rec.classes, rec.owner, "exact", 1.0, same_industry)
            )
            continue

        jw = jaro_winkler(n, rec.norm)
        lev = levenshtein(n, rec.norm)
        if lev <= _spelling_threshold(min(len(n), len(rec.norm))) or jw >= 0.92:
            matches.append(
                TmMatch(rec.mark, rec.status, rec.classes, rec.owner, "spelling", jw, same_industry)
            )
            continue

        if (rec.sdx and rec.sdx == n_sdx and jw >= 0.84) or (rec.pkey and rec.pkey == n_pkey):
            matches.append(
                TmMatch(rec.mark, rec.status, rec.classes, rec.owner, "phonetic", jw, same_industry)
            )

    matches.sort(key=lambda m: (-m.similarity, m.mark))
    active = [m for m in matches if m.status in ("live", "pending")]

    exact = next((m for m in active if m.kind == "exact"), None)
    if exact:
        cls = ", ".join(str(c) for c in exact.classes) or "unspecified"
        return ScreenResult(
            RISK_HIGH,
            f"Registered: {exact.mark}",
            f"Exact {exact.status} trademark found (Class {cls}"
            + (f", {exact.owner}" if exact.owner else "")
            + "). Consider another name.",
            matches,
        )

    similar_same = next((m for m in active if m.same_industry), None)
    if similar_same:
        cls = ", ".join(str(c) for c in similar_same.classes) or "unspecified"
        how = "Sounds like" if similar_same.kind == "phonetic" else "Similar spelling to"
        return ScreenResult(
            RISK_MEDIUM,
            f"Similar {similar_same.status} mark (Class {cls})",
            f"{how} {similar_same.status} trademark {similar_same.mark} (Class {cls}). "
            "Different spelling, same industry.",
            matches,
        )

    if active:
        m = active[0]
        cls = ", ".join(str(c) for c in m.classes) or "unspecified"
        return ScreenResult(
            RISK_LOW,
            f"Similar mark, unrelated class",
            f"Similar {m.status} trademark {m.mark} exists, but in an unrelated industry "
            f"(Class {cls}).",
            matches,
        )

    if matches:  # dead marks only
        return ScreenResult(
            RISK_LOW,
            "None live",
            "Only dead or abandoned similar marks found.",
            matches,
        )

    return ScreenResult(RISK_LOW, "None found", "No similar live marks found.", [])
