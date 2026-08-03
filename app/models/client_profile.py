"""Client profile ORM (Phase 8b).

Captures the structured profile that drives the per-client tax-form set:
entity_type, industry, tax_year, home_state, additional states,
fiscal_year_end_month, plus a free-form jsonb for entity-specific
attributes (e.g. number of partners for partnerships, S-election date
for S-corps). One row per client (1:1).

Tenant-scoped: RLS + FORCE, firm/client-filtered like every other
tenant table. Both firm staff and client portal may READ; only firm
staff may write (enforced at the API layer).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import Industry


class ClientProfile(Base):
    """1:1 structured profile for a client. Drives the form-set engine."""

    __tablename__ = "client_profile"
    __table_args__ = (
        UniqueConstraint("client_id", name="uq_client_profile_client_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    firm_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    client_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("client.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Stored as the enum's string value. We keep it as String (not a PG
    # enum type) so a new EntityType — e.g. "non_profit" — can ship as a
    # pure data/enum change, without a DB migration.
    #
    # Nullable as of migration 0010: a portal user can populate contact
    # info before the firm has confirmed entity_type. The form-set engine
    # fails closed when entity_type is missing.
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    industry: Mapped[str] = mapped_column(
        String(64), nullable=False, default=Industry.GENERIC.value
    )
    # The tax year (e.g. 2025) the profile currently applies to. When a
    # client crosses into a new tax year the firm bumps this — the
    # entity_form_ruleset for that (entity_type, tax_year) is the one
    # used to compute their form set.
    #
    # Nullable as of migration 0010 — same rationale as entity_type.
    tax_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Two-letter state abbreviation; nullable while client onboarding is
    # in progress.
    home_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # JSON list of two-letter codes, e.g. ["CA","NY"]. Stored as JSONB
    # so we can index/query in the future without a schema migration.
    additional_states: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True
    )
    # 1–12, month the fiscal year ends. 12 = calendar year.
    fiscal_year_end_month: Mapped[int] = mapped_column(
        Integer, nullable=False, default=12
    )
    # Free-form per-entity attributes. Examples:
    #   {"s_election_effective": "2024-01-01"} for S-corps.
    #   {"member_count": 3} for partnerships.
    # No schema enforcement here — the CPA/UI layer validates.
    entity_attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ------------------------------------------------------------------ #
    # Phase 8c — Business identity and contact info.
    # All nullable. Editable by firm staff AND by the owning client (the
    # client portal). Address fields are mailing address; `home_state`
    # above remains the *tax* home state (sometimes different).
    # ------------------------------------------------------------------ #
    business_legal_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    dba_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ein: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    address_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    country: Mapped[str] = mapped_column(
        String(2), nullable=False, default="US"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
