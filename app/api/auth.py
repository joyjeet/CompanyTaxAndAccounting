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


def _requested_uuid(request: Request, header: str) -> UUID | None:
    """Read an optional context hint from a request header.

    These are hints only. `resolve_identity` checks them against the caller's
    own memberships, so a forged header can narrow access but never widen it.
    """
    raw = request.headers.get(header)
    if not raw:
        return None
    try:
        return UUID(raw.strip())
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{header} is not a valid UUID",
        ) from e


def get_identity(request: Request) -> AuthIdentity:
    """Validate the bearer token and return the tenant identity.

    Fail-closed: ANY validation failure (missing token, expired, wrong audience,
    bad signature, malformed claims) results in 401. There is no default
    tenant; there is no anonymous mode.

    With `app_authz_source='membership'` the token only establishes *who* the
    caller is; the firm/client/scope come from `firm_membership`. See
    `app.domain.identity_resolution`.
    """
    # Imported lazily so the security module can import auth types without
    # circular imports.
    from app.core.config import get_settings
    from app.security.auth import InvalidTokenError, get_identity_provider

    token = _extract_bearer(request)
    provider = get_identity_provider()
    settings = get_settings()

    if settings.app_authz_source == "claims":
        try:
            return provider.validate(token=token)
        except InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    try:
        principal = provider.validate_principal(token=token)
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    return resolve_request_identity(
        subject=principal.subject,
        requested_firm_id=_requested_uuid(request, "X-CTAA-Firm"),
        requested_client_id=_requested_uuid(request, "X-CTAA-Client"),
    )


def resolve_request_identity(
    *,
    subject: str,
    requested_firm_id: UUID | None = None,
    requested_client_id: UUID | None = None,
) -> AuthIdentity:
    """Membership lookup + HTTP error mapping.

    Note the status codes: these are *authenticated* callers, so nothing here
    is a 401. Sending 401 would make the SPA bounce the user back through the
    identity provider, which cannot fix a missing membership and produces a
    redirect loop.
    """
    from app.db.session import subject_session
    from app.domain.identity_resolution import (
        AmbiguousContextError,
        NoMembershipError,
        UnknownContextError,
        resolve_identity,
    )

    with subject_session(subject) as sess:
        try:
            return resolve_identity(
                sess,
                subject=subject,
                requested_firm_id=requested_firm_id,
                requested_client_id=requested_client_id,
            )
        except AmbiguousContextError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": str(e),
                    "code": "context_required",
                    "options": [
                        {
                            "firm_id": str(o.firm_id),
                            "firm_name": o.firm_name,
                            "role": o.role.value,
                            "client_id": str(o.client_id) if o.client_id else None,
                            "client_name": o.client_name,
                        }
                        for o in e.options
                    ],
                },
            ) from e
        except (NoMembershipError, UnknownContextError) as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(e)
            ) from e
