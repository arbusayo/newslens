"""Pydantic request/response contracts for the public API (spec §6)."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator, model_validator


def to_iso_z(value: datetime) -> str:
    """UTC ISO 8601 with a literal 'Z' suffix, matching the spec's examples
    (pydantic's own default emits '+00:00', which would not match).
    """
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class NormalizedArticle(BaseModel):
    """One search result, normalised from whichever news provider answered
    (spec §5/§6.1). The frontend depends only on this shape, never on a
    provider's own field names.
    """

    url: str
    title: str
    source: str | None = None
    published_at: datetime | None = None
    description: str | None = None
    content: str | None = None
    analysis_id: int | None = None

    @field_serializer("published_at")
    def _serialize_published_at(self, value: datetime | None) -> str | None:
        return to_iso_z(value) if value is not None else None


class ArticlesResponse(BaseModel):
    articles: list[NormalizedArticle]


# Proposed limits from spec §6.2.
_URL_MAX_LENGTH = 2048
_TITLE_MAX_LENGTH = 500
_SOURCE_MAX_LENGTH = 250
_DESCRIPTION_MAX_LENGTH = 2000
_CONTENT_MAX_LENGTH = 10000


class Sentiment(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class AnalysisSnapshot(BaseModel):
    """The article snapshot a client submits to POST /api/analyses
    (spec §6.2). Deliberately has no content_scope or sentiment field —
    the server derives analysis scope itself, never from a client
    assertion.
    """

    url: str
    title: str
    source: str | None = None
    published_at: datetime | None = None
    description: str | None = None
    content: str | None = None

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > _URL_MAX_LENGTH or not value.lower().startswith(("http://", "https://")):
            raise ValueError(f"url must be a non-blank http(s) URL of at most {_URL_MAX_LENGTH} characters")
        return value

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > _TITLE_MAX_LENGTH:
            raise ValueError(f"title must be non-blank and at most {_TITLE_MAX_LENGTH} characters")
        return value

    @field_validator("source")
    @classmethod
    def _validate_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > _SOURCE_MAX_LENGTH:
            raise ValueError(f"source must be at most {_SOURCE_MAX_LENGTH} characters")
        return value or None

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > _DESCRIPTION_MAX_LENGTH:
            raise ValueError(f"description must be at most {_DESCRIPTION_MAX_LENGTH} characters")
        return value or None

    @field_validator("content")
    @classmethod
    def _validate_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > _CONTENT_MAX_LENGTH:
            raise ValueError(f"content must be at most {_CONTENT_MAX_LENGTH} characters")
        return value or None

    @model_validator(mode="after")
    def _require_some_content(self) -> "AnalysisSnapshot":
        # A title-only snapshot gives the AI provider nothing to actually
        # summarise; reject it here rather than asking it to paraphrase a
        # headline alone.
        if not self.description and not self.content:
            raise ValueError("at least one of description or content is required")
        return self


class AIAnalysisOutput(BaseModel):
    """What an AI provider module returns: just the generated content,
    not persistence fields (those come from the snapshot/DB, not the
    model). `model` is the provider's own resolved model identifier, not
    necessarily identical to the configured OPENAI_MODEL alias.
    """

    summary: str
    sentiment: Sentiment
    model: str


class AnalysisResource(BaseModel):
    """A saved analysis, returned by POST /api/analyses and both GET
    analysis endpoints (spec §6.2). Deliberately excludes `model` — an
    internal-traceability column, not part of the public contract.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    article_url: str
    title: str
    source: str | None
    published_at: datetime | None
    description: str | None
    summary: str
    sentiment: str
    content_scope: str
    created_at: datetime

    @field_serializer("published_at")
    def _serialize_published_at(self, value: datetime | None) -> str | None:
        return to_iso_z(value) if value is not None else None

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        return to_iso_z(value)


class AnalysesListResponse(BaseModel):
    analyses: list[AnalysisResource]
