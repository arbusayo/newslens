"""HTTP endpoints. Base path /api, mounted in app.main.

Routes validate input, call services and map service-layer errors to HTTP
status codes — they don't build queries or talk to the database directly.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.schemas import AnalysisResource, AnalysisSnapshot, ArticlesResponse
from app.services.analysis import attach_saved_analysis_ids, create_or_get_analysis
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

    attach_saved_analysis_ids(articles, db)
    return ArticlesResponse(articles=articles)


@router.post("/analyses", response_model=AnalysisResource, status_code=201)
def create_analysis(
    snapshot: AnalysisSnapshot,
    response: Response,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> AnalysisResource:
    try:
        row, created = create_or_get_analysis(snapshot, settings, db)
    except ProviderTimeout as exc:
        logger.warning("analysis generation timed out: %s", exc)
        raise HTTPException(status_code=504, detail="AI analysis request timed out") from exc
    except ProviderUnavailable as exc:
        logger.warning("analysis generation unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="AI analysis temporarily unavailable") from exc
    except ProviderError as exc:
        logger.warning("analysis generation failed: %s", exc)
        raise HTTPException(status_code=502, detail="AI analysis error") from exc

    if created:
        response.headers["Location"] = f"/api/analyses/{row.id}"
    else:
        response.status_code = 200

    return AnalysisResource.model_validate(row)
