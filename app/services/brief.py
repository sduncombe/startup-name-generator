"""Deterministic inference of generator inputs from a natural-language brand brief."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.naming_entity import get_naming_entity, normalize_naming_entity
from app.services.preferences import (
    build_preference_profile,
    language_display,
    normalize_language,
)

STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "for",
    "with",
    "that",
    "this",
    "these",
    "those",
    "from",
    "into",
    "onto",
    "over",
    "under",
    "before",
    "after",
    "about",
    "above",
    "below",
    "between",
    "through",
    "during",
    "without",
    "within",
    "along",
    "across",
    "who",
    "whom",
    "whose",
    "which",
    "what",
    "when",
    "where",
    "why",
    "how",
    "are",
    "is",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "must",
    "can",
    "to",
    "of",
    "in",
    "on",
    "at",
    "by",
    "as",
    "it",
    "its",
    "their",
    "them",
    "they",
    "we",
    "you",
    "your",
    "our",
    "my",
    "me",
    "i",
    "people",
    "lets",
    "let",
    "using",
    "use",
    "used",
    "like",
    "likes",
    "want",
    "wants",
    "need",
    "needs",
    "help",
    "helps",
    "make",
    "makes",
    "building",
    "build",
    "built",
    "website",
    "app",
    "platform",
    "product",
    "service",
    "company",
    "startup",
    "tool",
    "software",
    "problem",
    "problems",
    "solving",
    "solve",
    "solved",
    "struggle",
    "struggles",
    "struggling",
    "spend",
    "spends",
    "spending",
    "know",
    "knows",
    "time",
    "too",
    "much",
    "many",
    "hard",
    "difficult",
    "unable",
    "cannot",
    "dont",
    "doesnt",
}

TONE_HINTS = {
    "airbnb": "Warm, welcoming, trustworthy",
    "notion": "Calm, modern, flexible",
    "houzz": "Home-focused, visual, aspirational",
    "apple": "Premium, simple, precise",
    "stripe": "Clear, modern, confident",
    "figma": "Creative, collaborative, sharp",
    "slack": "Friendly, energetic, clear",
    "linear": "Minimal, precise, product-led",
    "spotify": "Bold, cultural, expressive",
    "nike": "Energetic, bold, motivational",
}


@dataclass
class InferredBrief:
    category: str
    keywords: list[str]
    tone: str
    brand_brief: str
    problem: str
    audience: str
    liked_brands: str
    avoid: str
    naming_entity: str = ""
    naming_entity_label: str = ""
    primary_language: str = "en-global"
    primary_language_other: str = ""
    preference_traits: list[str] | None = None

    @property
    def building(self) -> str:
        """Backward-compatible alias for older call sites."""
        return self.problem


def compose_brand_brief(
    *,
    problem: str = "",
    building: str = "",
    audience: str = "",
    liked_brands: str = "",
    avoid: str = "",
    naming_entity: str = "",
    primary_language: str = "en-global",
    primary_language_other: str = "",
) -> str:
    problem_text = (problem or building).strip()
    entity = get_naming_entity(naming_entity)
    parts: list[str] = []
    if entity:
        parts.append(f"What we're naming: {entity.label}")
        parts.append(entity.framing)
    parts.append(f"Problem we're solving: {problem_text}")
    parts.append(f"Primary language: {language_display(primary_language, primary_language_other)}")
    if audience.strip():
        parts.append(f"Target audience: {audience.strip()}")
    if liked_brands.strip():
        parts.append(
            "Brands whose naming style we admire (extract patterns — never copy the names): "
            + liked_brands.strip()
        )
        parts.append(
            "Desired naming characteristics from those brands: short, memorable, "
            "commercially believable, easy to pronounce, easy to spell after hearing, "
            "timeless, not trendy, not AI-generated."
        )
    if avoid.strip():
        parts.append(f"Hard avoid (do not generate names that violate these): {avoid.strip()}")
    if entity and entity.guidance:
        parts.append(f"Entity naming rules: {entity.guidance}")
    return "\n".join(parts)


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]{1,}", text.lower())
    out: list[str] = []
    for w in words:
        w = w.strip("'-")
        if len(w) < 3 or w in STOPWORDS:
            continue
        out.append(w)
    return out


def _unique(items: list[str], *, limit: int = 12) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def infer_brief(
    *,
    problem: str = "",
    building: str = "",
    audience: str = "",
    liked_brands: str = "",
    avoid: str = "",
    naming_entity: str = "",
    primary_language: str = "en-global",
    primary_language_other: str = "",
    primary_market: str | None = None,  # legacy ignored
    primary_market_other: str | None = None,  # legacy ignored
    category: str | None = None,
    keywords: list[str] | None = None,
    tone: str | None = None,
) -> InferredBrief:
    problem = (problem or building or "").strip()
    audience = (audience or "").strip()
    liked_brands = (liked_brands or "").strip()
    avoid = (avoid or "").strip()
    entity_code = normalize_naming_entity(naming_entity)
    entity = get_naming_entity(entity_code)
    lang, lang_other = normalize_language(primary_language, primary_language_other)
    prefs = build_preference_profile(
        primary_language=lang,
        primary_language_other=lang_other,
        audience=audience,
        liked_brands=liked_brands,
        avoid=avoid,
    )

    if not problem and category:
        problem = category.strip()

    cat = (category or "").strip() or problem.split(".")[0].strip()[:120] or "Brand"
    if len(cat) > 160:
        cat = cat[:157].rstrip() + "…"

    kw = list(keywords or [])
    if not kw:
        kw = _unique(_tokens(problem) + _tokens(audience), limit=10)
    if not kw:
        kw = ["brand", "product", "app"]

    tone_val = (tone or "").strip()
    if not tone_val:
        tones: list[str] = []
        for brand in re.split(r"[,;/]| and ", liked_brands):
            hint = TONE_HINTS.get(brand.strip().lower())
            if hint:
                tones.append(hint)
        # Audience / trait-driven tone (materially affects generator pools)
        if "warm" in prefs.traits or "friendly" in prefs.traits:
            tones.append("Warm, friendly, approachable")
        if "premium" in prefs.traits or "sophisticated" in prefs.traits:
            tones.append("Premium, precise, minimal")
        if "playful" in prefs.traits:
            tones.append("Playful, energetic")
        if "calm" in prefs.traits or "soft" in prefs.traits:
            tones.append("Calm, soft")
        if "tech_ai" in prefs.avoid_traits or "enterprise" in prefs.avoid_traits:
            tones.append("Human, consumer-friendly")
        tone_val = "; ".join(_unique(tones, limit=3)) or "Friendly, modern, trustworthy"

    brief = compose_brand_brief(
        problem=problem or cat,
        audience=audience,
        liked_brands=liked_brands,
        avoid=avoid,
        naming_entity=entity_code,
        primary_language=lang,
        primary_language_other=lang_other,
    )
    return InferredBrief(
        category=cat,
        keywords=kw,
        tone=tone_val,
        brand_brief=brief,
        problem=problem or cat,
        audience=audience,
        liked_brands=liked_brands,
        avoid=avoid,
        naming_entity=entity_code,
        naming_entity_label=entity.label if entity else "",
        primary_language=lang,
        primary_language_other=lang_other,
        preference_traits=sorted(prefs.traits),
    )


METHOD_DIRECTIONS = {
    "descriptive": ("Clear & descriptive", "Straightforward names that say what the product does."),
    "compound": ("Familiar compounds", "Two everyday ideas joined into something ownable."),
    "invented": ("Invented & distinctive", "Fresh coinages that still feel pronounceable."),
    "evocative": ("Evocative & abstract", "Feeling and imagery first. Meaning comes from the brand."),
    "suggestive": ("Suggestive twists", "Hints at the space without spelling out the product."),
    "real_word": ("Familiar brands", "Existing words used in a new context — memorable, ownable, commercially believable."),
    "modified_category": ("Suggestive twists", "Hints at the space without spelling out the product."),
    "modified": ("Suggestive twists", "Hints at the space without spelling out the product."),
    "llm": ("Creative AI directions", "Names brainstormed from your brief."),
}


def direction_for_method(method: str) -> tuple[str, str]:
    return METHOD_DIRECTIONS.get(method, ("Other ideas", "Additional candidates from the generator."))
