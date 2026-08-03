"""Deterministic inference of generator inputs from a natural-language brand brief."""

from __future__ import annotations

import re
from dataclasses import dataclass

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
    building: str
    audience: str
    liked_brands: str
    avoid: str


def compose_brand_brief(
    *,
    building: str,
    audience: str = "",
    liked_brands: str = "",
    avoid: str = "",
) -> str:
    parts = [f"What we're building: {building.strip()}"]
    if audience.strip():
        parts.append(f"Who it's for: {audience.strip()}")
    if liked_brands.strip():
        parts.append(f"Brands we like: {liked_brands.strip()}")
    if avoid.strip():
        parts.append(f"Avoid: {avoid.strip()}")
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
    building: str,
    audience: str = "",
    liked_brands: str = "",
    avoid: str = "",
    category: str | None = None,
    keywords: list[str] | None = None,
    tone: str | None = None,
) -> InferredBrief:
    building = (building or "").strip()
    audience = (audience or "").strip()
    liked_brands = (liked_brands or "").strip()
    avoid = (avoid or "").strip()

    if not building and category:
        building = category.strip()

    cat = (category or "").strip() or building.split(".")[0].strip()[:120] or "Consumer product"
    if len(cat) > 160:
        cat = cat[:157].rstrip() + "…"

    kw = list(keywords or [])
    if not kw:
        kw = _unique(_tokens(building) + _tokens(audience), limit=10)
    if not kw:
        kw = ["brand", "home", "app"]

    tone_val = (tone or "").strip()
    if not tone_val:
        tones: list[str] = []
        for brand in re.split(r"[,;/]| and ", liked_brands):
            hint = TONE_HINTS.get(brand.strip().lower())
            if hint:
                tones.append(hint)
        if "premium" in avoid.lower() or "luxury" in liked_brands.lower():
            tones.append("Approachable, not luxury-coded")
        if any(x in avoid.lower() for x in ("ai", "enterprise", "corporate")):
            tones.append("Human, consumer-friendly")
        tone_val = "; ".join(_unique(tones, limit=3)) or "Friendly, modern, trustworthy"

    brief = compose_brand_brief(
        building=building or cat,
        audience=audience,
        liked_brands=liked_brands,
        avoid=avoid,
    )
    return InferredBrief(
        category=cat,
        keywords=kw,
        tone=tone_val,
        brand_brief=brief,
        building=building or cat,
        audience=audience,
        liked_brands=liked_brands,
        avoid=avoid,
    )


METHOD_DIRECTIONS = {
    "descriptive": ("Clear & descriptive", "Straightforward names that say what the product does."),
    "compound": ("Familiar compounds", "Two everyday ideas joined into something ownable."),
    "invented": ("Invented & distinctive", "Fresh coinages that still feel pronounceable."),
    "evocative": ("Evocative & abstract", "Feeling and imagery first. Meaning comes from the brand."),
    "suggestive": ("Suggestive twists", "Hints at the space without spelling out the product."),
    "modified_category": ("Suggestive twists", "Hints at the space without spelling out the product."),
    "modified": ("Suggestive twists", "Hints at the space without spelling out the product."),
    "llm": ("Creative AI directions", "Names brainstormed from your brief."),
}


def direction_for_method(method: str) -> tuple[str, str]:
    return METHOD_DIRECTIONS.get(method, ("Other ideas", "Additional candidates from the generator."))
