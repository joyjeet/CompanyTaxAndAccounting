"""Tenant-scoped DB session dependency for FastAPI handlers."""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.core.context import access_scope_var, actor_var, client_id_var, firm_id_var
from app.db.session import tenant_session


def db_session(identity: AuthIdentity = Depends(get_identity)) -> Iterator[Session]:
    """Open a transaction-scoped session with RLS GUCs set from the *identity*.

    The tenant context is derived from `identity` server-side. Request bodies
    and query params CANNOT influence it.
    """
    ctx = identity.to_tenant_context()
    # Tag log context with the validated identity. ContextVars are reset by
    # the request middleware after the response is dispatched, so values do
    # not leak across requests sharing the worker process.
    firm_id_var.set(ctx.firm_id)
    client_id_var.set(ctx.client_id)
    access_scope_var.set(ctx.scope.value)
    actor_var.set(identity.subject)
    with tenant_session(ctx) as sess:
        yield sess
