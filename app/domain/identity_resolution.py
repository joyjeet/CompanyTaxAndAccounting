"""Resolve an authenticated principal to a tenant context.

This is the authorization half of login. Authentication (Entra ID / OIDC)
answers *who you are* and hands us a stable `subject`. This module answers
*what you may reach*, using our own `firm_membership` rows.

Why not read it from token claims:

* Revocation. A claim is frozen into the token until it expires — remove
  someone from a firm and they keep access for the rest of the token's life.
  A membership lookup takes effect on the very next request.
* Onboarding. A CPA's client roster churns constantly. Encoding it as
  directory extension attributes means a directory write (and directory-admin
  rights) for what is purely an application concern.

The token is still fully validated before anything here runs; `subject` is
never taken from user-controlled input.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity
from app.db.tenant import AccessScope
from app.models.enums import MembershipStatus, StaffRole
from app.models.identity import FirmMembership, UserAccount


class AuthorizationError(Exception):
    """Base class for 'authenticated, but not permitted' outcomes."""


class NoMembershipError(AuthorizationError):
    """The token is valid but the subject has no active membership."""


class AmbiguousContextError(AuthorizationError):
    """The subject has several memberships and did not say which one to use."""

    def __init__(self, message: str, options: list[MembershipOption]) -> None:
        super().__init__(message)
        self.options = options


class UnknownContextError(AuthorizationError):
    """The requested firm/client is not one the subject may act as."""


@dataclass(frozen=True, slots=True)
class MembershipOption:
    """One context the signed-in user may act in. Safe to send to the client."""

    firm_id: UUID
    firm_name: str
    role: StaffRole
    client_id: UUID | None
    client_name: str | None

    @property
    def scope(self) -> AccessScope:
        return (
            AccessScope.CLIENT
            if self.role is StaffRole.CLIENT_PORTAL
            else AccessScope.FIRM
        )


def _rows(sess: Session, subject: str) -> list[FirmMembership]:
    """Active memberships for `subject`, visible via the p_self_read policy.

    Must be called inside `subject_session(subject)`, otherwise RLS returns
    nothing and every login looks like "no membership".
    """
    return list(
        sess.execute(
            select(FirmMembership)
            .join(UserAccount, UserAccount.id == FirmMembership.user_id)
            .where(
                UserAccount.subject == subject,
                FirmMembership.status == MembershipStatus.ACTIVE,
            )
            .order_by(FirmMembership.created_at.asc())
        )
        .scalars()
        .all()
    )


def _names(sess: Session, memberships: list[FirmMembership]) -> tuple[dict, dict]:
    """Look up firm and client display names for the context picker.

    `firm` and `client` are tenant-scoped, so a subject-only session cannot read
    them. We deliberately do not widen RLS just to fetch a label: an unnamed
    option is a cosmetic problem, an over-broad policy is a security one. The
    caller falls back to the id when a name is missing.
    """
    from sqlalchemy import text

    firm_ids = {m.firm_id for m in memberships}
    client_ids = {m.client_id for m in memberships if m.client_id is not None}
    firms: dict[UUID, str] = {}
    clients: dict[UUID, str] = {}
    if firm_ids:
        rows = sess.execute(
            text("SELECT id, name FROM firm WHERE id = ANY(:ids)"),
            {"ids": list(firm_ids)},
        ).all()
        firms = {r[0]: r[1] for r in rows}
    if client_ids:
        rows = sess.execute(
            text("SELECT id, name FROM client WHERE id = ANY(:ids)"),
            {"ids": list(client_ids)},
        ).all()
        clients = {r[0]: r[1] for r in rows}
    return firms, clients


def list_memberships(sess: Session, *, subject: str) -> list[MembershipOption]:
    """Every context `subject` may act in. Drives the post-login picker."""
    memberships = _rows(sess, subject)
    if not memberships:
        return []
    firms, clients = _names(sess, memberships)
    return [
        MembershipOption(
            firm_id=m.firm_id,
            firm_name=firms.get(m.firm_id) or str(m.firm_id),
            role=m.role,
            client_id=m.client_id,
            client_name=(
                clients.get(m.client_id) if m.client_id is not None else None
            ),
        )
        for m in memberships
    ]


def resolve_identity(
    sess: Session,
    *,
    subject: str,
    requested_firm_id: UUID | None = None,
    requested_client_id: UUID | None = None,
) -> AuthIdentity:
    """Turn a validated `subject` into an `AuthIdentity`.

    The requested firm/client are *hints* from the client app, only ever used
    to disambiguate between memberships the user already holds. A hint that
    does not match a membership is rejected — it can never widen access.
    """
    memberships = _rows(sess, subject)
    if not memberships:
        raise NoMembershipError(
            "Your sign-in succeeded but this account is not linked to a firm. "
            "Ask your firm administrator to invite you."
        )

    if requested_firm_id is not None:
        memberships = [m for m in memberships if m.firm_id == requested_firm_id]
        if requested_client_id is not None:
            memberships = [
                m for m in memberships if m.client_id == requested_client_id
            ]
        if not memberships:
            raise UnknownContextError(
                "You do not have access to the requested firm or client."
            )

    if len(memberships) > 1:
        raise AmbiguousContextError(
            "Several contexts are available; choose one.",
            list_memberships(sess, subject=subject),
        )

    m = memberships[0]
    is_portal = m.role is StaffRole.CLIENT_PORTAL
    # Defence in depth. The DB CHECK constraint guarantees this pairing, but a
    # portal identity without a client_id would build a FIRM-scoped context and
    # hand a client user the whole firm, so we refuse rather than assume.
    if is_portal and m.client_id is None:
        raise NoMembershipError("Portal membership is missing its client link.")

    return AuthIdentity(
        subject=subject,
        firm_id=m.firm_id,
        scope=AccessScope.CLIENT if is_portal else AccessScope.FIRM,
        client_id=m.client_id if is_portal else None,
    )
