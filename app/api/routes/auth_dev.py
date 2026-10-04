"""Dev-only auth helpers.

Exposes `POST /auth/dev-token` which mints an HS256 JWT identical in shape to
what `TestTokenIdentityProvider` accepts. The endpoint refuses to register in
any environment where it could leak: it is wired into the FastAPI app ONLY
when `app_env != 'prod'` AND `app_auth_mode == 'test'`.

Without this endpoint the frontend dev experience would require either (a) a
live Entra ID tenant, or (b) hardcoded long-lived tokens checked into env
files. Neither is acceptable.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import owner_session, tenant_session
from app.db.tenant import AccessScope, TenantContext
from app.models.accounting import Client, Firm
from app.security.auth import mint_test_token

router = APIRouter(prefix="/auth", tags=["auth-dev"])


class DevTokenIn(BaseModel):
    sub: str = Field(min_length=1, max_length=128)
    role: Literal["firm_staff", "client_portal"]
    firm_id: UUID | None = None
    client_id: UUID | None = None
    expires_in_seconds: int = Field(default=3600, ge=60, le=86_400)


class DevTokenOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class DevLoginClientOut(BaseModel):
    id: UUID
    name: str


class DevLoginFirmOut(BaseModel):
    id: UUID
    name: str
    clients: list[DevLoginClientOut]


class DevLoginOptionsOut(BaseModel):
    firms: list[DevLoginFirmOut]


def _default_firm_and_client(
    *,
    firm_id: UUID | None,
    client_id: UUID | None,
    role: Literal["firm_staff", "client_portal"],
) -> tuple[UUID, UUID | None]:
    """Resolve firm/client for dev tokens when callers omit GUIDs.

    Dev login should be friendly and avoid copy/pasting tenant GUIDs.
    We therefore pick deterministic defaults from seeded firms/clients.
    """
    with owner_session() as sess:
        firms = sess.execute(select(Firm).order_by(Firm.created_at.desc())).scalars().all()
        if not firms:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="no firms found; seed demo data first",
            )

        resolved_firm = firm_id or firms[0].id

    with tenant_session(
        TenantContext(
            firm_id=resolved_firm,
            client_id=None,
            scope=AccessScope.FIRM,
        )
    ) as tenant_sess:
        firm_clients = (
            tenant_sess.execute(
                select(Client)
                .where(Client.firm_id == resolved_firm)
                .order_by(Client.created_at.desc())
            )
            .scalars()
            .all()
        )

        if role == "firm_staff":
            return resolved_firm, client_id

        # client_portal: pick explicit client, else first client in firm.
        if client_id is not None:
            return resolved_firm, client_id
        if not firm_clients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="selected firm has no clients",
            )
        return resolved_firm, firm_clients[0].id


@router.get("/dev-login-options", response_model=DevLoginOptionsOut)
def dev_login_options() -> DevLoginOptionsOut:
    """Return human-readable firm/client options for dev login screens."""
    settings = get_settings()
    if settings.app_env == "prod" or settings.app_auth_mode != "test":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not found",
        )

    with owner_session() as sess:
        firms = sess.execute(select(Firm).order_by(Firm.created_at.desc())).scalars().all()
        out: list[DevLoginFirmOut] = []
        for f in firms:
            with tenant_session(
                TenantContext(
                    firm_id=f.id,
                    client_id=None,
                    scope=AccessScope.FIRM,
                )
            ) as tenant_sess:
                clients = (
                    tenant_sess.execute(
                        select(Client)
                        .where(Client.firm_id == f.id)
                        .order_by(Client.created_at.desc())
                    )
                    .scalars()
                    .all()
                )
            out.append(
                DevLoginFirmOut(
                    id=f.id,
                    name=f.name,
                    clients=[DevLoginClientOut(id=c.id, name=c.name) for c in clients],
                )
            )

    return DevLoginOptionsOut(firms=out)


@router.post("/dev-token", response_model=DevTokenOut)
def dev_token(body: DevTokenIn) -> DevTokenOut:
    """Mint an HS256 JWT for dev/test. Maps `role` to claim values that the
    real `TestTokenIdentityProvider` will accept."""
    settings = get_settings()
    # Defense in depth — the router is only registered in non-prod, but
    # double-check at request time.
    if settings.app_env == "prod" or settings.app_auth_mode != "test":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not found",
        )
    resolved_firm_id, resolved_client_id = _default_firm_and_client(
        firm_id=body.firm_id,
        client_id=body.client_id,
        role=body.role,
    )
    role_claim = (
        settings.oidc_role_firm if body.role == "firm_staff" else settings.oidc_role_client
    )
    token = mint_test_token(
        sub=body.sub,
        firm_id=resolved_firm_id,
        role=role_claim,
        client_id=resolved_client_id,
        expires_in=body.expires_in_seconds,
    )
    return DevTokenOut(
        access_token=token,
        expires_in=body.expires_in_seconds,
    )
