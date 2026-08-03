from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import httpx

from app.config import get_settings
from app.services.naming_entity import NamingEntity, get_naming_entity

logger = logging.getLogger(__name__)

PROVIDERS = ("openai", "anthropic", "xai", "gemini")

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5",
    "xai": "grok-2-latest",
    "gemini": "gemini-2.0-flash",
}


@dataclass
class LlmCredentials:
    """Ephemeral per-request credentials. Never persist or log."""

    provider: str
    api_key: str
    model: str = ""


@dataclass
class LlmName:
    name: str
    direction: str = ""
    why: str = ""
    tier: str = ""


@dataclass
class LlmGenerationResult:
    directions: list[dict[str, str]] = field(default_factory=list)
    names: list[LlmName] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    raw_text: str = ""


class LlmError(RuntimeError):
    pass


def normalize_provider(provider: str | None) -> str:
    p = (provider or "").strip().lower()
    if p in {"openai_compatible"}:
        return "openai"
    return p


def resolve_credentials(
    *,
    request_provider: str | None = None,
    request_api_key: str | None = None,
    request_model: str | None = None,
) -> LlmCredentials | None:
    """
    Prefer BYOK from the request. Optionally allow server env keys only when
    ALLOW_SERVER_LLM_KEYS=true (private self-host). Public deployments leave
    that off and leave env keys empty: no fallback to host credentials.
    """
    settings = get_settings()
    key = (request_api_key or "").strip()
    provider = normalize_provider(request_provider) or normalize_provider(settings.llm_provider)

    if key:
        if provider not in PROVIDERS:
            raise LlmError(
                f"Unsupported provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}"
            )
        model = (request_model or "").strip() or DEFAULT_MODELS.get(provider, "")
        return LlmCredentials(provider=provider, api_key=key, model=model)

    # Server keys only for explicit private deployments
    if not settings.allow_server_llm_keys:
        return None

    if provider == "anthropic" and (settings.anthropic_api_key or settings.llm_api_key):
        return LlmCredentials(
            provider="anthropic",
            api_key=(settings.anthropic_api_key or settings.llm_api_key),
            model=(request_model or settings.llm_model or DEFAULT_MODELS["anthropic"]),
        )
    if provider == "openai" and (settings.openai_api_key or settings.llm_api_key):
        return LlmCredentials(
            provider="openai",
            api_key=(settings.openai_api_key or settings.llm_api_key),
            model=(request_model or settings.llm_model or DEFAULT_MODELS["openai"]),
        )
    if provider == "xai" and (settings.xai_api_key or settings.llm_api_key):
        return LlmCredentials(
            provider="xai",
            api_key=(settings.xai_api_key or settings.llm_api_key),
            model=(request_model or settings.llm_model or DEFAULT_MODELS["xai"]),
        )
    if provider == "gemini" and (settings.gemini_api_key or settings.llm_api_key):
        return LlmCredentials(
            provider="gemini",
            api_key=(settings.gemini_api_key or settings.llm_api_key),
            model=(request_model or settings.llm_model or DEFAULT_MODELS["gemini"]),
        )
    return None


def llm_status() -> dict:
    settings = get_settings()
    return {
        "byok_required": not settings.allow_server_llm_keys,
        "allow_server_llm_keys": bool(settings.allow_server_llm_keys),
        "providers": list(PROVIDERS),
        "default_models": dict(DEFAULT_MODELS),
        # Never reveal whether server keys exist in public mode
        "server_keys_enabled": bool(settings.allow_server_llm_keys),
    }


