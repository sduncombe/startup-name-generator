from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import httpx

from app.config import get_settings

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
    naming_style: str = "brandable",
) -> LlmGenerationResult:
    if not brand_brief.strip():
        return LlmGenerationResult()
    if not credentials.api_key:
        raise LlmError("AI generation requires your own API key (BYOK).")

    settings = get_settings()
    target = count or settings.llm_name_count
    prompt = _build_prompt(
        category=category,
        keywords=keywords,
        tone=tone,
        brand_brief=brand_brief,
        max_length=max_length,
        count=target,
        naming_style=naming_style,
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

    parsed = _parse_response(text, max_length=max_length)
    parsed.provider = provider
    parsed.model = model
    parsed.raw_text = text
    return parsed


_STYLE_GUIDANCE = {
    "brandable": (
        "Prefer inventeds, abstracts, evocatives, and light compounds "
        "(Apple, Stripe, Slack, Notion energy). Do NOT name the product literally. "
        "Avoid stuffing category keywords into the name. Meaning can come later from the brand."
    ),
    "balanced": (
        "Mix inventeds, evocatives, compounds, suggestives, and a few descriptive names. "
        "Favor brandable ownability over SEO-style product phrases."
    ),
    "descriptive": (
        "Lean toward clear, suggestive, and descriptive names that hint at what the product does, "
        "while still staying short and pronounceable."
    ),
}


def _build_prompt(
    *,
    category: str,
    keywords: list[str],
    tone: str,
    brand_brief: str,
    max_length: int,
    count: int,
    naming_style: str = "brandable",
) -> str:
    kw = ", ".join(keywords) if keywords else "(none)"
    style = naming_style if naming_style in _STYLE_GUIDANCE else "brandable"
    style_note = _STYLE_GUIDANCE[style]
    return f"""You are a consumer brand naming strategist helping name a company.

Your only job is creative naming directions and candidate names.
Do NOT check domains, conflicts, pronunciation, or scores; code handles that.

Return ONLY valid JSON (no markdown fences) with this shape:
{{
  "directions": [
    {{"name": "short direction label", "description": "one sentence"}}
  ],
  "names": [
    {{"name": "BrandName", "direction": "direction label", "why": "one short reason"}}
  ]
}}

Requirements:
- Infer category, keywords, and tone from the brief yourself.
- Propose 3–5 distinct naming directions grounded in the brief.
- Propose about {count} candidate brand names total across those directions.
- Naming style preference: {style}. {style_note}
- Names must be easy to pronounce and spell after hearing once.
- Prefer 5–{max_length} letters, 2–3 syllables, no numbers/hyphens/punctuation.
- Prefer names that work for the Primary language in the brief (pronounceability, spelling, cultural fit).
- Infer style traits from Brands we like (short, abstract, premium, playful, etc.). Never copy those brand names.
- Respect Avoid: do not propose names that match those characteristics.
- Target audience should shape tone and sophistication.
- Avoid obvious major-brand collisions.
- Do not invent gibberish consonant piles.

Hint fields (may be incomplete; prefer the brief):
Category hint: {category}
Keyword hint: {kw}
Tone hint: {tone}
Max length: {max_length}

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
        "max_tokens": 4096,
        "temperature": 0.9,
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
        "temperature": 0.9,
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
            "temperature": 0.9,
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


def _parse_response(text: str, *, max_length: int) -> LlmGenerationResult:
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
            raw_name, direction, why = item, "", ""
        elif isinstance(item, dict):
            raw_name = str(item.get("name") or "")
            direction = str(item.get("direction") or "")
            why = str(item.get("why") or "")
        else:
            continue
        name = _normalize_candidate(raw_name, max_length=max_length)
        if not name:
            continue
        key = re.sub(r"[^a-z]", "", name.lower())
        if key in seen:
            continue
        seen.add(key)
        names.append(LlmName(name=name, direction=direction, why=why))

    return LlmGenerationResult(directions=directions, names=names)


def _normalize_candidate(name: str, *, max_length: int) -> str:
    name = name.strip().strip("\"'")
    name = re.sub(r"[^A-Za-z ]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return ""
    compact = re.sub(r"[^A-Za-z]", "", name)
    if len(compact) < 4 or len(compact) > max_length:
        return ""
    if " " not in name:
        return compact[:1].upper() + compact[1:].lower()
    return " ".join(w[:1].upper() + w[1:].lower() for w in name.split())
