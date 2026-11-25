"""Queries against persisted article_analyses rows.

Internal to app.services.analysis: callers outside this package import
from app.services.analysis itself (its __init__.py), not from here
directly, so the package's internal split between persistence (this
file) and AI-provider calls (e.g. openai_provider.py, added in a later
increment) stays an implementation detail.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ArticleAnalysis
from app.schemas import NormalizedArticle


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
