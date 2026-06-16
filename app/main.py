"""FastAPI app entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import clients, documents, drafts, health
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="CTAA — Company Tax and Accounting",
        version="0.1.0",
        description=(
            "AI-assisted financial statement and tax preparation platform. "
            "Foundation phase: deterministic accounting core + tenant isolation. "
            "Phase 2: document ingestion + AI-drafted classification."
        ),
    )

    # CORS — only the explicitly configured frontend origins. Credentials
    # are NOT enabled because we use bearer tokens, not cookies.
    origins = [o.strip() for o in settings.app_cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.include_router(health.router)
    app.include_router(clients.router)
    app.include_router(documents.router)
    app.include_router(drafts.router)

    # Dev-only routes: only mount when the server is in non-prod test-mode.
    # The router itself also performs a runtime check.
    if settings.app_env != "prod" and settings.app_auth_mode == "test":
        from app.api.routes import auth_dev

        app.include_router(auth_dev.router)

    return app


app = create_app()
