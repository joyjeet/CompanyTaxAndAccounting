"""Authentication: real JWT validation (Entra ID / OIDC).

Tokens come in via the standard `Authorization: Bearer <jwt>` header. The
heavy lifting (signature, issuer, audience, expiry, claim mapping) lives in
`app.security.auth.IdentityProvider`; this module is only the FastAPI
adapter that returns an `AuthIdentity` or raises HTTP 401.

Critical contract: the tenant context is derived ONLY from the validated
identity, never from request body / query / non-Authorization headers. The
existing `db_session` dependency uses this `AuthIdentity` to set the RLS
GUCs; nothing about that path changed in Phase 3.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request, status

from app.db.tenant import AccessScope, TenantContext


@dataclass(frozen=True, slots=True)
class AuthIdentity:
    """Authenticated identity derived from the validated token.

    Scope semantics:
      - FIRM: a CPA-firm staff member; client_id may be None (sees all clients).
      - CLIENT: a portal user; client_id is required.
    """

    subject: str  # principal id (Entra ID `oid`).
    firm_id: UUID
    scope: AccessScope
    client_id: UUID | None = None

    def to_tenant_context(self) -> TenantContext:
        return TenantContext(
            firm_id=self.firm_id,
            client_id=self.client_id,
            scope=self.scope,
        )


def _extract_bearer(request: Request) -> str:
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return parts[1].strip()


def get_identity(request: Request) -> AuthIdentity:
    """Validate the bearer token and return the tenant identity.

    Fail-closed: ANY validation failure (missing token, expired, wrong audience,
    bad signature, malformed claims) results in 401. There is no default
    tenant; there is no anonymous mode.
    """
    # Imported lazily so the security module can import auth types without
    # circular imports.
    from app.security.auth import InvalidTokenError, get_identity_provider

    token = _extract_bearer(request)
    try:
        return get_identity_provider().validate(token=token)
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