async def generate_names_from_brief(
    *,
    category: str,
    keywords: list[str],
    tone: str,
    brand_brief: str,
    max_length: int,
    credentials: LlmCredentials,
    count: int | None = None,
    naming_style: str = "invented",
    naming_entity: str = "",
    liked_brands: str = "",
    avoid: str = "",
) -> LlmGenerationResult:
    if not brand_brief.strip():
        return LlmGenerationResult()
    if not credentials.api_key:
        raise LlmError("AI generation requires your own API key (BYOK).")

    settings = get_settings()
    target = count or settings.llm_name_count
    entity = get_naming_entity(naming_entity)
    # Entity rules can override the form max length (local retailers need room).
    effective_max = max(max_length, entity.max_length) if entity else max_length
    prompt = _build_prompt(
        category=category,
        keywords=keywords,
        tone=tone,
        brand_brief=brand_brief,
        max_length=effective_max,
        count=target,
        naming_style=naming_style,
        entity=entity,
        liked_brands=liked_brands,
        avoid=avoid,
    )

    provider = credentials.provider
    model = credentials.model or DEFAULT_MODELS.get(provider, "")
    try:
        if provider == "anthropic":
            text = await _call_anthropic(prompt, api_key=credentials.api_key, model=model)
        elif provider == "openai":
            text = await _call_openai_compatible(
                prompt,
                api_key=credentials.api_key,
                model=model,
                base_url=settings.openai_base_url or "https://api.openai.com/v1",
            )
        elif provider == "xai":
            text = await _call_openai_compatible(
                prompt,
                api_key=credentials.api_key,
                model=model,
                base_url=settings.xai_base_url or "https://api.x.ai/v1",
            )
        elif provider == "gemini":
            text = await _call_gemini(prompt, api_key=credentials.api_key, model=model)
        else:
            raise LlmError(f"Unsupported provider: {provider}")
    except LlmError:
        raise
    except Exception as exc:  # noqa: BLE001
        # Do not include request headers/key material in logs
        logger.warning("LLM provider call failed provider=%s error=%s", provider, type(exc).__name__)
        raise LlmError(f"LLM provider error ({type(exc).__name__})") from None

    parsed = _parse_response(text, max_length=effective_max, entity=entity)
    parsed.provider = provider
    parsed.model = model
    parsed.raw_text = text
    return parsed


_STYLE_GUIDANCE = {
    "invented": (
        "INVENTED philosophy: Purpose-built brand names that still feel natural — "
        "Figma / Canva / Houzz / Vercel energy. Short, ownable, intentional coinages. "
        "Reject Roomly / Velora / syllable-soup inventeds. Prefer names that feel designed, not assembled."
    ),
    "real_word": (
        "REAL WORDS philosophy: Use ONLY existing English words as brands — "
        "Stripe / Cursor / Ramp / Atlas / Beacon / Canvas / Harbor / Vault. "
        "Do NOT invent or blend syllables. Familiar language in a new context."
    ),
    "compound": (
        "COMPOUND philosophy: Join two familiar concepts into one memorable brand — "
        "Basecamp / Mailchimp / DigitalOcean / GitHub / PandaMaven energy. "
        "Both halves should be real/recognizable words. Never glue random syllables. "
        "TitleCase single token (Basecamp), not spaced phrases, unless the entity allows spaces."
    ),
    "descriptive": (
        "DESCRIPTIVE philosophy: Names that immediately communicate what is offered — "
        "SurveyMonkey / PayPal energy — while still memorable and commercially believable. "
        "Not SEO keyword piles (HomeFurniture)."
    ),
}

_POSITIVE_PATTERN_EXAMPLES = (
    "Stripe, Cursor, Ramp, Mercury, Atlas, Canvas, Beacon, Vault, Harbor, Frame, "
    "Linear, Notion, Figma, Houzz"
)

_NEGATIVE_EXAMPLES = (
    "Roomly, Dwello, Bapaen, Bruksen, Booflar, Velora, Norva, HomeAI, Furnishly, VisionXR"
)


def _liked_pattern_block(liked_brands: str, entity_refs: str) -> str:
    brands = [b.strip() for b in re.split(r"[,;/]| and ", liked_brands or "") if b.strip()]
    if brands:
        listed = ", ".join(brands)
        source = f"the brands the user listed ({listed})"
    else:
        listed = entity_refs
        source = f"reference brands such as {listed}"
    return f"""Learn naming PATTERNS from {source} — do NOT imitate or remix those company names.

Extract characteristics like:
- short
- memorable
- commercially believable
- easy to pronounce once
- easy to spell after hearing
- subtle meaning (not literal product descriptions)
- visually clean
- timeless (not trendy)
- not AI-generated

Aim for names that feel inevitable rather than invented."""


