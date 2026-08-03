from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.brief import infer_brief
from app.services.naming_entity import normalize_naming_entity
from app.services.naming_style import normalize_naming_style
from app.services.preferences import normalize_language


class RunCreate(BaseModel):
    """Consultant-style brief. Advanced generator knobs stay optional."""

    model_config = ConfigDict(populate_by_name=True)

    # Primary conversational field: the problem being solved.
    # "building" remains accepted as a backward-compatible alias.
    problem: str = Field(
        default="",
        max_length=2000,
        validation_alias=AliasChoices("problem", "building"),
    )
    # Required: what kind of brand / thing is being named.
    naming_entity: str = Field(
        default="",
        max_length=64,
        validation_alias=AliasChoices("naming_entity", "naming", "what_naming"),
    )
    audience: str = Field(default="", max_length=1000)
    liked_brands: str = Field(default="", max_length=500)
    avoid: str = Field(default="", max_length=1000)

    # Primary language shapes phonotactics, endings, and scoring.
    primary_language: str = Field(
        default="en-global",
        max_length=32,
        validation_alias=AliasChoices("primary_language", "primary_market"),
    )
    primary_language_other: str = Field(
        default="",
        max_length=120,
        validation_alias=AliasChoices("primary_language_other", "primary_market_other"),
    )

    # Naming philosophies (distinct strategies):
    # invented | real_word | compound | descriptive
    # Legacy brandable/balanced are accepted and normalized to invented.
    naming_style: str = "invented"

    # Optional / advanced (inferred when omitted)
    category: str = Field(default="", max_length=200)
    keywords: list[str] = Field(default_factory=list)
    tone: str = Field(default="", max_length=200)
    brand_brief: str = Field(default="", max_length=4000)

    max_length: int = Field(default=12, ge=4, le=20)
    extensions: list[str] = Field(default_factory=lambda: [".com", ".app", ".co"])
    generate_count: int = Field(default=24, ge=12, le=2000)
    domain_check_top: int = Field(default=40, ge=0, le=2000)
    conflict_check_top: int = Field(default=40, ge=0, le=500)
    trademark_check_top: int = Field(default=40, ge=0, le=500)
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

    @field_validator("primary_language", mode="before")
    @classmethod
    def normalize_primary_language(cls, value: Any) -> str:
        # Map legacy market codes if an old client still sends them.
        legacy = {
            "global": "en-global",
            "us": "en-us",
            "uk": "en-uk",
            "ca": "en-global",
            "eu": "en-global",
            "au": "en-global",
        }
        raw = str(value or "en-global").strip().lower()
        raw = legacy.get(raw, raw)
        code, _ = normalize_language(raw)
        return code

    @field_validator("naming_entity", mode="before")
    @classmethod
    def normalize_entity(cls, value: Any) -> str:
        return normalize_naming_entity(str(value or ""))

    @field_validator("naming_style", mode="before")
    @classmethod
    def normalize_style(cls, value: Any) -> str:
        return normalize_naming_style(str(value or "invented"))

    @model_validator(mode="after")
    def infer_missing_fields(self) -> RunCreate:
        if not self.problem.strip() and not self.category.strip() and not self.brand_brief.strip():
            raise ValueError("Tell us what problem you are solving")
        if not self.naming_entity:
            raise ValueError("Tell us what you are naming (software company, podcast, local business, …)")

        problem = self.problem.strip()
        if not problem and self.brand_brief.strip():
            problem = self.brand_brief.strip().split("\n")[0][:200]

        lang, lang_other = normalize_language(self.primary_language, self.primary_language_other)
        self.primary_language = lang
        self.primary_language_other = lang_other

        inferred = infer_brief(
            problem=problem or self.category,
            audience=self.audience,
            liked_brands=self.liked_brands,
            avoid=self.avoid,
            naming_entity=self.naming_entity,
            primary_language=lang,
            primary_language_other=lang_other,
            category=self.category or None,
            keywords=self.keywords or None,
            tone=self.tone or None,
        )
        self.category = inferred.category
        self.keywords = inferred.keywords
        self.tone = inferred.tone
        self.naming_entity = inferred.naming_entity or self.naming_entity
        if not self.brand_brief.strip():
            self.brand_brief = inferred.brand_brief
        if not self.problem.strip():
            self.problem = inferred.problem
        return self


class FavoriteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    favorite: bool = True


class DomainCheckRequest(BaseModel):
    top_n: int | None = Field(default=None, ge=1, le=2000)
    resume: bool = True


class ConflictCheckRequest(BaseModel):
    top_n: int | None = Field(default=None, ge=1, le=500)


class TrademarkCheckRequest(BaseModel):
    top_n: int | None = Field(default=None, ge=1, le=500)
