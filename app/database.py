"""Database engine, session lifecycle and schema initialisation.

No migration framework: this is a single-table schema (spec §7), so
create_all() at startup is sufficient and idempotent. Engine/session
factory are resolved lazily and cached, same pattern as get_settings() —
importing this module never touches the database.
"""
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, always closed."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create any missing tables. Idempotent; safe to call on every startup."""
    import app.models  # noqa: F401  # registers ArticleAnalysis on Base.metadata

    Base.metadata.create_all(bind=get_engine())
