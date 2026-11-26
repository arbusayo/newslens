"""Environment-backed application settings.

Resolved lazily via get_settings() rather than at import time, so importing
the app (e.g. in tests) never requires real provider keys to be set.
"""
from functools import lru_cache

from pydantic import field_validator
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

    @field_validator("database_url")
    @classmethod
    def _ensure_psycopg_driver(cls, value: str) -> str:
        """Managed Postgres providers (Render, Heroku-style hosts, etc.)
        generate plain `postgres://`/`postgresql://` connection strings --
        they have no reason to know we need SQLAlchemy's `+psycopg` driver
        suffix. Normalise it here so a hosting provider's own
        auto-generated DATABASE_URL just works, without requiring anyone
        to hand-edit it. A no-op for the `postgresql+psycopg://` strings
        already used locally.
        """
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://") :]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
