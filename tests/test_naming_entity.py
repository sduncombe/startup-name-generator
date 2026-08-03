from __future__ import annotations

from app.services.brief import compose_brand_brief, infer_brief
from app.services.filter import filter_name
from app.services.llm import _build_prompt, _normalize_candidate
from app.services.naming_entity import get_naming_entity, normalize_naming_entity


def test_normalize_naming_entity():
    assert normalize_naming_entity("Software company") == "software_company"
    assert normalize_naming_entity("mobile_app") == "mobile_app"
    assert normalize_naming_entity("furniture retailer") == "local_furniture_retailer"
    assert normalize_naming_entity("") == ""


def test_brief_includes_entity_framing():
    brief = compose_brand_brief(
        problem="People can't visualize furniture before buying.",
        naming_entity="software_company",
    )
    assert "What we're naming: Software company" in brief
    assert "venture-backed software company" in brief

    retail = compose_brand_brief(
        problem="People can't visualize furniture before buying.",
        naming_entity="local_furniture_retailer",
    )
    assert "local furniture store" in retail.lower()
    assert "Oak & Home" in retail or "retailer" in retail.lower()


def test_prompt_is_entity_decisive():
    soft = get_naming_entity("software_company")
    local = get_naming_entity("local_furniture_retailer")
    soft_prompt = _build_prompt(
        category="furniture",
        keywords=["furniture", "home"],
        tone="modern",
        brand_brief="Problem: furniture visualization",
        max_length=12,
        count=40,
        entity=soft,
    )
    local_prompt = _build_prompt(
        category="furniture",
        keywords=["furniture", "home"],
        tone="warm",
        brand_brief="Problem: furniture visualization",
        max_length=28,
        count=40,
        entity=local,
    )
    assert "venture-backed software company" in soft_prompt
    assert "must NOT sound like a different category" in soft_prompt
    assert "Interbrand or Pentagram" in soft_prompt
    assert "local furniture store" in local_prompt.lower()
    assert "tech inventeds" in local_prompt or "tech-startup" in local_prompt
    # Prompts must diverge hard
    assert soft_prompt != local_prompt
    assert "Stripe" in soft_prompt
    assert "Crate & Barrel" in local_prompt or "West Elm" in local_prompt


def test_local_entity_allows_multiword_names():
    entity = get_naming_entity("local_furniture_retailer")
    name = _normalize_candidate("Oak & Home", max_length=28, entity=entity)
    assert name == "Oak & Home"
    assert filter_name("Oak & Home", max_length=12, entity=entity).ok
    # Software entity should reject ampersand / spaces preference
    soft = get_naming_entity("software_company")
    compact = _normalize_candidate("Oak & Home", max_length=12, entity=soft)
    assert "&" not in compact


def test_infer_brief_carries_entity():
    inferred = infer_brief(
        problem="People can't visualize furniture before buying.",
        naming_entity="mobile_app",
    )
    assert inferred.naming_entity == "mobile_app"
    assert inferred.naming_entity_label == "Mobile app"
    assert "Mobile app" in inferred.brand_brief