def _avoid_block(avoid: str, *, naming_style: str) -> str:
    user_avoid = (avoid or "").strip()
    lines = [
        "Hard creative constraints — violate none of these:",
        "- Invented words that sound algorithmically assembled",
        "- Random syllable combinations (Bapaen / Booflar energy)",
        "- AI-sounding names",
        "- Generic startup suffixes: -ly, -ify, -io",
        "- Soft Latinate coinages: -ora, -iva, -ova (Velora / Norva)",
        f"- Negative examples (never return anything in this family): {_NEGATIVE_EXAMPLES}",
    ]
    if naming_style == "real_word":
        lines.append("- Any coined / blended / non-dictionary word")
    if naming_style == "compound":
        lines.append("- Single invented words; compounds must be two recognizable concepts joined")
    if naming_style == "invented":
        lines.append("- Literal product descriptions and keyword SEO piles")
    if user_avoid:
        lines.append(f"- USER AVOID LIST (absolute): {user_avoid}")
        lines.append(
            "  Treat every item above as a hard ban on substrings, roots, themes, and suffixes."
        )
    else:
        lines.append(
            "- Also avoid lazy category words unless the entity is a local/descriptive business: "
            "Vision, AI, VR, XR used as roots"
        )
    return "\n".join(lines)


def _build_prompt(
    *,
    category: str,
    keywords: list[str],
    tone: str,
    brand_brief: str,
    max_length: int,
    count: int,
    naming_style: str = "invented",
    entity: NamingEntity | None = None,
    liked_brands: str = "",
    avoid: str = "",
) -> str:
    from app.services.naming_style import normalize_naming_style

    kw = ", ".join(keywords) if keywords else "(none)"
    style = normalize_naming_style(naming_style)
    style_note = _STYLE_GUIDANCE.get(style) or _STYLE_GUIDANCE["invented"]

    if entity:
        framing = entity.framing
        refs = ", ".join(entity.reference_brands)
        entity_rules = entity.guidance
        entity_label = entity.label
        form_rules = []
        if entity.allow_spaces:
            form_rules.append("multi-word names are encouraged when they feel natural")
        if entity.allow_ampersand:
            form_rules.append("ampersands (&) are allowed")
        if entity.prefer_brandable:
            form_rules.append("favor short ownable brandables over literal phrases")
        else:
            form_rules.append(
                "favor clear, place-rooted or descriptive constructions over tech inventeds"
            )
        form_note = "; ".join(form_rules) if form_rules else "follow the entity framing"
        credibility_test = (
            f"Would I believe this is a real {entity_label.lower()} people would trust or buy from?"
        )
        allowed_chars = "letters"
        if entity.allow_spaces:
            allowed_chars += " / spaces"
        if entity.allow_ampersand:
            allowed_chars += " / &"
    else:
        framing = "The user is naming a brand."
        refs = "Stripe, Figma, Canva, Airbnb, Linear, Notion, Ramp, Vercel, Houzz"
        entity_rules = "Favor intentional, memorable, commercially believable names."
        entity_label = "brand"
        form_note = "prefer single-word brandables unless the brief clearly needs otherwise"
        credibility_test = "Would I believe this brand could succeed commercially?"
        allowed_chars = "letters"

    # Consultant shortlist: fewer names a founder might actually consider.
    ask = max(8, min(int(count), 20))
    liked_block = _liked_pattern_block(liked_brands, refs)
    avoid_block = _avoid_block(avoid, naming_style=style)

    return f"""You are an opinionated brand strategist at the level of Interbrand or Pentagram.

{framing}

You are NOT a random name generator. You create names that sound like companies someone would
naturally mention in conversation.

If a name would make someone say "that sounds like an AI startup generator made it," reject it
and invent another. Prefer names that feel inevitable rather than invented.

Do NOT check domains, conflicts, pronunciation, or scores; code handles that.

{liked_block}

Pattern energy to aim for (examples of feel — never copy these strings as outputs):
{_POSITIVE_PATTERN_EXAMPLES}

{avoid_block}

Quality bar — every returned name must pass ALL of these or be omitted:
1. "{credibility_test}"
2. "We use ____ at work every day" sounds natural.
3. You would put it on a pitch deck or storefront without embarrassment.
4. Someone might say: "That's actually a really good name."
Prefer fewer excellent names over padding with mediocre ones. Empty is better than sludge.

Return ONLY valid JSON (no markdown fences) with this shape:
{{
  "directions": [
    {{"name": "short direction label", "description": "one sentence"}}
  ],
  "names": [
    {{"name": "BrandName", "direction": "direction label", "why": "one short reason", "tier": "A"}}
  ]
}}

Hard requirements:
- The entity type is decisive. Names for a {entity_label} must NOT sound like a different category.
- {entity_rules}
- Form rules for this entity: {form_note}.
- Propose 3–5 distinct naming directions grounded in the brief AND the entity type.
- Propose at most {ask} candidate names total. Mark only true standouts tier "A".
- Naming style: {style}. {style_note}
- Easy to pronounce and spell after hearing once.
- Prefer up to {max_length} characters ({allowed_chars}). No numbers, no hyphens, no URLs.
- Prefer names that fit the Primary language in the brief.
- Never copy Brands we like or other major brands.
- Target audience should shape tone and sophistication.

Hint fields (may be incomplete; prefer the brief + constraints above):
Category hint: {category}
Keyword hint: {kw}
Tone hint: {tone}
Max length: {max_length}
Entity: {entity_label}

Brand brief:
{brand_brief.strip()}
"""


