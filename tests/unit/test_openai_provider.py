"""Unit tests for the OpenAI provider: no DB, no real network -- only the
SDK client itself is mocked. This is genuine unit-level logic (response
parsing, validation, SDK-exception mapping), unlike tests/integration/.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from app.schemas import AnalysisSnapshot, Sentiment
from app.services.analysis import openai_provider
from app.services.errors import ProviderError, ProviderTimeout, ProviderUnavailable

_FAKE_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _snapshot() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        url="https://example.com/a",
        title="Title",
        source="Example News",
        published_at=None,
        description="A description.",
        content=None,
    )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(openai_api_key="test-key", openai_model="gpt-4o-mini")


def _completion(parsed=None, refusal=None, model="gpt-4o-mini-2024-07-18"):
    message = SimpleNamespace(parsed=parsed, refusal=refusal)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], model=model)


def _mock_client(**parse_kwargs):
    client = MagicMock()
    if "side_effect" in parse_kwargs:
        client.beta.chat.completions.parse.side_effect = parse_kwargs["side_effect"]
    else:
        client.beta.chat.completions.parse.return_value = parse_kwargs["return_value"]
    return client


@patch("app.services.analysis.openai_provider._client")
def test_analyze_returns_summary_sentiment_and_resolved_model(mock_client_factory):
    parsed = SimpleNamespace(summary="A fair, factual summary.", sentiment=Sentiment.neutral)
    mock_client_factory.return_value = _mock_client(
        return_value=_completion(parsed=parsed, model="gpt-4o-mini-2024-07-18")
    )

    result = openai_provider.analyze(_snapshot(), _settings())

    assert result.summary == "A fair, factual summary."
    assert result.sentiment == Sentiment.neutral
    assert result.model == "gpt-4o-mini-2024-07-18"


@patch("app.services.analysis.openai_provider._client")
def test_analyze_raises_provider_error_on_refusal(mock_client_factory):
    mock_client_factory.return_value = _mock_client(return_value=_completion(refusal="cannot comply"))

    with pytest.raises(ProviderError):
        openai_provider.analyze(_snapshot(), _settings())


@patch("app.services.analysis.openai_provider._client")
def test_analyze_rejects_blank_summary(mock_client_factory):
    parsed = SimpleNamespace(summary="   ", sentiment=Sentiment.neutral)
    mock_client_factory.return_value = _mock_client(return_value=_completion(parsed=parsed))

    with pytest.raises(ProviderError):
        openai_provider.analyze(_snapshot(), _settings())


@patch("app.services.analysis.openai_provider._client")
def test_analyze_rejects_oversized_summary(mock_client_factory):
    parsed = SimpleNamespace(summary="x" * 1001, sentiment=Sentiment.neutral)
    mock_client_factory.return_value = _mock_client(return_value=_completion(parsed=parsed))

    with pytest.raises(ProviderError):
        openai_provider.analyze(_snapshot(), _settings())


@pytest.mark.parametrize(
    "sdk_exception, expected_error",
    [
        (APITimeoutError(request=_FAKE_REQUEST), ProviderTimeout),
        (APIConnectionError(request=_FAKE_REQUEST), ProviderError),
        (
            RateLimitError("rate limited", response=httpx.Response(429, request=_FAKE_REQUEST), body=None),
            ProviderUnavailable,
        ),
        (
            APIStatusError("server error", response=httpx.Response(500, request=_FAKE_REQUEST), body=None),
            ProviderError,
        ),
    ],
)
@patch("app.services.analysis.openai_provider._client")
def test_sdk_exceptions_map_to_controlled_provider_errors(mock_client_factory, sdk_exception, expected_error):
    mock_client_factory.return_value = _mock_client(side_effect=sdk_exception)

    with pytest.raises(expected_error):
        openai_provider.analyze(_snapshot(), _settings())
