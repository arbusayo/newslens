"""Shared pytest fixtures: isolated test database, dummy provider settings.

Settings() is a process-wide cached singleton (see app/config.py), so the
required env vars below must exist before anything imports app.config —
including a dedicated test database, never the dev/hosted one (spec §11).

These are unconditional overrides, NOT os.environ.setdefault(): running
via `docker compose run --rm app pytest` inherits every real value from
.env through Compose's env_file: directive before Python even starts, so
setdefault here would silently be a no-op and tests would run against
the real database and real-looking keys. Every value below must win
regardless of what's already in the environment.
"""
import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ["NEWS_PROVIDER"] = "gnews"
os.environ["GNEWS_API_KEY"] = "test-gnews-key"
os.environ["GNEWS_BASE_URL"] = "https://gnews.io/api/v4/search"
os.environ["AI_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = "test-openai-key"
os.environ["OPENAI_MODEL"] = "gpt-4o-mini"

_TEST_DB_NAME = "newslens_test"
_ADMIN_DATABASE_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql://newslens:newslens@db:5432/postgres"
)
os.environ["DATABASE_URL"] = f"postgresql+psycopg://newslens:newslens@db:5432/{_TEST_DB_NAME}"


def _ensure_test_database_exists() -> None:
    """Create the isolated test database if it doesn't exist yet.

    Connects to Postgres's own maintenance database to do so — never the
    app's real database, so tests can never touch dev or hosted data.
    """
    with psycopg.connect(_ADMIN_DATABASE_URL, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (_TEST_DB_NAME,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')


_ensure_test_database_exists()

from app.database import Base, get_engine  # noqa: E402  (must follow the env setup above)
from app.main import app  # noqa: E402

Base.metadata.create_all(bind=get_engine())


@pytest.fixture(autouse=True)
def _clean_database():
    """Truncate the single table before every test, for isolation."""
    with get_engine().begin() as conn:
        conn.exec_driver_sql("TRUNCATE TABLE article_analyses RESTART IDENTITY")
    yield


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session():
    """Direct DB access for arranging test data, independent of the app's
    own per-request sessions (both point at the same test database).
    """
    with Session(get_engine()) as session:
        yield session