async def _call_anthropic(prompt: str, *, api_key: str, model: str) -> str:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 8192,
        "temperature": 0.72,
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
        )
    if resp.status_code >= 400:
        logger.warning("Anthropic error status=%s", resp.status_code)
        raise LlmError(f"Anthropic API error ({resp.status_code})")
    data = resp.json()
    parts = data.get("content") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    if not text.strip():
        raise LlmError("Anthropic returned empty content")
    return text


async def _call_openai_compatible(
    prompt: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> str:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "temperature": 0.72,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=body,
        )
    if resp.status_code >= 400:
        logger.warning("OpenAI-compatible error status=%s", resp.status_code)
        raise LlmError(f"Provider API error ({resp.status_code})")
    data = resp.json()
    text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    if not text.strip():
        raise LlmError("Provider returned empty content")
    return text


async def _call_gemini(prompt: str, *, api_key: str, model: str) -> str:
    # Key goes in header, not query string (never in URLs)
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.72,
            "responseMimeType": "application/json",
        },
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(url, headers=headers, json=body)
    if resp.status_code >= 400:
        logger.warning("Gemini error status=%s", resp.status_code)
        raise LlmError(f"Gemini API error ({resp.status_code})")
    data = resp.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise LlmError("Gemini returned empty content") from None
    return text


def _parse_response(
    text: str,
    *,
    max_length: int,
    entity: NamingEntity | None = None,
) -> LlmGenerationResult:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise LlmError("LLM response was not valid JSON") from None
        data = json.loads(match.group(0))

    directions: list[dict[str, str]] = []
    for d in data.get("directions") or []:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name") or "").strip()
        desc = str(d.get("description") or "").strip()
        if name:
            directions.append({"name": name, "description": desc})

    names: list[LlmName] = []
    seen: set[str] = set()
    for item in data.get("names") or []:
        if isinstance(item, str):
            raw_name, direction, why, tier = item, "", "", ""
        elif isinstance(item, dict):
            raw_name = str(item.get("name") or "")
            direction = str(item.get("direction") or "")
            why = str(item.get("why") or "")
            tier = str(item.get("tier") or "").strip().upper()[:1]
        else:
            continue
        name = _normalize_candidate(raw_name, max_length=max_length, entity=entity)
        if not name:
            continue
        key = re.sub(r"[^a-z]", "", name.lower())
        if key in seen:
            continue
        seen.add(key)
        names.append(LlmName(name=name, direction=direction, why=why, tier=tier))

    return LlmGenerationResult(directions=directions, names=names)


def _normalize_candidate(
    name: str,
    *,
    max_length: int,
    entity: NamingEntity | None = None,
) -> str:
    name = name.strip().strip("\"'")
    allow_amp = bool(entity and entity.allow_ampersand)
    allow_spaces = bool(entity.allow_spaces) if entity else False
    if allow_amp:
        name = re.sub(r"[^A-Za-z &]", "", name)
        name = re.sub(r"\s*&\s*", " & ", name)
    else:
        name = re.sub(r"[^A-Za-z ]", "", name)
    name = re.sub(r"\s+", " ", name).strip(" &")
    if not name:
        return ""
    compact = re.sub(r"[^A-Za-z]", "", name)
    # Display length includes spaces/ampersand for local-style names.
    display_len = len(name) if allow_spaces or allow_amp else len(compact)
    if len(compact) < 4 or display_len > max_length:
        return ""
    if not allow_spaces and " " in name:
        name = compact
    if not allow_amp:
        name = name.replace("&", "")
        name = re.sub(r"\s+", " ", name).strip()
    if " " not in name and "&" not in name:
        return compact[:1].upper() + compact[1:].lower()
    parts = []
    for w in name.split(" "):
        if w == "&":
            parts.append("&")
        elif w:
            parts.append(w[:1].upper() + w[1:].lower())
    return " ".join(parts)
