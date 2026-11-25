"""SQLAlchemy model for the single `article_analyses` table (spec §7).

sentiment and content_scope are plain String columns with a CheckConstraint
rather than a SQLAlchemy/Postgres ENUM type, so adding a value later is a
code change, not a database migration (spec §9: no migration
infrastructure for this schema).
"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ArticleAnalysis(Base):
    __tablename__ = "article_analyses"
    __table_args__ = (
        CheckConstraint(
            "sentiment IN ('positive', 'neutral', 'negative')",
            name="ck_article_analyses_sentiment",
        ),
        CheckConstraint(
            "content_scope IN ('excerpt', 'full')",
            name="ck_article_analyses_content_scope",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[str] = mapped_column(String(10), nullable=False)
    content_scope: Mapped[str] = mapped_column(String(10), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
