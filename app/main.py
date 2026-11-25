"""Application setup: FastAPI instance, health endpoint and demo-access auth.

Static UI assets and API routes are added in later increments.
"""
import base64
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

# Paths the hosting platform (or a bare health-checker) must reach without
# credentials. Keep this list minimal and explicit.
PUBLIC_PATHS = {"/health"}


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Restricts the demo to a single shared username/password.

    Deliberately simple: no sessions, no user table. See spec §10 — this is
    a restricted-demo access gate, not a production auth system.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        settings = get_settings()
        username, password = _parse_basic_auth(request.headers.get("authorization", ""))

        valid = secrets.compare_digest(username, settings.demo_username) and secrets.compare_digest(
            password, settings.demo_password
        )
        if not valid:
            return JSONResponse(
                {"detail": "Demo authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": "Basic"},
            )
        return await call_next(request)


def _parse_basic_auth(header: str) -> tuple[str, str]:
    if not header.startswith("Basic "):
        return "", ""
    try:
        decoded = base64.b64decode(header[len("Basic ") :]).decode("utf-8")
    except Exception:
        return "", ""
    username, _, password = decoded.partition(":")
    return username, password


def create_app() -> FastAPI:
    app = FastAPI(title="NewsLens")
    app.add_middleware(BasicAuthMiddleware)

    @app.get("/health")
    def health() -> dict:
        """Liveness only: no DB query, no provider call, no secrets."""
        return {"status": "ok"}

    return app


app = create_app()
