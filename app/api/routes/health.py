"""Health endpoints. No tenant context required."""
from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.db.session import engine

router = APIRouter(tags=["health"])


@router.get("/livez")
def livez() -> dict[str, str]:
    """Liveness — the process is up. Used by container probes."""
    return {"status": "alive"}


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Backwards-compatible alias for /livez. Kept for existing probes."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(response: Response) -> dict[str, object]:
    """Readiness — every downstream we need before accepting traffic.

    Returns 503 on first failed dependency. Fail-closed by design: an
    unreachable DB must drain the pod from the load balancer immediately,
    not silently degrade.
    """
    checks: dict[str, str] = {}
    ok = True

    # Postgres
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error: {type(e).__name__}"
        ok = False

    if not ok:
        response.status_code = 503
    return {"status": "ready" if ok else "degraded", "checks": checks}
