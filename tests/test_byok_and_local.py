from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Force public BYOK mode for tests — no server LLM keys
os.environ["ALLOW_SERVER_LLM_KEYS"] = "false"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["XAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["DATABASE_PATH"] = "data/test-runs.db"

from app.config import get_settings
from app.main import app
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
    assert "openai" in h["providers"]
    assert "xai" in h["providers"]
    assert "gemini" in h["providers"]


def test_local_generate_without_any_keys(client):
    created = client.post(
        "/api/runs",
        json={
            "category": "Test app",
            "keywords": ["home", "room"],
            "tone": "Friendly",
            "brand_brief": "",
            "max_length": 10,
            "generate_count": 80,
            "extensions": [".com"],
        },
    )
    assert created.status_code == 200
    run_id = created.json()["run"]["id"]
    gen = client.post(f"/api/runs/{run_id}/generate")
    assert gen.status_code == 200
    body = gen.json()["result"]
    assert body["generated"] >= 50
    assert body["llm"] == 0
    full = client.get(f"/api/runs/{run_id}").json()
    assert all(c["method"] != "llm" for c in full["candidates"])
    assert any(c.get("radio_result") for c in full["candidates"])


def test_brief_without_key_skips_llm(client):
    created = client.post(
        "/api/runs",
        json={
            "category": "Test app",
            "keywords": ["home"],
            "tone": "Friendly",
            "brand_brief": "Feel like Notion, not corporate AI.",
            "max_length": 10,
            "generate_count": 60,
        },
    )
    run_id = created.json()["run"]["id"]
    gen = client.post(f"/api/runs/{run_id}/generate")
    assert gen.status_code == 200
    result = gen.json()["result"]
    assert result["llm"] == 0
    assert result["llm_error"]
    assert "API key" in result["llm_error"]


def test_resolve_credentials_byok_only():
    creds = resolve_credentials(
        request_provider="openai",
        request_api_key="sk-test-not-real",
        request_model="gpt-4o-mini",
    )
    assert creds is not None
    assert creds.provider == "openai"
    assert creds.api_key == "sk-test-not-real"

    # No request key + public mode → None (even if env had keys, we cleared them)
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
            "category": "Test",
            "keywords": ["a"],
            "tone": "x",
            "brand_brief": "brief",
            "generate_count": 50,
        },
    )
    run_id = created.json()["run"]["id"]
    # Even if a key is sent, it must not appear in stored run JSON
    client.post(
        f"/api/runs/{run_id}/generate",
        headers={
            "X-LLM-Provider": "anthropic",
            "X-LLM-API-Key": "sk-ant-fake-should-never-be-stored",
        },
    )
    full = client.get(f"/api/runs/{run_id}").json()
    blob = str(full)
    assert "sk-ant-fake-should-never-be-stored" not in blob
