"""GNews provider: fetch + normalise recent articles.

Provider-specific response shape is isolated here; app.schemas.
NormalizedArticle is the only thing the rest of the app depends on.
See spec §5 for normalisation rules and the GNews free-plan caveats
(result cap, quota, possibly-unreliable sort/date-range params — this
module re-sorts server-side rather than trusting the provider's order).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import httpx

from app.config import Settings
from app.schemas import NormalizedArticle
from app.services.errors import ProviderError, ProviderTimeout, ProviderUnavailable

logger = logging.getLogger(__name__)

_BASE_URL = "https://gnews.io/api/v4/search"
_SEARCH_WINDOW_DAYS = 7
_MAX_RESULTS = 10


@lru_cache
def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0))


def search(query: str, settings: Settings) -> list[NormalizedArticle]:
    now = datetime.now(timezone.utc)
    params = {
        "q": query,
        "lang": "en",
        "max": _MAX_RESULTS,
        "sortby": "publishedAt",
        "from": _format_gnews_datetime(now - timedelta(days=_SEARCH_WINDOW_DAYS)),
        "to": _format_gnews_datetime(now),
        "apikey": settings.gnews_api_key,
    }

    try:
        response = _client().get(_BASE_URL, params=params)
    except httpx.TimeoutException as exc:
        logger.warning("GNews request timed out: %s", exc)
        raise ProviderTimeout("GNews request timed out") from exc
    except httpx.RequestError as exc:
        logger.warning("GNews request failed: %s", exc)
        raise ProviderError("GNews request failed") from exc

    if response.status_code == 429:
        logger.warning("GNews quota exhausted (429)")
        raise ProviderUnavailable("GNews quota exhausted")
    if response.status_code >= 500:
        logger.warning("GNews server error: %s", response.status_code)
        raise ProviderError(f"GNews server error: {response.status_code}")
    if response.status_code >= 400:
        logger.warning("GNews rejected the request: %s", response.status_code)
        raise ProviderError(f"GNews rejected the request: {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("GNews returned an unparsable response: %s", exc)
        raise ProviderError("GNews returned an unparsable response") from exc

    articles = _normalise(payload.get("articles", []))
    # Trust our own ordering, not the provider's (spec §5): newest first,
    # articles with no published_at sort last.
    articles.sort(
        key=lambda a: a.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return articles


def _normalise(raw_articles: list[dict]) -> list[NormalizedArticle]:
    seen_urls: set[str] = set()
    normalised: list[NormalizedArticle] = []

    for raw in raw_articles:
        url = (raw.get("url") or "").strip()
        title = (raw.get("title") or "").strip()
        if not url or not url.lower().startswith(("http://", "https://")) or not title:
            continue  # spec §5: skip malformed articles lacking a usable URL/title
        if url in seen_urls:
            continue
        seen_urls.add(url)

        source = raw.get("source")
        source_name = (source.get("name") if isinstance(source, dict) else None) or None

        normalised.append(
            NormalizedArticle(
                url=url,
                title=title,
                source=source_name,
                published_at=_parse_published_at(raw.get("publishedAt")),
                description=raw.get("description") or None,
                content=raw.get("content") or None,
                analysis_id=None,  # filled in by the route after one DB lookup
            )
        )

    return normalised


def _parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_gnews_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")
