"""Dispatches to a news-provider implementation selected by settings.news_provider.

To add a provider: write a module with the same `search(query, settings)
-> list[NormalizedArticle]` signature (raising ProviderError /
ProviderTimeout / ProviderUnavailable on failure), then add one entry to
_PROVIDER_MODULES below. Modules, not bound functions, are stored here so
that patching a provider module's `search` attribute (as tests do) is
honoured at call time rather than bypassed by an eagerly-bound reference.
"""
from app.config import Settings
from app.schemas import NormalizedArticle
from app.services.errors import ProviderError

from . import gnews

_PROVIDER_MODULES = {
    "gnews": gnews,
}


def search_articles(query: str, settings: Settings) -> list[NormalizedArticle]:
    module = _PROVIDER_MODULES.get(settings.news_provider)
    if module is None:
        raise ProviderError(f"Unknown news provider: {settings.news_provider!r}")
    return module.search(query, settings)
