"""FastAPI app entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.routes import (
    clients,
    documents,
    drafts,
    health,
    journal_entries,
    reports,
    rules_engine,
    statements_preview,
    team,
    tax,
)
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.integrations.registry import bootstrap_from_settings


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    # Wire production integrations from env (no-op for test/local defaults).
    # Must happen before the first request so the registry has the right
    # storage backend installed.
    bootstrap_from_settings()

    app = FastAPI(
        title="CTAA — Company Tax and Accounting",
        version="0.1.0",
        description=(
            "AI-assisted financial statement and tax preparation platform. "
            "Foundation phase: deterministic accounting core + tenant isolation. "
            "Phase 2: document ingestion + AI-drafted classification."
        ),
    )

    # Middleware: order matters. Last-added is the outermost wrapper, so the
    # actual execution order on a request is bottom-up here:
    #   1. RequestContextMiddleware (innermost — sets ctx vars)
    #   2. RateLimitMiddleware
    #   3. SecurityHeadersMiddleware
    #   4. CORS (outermost — handles preflight first)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

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
    app.include_router(journal_entries.router)
    app.include_router(statements_preview.router)
    app.include_router(tax.router)
    app.include_router(reports.router)
    app.include_router(rules_engine.router)
    app.include_router(team.router)

    # Admin routes (Phase 7) — crypto-shred + audit export. Gated on firm
    # admin scope inside the router itself.
    from app.api.routes import admin, audit_export

    app.include_router(admin.router)
    app.include_router(audit_export.router)

    # Dev-only routes: only mount when the server is in non-prod test-mode.
    # The router itself also performs a runtime check.
    if settings.app_env != "prod" and settings.app_auth_mode == "test":
        from app.api.routes import auth_dev

        app.include_router(auth_dev.router)

    # Demo / seed helpers: mounted whenever we're not in prod. Gated to
    # firm-scope inside the router so portal users can't use it.
    if settings.app_env != "prod":
        from app.api.routes import dev

        app.include_router(dev.router)

    return app


app = create_app()
