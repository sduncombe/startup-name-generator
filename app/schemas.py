from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class RunCreate(BaseModel):
    category: str = Field(min_length=1, max_length=200)
    keywords: list[str] = Field(default_factory=list)
    tone: str = Field(default="Friendly, modern, trustworthy", max_length=200)
    brand_brief: str = Field(default="", max_length=4000)
    max_length: int = Field(default=12, ge=4, le=20)
    extensions: list[str] = Field(default_factory=lambda: [".com", ".app", ".co"])
    generate_count: int = Field(default=1000, ge=50, le=10000)
    domain_check_top: int = Field(default=200, ge=0, le=2000)
    conflict_check_top: int = Field(default=50, ge=0, le=500)
    radio_test_top: int | None = Field(default=None, ge=0, le=2000)

    @field_validator("keywords", mode="before")
    @classmethod
    def split_keywords(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            parts = [p.strip() for p in value.replace(";", ",").split(",")]
            return [p for p in parts if p]
        return [str(v).strip() for v in value if str(v).strip()]

    @field_validator("extensions")
    @classmethod
    def normalize_extensions(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for ext in value:
            e = ext.strip().lower()
            if not e:
                continue
            if not e.startswith("."):
                e = f".{e}"
            if e not in out:
                out.append(e)
        if not out:
            raise ValueError("At least one domain extension is required")
        return out


class FavoriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    favorite: bool = True


class DomainCheckRequest(BaseModel):
    top_n: int | None = Field(default=None, ge=1, le=2000)
    resume: bool = True


class ConflictCheckRequest(BaseModel):
    top_n: int | None = Field(default=None, ge=1, le=500)
