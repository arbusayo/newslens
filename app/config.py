"""Environment-backed application settings.

Resolved lazily via get_settings() rather than at import time, so importing
the app (e.g. in tests) never requires real provider keys to be set.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # News provider — selects a module in app/services/news/
    news_provider: str
    gnews_api_key: str
    gnews_base_url: str

    # AI provider — selects a module in app/services/analysis/
    ai_provider: str
    openai_api_key: str
    openai_model: str

    database_url: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
