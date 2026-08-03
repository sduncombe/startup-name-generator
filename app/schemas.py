from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.brief import infer_brief


class RunCreate(BaseModel):
    """Consultant-style brief. Advanced generator knobs stay optional."""

    # Primary conversational fields
    building: str = Field(default="", max_length=2000)
    audience: str = Field(default="", max_length=1000)
    liked_brands: str = Field(default="", max_length=500)
    avoid: str = Field(default="", max_length=1000)

    # Optional / advanced (inferred when omitted)
    category: str = Field(default="", max_length=200)
    keywords: list[str] = Field(default_factory=list)
    tone: str = Field(default="", max_length=200)
    brand_brief: str = Field(default="", max_length=4000)

    max_length: int = Field(default=12, ge=4, le=20)
    extensions: list[str] = Field(default_factory=lambda: [".com", ".app", ".co"])
    generate_count: int = Field(default=400, ge=50, le=10000)
    domain_check_top: int = Field(default=40, ge=0, le=2000)
    conflict_check_top: int = Field(default=40, ge=0, le=500)
    radio_test_top: int | None = Field(default=None, ge=0, le=2000)

    # When true, create run then generate + domain + conflict in one request
    run_pipeline: bool = True

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

    @model_validator(mode="after")
    def infer_missing_fields(self) -> RunCreate:
        if not self.building.strip() and not self.category.strip() and not self.brand_brief.strip():
            raise ValueError("Tell us what you are building")

        building = self.building.strip()
        if not building and self.brand_brief.strip():
            building = self.brand_brief.strip().split("\n")[0][:200]

        inferred = infer_brief(
            building=building or self.category,
            audience=self.audience,
            liked_brands=self.liked_brands,
            avoid=self.avoid,
            category=self.category or None,
            keywords=self.keywords or None,
            tone=self.tone or None,
        )
        self.category = inferred.category
        self.keywords = inferred.keywords
        self.tone = inferred.tone
        if not self.brand_brief.strip():
            self.brand_brief = inferred.brand_brief
        if not self.building.strip():
            self.building = inferred.building
        return self


class FavoriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    favorite: bool = True


class DomainCheckRequest(BaseModel):
    top_n: int | None = Field(default=None, ge=1, le=2000)
    resume: bool = True


class ConflictCheckRequest(BaseModel):
    top_n: int | None = Field(default=None, ge=1, le=500)
