from __future__ import annotations

import itertools
import random
import re
from dataclasses import dataclass
from functools import lru_cache

from app.config import load_yaml, syllables_config, vocabulary_config
from app.services.brand_quality import brand_quality_ok, join_morphemes, title_name
from app.services.filter import compact_key, filter_name, normalize_name
from app.services.naming_style import STYLE_WEIGHTS, VALID_STYLES, normalize_naming_style
from app.services.preferences import PreferenceProfile, build_preference_profile, language_profile
from app.services.pronunciation import pronounce_guide
from app.services.real_words import is_real_word_candidate, real_word_lexicon, real_word_set

# Re-export for tests / callers
__all__ = ["Candidate", "NameGenerator", "STYLE_WEIGHTS", "VALID_STYLES", "normalize_naming_style"]


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


def _looks_like_compound(key: str, known: frozenset[str]) -> bool:
    """True when name splits into two lexicon halves (Basecamp / Mailchimp energy)."""
    if len(key) < 6:
        return False
    for i in range(3, min(9, len(key) - 2)):
        left, right = key[:i], key[i:]
        if 3 <= len(right) <= 8 and left in known and right in known:
            return True
    return False


@lru_cache
def _brand_lexicon() -> dict:
    return load_yaml("brand_lexicon.yaml")


