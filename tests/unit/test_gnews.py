"""Unit tests for the GNews provider's own logic: no DB, no real network --
only the httpx client is mocked, and several tests call the private
parsing/normalisation functions directly. These are the functions that
were previously only exercised indirectly (via tests that mock
gnews.search itself away entirely), so the actual GNews-shape parsing,
malformed-article filtering, dedup, null-safe date sorting and
status-code-to-ProviderError mapping had zero direct coverage.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.errors import ProviderError, ProviderTimeout, ProviderUnavailable
from app.services.news import gnews


def _settings(**overrides) -> SimpleNamespace:
    data = dict(gnews_api_key="test-key", gnews_base_url="https://gnews.example/api/v4/search")
    data.update(overrides)
    return SimpleNamespace(**data)


# --- _normalise -------------------------------------------------------------


def test_normalise_skips_article_with_no_url():
    articles = gnews._normalise([{"title": "No URL here"}])
    assert articles == []


def test_normalise_skips_article_with_blank_url():
    articles = gnews._normalise([{"url": "   ", "title": "Blank URL"}])
    assert articles == []


@pytest.mark.parametrize("bad_url", ["ftp://example.com/a", "javascript:alert(1)", "example.com/no-scheme"])
def test_normalise_skips_non_http_url(bad_url):
    articles = gnews._normalise([{"url": bad_url, "title": "Not http(s)"}])
    assert articles == []


def test_normalise_skips_article_with_no_title():
    articles = gnews._normalise([{"url": "https://example.com/a"}])
    assert articles == []


def test_normalise_skips_article_with_blank_title():
    articles = gnews._normalise([{"url": "https://example.com/a", "title": "   "}])
    assert articles == []


def test_normalise_dedupes_same_url_keeping_first():
    raw = [
        {"url": "https://example.com/a", "title": "First version"},
        {"url": "https://example.com/a", "title": "Second version (duplicate URL)"},
    ]
    articles = gnews._normalise(raw)
    assert len(articles) == 1
    assert articles[0].title == "First version"


def test_normalise_handles_missing_source():
    articles = gnews._normalise([{"url": "https://example.com/a", "title": "T"}])
    assert articles[0].source is None


def test_normalise_handles_malformed_source_shape():
    # GNews always sends source as an object; tolerate a provider sending
    # something else rather than raising.
    articles = gnews._normalise([{"url": "https://example.com/a", "title": "T", "source": "Not a dict"}])
    assert articles[0].source is None


def test_normalise_extracts_source_name():
    articles = gnews._normalise(
        [{"url": "https://example.com/a", "title": "T", "source": {"name": "Example News", "url": "https://example.com"}}]
    )
    assert articles[0].source == "Example News"


def test_normalise_treats_empty_description_and_content_as_none():
    articles = gnews._normalise([{"url": "https://example.com/a", "title": "T", "description": "", "content": ""}])
    assert articles[0].description is None
    assert articles[0].content is None


def test_normalise_trims_whitespace_from_url_and_title():
    articles = gnews._normalise([{"url": "  https://example.com/a  ", "title": "  Title  "}])
    assert articles[0].url == "https://example.com/a"
    assert articles[0].title == "Title"


def test_normalise_never_sets_analysis_id():
    articles = gnews._normalise([{"url": "https://example.com/a", "title": "T"}])
    assert articles[0].analysis_id is None


def test_normalise_skips_only_malformed_entries_keeps_the_rest():
    raw = [
        {"url": "https://example.com/good", "title": "Good one"},
        {"title": "Missing URL"},
        {"url": "not-a-url", "title": "Bad scheme"},
        {"url": "https://example.com/good2", "title": ""},
    ]
    articles = gnews._normalise(raw)
    assert [a.url for a in articles] == ["https://example.com/good"]


# --- _parse_published_at -----------------------------------------------------


def test_parse_published_at_none_for_missing_value():
    assert gnews._parse_published_at(None) is None
    assert gnews._parse_published_at("") is None


def test_parse_published_at_parses_z_suffix():
    result = gnews._parse_published_at("2026-11-25T08:00:00Z")
    assert result == datetime(2026, 11, 25, 8, 0, 0, tzinfo=timezone.utc)


def test_parse_published_at_parses_explicit_offset():
    result = gnews._parse_published_at("2026-11-25T08:00:00+02:00")
    assert result is not None
    assert result.utcoffset().total_seconds() == 2 * 3600


def test_parse_published_at_none_for_malformed_value():
    assert gnews._parse_published_at("not a date") is None


# --- _format_gnews_datetime --------------------------------------------------


def test_format_gnews_datetime():
    value = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert gnews._format_gnews_datetime(value) == "2026-01-02T03:04:05Z"


# --- search() -----------------------------------------------------------------


def _mock_client(response=None, side_effect=None):
    client = MagicMock()
    if side_effect is not None:
        client.get.side_effect = side_effect
    else:
        client.get.return_value = response
    return client


@patch("app.services.news.gnews._client")
def test_search_sends_expected_query_params(mock_client_factory):
    client = _mock_client(response=httpx.Response(200, json={"articles": []}))
    mock_client_factory.return_value = client

    gnews.search("artificial intelligence", _settings())

    called_url, called_kwargs = client.get.call_args
    assert called_url[0] == "https://gnews.example/api/v4/search"
    params = called_kwargs["params"]
    assert params["q"] == "artificial intelligence"
    assert params["lang"] == "en"
    assert params["max"] == 10
    assert params["sortby"] == "publishedAt"
    assert params["apikey"] == "test-key"
    # GNews's expected datetime shape, not ours
    assert params["from"].endswith("Z")
    assert params["to"].endswith("Z")


@patch("app.services.news.gnews._client")
def test_search_sorts_newest_first_with_nulls_last(mock_client_factory):
    payload = {
        "articles": [
            {"url": "https://example.com/older", "title": "Older", "publishedAt": "2026-01-01T00:00:00Z"},
            {"url": "https://example.com/no-date", "title": "No date"},
            {"url": "https://example.com/newer", "title": "Newer", "publishedAt": "2026-06-01T00:00:00Z"},
        ]
    }
    mock_client_factory.return_value = _mock_client(response=httpx.Response(200, json=payload))

    articles = gnews.search("q", _settings())

    assert [a.url for a in articles] == [
        "https://example.com/newer",
        "https://example.com/older",
        "https://example.com/no-date",
    ]


@patch("app.services.news.gnews._client")
def test_search_skips_malformed_articles_in_real_response(mock_client_factory):
    payload = {
        "articles": [
            {"url": "https://example.com/good", "title": "Good"},
            {"title": "Missing URL"},
        ]
    }
    mock_client_factory.return_value = _mock_client(response=httpx.Response(200, json=payload))

    articles = gnews.search("q", _settings())

    assert [a.url for a in articles] == ["https://example.com/good"]


@patch("app.services.news.gnews._client")
def test_search_raises_provider_timeout(mock_client_factory):
    mock_client_factory.return_value = _mock_client(side_effect=httpx.TimeoutException("timed out"))
    with pytest.raises(ProviderTimeout):
        gnews.search("q", _settings())


@patch("app.services.news.gnews._client")
def test_search_raises_provider_error_on_connection_failure(mock_client_factory):
    mock_client_factory.return_value = _mock_client(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(ProviderError):
        gnews.search("q", _settings())


@patch("app.services.news.gnews._client")
def test_search_raises_provider_unavailable_on_429(mock_client_factory):
    mock_client_factory.return_value = _mock_client(response=httpx.Response(429, json={"error": "quota"}))
    with pytest.raises(ProviderUnavailable):
        gnews.search("q", _settings())


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
@patch("app.services.news.gnews._client")
def test_search_raises_provider_error_on_4xx(mock_client_factory, status_code):
    mock_client_factory.return_value = _mock_client(response=httpx.Response(status_code, json={"error": "bad"}))
    with pytest.raises(ProviderError):
        gnews.search("q", _settings())


@pytest.mark.parametrize("status_code", [500, 502, 503])
@patch("app.services.news.gnews._client")
def test_search_raises_provider_error_on_5xx(mock_client_factory, status_code):
    mock_client_factory.return_value = _mock_client(response=httpx.Response(status_code, json={"error": "bad"}))
    with pytest.raises(ProviderError):
        gnews.search("q", _settings())


@patch("app.services.news.gnews._client")
def test_search_raises_provider_error_on_unparsable_json(mock_client_factory):
    mock_client_factory.return_value = _mock_client(response=httpx.Response(200, content=b"not json"))
    with pytest.raises(ProviderError):
        gnews.search("q", _settings())
