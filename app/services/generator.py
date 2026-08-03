from __future__ import annotations

import itertools
import random
import re
from dataclasses import dataclass

from app.config import syllables_config, vocabulary_config
from app.services.filter import compact_key, filter_name, normalize_name
from app.services.pronunciation import pronounce_guide


@dataclass
class Candidate:
    name: str
    pronunciation: str
    method: str
    rejected: bool = False
    reject_reason: str = ""


def _title_join(parts: list[str]) -> str:
    return "".join(p[:1].upper() + p[1:].lower() for p in parts if p)


def _spaced(parts: list[str]) -> str:
    return " ".join(p[:1].upper() + p[1:].lower() for p in parts if p)


class NameGenerator:
    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.vocab = vocabulary_config()
        self.syllables = syllables_config()

    def generate(
        self,
        *,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        count: int,
    ) -> list[Candidate]:
        bag: dict[str, Candidate] = {}
        target = max(count * 3, count + 200)  # overgenerate then filter

        strategies = [
            self._descriptive,
            self._compounds,
            self._invented,
            self._modified_category,
        ]

        # Round-robin strategies until we have enough unique keys
        for i in range(target):
            strategy = strategies[i % len(strategies)]
            for cand in strategy(category, keywords, tone, max_length):
                key = compact_key(cand.name)
                if not key or key in bag:
                    continue
                result = filter_name(cand.name, max_length=max_length)
                if not result.ok:
                    continue
                cand.pronunciation = pronounce_guide(cand.name)
                bag[key] = cand
                if len(bag) >= count:
                    return list(bag.values())

        # Fill remaining with invented if still short
        while len(bag) < count:
            for cand in self._invented(category, keywords, tone, max_length, batch=50):
                key = compact_key(cand.name)
                if key in bag:
                    continue
                result = filter_name(cand.name, max_length=max_length)
                if not result.ok:
                    continue
                cand.pronunciation = pronounce_guide(cand.name)
                bag[key] = cand
                if len(bag) >= count:
                    break
            else:
                break

        return list(bag.values())

    @staticmethod
    def _words(values: list | None) -> list[str]:
        """Coerce YAML values to clean lowercase strings (skip bool/None)."""
        out: list[str] = []
        for v in values or []:
            if v is None or isinstance(v, bool):
                continue
            s = str(v).strip().lower()
            if s and s not in out:
                out.append(s)
        return out

    def _pool(self, keywords: list[str], tone: str) -> dict[str, list[str]]:
        v = self.vocab
        nouns = self._words(v.get("nouns"))
        verbs = self._words(v.get("verbs"))
        benefits = self._words(v.get("benefits"))
        modifiers = self._words(v.get("modifiers"))

        for kw in keywords:
            k = str(kw).strip().lower()
            if not k:
                continue
            if k not in nouns:
                nouns.append(k)
            if k not in verbs and len(k) <= 10:
                verbs.append(k)

        tone_key = tone.lower()
        for label, words in (v.get("tone_words") or {}).items():
            if label in tone_key:
                for w in self._words(words):
                    if w not in benefits:
                        benefits.append(w)

        self.rng.shuffle(nouns)
        self.rng.shuffle(verbs)
        self.rng.shuffle(benefits)
        self.rng.shuffle(modifiers)
        return {
            "nouns": nouns,
            "verbs": verbs,
            "benefits": benefits,
            "modifiers": modifiers,
        }

    def _descriptive(
        self,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        batch: int = 80,
    ) -> list[Candidate]:
        pool = self._pool(keywords, tone)
        templates = list(self.vocab.get("phrase_templates", []))
        out: list[Candidate] = []
        for _ in range(batch):
            tmpl = self.rng.choice(templates)
            values = {
                "noun": self.rng.choice(pool["nouns"]),
                "verb": self.rng.choice(pool["verbs"]),
                "benefit": self.rng.choice(pool["benefits"]),
                "modifier": self.rng.choice(pool["modifiers"]),
            }
            try:
                phrase = tmpl.format(**values)
            except KeyError:
                continue
            # Prefer compact brandable form, keep spaced only if short
            words = [w for w in re.split(r"\s+", phrase) if w]
            compact = _title_join(words)
            spaced = _spaced(words)
            chosen = compact if len(compact_key(compact)) <= max_length else spaced
            if len(compact_key(chosen)) > max_length:
                continue
            out.append(Candidate(name=chosen, pronunciation="", method="descriptive"))
        return out

    def _compounds(
        self,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        batch: int = 100,
    ) -> list[Candidate]:
        pool = self._pool(keywords, tone)
        lefts = pool["nouns"][:40] + pool["verbs"][:20]
        rights = pool["modifiers"][:30] + pool["benefits"][:20] + pool["nouns"][:20]
        out: list[Candidate] = []
        pairs = list(itertools.product(lefts[:25], rights[:25]))
        self.rng.shuffle(pairs)
        for a, b in pairs[:batch]:
            if a.lower() == b.lower():
                continue
            name = _title_join([a, b])
            if len(compact_key(name)) > max_length:
                continue
            out.append(Candidate(name=name, pronunciation="", method="compound"))
        return out

    def _invented(
        self,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        batch: int = 120,
    ) -> list[Candidate]:
        onsets = self.syllables.get("onsets", [])
        nuclei = self.syllables.get("nuclei", [])
        codas = self.syllables.get("codas", [])
        endings = self.syllables.get("endings", [])
        out: list[Candidate] = []
        for _ in range(batch):
            pattern = self.rng.choice(self.syllables.get("patterns", ["CV-CV"]))
            parts: list[str] = []
            for piece in pattern.split("-"):
                onset = self.rng.choice(onsets) if piece.startswith("C") else ""
                nucleus = self.rng.choice(nuclei)
                coda = ""
                if piece.endswith("C") and len(piece) >= 3:
                    coda = self.rng.choice([c for c in codas if c])
                elif "C" in piece[1:]:
                    coda = self.rng.choice(codas)
                parts.append(f"{onset}{nucleus}{coda}")
            # Sometimes attach a brand ending
            if self.rng.random() < 0.45:
                end = self.rng.choice(endings)
                base = "".join(parts)
                if not base.endswith(end):
                    name = base[:1].upper() + base[1:] + end
                else:
                    name = base[:1].upper() + base[1:]
            else:
                base = "".join(parts)
                name = base[:1].upper() + base[1:]
            name = normalize_name(name)
            if not name or len(compact_key(name)) > max_length:
                continue
            out.append(Candidate(name=name, pronunciation="", method="invented"))
        return out

    def _modified_category(
        self,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        batch: int = 80,
    ) -> list[Candidate]:
        stems_map = self.vocab.get("category_stems", {})
        stems: list[str] = []
        cat = category.lower()
        for key, values in stems_map.items():
            if key in cat or any(str(k).lower() in cat for k in keywords):
                stems.extend(self._words(values))
        if not stems:
            for values in stems_map.values():
                stems.extend(self._words(values))
        endings = self._words(self.syllables.get("endings")) or ["ora", "ivo", "a", "o", "lyn", "wise"]
        out: list[Candidate] = []
        for _ in range(batch):
            stem = self.rng.choice(stems)
            end = self.rng.choice(endings)
            # Avoid doubling stem/end
            if stem.endswith(end[:2]):
                end = self.rng.choice([e for e in endings if e != end] or [end])
            name = stem[:1].upper() + stem[1:] + end
            if len(compact_key(name)) > max_length:
                name = (stem[:1].upper() + stem[1:] + end[:2])
            if len(compact_key(name)) > max_length:
                continue
            out.append(Candidate(name=name, pronunciation="", method="modified_category"))
        return out
