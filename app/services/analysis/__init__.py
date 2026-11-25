"""The analysis service: everything about article_analyses lives here.

Public surface for the rest of the app — routes import from
app.services.analysis, never from its submodules directly. Internally
this package will hold both persistence (store.py: querying/saving
ArticleAnalysis rows) and, from the next increment on, the AI-provider
seam (e.g. openai_provider.py, dispatched by settings.ai_provider — the
same pattern as app.services.news) that generates new analyses.
"""
from app.services.analysis.store import attach_saved_analysis_ids

__all__ = ["attach_saved_analysis_ids"]
