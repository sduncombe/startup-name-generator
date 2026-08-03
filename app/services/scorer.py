from __future__ import annotations

import re
from typing import Any

from app.config import blocklist_config, scoring_config, vocabulary_config
from app.services.filter import compact_key
from app.services.preferences import PreferenceProfile, preference_bonus, preference_penalty
from app.services.pronunciation import consecutive_consonants, syllable_count


def score_candidate(
    name: str,
    *,
    method: str,
    category: str,
    keywords: list[str],
    tone: str,
    domains: dict[str, Any] | None = None,
    conflict_level: str = "Not checked",
    naming_style: str = "brandable",
    preferences: PreferenceProfile | None = None,
) -> dict[str, Any]:
    cfg = scoring_config()
    weights = dict(cfg.get("weights", {}) or {})
    style_overrides = (cfg.get("style_weights") or {}).get(naming_style) or {}
    weights.update({k: float(v) for k, v in style_overrides.items()})
    penalties_cfg = cfg.get("penalties", {})
    length_cfg = cfg.get("length", {})
    syll_cfg = cfg.get("syllables", {})

    key = compact_key(name)
    syll = syllable_count(key)
    length = len(key)

    pronounce = _pronounceability(key, syll, syll_cfg)
    spelling = _spelling_clarity(key)
    memory = _memorability(key, method, syll)
    length_score = _length_score(length, length_cfg)
    relevance = _category_relevance(key, category, keywords, tone, naming_style=naming_style)
    flexibility = _brand_flexibility(key, method)
    domain_score = _domain_availability(domains or {})

    components = {
        "pronounceability": round(pronounce, 1),
        "spelling_clarity": round(spelling, 1),
        "memorability": round(memory, 1),
        "length": round(length_score, 1),
        "category_relevance": round(relevance, 1),
        "brand_flexibility": round(flexibility, 1),
        "domain_availability": round(domain_score, 1),
    }

    # weights sum to 100; each component is 0-100; contribution = component * weight/100
    total = sum(components.get(k, 0) * float(weights.get(k, 0)) / 100.0 for k in weights)

    penalty = 0.0
    notes: list[str] = []

    if consecutive_consonants(key) >= 3:
        penalty += float(penalties_cfg.get("hard_pronunciation", 25)) * 0.4
        notes.append("consonant cluster")
    if re.search(r"(.)\1", key) and method == "invented":
        # mild: doubles can be fine
        pass
    if length > int(length_cfg.get("ideal_max", 10)):
        penalty += float(penalties_cfg.get("long_name", 10))
        notes.append("long name")

    block = blocklist_config()
    stems = [s.lower() for s in block.get("brand_stems", [])]
    for stem in stems:
        if stem and stem in key and key != stem:
            # Nest in Nestlyn etc.
            if stem == "nest" and key.startswith("nest"):
                penalty += float(penalties_cfg.get("blocklist_hit", 45)) * 0.5
                notes.append(f"contains brand stem '{stem}'")
            elif len(stem) >= 4 and stem in key:
                penalty += float(penalties_cfg.get("major_trademark_similarity", 35)) * 0.6
                notes.append(f"similar to brand stem '{stem}'")

    if conflict_level.startswith("High"):
        penalty += float(penalties_cfg.get("existing_company_match", 40))
    elif conflict_level.startswith("Possible"):
        penalty += float(penalties_cfg.get("existing_app_match", 30)) * 0.7

    if domains:
        statuses = [str(v.get("status", "unknown")).lower() for v in domains.values()]
        if statuses and all(s in {"registered", "premium", "aftermarket"} for s in statuses):
            penalty += float(penalties_cfg.get("unavailable_all_domains", 15))
            notes.append("no preferred domains available")

    if preferences is not None:
        pref_pen, pref_notes = preference_penalty(name, preferences)
        penalty += pref_pen
        notes.extend(pref_notes)
        pref_bonus, _bonus_notes = preference_bonus(name, preferences)
        total += pref_bonus

    total = max(0.0, min(100.0, total - penalty))
    return {
        "total_score": round(total, 1),
        "scores": components,
        "penalty": round(penalty, 1),
        "penalty_notes": notes,
    }


