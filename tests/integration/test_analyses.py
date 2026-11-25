"""POST /api/analyses and the History endpoints (GET /api/analyses,
GET /api/analyses/{id}): validation, generation, dedup/race handling,
and read-only retrieval.

openai_provider.analyze is mocked throughout -- no real network call,
no API credits spent. The database is real (see tests/integration/
conftest.py): the dedup/race behaviour is specifically PostgreSQL
constraint handling, which is exactly what should NOT be mocked away.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models import ArticleAnalysis
from app.schemas import AIAnalysisOutput, AnalysisSnapshot, Sentiment
from app.services.analysis.store import insert_or_get_existing
from app.services.errors import ProviderError, ProviderTimeout, ProviderUnavailable


def _snapshot_payload(**overrides) -> dict:
    payload = {
        "url": "https://example.com/news/a",
        "title": "Enterprise AI adoption accelerates",
        "source": "Example News",
        "published_at": "2026-11-24T08:00:00Z",
        "description": "Businesses are adopting AI in everyday operations.",
        "content": "Available article excerpt...",
    }
    payload.update(overrides)
    return payload


def _ai_output(**overrides) -> AIAnalysisOutput:
    data = dict(
        summary="Businesses are expanding their use of AI to improve efficiency.",
        sentiment=Sentiment.positive,
        model="gpt-4o-mini-2024-07-18",  # deliberately not equal to settings.openai_model
    )
    data.update(overrides)
    return AIAnalysisOutput(**data)


@patch("app.services.analysis.openai_provider.analyze")
def test_create_analysis_returns_201_and_persists_resolved_model(mock_analyze, client, db_session):
    mock_analyze.return_value = _ai_output()

    response = client.post("/api/analyses", json=_snapshot_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["article_url"] == "https://example.com/news/a"
    assert body["summary"] == _ai_output().summary
    assert body["sentiment"] == "positive"
    assert body["content_scope"] == "excerpt"
    assert "model" not in body  # internal traceability column, not public (spec §6.2)
    assert response.headers["location"] == f"/api/analyses/{body['id']}"

    row = db_session.get(ArticleAnalysis, body["id"])
    assert row is not None
    assert row.model == "gpt-4o-mini-2024-07-18"  # the resolved model, not the configured alias


@patch("app.services.analysis.openai_provider.analyze")
def test_repeated_analysis_returns_200_same_id_no_second_ai_call(mock_analyze, client):
    mock_analyze.return_value = _ai_output()

    first = client.post("/api/analyses", json=_snapshot_payload())
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = client.post("/api/analyses", json=_snapshot_payload())
    assert second.status_code == 200
    assert second.json()["id"] == first_id

    mock_analyze.assert_called_once()


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"url": "not-a-url"},
        {"description": None, "content": None},  # neither field present: nothing to summarise
    ],
)
def test_invalid_snapshot_is_rejected_without_ai_call(overrides, client):
    with patch("app.services.analysis.openai_provider.analyze") as mock_analyze:
        response = client.post("/api/analyses", json=_snapshot_payload(**overrides))

    assert response.status_code == 422
    mock_analyze.assert_not_called()


@pytest.mark.parametrize(
    "exception, expected_status",
    [
        (ProviderTimeout("timed out"), 504),
        (ProviderUnavailable("quota exhausted"), 503),
        (ProviderError("refused"), 502),
    ],
)
@patch("app.services.analysis.openai_provider.analyze")
def test_failed_generation_returns_controlled_error_and_persists_nothing(
    mock_analyze, exception, expected_status, client, db_session
):
    mock_analyze.side_effect = exception

    response = client.post("/api/analyses", json=_snapshot_payload(url="https://example.com/news/failed"))

    assert response.status_code == expected_status
    assert db_session.query(ArticleAnalysis).count() == 0


def test_concurrent_insert_race_returns_existing_row_not_a_duplicate(db_session):
    """Directly exercises store.insert_or_get_existing against real
    Postgres: simulates two requests racing to insert the same URL by
    inserting the 'winning' row first, then calling the same insert path
    a second time for the same snapshot -- it must recover via the
    UNIQUE(article_url) violation, not raise or create a duplicate.
    """
    snapshot = AnalysisSnapshot(**_snapshot_payload(url="https://example.com/news/race"))
    output = _ai_output()

    winner, created_first = insert_or_get_existing(db_session, snapshot, output)
    assert created_first is True

    loser, created_second = insert_or_get_existing(db_session, snapshot, output)
    assert created_second is False
    assert loser.id == winner.id

    assert db_session.query(ArticleAnalysis).filter_by(article_url=snapshot.url).count() == 1


@patch("app.services.analysis.openai_provider.analyze")
@patch("app.services.news.gnews.search")
def test_list_analyses_returns_saved_records_newest_first_no_external_calls(
    mock_search, mock_analyze, client, db_session
):
    older = ArticleAnalysis(
        article_url="https://example.com/older",
        title="Older",
        summary="Older summary.",
        sentiment="neutral",
        content_scope="excerpt",
        model="gpt-4o-mini",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    newer = ArticleAnalysis(
        article_url="https://example.com/newer",
        title="Newer",
        summary="Newer summary.",
        sentiment="positive",
        content_scope="excerpt",
        model="gpt-4o-mini",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    db_session.add_all([older, newer])
    db_session.commit()

    response = client.get("/api/analyses")

    assert response.status_code == 200
    urls_in_order = [a["article_url"] for a in response.json()["analyses"]]
    assert urls_in_order == ["https://example.com/newer", "https://example.com/older"]
    mock_search.assert_not_called()
    mock_analyze.assert_not_called()


def test_list_analyses_returns_empty_array_when_none_exist(client):
    response = client.get("/api/analyses")

    assert response.status_code == 200
    assert response.json() == {"analyses": []}


def test_get_analysis_by_id_returns_saved_resource(client, db_session):
    row = ArticleAnalysis(
        article_url="https://example.com/direct",
        title="Direct lookup",
        summary="A summary.",
        sentiment="negative",
        content_scope="excerpt",
        model="gpt-4o-mini",
    )
    db_session.add(row)
    db_session.commit()

    response = client.get(f"/api/analyses/{row.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == row.id
    assert body["sentiment"] == "negative"
    assert "model" not in body


def test_get_analysis_by_id_returns_404_when_missing(client):
    response = client.get("/api/analyses/999999")

    assert response.status_code == 404
