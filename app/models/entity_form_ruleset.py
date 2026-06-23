"""Entity-form ruleset ORM (Phase 8b).

Versioned, CPA-activated mapping from (entity_type, tax_year) to the
list of required federal tax forms/schedules. Reference data — NOT
tenant-scoped.

A client whose (entity_type, tax_year) has no ACTIVE ruleset
**fails closed**: the form-set service raises and no worksheet,
artifact, or downstream computation may be produced. This is the
explicit "no AI tax logic without a CPA-activated rule" guarantee.

The ruleset's `required_forms` column is a JSON list of TaxFormCode
enum values, e.g. `["F1120","F1120_SCH_K1"]`. Per the work order,
new forms/schedules not yet in the catalog are scaffolded as
UNVERIFIED stubs flagged for CPA review.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import EntityFormRulesetStatus


class EntityFormRuleset(Base):
    """One versioned (entity_type, tax_year, version) form-set ruleset."""

    __tablename__ = "entity_form_ruleset"
    __table_args__ = (
        UniqueConstraint(
            "entity_type", "tax_year", "version",
            name="uq_efr_entity_year_version",
        ),
        Index(
            "ix_efr_entity_year_status",
            "entity_type", "tax_year", "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    # Stored as the EntityType string value (not as a PG enum) so adding
    # a new entity type is a data-only change. See ClientProfile.entity_type.
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[EntityFormRulesetStatus] = mapped_column(
        SAEnum(
            EntityFormRulesetStatus,
            name="entity_form_ruleset_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=EntityFormRulesetStatus.DRAFT,
    )
    # JSON list of TaxFormCode string values. Stored as JSONB for future
    # querying. The service layer coerces back to TaxFormCode enum values
    # when reading.
    required_forms: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # Free-form notes for the CPA — provenance, IRS publication refs.
    notes: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
