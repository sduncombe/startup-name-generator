from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Force public BYOK mode for tests: no server LLM keys
os.environ["ALLOW_SERVER_LLM_KEYS"] = "false"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["XAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["DATABASE_PATH"] = "data/test-runs.db"

from app.config import get_settings
from app.main import app
from app.services.brief import infer_brief
from app.services.llm import LlmError, LlmGenerationResult, LlmName, resolve_credentials
from app.services.radio_test import radio_test


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("ALLOW_SERVER_LLM_KEYS", "false")
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c


def test_health_public_byok(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    assert h["byok_required"] is True
    assert "anthropic" in h["providers"]


def test_infer_brief_from_natural_language():
    inferred = infer_brief(
        problem="People can't visualize furniture before buying.",
        naming_entity="software_company",
        audience="Homeowners buying furniture.",
        liked_brands="Airbnb, Notion, Houzz",
        avoid="AI sounding names. Enterprise.",
        primary_language="fr",
    )
    assert "furniture" in inferred.keywords or "home" in inferred.keywords or "visualize" in inferred.keywords
    assert inferred.category
    assert inferred.tone
    assert "Problem we're solving" in inferred.brand_brief
    assert "What we're naming: Software company" in inferred.brand_brief
    assert "Primary language: French" in inferred.brand_brief
    assert inferred.primary_language == "fr"
    assert inferred.naming_entity == "software_company"


def test_one_click_pipeline_without_keys(client):
    created = client.post(
        "/api/runs",
        json={
            "problem": "People can't visualize furniture before buying.",
            "naming_entity": "software_company",
            "audience": "Homeowners buying furniture.",
            "liked_brands": "Airbnb, Notion",
            "avoid": "Enterprise and AI-sounding names",
            "generate_count": 80,
            "domain_check_top": 0,
            "conflict_check_top": 5,
            "run_pipeline": True,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["run"]["id"]
    assert body["result"]["generated"] >= 12
    assert body["result"]["llm"] == 0
    assert body["candidates"]
    assert body["result"]["directions"]
    # Directions should organize ideas even without AI
    assert any(c.get("direction") for c in body["candidates"])
    # Trademark screening runs automatically as part of the pipeline
    assert body["result"]["trademarks"]["checked"] > 0
    screened = [c for c in body["candidates"] if c.get("trademark_risk")]
    assert screened
    assert all(c["trademark_risk"] in ("low", "medium", "high") for c in screened)


def test_create_without_pipeline_still_works(client):
    created = client.post(
        "/api/runs",
        json={
            "problem": "Busy parents struggle to plan meals for the week.",
            "naming_entity": "mobile_app",
            "run_pipeline": False,
            "generate_count": 80,
        },
    )
    assert created.status_code == 200
    run_id = created.json()["run"]["id"]
    gen = client.post(f"/api/runs/{run_id}/generate")
    assert gen.status_code == 200
    # Quality cull keeps a consultant shortlist (not a padded dump).
    assert gen.json()["result"]["generated"] >= 12
    assert gen.json()["result"]["generated"] <= 24


def test_resolve_credentials_byok_only():
    creds = resolve_credentials(
        request_provider="openai",
        request_api_key="sk-test-not-real",
        request_model="gpt-4o-mini",
    )
    assert creds is not None
    assert creds.provider == "openai"
    assert resolve_credentials() is None


def test_radio_test_fields():
    r = radio_test("Livora")
    assert 0 <= r.score <= 100
    assert r.passed in (True, False)
    d = r.to_dict()
    assert "alternate_spellings" in d
    assert d["radio_result"] in ("pass", "fail")


def _fake_ai_result(provider: str = "anthropic", model: str = "claude-test"):
    # Commercially believable shapes — not soft inventeds (Velora/Roomly).
    names = [
        "Harbor", "Prism", "Atlas", "Cedar", "Vault", "Linear",
        "Notion", "Forge", "Beacon", "Summit", "Radius", "Canvas",
        "North", "Pulse", "Ridge", "Lumen", "Orbit", "Facet",
        "Grove", "Helix", "Meridian", "Signal", "Clarity", "Forma",
    ]
    return LlmGenerationResult(
        directions=[{"name": "AI concepts", "description": "Generated from the brief."}],
        names=[
            LlmName(name=n, direction="AI concepts", why="Brief-derived", tier="A")
            for n in names
        ],
        provider=provider,
        model=model,
    )


def test_ai_enabled_returns_ai_only(client, monkeypatch):
    called = {}

    async def fake_generate(**kwargs):
        called["provider"] = kwargs["credentials"].provider
        called["model"] = kwargs["credentials"].model
        return _fake_ai_result(called["provider"], called["model"])

    monkeypatch.setattr("app.services.pipeline.generate_names_from_brief", fake_generate)
    created = client.post(
        "/api/runs",
        json={
            "problem": "Teams lose track of customer research.",
            "naming_entity": "software_company",
            "generate_count": 40,
            "run_pipeline": False,
        },
    )
    run_id = created.json()["run"]["id"]
    generated = client.post(
        f"/api/runs/{run_id}/generate",
        headers={
            "X-LLM-Enabled": "true",
            "X-LLM-Provider": "anthropic",
            "X-LLM-API-Key": "test-key-never-persist",
            "X-LLM-Model": "claude-test",
        },
    )
    assert generated.status_code == 200, generated.text
    run = client.get(f"/api/runs/{run_id}").json()
    ai = run["run"]["llm"]
    assert called == {"provider": "anthropic", "model": "claude-test"}
    assert ai["status"] == "succeeded"
    assert ai["provider"] == "anthropic"
    assert ai["model"] == "claude-test"
    assert ai["accepted_count"] >= 12
    sources = [c["source"] for c in run["candidates"]]
    assert sources.count("ai") >= 12
    # AI runs are AI-only: local coinages must not be mixed in.
    assert set(sources) == {"ai"}
    assert all(c["generation_source"] == "ai" for c in run["candidates"])
    assert "test-key-never-persist" not in str(run)
    # Soft inventeds must not survive the quality gate.
    keys = {c["name"].lower() for c in run["candidates"]}
    assert "velora" not in keys


def test_ai_disabled_never_calls_provider(client, monkeypatch):
    async def must_not_call(**_kwargs):
        raise AssertionError("provider should not be called")

    monkeypatch.setattr("app.services.pipeline.generate_names_from_brief", must_not_call)
    created = client.post(
        "/api/runs",
        json={"problem": "Local-only naming.", "naming_entity": "software_company", "generate_count": 20, "run_pipeline": False},
    )
    run_id = created.json()["run"]["id"]
    generated = client.post(
        f"/api/runs/{run_id}/generate",
        headers={
            "X-LLM-Enabled": "false",
            "X-LLM-Provider": "anthropic",
            "X-LLM-API-Key": "present-but-disabled",
        },
    )
    assert generated.status_code == 200, generated.text
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["run"]["llm"]["status"] == "disabled"
    assert {c["source"] for c in run["candidates"]} == {"local"}


def test_ai_failure_is_visible_and_not_silent(client, monkeypatch):
    async def fail_generate(**_kwargs):
        raise LlmError("Anthropic API error (401)")

    monkeypatch.setattr("app.services.pipeline.generate_names_from_brief", fail_generate)
    created = client.post(
        "/api/runs",
        json={"problem": "A test brief.", "naming_entity": "software_company", "generate_count": 20, "run_pipeline": False},
    )
    run_id = created.json()["run"]["id"]
    generated = client.post(
        f"/api/runs/{run_id}/generate",
        headers={
            "X-LLM-Enabled": "true",
            "X-LLM-Provider": "anthropic",
            "X-LLM-API-Key": "invalid-key",
        },
    )
    assert generated.status_code == 502
    assert "Anthropic API error (401)" in generated.json()["detail"]
    run = client.get(f"/api/runs/{run_id}").json()["run"]
    assert run["status"] == "ai_failed"
    assert run["llm"]["status"] == "failed"
    assert "401" in run["llm"]["error"]


def test_key_not_persisted_in_run(client, monkeypatch):
    async def fake_generate(**kwargs):
        return _fake_ai_result(kwargs["credentials"].provider, kwargs["credentials"].model)

    monkeypatch.setattr("app.services.pipeline.generate_names_from_brief", fake_generate)
    created = client.post(
        "/api/runs",
        json={
            "building": "Test product",  # legacy alias still accepted
            "naming_entity": "software_company",
            "generate_count": 50,
            "domain_check_top": 0,
            "conflict_check_top": 0,
            "run_pipeline": True,
        },
        headers={
            "X-LLM-Provider": "anthropic",
            "X-LLM-API-Key": "sk-ant-fake-should-never-be-stored",
        },
    )
    assert created.status_code == 200
    blob = str(created.json())
    assert "sk-ant-fake-should-never-be-stored" not in blob
