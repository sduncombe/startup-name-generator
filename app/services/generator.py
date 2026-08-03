from __future__ import annotations

import itertools
import random
import re
from dataclasses import dataclass

from app.config import syllables_config, vocabulary_config
from app.services.filter import compact_key, filter_name, normalize_name
from app.services.pronunciation import pronounce_guide

# Strategy mix by naming philosophy. Weights are relative.
# Brandable defaults toward invented / abstract / evocative names that
# companies can grow into, not SEO-style product descriptions.
STYLE_WEIGHTS: dict[str, dict[str, float]] = {
    "brandable": {
        "invented": 0.35,
        "evocative": 0.25,
        "compound": 0.20,
        "suggestive": 0.15,
        "descriptive": 0.05,
    },
    "balanced": {
        "invented": 0.22,
        "evocative": 0.18,
        "compound": 0.22,
        "suggestive": 0.18,
        "descriptive": 0.20,
    },
    "descriptive": {
        "invented": 0.08,
        "evocative": 0.10,
        "compound": 0.25,
        "suggestive": 0.22,
        "descriptive": 0.35,
    },
}

VALID_STYLES = frozenset(STYLE_WEIGHTS)


def normalize_naming_style(value: str | None) -> str:
    style = (value or "brandable").strip().lower()
    return style if style in VALID_STYLES else "brandable"


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
        naming_style: str = "brandable",
    ) -> list[Candidate]:
        style = normalize_naming_style(naming_style)
        bag: dict[str, Candidate] = {}

        strategies = {
            "descriptive": self._descriptive,
            "compound": self._compounds,
            "invented": self._invented,
            "evocative": self._evocative,
            "suggestive": self._suggestive,
        }
        weights = STYLE_WEIGHTS[style]
        # Hard quotas so one prolific method cannot dominate the bag.
        quotas = {m: max(1, int(round(count * w))) for m, w in weights.items()}
        # Keep total close to requested count
        while sum(quotas.values()) > count:
            richest = max(quotas, key=quotas.get)
            if quotas[richest] <= 1:
                break
            quotas[richest] -= 1
        while sum(quotas.values()) < count:
            richest = max(weights, key=weights.get)
            quotas[richest] += 1

        method_counts = {m: 0 for m in quotas}

        def _accept(cand: Candidate) -> bool:
            key = compact_key(cand.name)
            if not key or key in bag:
                return False
            result = filter_name(cand.name, max_length=max_length)
            if not result.ok:
                return False
            cand.pronunciation = pronounce_guide(cand.name)
            bag[key] = cand
            method_counts[cand.method] = method_counts.get(cand.method, 0) + 1
            return True

        # Fill each method up to its quota (overgenerate within the method).
        for method, quota in quotas.items():
            attempts = 0
            while method_counts.get(method, 0) < quota and attempts < quota * 8:
                attempts += 1
                batch = strategies[method](
                    category, keywords, tone, max_length, batch=24, style=style
                )
                for cand in batch:
                    if method_counts.get(method, 0) >= quota:
                        break
                    _accept(cand)

        # Top up shortfalls with brandable-friendly inventeds / evocatives
        fillers = ["invented", "evocative", "compound", "suggestive", "descriptive"]
        guard = 0
        while len(bag) < count and guard < count * 10:
            guard += 1
            method = fillers[guard % len(fillers)]
            for cand in strategies[method](
                category, keywords, tone, max_length, batch=20, style=style
            ):
                if _accept(cand) and len(bag) >= count:
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

    def _pool(
        self,
        keywords: list[str],
        tone: str,
        *,
        inject_keywords: bool = True,
    ) -> dict[str, list[str]]:
        v = self.vocab
        nouns = self._words(v.get("nouns"))
        verbs = self._words(v.get("verbs"))
        benefits = self._words(v.get("benefits"))
        modifiers = self._words(v.get("modifiers"))

        if inject_keywords:
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

    def _abstract_pool(self, tone: str) -> dict[str, list[str]]:
        roots = self._words(self.vocab.get("abstract_roots"))
        lefts = self._words(self.vocab.get("evocative_left"))
        rights = self._words(self.vocab.get("evocative_right"))
        tone_key = tone.lower()
        for label, words in (self.vocab.get("tone_words") or {}).items():
            if label in tone_key:
                for w in self._words(words):
                    if w not in lefts:
                        lefts.append(w)
        self.rng.shuffle(roots)
        self.rng.shuffle(lefts)
        self.rng.shuffle(rights)
        return {"roots": roots, "lefts": lefts, "rights": rights}

    def _descriptive(
        self,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        batch: int = 80,
        style: str = "brandable",
    ) -> list[Candidate]:
        pool = self._pool(keywords, tone, inject_keywords=True)
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
        style: str = "brandable",
    ) -> list[Candidate]:
        # Brandable compounds prefer abstract roots over product keywords.
        if style == "brandable":
            abs_pool = self._abstract_pool(tone)
            lefts = abs_pool["roots"][:40] + abs_pool["lefts"][:20]
            rights = abs_pool["rights"][:30] + abs_pool["roots"][:20]
        elif style == "balanced":
            pool = self._pool(keywords, tone, inject_keywords=False)
            abs_pool = self._abstract_pool(tone)
            lefts = abs_pool["roots"][:20] + pool["nouns"][:20] + pool["verbs"][:10]
            rights = abs_pool["rights"][:20] + pool["modifiers"][:15] + pool["benefits"][:15]
        else:
            pool = self._pool(keywords, tone, inject_keywords=True)
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

    def _evocative(
        self,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        batch: int = 100,
        style: str = "brandable",
    ) -> list[Candidate]:
        """Feeling / imagery blends with no product keywords (Stripe, Slack energy)."""
        abs_pool = self._abstract_pool(tone)
        endings = self._words(self.syllables.get("endings")) or ["a", "o", "ora", "ly", "en"]
        out: list[Candidate] = []
        for _ in range(batch):
            mode = self.rng.random()
            if mode < 0.4 and abs_pool["roots"]:
                # Soften / twist a single abstract root
                root = self.rng.choice(abs_pool["roots"])
                end = self.rng.choice(endings)
                if root.endswith(end[:1]):
                    name = root[:1].upper() + root[1:]
                else:
                    name = root[:1].upper() + root[1:] + end
            elif mode < 0.75:
                left = self.rng.choice(abs_pool["lefts"] or abs_pool["roots"])
                right = self.rng.choice(abs_pool["rights"] or abs_pool["roots"])
                if left == right:
                    continue
                name = _title_join([left, right])
            else:
                # Blend two short roots
                a = self.rng.choice(abs_pool["roots"])
                b = self.rng.choice(abs_pool["roots"])
                if a == b:
                    continue
                cut = max(2, min(len(a), len(b) // 2 + 1))
                blend = a[:cut] + b[-(len(b) - 1) :]
                name = blend[:1].upper() + blend[1:]
            name = normalize_name(name)
            if not name or len(compact_key(name)) > max_length:
                continue
            out.append(Candidate(name=name, pronunciation="", method="evocative"))
        return out

    def _invented(
        self,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        batch: int = 120,
        style: str = "brandable",
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

    def _suggestive(
        self,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        batch: int = 80,
        style: str = "brandable",
    ) -> list[Candidate]:
        """Hints at the space without spelling out the product (modified stems)."""
        stems_map = self.vocab.get("category_stems", {})
        stems: list[str] = []
        cat = category.lower()
        # Brandable: lighter stem use, mix with abstract roots
        if style == "brandable":
            abs_roots = self._words(self.vocab.get("abstract_roots"))
            for key, values in stems_map.items():
                if key in cat or any(str(k).lower() in cat for k in keywords):
                    stems.extend(self._words(values)[:4])
            stems = stems[:8] + abs_roots[:20]
        else:
            for key, values in stems_map.items():
                if key in cat or any(str(k).lower() in cat for k in keywords):
                    stems.extend(self._words(values))
            if not stems:
                for values in stems_map.values():
                    stems.extend(self._words(values))
        if not stems:
            stems = self._words(self.vocab.get("abstract_roots"))
        endings = self._words(self.syllables.get("endings")) or ["ora", "ivo", "a", "o", "lyn", "wise"]
        out: list[Candidate] = []
        for _ in range(batch):
            stem = self.rng.choice(stems)
            end = self.rng.choice(endings)
            if stem.endswith(end[:2]):
                end = self.rng.choice([e for e in endings if e != end] or [end])
            name = stem[:1].upper() + stem[1:] + end
            if len(compact_key(name)) > max_length:
                name = stem[:1].upper() + stem[1:] + end[:2]
            if len(compact_key(name)) > max_length:
                continue
            out.append(Candidate(name=name, pronunciation="", method="suggestive"))
        return out
