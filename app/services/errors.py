"""Shared provider-error types.

Both the news and AI provider dispatchers (app/services/news,
app/services/analysis) raise these; routes.py maps them to the status
codes in spec §6.5 in one place, regardless of which provider raised them.
"""


class ProviderError(Exception):
    """The provider returned an error response or an unusable result."""


class ProviderTimeout(ProviderError):
    """The request to the provider timed out."""


class ProviderUnavailable(ProviderError):
    """The provider is temporarily unavailable (e.g. quota exhausted)."""
