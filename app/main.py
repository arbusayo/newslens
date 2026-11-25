"""Application setup: FastAPI instance.

No access control is applied — the hosted demo is intentionally public
(product decision; see README for the accepted cost/exposure tradeoff).
Serves the static UI from the same origin as the API (spec §4), no
separate frontend server or build pipeline.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routes import router

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Single-table schema, no migration framework: create_all() is
    # idempotent and sufficient (spec §4/§7/§9).
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="NewsLens", lifespan=lifespan)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
