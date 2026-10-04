"""Sign-in context endpoints.

`GET /auth/context` answers "which firms/clients may I act as?" for the
signed-in user. It deliberately does NOT use the `db_session` dependency:
that dependency needs a resolved tenant context, and this endpoint exists
precisely for the moment before one has been chosen.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.api.auth import _extract_bearer

router = APIRouter(prefix="/auth", tags=["auth"])


class ContextOptionOut(BaseModel):
    firm_id: str
    firm_name: str
    role: str
    scope: str
    client_id: str | None = None
    client_name: str | None = None


class ContextListOut(BaseModel):
    subject: str
    email: str | None = None
    options: list[ContextOptionOut]


@router.get("/context", response_model=ContextListOut)
def list_context(request: Request) -> ContextListOut:
    """Contexts available to the caller. Empty list means "not onboarded yet"."""
    from app.db.session import subject_session
    from app.domain.identity_resolution import list_memberships
    from app.security.auth import InvalidTokenError, get_identity_provider

    token = _extract_bearer(request)
    try:
        principal = get_identity_provider().validate_principal(token=token)
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    with subject_session(principal.subject) as sess:
        options = list_memberships(sess, subject=principal.subject)

    return ContextListOut(
        subject=principal.subject,
        email=principal.email,
        options=[
            ContextOptionOut(
                firm_id=str(o.firm_id),
                firm_name=o.firm_name,
                role=o.role.value,
                scope=o.scope.value,
                client_id=str(o.client_id) if o.client_id else None,
                client_name=o.client_name,
            )
            for o in options
        ],
    )
