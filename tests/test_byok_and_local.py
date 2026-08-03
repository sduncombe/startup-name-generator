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
from app.services.llm import resolve_credentials
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
        audience="Homeowners buying furniture.",
        liked_brands="Airbnb, Notion, Houzz",
        avoid="AI sounding names. Enterprise.",
        primary_market="ca",
    )
    assert "furniture" in inferred.keywords or "home" in inferred.keywords or "visualize" in inferred.keywords
    assert inferred.category
    assert "Friendly" in inferred.tone or "Warm" in inferred.tone or "Calm" in inferred.tone
    assert "Problem we're solving" in inferred.brand_brief
    assert "Primary market: Canada" in inferred.brand_brief
    assert inferred.primary_market == "ca"


def test_primary_market_defaults_to_global_and_accepts_other():
    from app.services.brief import market_display, normalize_market

    assert normalize_market(None) == ("global", "")
    assert market_display("uk") == "United Kingdom"
    code, other = normalize_market("other", "Japan")
    assert code == "other" and other == "Japan"
    assert market_display("other", "Japan") == "Japan"


def test_one_click_pipeline_without_keys(client):
    created = client.post(
        "/api/runs",
        json={
            "problem": "People can't visualize furniture before buying.",
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
    assert body["result"]["generated"] >= 50
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
            "run_pipeline": False,
            "generate_count": 80,
        },
    )
    assert created.status_code == 200
    run_id = created.json()["run"]["id"]
    gen = client.post(f"/api/runs/{run_id}/generate")
    assert gen.status_code == 200
    assert gen.json()["result"]["generated"] >= 50


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


def test_key_not_persisted_in_run(client):
    created = client.post(
        "/api/runs",
        json={
            "building": "Test product",  # legacy alias still accepted
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
