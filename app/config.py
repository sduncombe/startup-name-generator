from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_path: str = "data/runs.db"
    host: str = "127.0.0.1"
    port: int = 8000
    public_app_url: str = "https://names.seanduncombe.com"
    github_repo_url: str = "https://github.com/sduncombe/startup-name-generator"

    domain_provider: str = "rdap"
    domain_api_key: str = ""
    domain_api_secret: str = ""
    domain_check_concurrency: int = 3
    domain_check_timeout_seconds: float = 8.0

    # BYOK is the public default. Server-side keys are opt-in for private deploys only.
    allow_server_llm_keys: bool = False
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-5"
    llm_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    xai_api_key: str = ""
    gemini_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    xai_base_url: str = "https://api.x.ai/v1"
    llm_name_count: int = 48
    radio_test_top: int = 80

    @property
    def db_path(self) -> Path:
        path = Path(self.database_path)
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config {name} must be a mapping")
    return data


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def scoring_config() -> dict[str, Any]:
    return load_yaml("scoring.yaml")


@lru_cache
def vocabulary_config() -> dict[str, Any]:
    return load_yaml("vocabulary.yaml")


@lru_cache
def syllables_config() -> dict[str, Any]:
    return load_yaml("syllables.yaml")


@lru_cache
def blocklist_config() -> dict[str, Any]:
    return load_yaml("blocklist.yaml")


@lru_cache
def domains_config() -> dict[str, Any]:
    return load_yaml("domains.yaml")
