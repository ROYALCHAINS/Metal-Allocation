"""
main.py
Royal Metal Allocation System — Python port

FastAPI application factory. Owns HTTP wiring only — business logic belongs
in services/, not here (CLAUDE.md section 2, "Where things belong").

Run it either way, from inside this directory:
    python main.py
    uvicorn main:app --reload
"""

from pathlib import Path

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from config import settings
from routers.allocations import router as allocations_router
from routers.audit import router as audit_router
from routers.auth import router as auth_router
from routers.reports import router as reports_router
from routers.sectors import router as sectors_router
from schemas.common import HealthResponse

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


class _NoCacheStatic(StaticFiles):
    """Serve the frontend with caching disabled.

    ES modules are cached aggressively by browsers, so during development an
    edited view would keep running the old code until a hard refresh — which
    looks exactly like "my change didn't apply". A plain refresh should always
    pick up the current file. Revisit before any production deployment, where
    cache headers are wanted.
    """

    def is_not_modified(self, response_headers, request_headers) -> bool:  # noqa: D102
        return False

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key, same_site="lax")
    app.include_router(auth_router)
    app.include_router(sectors_router)
    app.include_router(allocations_router)
    app.include_router(reports_router)
    app.include_router(audit_router)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=settings.app_version)

    # Frontend static files — mounted last so /health and /auth/* above take
    # precedence. Same-origin, so the session cookie needs no CORS handling.
    if FRONTEND_DIR.is_dir():
        app.mount("/", _NoCacheStatic(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    # No --reload here (it needs a subprocess import that isn't reliable
    # when launched as a plain script from anywhere). Use
    # `uvicorn main:app --reload` from inside this directory during active
    # development instead.
    uvicorn.run(app, host="127.0.0.1", port=8000)
