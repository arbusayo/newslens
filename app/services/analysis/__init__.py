"""The analysis service: everything about article_analyses lives here.

Public surface for the rest of the app — routes import from
app.services.analysis, never from its submodules directly. Internally
this package holds persistence (store.py) and the AI-provider seam
(e.g. openai_provider.py, dispatched by settings.ai_provider — the same
pattern as app.services.news) that generates new analyses.

Adding an AI provider: write a module with the same `analyze(snapshot,
settings) -> AIAnalysisOutput` signature (raising ProviderError /
ProviderTimeout / ProviderUnavailable on failure), then add one entry to
_PROVIDER_MODULES below.
"""
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ArticleAnalysis
from app.schemas import AIAnalysisOutput, AnalysisSnapshot
from app.services.errors import ProviderError

from . import openai_provider
from .store import attach_saved_analysis_ids, find_by_url, insert_or_get_existing

_PROVIDER_MODULES = {
    "openai": openai_provider,
}


def create_or_get_analysis(
    snapshot: AnalysisSnapshot, settings: Settings, db: Session
) -> tuple[ArticleAnalysis, bool]:
    """Return (resource, created) — created=True only for a genuinely new
    row (-> 201), False for an already-saved or concurrently-won one
    (-> 200). Follows spec §7's dedup/transaction sequencing exactly:
    check first, release the read transaction, call the AI provider with
    no DB transaction held open, then insert in a short write transaction.
    """
    existing = find_by_url(db, snapshot.url)
    if existing is not None:
        return existing, False

    # spec §7 step 2: release the read transaction/session before the
    # external AI call -- don't hold a DB transaction or checked-out
    # connection open while waiting on inference.
    db.commit()

    output = _generate(snapshot, settings)

    return insert_or_get_existing(db, snapshot, output)


def _generate(snapshot: AnalysisSnapshot, settings: Settings) -> AIAnalysisOutput:
    module = _PROVIDER_MODULES.get(settings.ai_provider)
    if module is None:
        raise ProviderError(f"Unknown AI provider: {settings.ai_provider!r}")
    return module.analyze(snapshot, settings)


__all__ = ["attach_saved_analysis_ids", "create_or_get_analysis"]
