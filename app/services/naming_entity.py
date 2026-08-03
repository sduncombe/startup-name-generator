"""What the user is naming — the primary brand-context signal for AI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NamingEntity:
    code: str
    label: str
    # Heavy prompt framing — drives the whole branding exercise.
    framing: str
    reference_brands: tuple[str, ...]
    # Generation rules
    prefer_brandable: bool = True
    allow_spaces: bool = False
    allow_ampersand: bool = False
    max_length: int = 12
    # Extra instructions unique to this entity type
    guidance: str = ""


NAMING_ENTITIES: dict[str, NamingEntity] = {
    "software_company": NamingEntity(
        code="software_company",
        label="Software company",
        framing="The user is naming a venture-backed software company.",
        reference_brands=(
            "Stripe", "Figma", "Canva", "Linear", "Notion", "Ramp", "Vercel", "Slack", "Airbnb", "Houzz",
        ),
        prefer_brandable=True,
        max_length=12,
        guidance=(
            "Favor short, ownable, abstract or lightly suggestive names. "
            "Avoid literal product phrases and local-business constructions."
        ),
    ),
    "mobile_app": NamingEntity(
        code="mobile_app",
        label="Mobile app",
        framing="The user is naming a consumer mobile app.",
        reference_brands=("Duolingo", "Calm", "Notion", "Headspace", "Venmo", "Robinhood", "BeReal", "Figma"),
        prefer_brandable=True,
        max_length=10,
        guidance=(
            "Favor punchy, app-store-friendly names. Short, playful or clean. "
            "Avoid corporate compound names and '… Furniture / … Home' retail phrasing."
        ),
    ),
    "ai_company": NamingEntity(
        code="ai_company",
        label="AI company",
        framing="The user is naming an AI / machine-learning company.",
        reference_brands=("OpenAI", "Anthropic", "Perplexity", "Hugging Face", "Scale", "Runway", "Midjourney"),
        prefer_brandable=True,
        max_length=12,
        guidance=(
            "Sound modern and technically credible without cliché AI tokens "
            "(avoid Neural, GPT, Bot, Mind, Cortex, GenAI as roots)."
        ),
    ),
    "local_business": NamingEntity(
        code="local_business",
        label="Local business",
        framing="The user is naming a local service or brick-and-mortar business.",
        reference_brands=("Warby Parker", "Everlane", "Lush", "REI", "Sweetgreen"),
        prefer_brandable=False,
        allow_spaces=True,
        allow_ampersand=True,
        max_length=28,
        guidance=(
            "Favor place-rooted, warm, trustworthy names. Multi-word names and "
            "ampersands are welcome. Avoid invented tech coinages."
        ),
    ),
    "local_furniture_retailer": NamingEntity(
        code="local_furniture_retailer",
        label="Local furniture retailer",
        framing="The user is naming a local furniture store / home retailer.",
        reference_brands=("Article", "West Elm", "Crate & Barrel", "Room & Board", "Design Within Reach"),
        prefer_brandable=False,
        allow_spaces=True,
        allow_ampersand=True,
        max_length=28,
        guidance=(
            "Think showroom and neighborhood retailer: Oak & Home, Northwood Furniture, "
            "Heritage Home, Modern Living. Multi-word descriptive/evocative names are expected. "
            "Do NOT invent tech-startup syllable brands."
        ),
    ),
    "professional_services": NamingEntity(
        code="professional_services",
        label="Professional services firm",
        framing="The user is naming a professional services firm (agency, consultancy, practice).",
        reference_brands=("Accenture", "McKinsey", "IDEO", "Pentagram", "Deloitte"),
        prefer_brandable=True,
        allow_spaces=True,
        max_length=22,
        guidance="Balance credibility and modernity. Avoid gimmicky consumer-app names.",
    ),
    "restaurant_cafe": NamingEntity(
        code="restaurant_cafe",
        label="Restaurant or café",
        framing="The user is naming a restaurant or café.",
        reference_brands=("Sweetgreen", "Chipotle", "Blue Bottle", "Eataly", "Noma"),
        prefer_brandable=False,
        allow_spaces=True,
        allow_ampersand=True,
        max_length=24,
        guidance="Evocative, appetizing, place-like. Avoid SaaS-style inventeds.",
    ),
    "consumer_brand": NamingEntity(
        code="consumer_brand",
        label="Consumer brand",
        framing="The user is naming a consumer product brand.",
        reference_brands=("Glossier", "Allbirds", "Away", "Casper", "Oatly", "Liquid Death"),
        prefer_brandable=True,
        max_length=14,
        guidance="Memorable CPG energy — distinctive but approachable.",
    ),
    "hardware_company": NamingEntity(
        code="hardware_company",
        label="Hardware company",
        framing="The user is naming a hardware / device company.",
        reference_brands=("Sonos", "Nest", "Ring", "Framework", "Nothing", "Dyson"),
        prefer_brandable=True,
        max_length=12,
        guidance="Solid, productized, slightly industrial or precise — not fluffy.",
    ),
    "podcast": NamingEntity(
        code="podcast",
        label="Podcast",
        framing="The user is naming a podcast.",
        reference_brands=("Serial", "The Daily", "How I Built This", "99% Invisible", "Reply All"),
        prefer_brandable=False,
        allow_spaces=True,
        max_length=28,
        guidance="Titles can be phrases. Avoid corporate SaaS inventeds.",
    ),
    "newsletter": NamingEntity(
        code="newsletter",
        label="Newsletter",
        framing="The user is naming a newsletter or email publication.",
        reference_brands=("The Hustle", "Morning Brew", "Lenny's Newsletter", "Stratechery"),
        prefer_brandable=False,
        allow_spaces=True,
        max_length=28,
        guidance="Publication energy — clear, editorial, sticky.",
    ),
    "youtube_channel": NamingEntity(
        code="youtube_channel",
        label="YouTube channel",
        framing="The user is naming a YouTube channel / creator brand.",
        reference_brands=("MKBHD", "Veritasium", "Vsauce", "The Verge"),
        prefer_brandable=True,
        allow_spaces=True,
        max_length=22,
        guidance="Creator-friendly and searchable. Avoid dull corporate names.",
    ),
    "nonprofit": NamingEntity(
        code="nonprofit",
        label="Nonprofit",
        framing="The user is naming a nonprofit organization.",
        reference_brands=("Charity: Water", "Khan Academy", "GiveDirectly", "Wikipedia"),
        prefer_brandable=False,
        allow_spaces=True,
        max_length=28,
        guidance="Mission-forward, trustworthy, human. Avoid jokey inventeds.",
    ),
    "personal_brand": NamingEntity(
        code="personal_brand",
        label="Personal brand",
        framing="The user is naming a personal brand / creator identity.",
        reference_brands=("MrBeast", "Ali Abdaal", "Morning Brew"),
        prefer_brandable=True,
        allow_spaces=True,
        max_length=20,
        guidance="Distinctive and ownable for a person — not a faceless corporation.",
    ),
}

DEFAULT_ENTITY = "software_company"


def normalize_naming_entity(value: str | None) -> str:
    raw = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "software": "software_company",
        "saas": "software_company",
        "startup": "software_company",
        "app": "mobile_app",
        "mobile": "mobile_app",
        "ai": "ai_company",
        "local": "local_business",
        "furniture": "local_furniture_retailer",
        "furniture_store": "local_furniture_retailer",
        "furniture_retailer": "local_furniture_retailer",
        "restaurant": "restaurant_cafe",
        "cafe": "restaurant_cafe",
        "services": "professional_services",
        "agency": "professional_services",
        "hardware": "hardware_company",
        "consumer": "consumer_brand",
        "product": "consumer_brand",
        "yt": "youtube_channel",
        "youtube": "youtube_channel",
        "charity": "nonprofit",
        "personal": "personal_brand",
    }
    raw = aliases.get(raw, raw)
    if raw in NAMING_ENTITIES:
        return raw
    return ""


def get_naming_entity(value: str | None) -> NamingEntity | None:
    code = normalize_naming_entity(value)
    return NAMING_ENTITIES.get(code) if code else None


def entity_choices() -> list[dict[str, str]]:
    return [{"code": e.code, "label": e.label} for e in NAMING_ENTITIES.values()]
