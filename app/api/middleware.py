"""HTTP middleware for Phase 7 hardening.

* RequestContextMiddleware  — populates ContextVars for logging + tracing.
* SecurityHeadersMiddleware — sets baseline browser-safety headers.
* RateLimitMiddleware       — in-memory token bucket per (client-ip, route).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.context import (
    access_scope_var,
    actor_var,
    client_id_var,
    firm_id_var,
    request_id_var,
)

# ---------------------------------------------------------------------------
# Request context
# ---------------------------------------------------------------------------

class RequestContextMiddleware(BaseHTTPMiddleware):
    """Set ContextVars per request so the JSON logger can tag every record.

    The tenant fields (firm_id/client_id/actor) are intentionally NOT set
    here — they are populated by the `db_session` dependency once the JWT is
    validated, so that pre-auth requests don't inherit stale values.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        tokens: list = [
            request_id_var.set(rid),
            firm_id_var.set(None),
            client_id_var.set(None),
            actor_var.set(None),
            access_scope_var.set(None),
        ]
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            for t, var in zip(
                tokens,
                (
                    request_id_var,
                    firm_id_var,
                    client_id_var,
                    actor_var,
                    access_scope_var,
                ),
                strict=True,
            ):
                var.reset(t)


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

_DEFAULT_CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply baseline browser-safety headers to every response."""

    def __init__(self, app, *, csp: str = _DEFAULT_CSP) -> None:
        super().__init__(app)
        self._csp = csp

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        h = response.headers
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        h.setdefault("Content-Security-Policy", self._csp)
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        # API responses must never be cached by intermediaries.
        if request.url.path.startswith("/api") or request.url.path.startswith("/v1"):
            h.setdefault("Cache-Control", "no-store")
        return response


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class _Bucket:
    __slots__ = ("tokens", "last")

    def __init__(self, tokens: float, last: float) -> None:
        self.tokens = tokens
        self.last = last


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket per (client-ip, route-prefix).

    In production this is the WAF + Front Door's job. This middleware is a
    defensive fallback in case the app is reached directly (e.g. a misrouted
    private endpoint), and it gives a deterministic 429 for tests.

    NOTE: in-memory state means quotas reset on restart and are not shared
    across replicas. For multi-replica throttling, deploy with a distributed
    backend (Redis) or rely on Front Door WAF rate-limit rules.
    """

    DEFAULT_RATE_PER_MIN = 600        # generous baseline
    SENSITIVE_RATE_PER_MIN = 30       # /auth/*, /admin/*
    UPLOAD_RATE_PER_MIN = 60          # /documents/upload

    _SENSITIVE_PREFIXES = ("/auth/", "/admin/")
    _UPLOAD_PREFIXES = ("/documents/upload", "/documents:upload")

    def __init__(self, app) -> None:
        super().__init__(app)
        self._lock = asyncio.Lock()
        self._buckets: dict[tuple[str, str], _Bucket] = defaultdict(
            lambda: _Bucket(tokens=self.DEFAULT_RATE_PER_MIN, last=time.monotonic())
        )

    def _route_key(self, path: str) -> tuple[str, int]:
        if any(path.startswith(p) for p in self._SENSITIVE_PREFIXES):
            return ("sensitive", self.SENSITIVE_RATE_PER_MIN)
        if any(path.startswith(p) for p in self._UPLOAD_PREFIXES):
            return ("upload", self.UPLOAD_RATE_PER_MIN)
        return ("default", self.DEFAULT_RATE_PER_MIN)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        ip = request.client.host if request.client else "unknown"
        route, rate_per_min = self._route_key(request.url.path)
        async with self._lock:
            b = self._buckets[(ip, route)]
            now = time.monotonic()
            elapsed = now - b.last
            b.tokens = min(float(rate_per_min), b.tokens + elapsed * (rate_per_min / 60.0))
            b.last = now
            if b.tokens < 1.0:
                return Response(
                    content='{"detail":"rate limit exceeded"}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": "60"},
                )
            b.tokens -= 1.0
        return await call_next(request)
