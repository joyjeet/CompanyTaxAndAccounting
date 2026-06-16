"""Tenant-scoped DB session dependency for FastAPI handlers."""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.db.session import tenant_session


def db_session(identity: AuthIdentity = Depends(get_identity)) -> Iterator[Session]:
    """Open a transaction-scoped session with RLS GUCs set from the *identity*.

    The tenant context is derived from `identity` server-side. Request bodies
    and query params CANNOT influence it.
    """
    ctx = identity.to_tenant_context()
    with tenant_session(ctx) as sess:
        yield sess
