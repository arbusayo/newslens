"""Application setup: FastAPI instance.

No access control is applied — the hosted demo is intentionally public
(product decision; see README for the accepted cost/exposure tradeoff).
Routes are added in later increments.
"""
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="NewsLens")
    return app


app = create_app()
