"""Queries against persisted article_analyses rows.

Internal to app.services.analysis: callers outside this package import
from app.services.analysis itself (its __init__.py), not from here
directly, so the package's internal split between persistence (this
file) and AI-provider calls (e.g. openai_provider.py, added in a later
increment) stays an implementation detail.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ArticleAnalysis
from app.schemas import AIAnalysisOutput, AnalysisSnapshot, NormalizedArticle

# SQLAlchemy's default name for the UNIQUE(article_url) constraint
# (<table>_<column>_key), confirmed against the real schema (spec §7).
_DUPLICATE_URL_CONSTRAINT = "article_analyses_article_url_key"

# GNews is the only news provider today and only ever supplies an excerpt,
# never full article text -- so this is a constant for now, not a real
# decision point. Becomes one if a provider that supplies full text is
# ever added.
_CONTENT_SCOPE = "excerpt"


def attach_saved_analysis_ids(articles: list[NormalizedArticle], db: Session) -> None:
    """Fill in analysis_id for every article already saved, in one query
    for all returned URLs rather than one query per article (spec §5).
    """
    if not articles:
        return

    urls = [article.url for article in articles]
    rows = db.execute(
        select(ArticleAnalysis.id, ArticleAnalysis.article_url).where(ArticleAnalysis.article_url.in_(urls))
    ).all()
    id_by_url = {url: id_ for id_, url in rows}
    for article in articles:
        article.analysis_id = id_by_url.get(article.url)


def find_by_url(db: Session, url: str) -> ArticleAnalysis | None:
    return db.execute(select(ArticleAnalysis).where(ArticleAnalysis.article_url == url)).scalar_one_or_none()


def insert_or_get_existing(
    db: Session, snapshot: AnalysisSnapshot, output: AIAnalysisOutput
) -> tuple[ArticleAnalysis, bool]:
    """Insert a new analysis row, in a short write transaction (spec §7
    step 4). If a concurrent request won the race and inserted the same
    URL first, recover by returning its row with created=False instead
    of raising -- any other integrity error is re-raised unchanged.
    """
    row = ArticleAnalysis(
        article_url=snapshot.url,
        title=snapshot.title,
        source=snapshot.source,
        published_at=snapshot.published_at,
        description=snapshot.description,
        summary=output.summary,
        sentiment=output.sentiment.value,
        content_scope=_CONTENT_SCOPE,
        model=output.model,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if not _is_duplicate_url_violation(exc):
            raise
        existing = find_by_url(db, snapshot.url)
        if existing is None:
            # The constraint fired because a row with this URL exists --
            # it should be findable. Surface the original error if not.
            raise
        return existing, False
    return row, True


def _is_duplicate_url_violation(exc: IntegrityError) -> bool:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None) == _DUPLICATE_URL_CONSTRAINT
