"""HTTP endpoints. Base path /api, mounted in app.main."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import ArticleAnalysis
from app.schemas import ArticlesResponse, NormalizedArticle
from app.services.errors import ProviderError, ProviderTimeout, ProviderUnavailable
from app.services.news import search_articles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_QUERY_MIN_LENGTH = 1
_QUERY_MAX_LENGTH = 200


@router.get("/articles", response_model=ArticlesResponse)
def get_articles(
    query: str = Query(..., description="Search keywords"),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> ArticlesResponse:
    trimmed = query.strip()
    if not (_QUERY_MIN_LENGTH <= len(trimmed) <= _QUERY_MAX_LENGTH):
        raise HTTPException(
            status_code=422,
            detail=f"query must be {_QUERY_MIN_LENGTH}-{_QUERY_MAX_LENGTH} characters after trimming whitespace",
        )

    try:
        articles = search_articles(trimmed, settings)
    except ProviderTimeout as exc:
        logger.warning("news search timed out: %s", exc)
        raise HTTPException(status_code=504, detail="News provider request timed out") from exc
    except ProviderUnavailable as exc:
        logger.warning("news search unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="News provider temporarily unavailable") from exc
    except ProviderError as exc:
        logger.warning("news search failed: %s", exc)
        raise HTTPException(status_code=502, detail="News provider error") from exc

    _attach_analysis_ids(articles, db)
    return ArticlesResponse(articles=articles)


def _attach_analysis_ids(articles: list[NormalizedArticle], db: Session) -> None:
    """One query for every returned URL, not one query per article (spec §5)."""
    if not articles:
        return
    urls = [article.url for article in articles]
    rows = db.execute(
        select(ArticleAnalysis.id, ArticleAnalysis.article_url).where(ArticleAnalysis.article_url.in_(urls))
    ).all()
    id_by_url = {url: id_ for id_, url in rows}
    for article in articles:
        article.analysis_id = id_by_url.get(article.url)