def _pronounceability(key: str, syll: int, syll_cfg: dict) -> float:
    score = 90.0
    ideal_min = int(syll_cfg.get("ideal_min", 2))
    ideal_max = int(syll_cfg.get("ideal_max", 3))
    if syll < ideal_min or syll > ideal_max:
        score -= 25
    score -= max(0, consecutive_consonants(key) - 2) * 15
    if re.search(r"q(?!u)|x|z{2}", key):
        score -= 20
    return max(0, min(100, score))


def _spelling_clarity(key: str) -> float:
    score = 88.0
    # Silent-letter / ambiguous digraph risks
    for digraph in ("gh", "ph", "ough", "eau", "ieux", "tion"):
        if digraph in key:
            score -= 12
    if re.search(r"[aeiou]{3,}", key):
        score -= 15
    if re.search(r"(.)\1\1", key):
        score -= 25
    # Prefer simple alphabet
    if any(ch in key for ch in "xqzj"):
        score -= 8
    return max(0, min(100, score))


def _memorability(key: str, method: str, syll: int) -> float:
    score = 70.0
    if method in {"compound", "evocative", "invented", "suggestive", "modified_category"}:
        score += 12
    elif method == "descriptive":
        score += 4
    if 5 <= len(key) <= 9:
        score += 10
    if syll in (2, 3):
        score += 8
    if key.endswith(("a", "o", "ora", "ivo", "ly", "en", "el")):
        score += 5
    return max(0, min(100, score))


def _length_score(length: int, length_cfg: dict) -> float:
    ideal_min = int(length_cfg.get("ideal_min", 5))
    ideal_max = int(length_cfg.get("ideal_max", 10))
    hard_max = int(length_cfg.get("hard_max", 12))
    if ideal_min <= length <= ideal_max:
        return 100.0
    if length < ideal_min:
        return max(0, 100 - (ideal_min - length) * 15)
    if length <= hard_max:
        return max(0, 100 - (length - ideal_max) * 12)
    return 20.0


def _category_relevance(
    key: str,
    category: str,
    keywords: list[str],
    tone: str,
    *,
    naming_style: str = "brandable",
) -> float:
    vocab = vocabulary_config()
    # Brandable: keyword-in-name is not a virtue (Apple does not contain "computer").
    if naming_style == "brandable":
        score = 55.0
        tone_l = tone.lower()
        for label, words in (vocab.get("tone_words") or {}).items():
            if label in tone_l:
                for w in words or []:
                    if w is None or isinstance(w, bool):
                        continue
                    ws = str(w).lower()
                    if ws and ws in key:
                        score += 5
        return max(0, min(100, score))

    score = 40.0
    tokens = set(keywords)
    for word in (category.lower().replace(",", " ").split()):
        tokens.add(word)
    for t in list(tokens):
        t = re.sub(r"[^a-z]", "", t.lower())
        if t and t in key:
            score += 12
    for stem_list in (vocab.get("category_stems") or {}).values():
        for stem in stem_list or []:
            if stem is None or isinstance(stem, bool):
                continue
            s = str(stem).lower()
            if s and s in key:
                score += 6
                break
    tone_l = tone.lower()
    for label, words in (vocab.get("tone_words") or {}).items():
        if label in tone_l:
            for w in words or []:
                if w is None or isinstance(w, bool):
                    continue
                ws = str(w).lower()
                if ws and ws in key:
                    score += 5
    return max(0, min(100, score))


def _brand_flexibility(key: str, method: str) -> float:
    score = 65.0
    if method in {"invented", "evocative"}:
        score += 18
    if method in {"suggestive", "modified_category"}:
        score += 10
    if method == "compound":
        score += 6
    if method == "descriptive":
        score -= 10
        if " " in key:
            score -= 15
    if len(key) <= 8:
        score += 10
    return max(0, min(100, score))


def _domain_availability(domains: dict[str, Any]) -> float:
    if not domains:
        return 50.0  # unknown until checked
    score = 20.0
    for ext, result in domains.items():
        status = str(result.get("status", "unknown")).lower()
        if status == "available":
            if ext == ".com":
                score = max(score, 100.0)
            else:
                score = max(score, 75.0)
        elif status in {"premium", "aftermarket"}:
            score = max(score, 35.0)
        elif status == "registered":
            score = max(score, 15.0)
        elif status in {"unknown", "error"}:
            score = max(score, 40.0)
    return score
