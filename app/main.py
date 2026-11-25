"""Application setup: FastAPI instance and health endpoint.

Static UI assets and API routes are added in later increments. No access
control is applied — the hosted demo is intentionally public (product
decision; see README for the accepted cost/exposure tradeoff).
"""
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="NewsLens")

    @app.get("/health")
    def health() -> dict:
        """Liveness only: no DB query, no provider call, no secrets."""
        return {"status": "ok"}

    return app


app = create_app()
