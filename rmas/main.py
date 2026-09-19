"""
main.py — FastAPI app factory. Configuration loading, router registration,
domain-exception -> HTTP translation, and a basic health endpoint.

Legacy Code.gs's doGet()/include() have no equivalent here (they served the
Apps Script HTML shell) — the frontend is a separate static app under
frontend/, served independently and talking to this API over fetch().
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from rmas.config import get_settings
from rmas.routers import allocations, audit, auth, diagnostics, reports, staging
from rmas.services.exceptions import DomainError

settings = get_settings()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.app_version)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # tighten to the deployed frontend origin before production use
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.default_status, content={"code": exc.code, "message": exc.message})

    @app.get("/health")
    def health() -> dict:
        return {"app_name": settings.app_name, "app_version": settings.app_version, "status": "ok"}

    app.include_router(auth.router)
    app.include_router(allocations.router)
    app.include_router(staging.router)
    app.include_router(reports.router)
    app.include_router(audit.router)
    app.include_router(diagnostics.router)

    return app


app = create_app()
