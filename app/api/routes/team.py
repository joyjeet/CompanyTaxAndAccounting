from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, and_, select, update
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.db.tenant import AccessScope
from app.domain.audit import write_audit
from app.models.enums import AuditAction, InviteStatus, MembershipStatus, StaffRole
from app.models.identity import FirmInvite, FirmMembership, UserAccount

router = APIRouter(prefix="/team", tags=["team"])

_ADMIN_ROLES = {StaffRole.FIRM_OWNER, StaffRole.FIRM_ADMIN}


class TeamMemberOut(BaseModel):
    id: UUID
    user_id: UUID
    subject: str
    email: str | None
    role: StaffRole
    status: MembershipStatus
    created_at: datetime
    updated_at: datetime


class InviteOut(BaseModel):
    id: UUID
    email: str
    role: StaffRole
    status: InviteStatus
    expires_at: datetime
    created_at: datetime


class TeamSummaryOut(BaseModel):
    members: list[TeamMemberOut]
    invites: list[InviteOut]


class InviteCreateIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: StaffRole
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InviteCreateOut(InviteOut):
    invite_token: str


class InviteAcceptIn(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class MembershipRoleIn(BaseModel):
    role: StaffRole


class MembershipStatusIn(BaseModel):
    status: MembershipStatus


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _subject_user(sess: Session, *, subject: str) -> UserAccount:
    user = sess.execute(select(UserAccount).where(UserAccount.subject == subject)).scalar_one_or_none()
    if user is None:
        user = UserAccount(subject=subject)
        sess.add(user)
        sess.flush()
    return user


def _require_firm_scope(identity: AuthIdentity) -> None:
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="firm-scope identity required",
        )


def _membership_query(firm_id: UUID) -> Select[tuple[FirmMembership, UserAccount]]:
    return (
        select(FirmMembership, UserAccount)
        .join(UserAccount, UserAccount.id == FirmMembership.user_id)
        .where(FirmMembership.firm_id == firm_id)
    )


