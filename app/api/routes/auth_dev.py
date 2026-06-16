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

from app.core.config import get_settings
from app.security.auth import mint_test_token

router = APIRouter(prefix="/auth", tags=["auth-dev"])


class DevTokenIn(BaseModel):
    sub: str = Field(min_length=1, max_length=128)
    role: Literal["firm_staff", "client_portal"]
    firm_id: UUID
    client_id: UUID | None = None
    expires_in_seconds: int = Field(default=3600, ge=60, le=86_400)


class DevTokenOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


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
    if body.role == "client_portal" and body.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_portal requires client_id",
        )
    role_claim = (
        settings.oidc_role_firm if body.role == "firm_staff" else settings.oidc_role_client
    )
    token = mint_test_token(
        sub=body.sub,
        firm_id=body.firm_id,
        role=role_claim,
        client_id=body.client_id,
        expires_in=body.expires_in_seconds,
    )
    return DevTokenOut(
        access_token=token,
        expires_in=body.expires_in_seconds,
    )
