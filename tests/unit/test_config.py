"""Unit tests for Settings' DATABASE_URL normalisation: no DB, no network.

Hosting providers (Render, Heroku-style hosts) generate plain
postgres://-or-postgresql://- connection strings with no reason to know
about SQLAlchemy's +psycopg driver suffix. This must be added
transparently, without requiring anyone to hand-edit a provider-generated
DATABASE_URL.
"""
import os

import pytest

from app.config import Settings


def _required_env(database_url: str) -> dict:
    return {
        "news_provider": "gnews",
        "gnews_api_key": "k",
        "gnews_base_url": "https://gnews.example",
        "ai_provider": "openai",
        "openai_api_key": "k",
        "openai_model": "m",
        "database_url": database_url,
    }


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "postgres://user:pass@host:5432/db",
            "postgresql+psycopg://user:pass@host:5432/db",
        ),
        (
            "postgresql://user:pass@host:5432/db",
            "postgresql+psycopg://user:pass@host:5432/db",
        ),
        (
            "postgresql://user:pass@host:5432/db?sslmode=require",
            "postgresql+psycopg://user:pass@host:5432/db?sslmode=require",
        ),
        (
            # Already correct (local dev / .env.example shape): untouched.
            "postgresql+psycopg://user:pass@host:5432/db",
            "postgresql+psycopg://user:pass@host:5432/db",
        ),
    ],
)
def test_database_url_gets_psycopg_driver_suffix(raw, expected):
    settings = Settings(_env_file=None, **_required_env(raw))
    assert settings.database_url == expected
