from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import InviteStatus, MembershipStatus, StaffRole


def _enum_values(enum_cls: type) -> list[str]:
    return [member.value for member in enum_cls]


class UserAccount(Base):
    __tablename__ = "user_account"
    __table_args__ = (
        UniqueConstraint("subject", name="uq_user_account_subject"),
        UniqueConstraint("email", name="uq_user_account_email"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FirmMembership(Base):
    __tablename__ = "firm_membership"
    __table_args__ = (
        UniqueConstraint("firm_id", "user_id", name="uq_firm_membership_firm_user"),
        CheckConstraint(
            "(role::text = 'client_portal') = (client_id IS NOT NULL)",
            name="ck_firm_membership_client_scope",
        ),
        Index("ix_firm_membership_firm_id", "firm_id"),
        Index("ix_firm_membership_user_id", "user_id"),
        Index("ix_firm_membership_status", "status"),
        Index("ix_firm_membership_client_id", "client_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("firm.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    # Set only for the client_portal role: which client this user may see.
    # Staff roles leave this NULL and see the whole firm. Enforced by
    # ck_firm_membership_client_scope.
    client_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    role: Mapped[StaffRole] = mapped_column(
        Enum(
            StaffRole,
            name="staff_role",
            native_enum=True,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(
            MembershipStatus,
            name="membership_status",
            native_enum=True,
            values_callable=_enum_values,
        ),
        nullable=False,
        server_default=MembershipStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FirmInvite(Base):
    __tablename__ = "firm_invite"
    __table_args__ = (
        Index("ix_firm_invite_firm_id", "firm_id"),
        Index("ix_firm_invite_status", "status"),
        Index("ix_firm_invite_email", "email"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("firm.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[StaffRole] = mapped_column(
        Enum(
            StaffRole,
            name="staff_role",
            native_enum=True,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    status: Mapped[InviteStatus] = mapped_column(
        Enum(
            InviteStatus,
            name="invite_status",
            native_enum=True,
            values_callable=_enum_values,
        ),
        nullable=False,
        server_default=InviteStatus.PENDING.value,
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    invited_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