def _ensure_caller_membership(
    sess: Session,
    *,
    identity: AuthIdentity,
) -> tuple[UserAccount, FirmMembership]:
    _require_firm_scope(identity)
    user = _subject_user(sess, subject=identity.subject)
    membership = sess.execute(
        select(FirmMembership).where(
            and_(
                FirmMembership.firm_id == identity.firm_id,
                FirmMembership.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        membership = FirmMembership(
            firm_id=identity.firm_id,
            user_id=user.id,
            role=StaffRole.FIRM_OWNER,
            status=MembershipStatus.ACTIVE,
        )
        sess.add(membership)
        sess.flush()
    if membership.status is not MembershipStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="membership is disabled",
        )
    return user, membership


def _require_team_admin(
    sess: Session,
    *,
    identity: AuthIdentity,
) -> tuple[UserAccount, FirmMembership]:
    user, membership = _ensure_caller_membership(sess, identity=identity)
    if membership.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="firm owner or firm admin role required",
        )
    return user, membership


def _member_to_out(m: FirmMembership, u: UserAccount) -> TeamMemberOut:
    return TeamMemberOut(
        id=m.id,
        user_id=u.id,
        subject=u.subject,
        email=u.email,
        role=m.role,
        status=m.status,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _invite_to_out(inv: FirmInvite) -> InviteOut:
    return InviteOut(
        id=inv.id,
        email=inv.email,
        role=inv.role,
        status=inv.status,
        expires_at=inv.expires_at,
        created_at=inv.created_at,
    )


@router.get("/members", response_model=TeamSummaryOut)
def list_team_members(
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> TeamSummaryOut:
    _ensure_caller_membership(sess, identity=identity)
    now = datetime.now(UTC)
    sess.execute(
        update(FirmInvite)
        .where(
            and_(
                FirmInvite.firm_id == identity.firm_id,
                FirmInvite.status == InviteStatus.PENDING,
                FirmInvite.expires_at < now,
            )
        )
        .values(status=InviteStatus.EXPIRED)
    )

    members = [
        _member_to_out(m, u)
        for m, u in sess.execute(
            _membership_query(identity.firm_id).order_by(UserAccount.subject.asc())
        ).all()
    ]
    invites = [
        _invite_to_out(i)
        for i in sess.execute(
            select(FirmInvite)
            .where(FirmInvite.firm_id == identity.firm_id)
            .order_by(FirmInvite.created_at.desc())
        ).scalars().all()
    ]
    return TeamSummaryOut(members=members, invites=invites)


@router.post("/invites", response_model=InviteCreateOut, status_code=status.HTTP_201_CREATED)
def create_invite(
    body: InviteCreateIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> InviteCreateOut:
    inviter, _ = _require_team_admin(sess, identity=identity)
    email = _normalize_email(body.email)
    now = datetime.now(UTC)

    existing = sess.execute(
        select(FirmInvite).where(
            and_(
                FirmInvite.firm_id == identity.firm_id,
                FirmInvite.email == email,
                FirmInvite.status == InviteStatus.PENDING,
                FirmInvite.expires_at >= now,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an active pending invite already exists for this email",
        )

    token = secrets.token_urlsafe(32)
    invite = FirmInvite(
        firm_id=identity.firm_id,
        email=email,
        role=body.role,
        status=InviteStatus.PENDING,
        token_hash=_hash_token(token),
        invited_by_user_id=inviter.id,
        expires_at=now + timedelta(days=body.expires_in_days),
    )
    sess.add(invite)
    sess.flush()

    write_audit(
        sess,
        firm_id=identity.firm_id,
        client_id=identity.firm_id,
        actor=identity.subject,
        action=AuditAction.USER_INVITE_CREATE,
        entity_type="firm_invite",
        entity_id=invite.id,
        details={"email": email, "role": body.role.value},
    )

    return InviteCreateOut(
        **_invite_to_out(invite).model_dump(),
        invite_token=token,
    )


@router.post("/invites/{invite_id}/cancel", response_model=InviteOut)
def cancel_invite(
    invite_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> InviteOut:
    _require_team_admin(sess, identity=identity)
    invite = sess.execute(
        select(FirmInvite).where(
            and_(
                FirmInvite.id == invite_id,
                FirmInvite.firm_id == identity.firm_id,
            )
        )
    ).scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")
    if invite.status is not InviteStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="only pending invites can be canceled",
        )

    invite.status = InviteStatus.CANCELED
    invite.canceled_at = datetime.now(UTC)

    write_audit(
        sess,
        firm_id=identity.firm_id,
        client_id=identity.firm_id,
        actor=identity.subject,
        action=AuditAction.USER_INVITE_CANCEL,
        entity_type="firm_invite",
        entity_id=invite.id,
        details={"email": invite.email},
    )
    return _invite_to_out(invite)


@router.post("/invites/accept", response_model=TeamMemberOut)
def accept_invite(
    body: InviteAcceptIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> TeamMemberOut:
    _require_firm_scope(identity)
    caller = _subject_user(sess, subject=identity.subject)
    invite = sess.execute(
        select(FirmInvite).where(
            and_(
                FirmInvite.firm_id == identity.firm_id,
                FirmInvite.token_hash == _hash_token(body.token),
            )
        )
    ).scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")

    if invite.status is InviteStatus.CANCELED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invite is canceled")
    if invite.status is InviteStatus.EXPIRED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invite is expired")
    now = datetime.now(UTC)
    if invite.expires_at < now:
        invite.status = InviteStatus.EXPIRED
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invite is expired")

    membership = sess.execute(
        select(FirmMembership).where(
            and_(
                FirmMembership.firm_id == identity.firm_id,
                FirmMembership.user_id == caller.id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        membership = FirmMembership(
            firm_id=identity.firm_id,
            user_id=caller.id,
            role=invite.role,
            status=MembershipStatus.ACTIVE,
        )
        sess.add(membership)
        sess.flush()
    else:
        membership.role = invite.role
        membership.status = MembershipStatus.ACTIVE

    invite.status = InviteStatus.ACCEPTED
    invite.accepted_at = now

    write_audit(
        sess,
        firm_id=identity.firm_id,
        client_id=identity.firm_id,
        actor=identity.subject,
        action=AuditAction.USER_INVITE_ACCEPT,
        entity_type="firm_invite",
        entity_id=invite.id,
        details={"membership_id": str(membership.id), "email": invite.email},
    )

    return _member_to_out(membership, caller)


@router.post("/members/{member_id}/role", response_model=TeamMemberOut)
def update_member_role(
    member_id: UUID,
    body: MembershipRoleIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> TeamMemberOut:
    _require_team_admin(sess, identity=identity)
    row = sess.execute(
        _membership_query(identity.firm_id).where(FirmMembership.id == member_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    membership, user = row
    membership.role = body.role
    write_audit(
        sess,
        firm_id=identity.firm_id,
        client_id=identity.firm_id,
        actor=identity.subject,
        action=AuditAction.USER_ROLE_UPDATE,
        entity_type="firm_membership",
        entity_id=membership.id,
        details={"subject": user.subject, "role": body.role.value},
    )
    return _member_to_out(membership, user)


@router.post("/members/{member_id}/status", response_model=TeamMemberOut)
def update_member_status(
    member_id: UUID,
    body: MembershipStatusIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> TeamMemberOut:
    _require_team_admin(sess, identity=identity)
    row = sess.execute(
        _membership_query(identity.firm_id).where(FirmMembership.id == member_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    membership, user = row
    membership.status = body.status
    write_audit(
        sess,
        firm_id=identity.firm_id,
        client_id=identity.firm_id,
        actor=identity.subject,
        action=AuditAction.USER_STATUS_UPDATE,
        entity_type="firm_membership",
        entity_id=membership.id,
        details={"subject": user.subject, "status": body.status.value},
    )
    return _member_to_out(membership, user)
