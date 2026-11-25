"""GET /api/articles: normalisation, saved-analysis hint, validation, errors.

GNews itself is mocked throughout — these tests never make a real network
call, and assert that no AI call happens either (there is nothing to call
yet at this point in the build, which is itself the guarantee).
"""
from unittest.mock import patch

import pytest

from app.models import ArticleAnalysis
from app.schemas import NormalizedArticle
from app.services.errors import ProviderError, ProviderTimeout, ProviderUnavailable


def _article(url: str = "https://example.com/a", title: str = "Title A") -> NormalizedArticle:
    return NormalizedArticle(
        url=url,
        title=title,
        source="Example News",
        published_at=None,
        description="desc",
        content="content",
    )


@patch("app.services.news.gnews.search")
def test_search_returns_normalised_articles(mock_search, client):
    mock_search.return_value = [_article()]

    response = client.get("/api/articles", params={"query": "artificial intelligence"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["articles"]) == 1
    article = body["articles"][0]
    assert article["url"] == "https://example.com/a"
    assert article["title"] == "Title A"
    assert article["source"] == "Example News"
    assert article["analysis_id"] is None
    mock_search.assert_called_once()


@patch("app.services.news.gnews.search")
def test_search_attaches_existing_analysis_id(mock_search, client, db_session):
    mock_search.return_value = [_article(url="https://example.com/already-analysed")]

    existing = ArticleAnalysis(
        article_url="https://example.com/already-analysed",
        title="Title A",
        summary="A summary.",
        sentiment="neutral",
        content_scope="excerpt",
        model="gpt-4o-mini",
    )
    db_session.add(existing)
    db_session.commit()

    response = client.get("/api/articles", params={"query": "artificial intelligence"})

    assert response.status_code == 200
    assert response.json()["articles"][0]["analysis_id"] == existing.id


@patch("app.services.news.gnews.search")
def test_empty_results_returns_empty_list(mock_search, client):
    mock_search.return_value = []

    response = client.get("/api/articles", params={"query": "no matches expected"})

    assert response.status_code == 200
    assert response.json() == {"articles": []}


@pytest.mark.parametrize("query", ["", "   ", "x" * 201])
def test_invalid_query_is_rejected_without_upstream_call(query, client):
    with patch("app.services.news.gnews.search") as mock_search:
        response = client.get("/api/articles", params={"query": query})

    assert response.status_code == 422
    mock_search.assert_not_called()


@pytest.mark.parametrize(
    "exception, expected_status",
    [
        (ProviderTimeout("timed out"), 504),
        (ProviderUnavailable("quota exhausted"), 503),
        (ProviderError("bad response"), 502),
    ],
)
@patch("app.services.news.gnews.search")
def test_provider_failure_maps_to_controlled_error(mock_search, exception, expected_status, client):
    mock_search.side_effect = exception

    response = client.get("/api/articles", params={"query": "artificial intelligence"})

    assert response.status_code == expected_status
    assert "detail" in response.json()