class NameGenerator:
    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.vocab = vocabulary_config()
        self.syllables = syllables_config()
        self.lexicon = _brand_lexicon()
        self.real_words = real_word_lexicon()

    def generate(
        self,
        *,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        count: int,
        naming_style: str = "invented",
        preferences: PreferenceProfile | None = None,
        audience: str = "",
        liked_brands: str = "",
        avoid: str = "",
        primary_language: str = "en-global",
        primary_language_other: str = "",
    ) -> list[Candidate]:
        style = normalize_naming_style(naming_style)
        prefs = preferences or build_preference_profile(
            primary_language=primary_language,
            primary_language_other=primary_language_other,
            audience=audience,
            liked_brands=liked_brands,
            avoid=avoid,
        )
        self._prefs = prefs
        self._naming_style = style
        bag: dict[str, Candidate] = {}

        strategies = {
            "descriptive": self._descriptive,
            "compound": self._compounds,
            "invented": self._invented,
            "evocative": self._evocative,
            "suggestive": self._suggestive,
            "real_word": self._real_word,
        }
        weights = dict(STYLE_WEIGHTS[style])
        # Preference bias only for philosophies that mix methods.
        if style in {"invented", "descriptive"}:
            for method, mult in (prefs.style_bias or {}).items():
                if method in weights:
                    weights[method] *= float(mult)
        total_w = sum(weights.values()) or 1.0
        weights = {m: w / total_w for m, w in weights.items() if w > 0}

        quotas = {m: max(1, int(round(count * w))) for m, w in weights.items()}
        while sum(quotas.values()) > count:
            richest = max(quotas, key=quotas.get)
            if quotas[richest] <= 1:
                break
            quotas[richest] -= 1
        while sum(quotas.values()) < count:
            richest = max(weights, key=weights.get)
            quotas[richest] += 1

        eff_max = max_length
        if "short" in prefs.traits:
            eff_max = min(max_length, 8)
        if style == "compound":
            # Compounds need room (Basecamp / DigitalOcean).
            eff_max = max(eff_max, min(max_length, 14))

        method_counts = {m: 0 for m in quotas}
        if style in {"invented", "real_word", "compound"}:
            min_cred = 68.0
        else:
            min_cred = 54.0
        known_real = real_word_set()

        def _accept(cand: Candidate) -> bool:
            key = compact_key(cand.name)
            if not key or key in bag:
                return False
            avoid_hit = any(tok in key for tok in prefs.avoid_tokens if len(tok) >= 4)
            if avoid_hit:
                return False
            result = filter_name(cand.name, max_length=eff_max)
            if not result.ok:
                return False
            if style == "real_word":
                if not is_real_word_candidate(key, known_real):
                    return False
            if style == "compound":
                if cand.method != "compound":
                    return False
                # Must read as two joined concepts (Basecamp), not a soft invented single.
                halves = frozenset(
                    self._words(self.real_words.get("compound_left"))
                    + self._words(self.real_words.get("compound_right"))
                    + self._words(self.vocab.get("evocative_left"))
                    + self._words(self.vocab.get("evocative_right"))
                )
                if not _looks_like_compound(key, known_real | halves):
                    return False
            if cand.method == "descriptive":
                gate = 0.0 if style == "descriptive" else (48.0 if style == "invented" else 0.0)
            else:
                gate = min_cred
            if gate > 0:
                ok, _reason = brand_quality_ok(
                    cand.name, method=cand.method, min_score=gate
                )
                if not ok:
                    return False
            lang = self._lang()
            if style not in {"real_word", "compound"} and lang.get("prefer_vowel_endings") and key[-1] not in "aeiou":
                soft = self._words(lang.get("soft_endings")) or ["a", "o", "i", "u", "e"]
                softened = join_morphemes(key, self.rng.choice([s for s in soft if len(s) <= 2] or soft))
                if (
                    softened
                    and softened != key
                    and len(softened) <= eff_max
                    and softened[-1] in "aeiou"
                    and softened not in bag
                ):
                    soft_ok, _ = brand_quality_ok(
                        title_name(softened), method=cand.method, min_score=max(48.0, gate - 8)
                    )
                    if soft_ok and filter_name(title_name(softened), max_length=eff_max).ok:
                        cand.name = title_name(softened)
                        key = softened
                    else:
                        return False
                else:
                    return False
            cand.pronunciation = pronounce_guide(cand.name)
            bag[key] = cand
            method_counts[cand.method] = method_counts.get(cand.method, 0) + 1
            return True

        oversample = 40 if style in {"invented", "real_word", "compound"} else 12
        for method, quota in quotas.items():
            attempts = 0
            limit = quota * oversample
            while method_counts.get(method, 0) < quota and attempts < limit:
                attempts += 1
                batch = strategies[method](
                    category, keywords, tone, eff_max, batch=32, style=style
                )
                for cand in batch:
                    if method_counts.get(method, 0) >= quota:
                        break
                    _accept(cand)

        if style == "real_word":
            fillers = ["real_word"]
        elif style == "compound":
            fillers = ["compound"]
        elif style == "descriptive":
            fillers = ["descriptive", "suggestive", "compound"]
        else:
            fillers = ["evocative", "invented", "compound", "suggestive"]
        guard = 0
        while len(bag) < count and guard < count * 40:
            guard += 1
            method = fillers[guard % len(fillers)]
            for cand in strategies[method](
                category, keywords, tone, eff_max, batch=24, style=style
            ):
                if _accept(cand) and len(bag) >= count:
                    break

        return list(bag.values())

    def _lang(self) -> dict:
        prefs = getattr(self, "_prefs", None)
        if not prefs:
            return language_profile("en-global")
        return language_profile(prefs.language)

    def _lex_words(self, *keys: str) -> list[str]:
        out: list[str] = []
        for key in keys:
            out.extend(self._words(self.lexicon.get(key)))
        return out

    def _soft_endings(self) -> list[str]:
        lang = self._lang()
        soft = self._words(lang.get("soft_endings"))
        lex = self._words(self.lexicon.get("soft_endings"))
        syl = self._words(self.syllables.get("endings"))
        merged = soft + lex + syl
        # Never glue product endings onto brandables.
        return [e for e in self._words(merged) if e not in {
            "nest", "place", "home", "room", "proof", "look", "live", "view", "fit", "sure", "wise",
        }]

    def _syllable_parts(self) -> tuple[list[str], list[str], list[str], list[str]]:
        lang = self._lang()
        onsets = self._words(self.lexicon.get("brand_onsets")) or self._words(self.syllables.get("onsets"))
        nuclei = self._words(self.lexicon.get("brand_nuclei")) or self._words(self.syllables.get("nuclei"))
        codas = self._words(self.lexicon.get("brand_codas")) or self._words(self.syllables.get("codas"))
        endings = self._soft_endings()

        prefer_onsets = self._words(lang.get("onset_prefer"))
        if prefer_onsets:
            onsets = [o for o in onsets if o in prefer_onsets] or prefer_onsets
        prefer_nuclei = self._words(lang.get("nucleus_prefer"))
        if prefer_nuclei:
            nuclei = [n for n in nuclei if n in prefer_nuclei] or prefer_nuclei

        max_cluster = int(lang.get("max_onset_cluster", 2))
        if max_cluster <= 0:
            onsets = [o for o in onsets if len(o) == 1] or ["m", "n", "k", "t", "s"]
        elif max_cluster == 1:
            onsets = [o for o in onsets if len(o) == 1] or onsets

        if lang.get("forbid_coda"):
            codas = [""]
        return onsets, nuclei, codas, endings

    @staticmethod
    def _words(values: list | None) -> list[str]:
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
        # Prefer curated brand lexicon roots.
        roots = self._words(
            roots
            + self._lex_words(
                "short_punchy",
                "soft_brandables",
                "classical_roots",
                "nature_roots",
                "science_roots",
                "architecture_roots",
                "geography_roots",
                "astronomy_roots",
                "mythology_roots",
            )
        )
        lefts = self._words(self.vocab.get("evocative_left"))
        # Keep compound/evocative rights as real words — never bare suffix particles.
        rights = self._words(self.vocab.get("evocative_right"))
        tone_key = tone.lower()
        for label, words in (self.vocab.get("tone_words") or {}).items():
            if label in tone_key:
                for w in self._words(words):
                    if w not in lefts:
                        lefts.append(w)
        prefs = getattr(self, "_prefs", None)
        traits = prefs.traits if prefs else set()
        if "warm" in traits or "friendly" in traits:
            for w in ("warm", "kind", "soft", "calm", "bright"):
                if w not in lefts:
                    lefts.append(w)
        if "premium" in traits or "sophisticated" in traits:
            for w in ("meridian", "sable", "ivory", "zenith", "atlas"):
                if w not in roots:
                    roots.append(w)
        if "playful" in traits:
            for w in ("spark", "ripple", "glow", "zest"):
                if w not in roots:
                    roots.append(w)
        self.rng.shuffle(roots)
        self.rng.shuffle(lefts)
        self.rng.shuffle(rights)
        return {"roots": roots, "lefts": lefts, "rights": rights}

    def _real_word_pool(self, tone: str) -> list[str]:
        """Curated real words only — never soft inventeds like velora/norva."""
        pools = [
            self._words(self.real_words.get(k))
            for k in (
                "punchy",
                "architecture",
                "nature",
                "science",
                "astronomy",
                "design",
                "navigation",
                "commerce",
                "materials",
                "qualities",
                "motion",
                "geography",
                "classical",
                "soft_real",
            )
        ]
        words = self._words([w for pool in pools for w in pool])
        tone_key = tone.lower()
        # Mild tone affinity: premium → classical/materials; warm → nature; tech → science.
        boost: list[str] = []
        if any(t in tone_key for t in ("premium", "sophisticated", "elegant", "luxury")):
            boost.extend(self._words(self.real_words.get("materials")))
            boost.extend(self._words(self.real_words.get("classical")))
            boost.extend(self._words(self.real_words.get("qualities")))
        if any(t in tone_key for t in ("warm", "friendly", "calm", "soft")):
            boost.extend(self._words(self.real_words.get("nature")))
            boost.extend(self._words(self.real_words.get("soft_real")))
        if any(t in tone_key for t in ("tech", "modern", "bold", "sharp")):
            boost.extend(self._words(self.real_words.get("science")))
            boost.extend(self._words(self.real_words.get("punchy")))
            boost.extend(self._words(self.real_words.get("architecture")))
        # Weight boosts by repeating once in the pool.
        words = self._words(words + boost)
        self.rng.shuffle(words)
        return words

    def _real_word(
        self,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        batch: int = 100,
        style: str = "invented",
    ) -> list[Candidate]:
        """Intact dictionary words as brands — Stripe / Linear / Cursor energy."""
        del category, keywords, style  # brief context used elsewhere; pool is curated
        singles = [w for w in self._real_word_pool(tone) if 4 <= len(w) <= max_length]
        lefts = self._words(self.real_words.get("compound_left"))
        rights = self._words(self.real_words.get("compound_right"))
        out: list[Candidate] = []
        for _ in range(batch):
            mode = self.rng.random()
            # ~82% intact single real words; ~18% two-real-word compounds.
            if mode < 0.82 or not lefts or not rights:
                if not singles:
                    continue
                name = title_name(self.rng.choice(singles))
            else:
                a = self.rng.choice(lefts)
                b = self.rng.choice(rights)
                if a == b:
                    continue
                joined = _title_join([a, b])
                if not (5 <= len(compact_key(joined)) <= max_length):
                    continue
                # Both halves must be authentic words (already from curated lists).
                name = joined
            name = normalize_name(name)
            if not name or len(compact_key(name)) > max_length:
                continue
            out.append(Candidate(name=name, pronunciation="", method="real_word"))
        return out

    def _descriptive(
        self,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        batch: int = 80,
        style: str = "invented",
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
        style: str = "invented",
    ) -> list[Candidate]:
        """Two familiar concepts joined — Basecamp / Mailchimp / GitHub energy."""
        del category  # entity/brief handled upstream
        if style == "compound":
            # Pure compound philosophy: real/evocative word pairs only.
            lefts = self._words(
                self.real_words.get("compound_left")
                or []
            ) + self._words(self.vocab.get("evocative_left"))
            rights = self._words(
                self.real_words.get("compound_right")
                or []
            ) + self._words(self.vocab.get("evocative_right"))
            # Also allow punchy real words as either half.
            punchy = [w for w in real_word_set() if 3 <= len(w) <= 6]
            lefts = self._words(lefts + punchy[:40])
            rights = self._words(rights + punchy[:40])
            self.rng.shuffle(lefts)
            self.rng.shuffle(rights)
        elif style == "invented":
            abs_pool = self._abstract_pool(tone)
            lefts = abs_pool["roots"][:50] + abs_pool["lefts"][:20]
            rights = [
                r
                for r in (abs_pool["rights"][:40] + abs_pool["roots"][:20])
                if len(r) <= 6
            ]
        elif style == "descriptive":
            pool = self._pool(keywords, tone, inject_keywords=True)
            lefts = pool["nouns"][:40] + pool["verbs"][:20]
            rights = pool["modifiers"][:30] + pool["benefits"][:20] + pool["nouns"][:20]
        else:
            abs_pool = self._abstract_pool(tone)
            pool = self._pool(keywords, tone, inject_keywords=False)
            lefts = abs_pool["roots"][:20] + pool["nouns"][:20]
            rights = abs_pool["rights"][:20] + pool["modifiers"][:15]

        out: list[Candidate] = []
        pairs = list(itertools.product(lefts[:36], rights[:36]))
        self.rng.shuffle(pairs)
        for a, b in pairs[:batch]:
            if a.lower() == b.lower():
                continue
            # Compound philosophy: always readable TitleCase join (BaseCamp → Basecamp).
            if style == "compound":
                name = _title_join([a, b])
            elif style == "invented" and (len(a) + len(b) > 9 or a[-1:].lower() in "aeiou"):
                key = join_morphemes(a, b)
                name = title_name(key)
            else:
                name = _title_join([a, b])
            key = compact_key(name)
            if len(key) > max_length or len(key) < 6:
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
        style: str = "invented",
    ) -> list[Candidate]:
        """Feeling / imagery from real roots — Stripe / Slack / Notion energy."""
        abs_pool = self._abstract_pool(tone)
        # Prefer intact curated roots; light compounds only from real word pairs.
        real_rights = [r for r in abs_pool["rights"] if 3 <= len(r) <= 5]
        out: list[Candidate] = []
        for _ in range(batch):
            mode = self.rng.random()
            if style == "invented" and mode < 0.78 and abs_pool["roots"]:
                name = title_name(self.rng.choice(abs_pool["roots"]))
            elif mode < 0.55 and abs_pool["roots"]:
                name = title_name(self.rng.choice(abs_pool["roots"]))
            elif mode < 0.88 and abs_pool["roots"] and real_rights:
                left = self.rng.choice(abs_pool["lefts"] or abs_pool["roots"])
                right = self.rng.choice(real_rights)
                if left == right or len(left) + len(right) > max_length + 1:
                    continue
                # Keep readable compounds (ClearPath), avoid TideSh-style scraps
                if style == "invented":
                    name = _title_join([left, right])
                else:
                    name = title_name(join_morphemes(left, right))
            else:
                a = self.rng.choice(abs_pool["roots"])
                b = self.rng.choice(abs_pool["roots"])
                if a == b or len(a) < 4 or len(b) < 4:
                    continue
                if style == "invented":
                    continue  # no scrap blends in brandable mode
                key = join_morphemes(a[:4], b[-3:])
                if not (5 <= len(key) <= max_length):
                    continue
                name = title_name(key)
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
        style: str = "invented",
    ) -> list[Candidate]:
        """Curated brandable stems from linguistic roots — never syllable soup."""
        lang = self._lang()
        pool = [
            w
            for w in self._lex_words(
                "short_punchy",
                "soft_brandables",
                "classical_roots",
                "nature_roots",
                "science_roots",
                "architecture_roots",
                "geography_roots",
                "astronomy_roots",
                "mythology_roots",
            )
            if 4 <= len(w) <= max_length
        ]
        if not pool:
            pool = self._words(self.vocab.get("abstract_roots"))
        out: list[Candidate] = []

        # Non-brandable styles may still do light phoneme coinage.
        onsets, nuclei, _codas, _endings = self._syllable_parts()

        for _ in range(batch):
            if style == "invented" or self.rng.random() < 0.85:
                key = self.rng.choice(pool)
            else:
                pattern = self.rng.choice(["CVC", "CVCV"])
                built: list[str] = []
                for i, ch in enumerate(pattern):
                    if ch == "C":
                        if i == 0 and onsets:
                            built.append(self.rng.choice([o for o in onsets if len(o) <= 2] or onsets))
                        else:
                            built.append(self.rng.choice([o for o in onsets if len(o) == 1] or list("nrlmts")))
                    else:
                        built.append(self.rng.choice(nuclei) if nuclei else "a")
                key = "".join(built)

            if not key or len(key) > max_length or len(key) < 4:
                continue
            bad = any(c and c in key for c in (lang.get("avoid_clusters") or ()))
            if bad:
                continue
            name = title_name(normalize_name(key))
            if name:
                out.append(Candidate(name=name, pronunciation="", method="invented"))
        return out

    def _suggestive(
        self,
        category: str,
        keywords: list[str],
        tone: str,
        max_length: int,
        batch: int = 80,
        style: str = "invented",
    ) -> list[Candidate]:
        """Hints at the space without spelling out the product."""
        stems_map = self.vocab.get("category_stems", {})
        stems: list[str] = []
        cat = category.lower()
        abs_roots = self._words(self.vocab.get("abstract_roots")) + self._lex_words(
            "classical_roots", "nature_roots", "science_roots"
        )
        if style == "invented":
            # Almost no product stems — suggestives should still feel brandable.
            for key, values in stems_map.items():
                if key in cat or any(str(k).lower() in cat for k in keywords):
                    stems.extend(self._words(values)[:2])
            stems = stems[:3] + abs_roots[:40]
        else:
            for key, values in stems_map.items():
                if key in cat or any(str(k).lower() in cat for k in keywords):
                    stems.extend(self._words(values))
            if not stems:
                for values in stems_map.values():
                    stems.extend(self._words(values))
        if not stems:
            stems = abs_roots
        # Prefer intact roots; avoid *ly product inventeds that sound AI-generated.
        endings = [
            e
            for e in (self._soft_endings() or ["a", "o", "el", "en", "ia", "on"])
            if e not in {"ly", "ify"}
        ] or ["a", "o", "el", "en", "on"]
        out: list[Candidate] = []
        for _ in range(batch):
            stem = self.rng.choice(stems)
            if style == "invented" or self.rng.random() < 0.55:
                # Prefer strong intact roots over glued endings.
                key = stem
            else:
                end = self.rng.choice(endings)
                key = join_morphemes(stem, end)
            if len(key) > max_length:
                key = stem[:max_length]
            if len(key) < 4 or len(key) > max_length:
                continue
            out.append(Candidate(name=title_name(key), pronunciation="", method="suggestive"))
        return out
