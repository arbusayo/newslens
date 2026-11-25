"""Pydantic request/response contracts for the public API (spec §6)."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, field_serializer


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
