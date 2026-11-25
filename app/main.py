"""Application setup: FastAPI instance.

No access control is applied — the hosted demo is intentionally public
(product decision; see README for the accepted cost/exposure tradeoff).
Static UI assets are mounted in a later increment.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Single-table schema, no migration framework: create_all() is
    # idempotent and sufficient (spec §4/§7/§9).
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="NewsLens", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
