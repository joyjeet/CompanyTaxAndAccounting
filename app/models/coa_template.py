"""COA template ORM — versioned, CPA-activated reference data.

Two tables, **shared reference data** (NOT tenant-scoped) similar to
`tax_form` / `tax_form_line`:

  * `coa_template`     — one row per (template key, version). Status moves
                         DRAFT → ACTIVE → SUPERSEDED on CPA activation.
  * `coa_template_node`— the tree of accounts inside one template version.

Templates are seeded by migration as DRAFT. The firm-level CPA explicitly
ACTIVATEs a version via `app.domain.coa_templates.activate_template`,
which supersedes any prior ACTIVE row with the same key.

Instantiation copies a template's nodes into the tenant-scoped
`chart_of_accounts` table for a client; lineage to the template_node id
is preserved on the COA row.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    AccountType,
    CoaTemplateKind,
    CoaTemplateStatus,
    NormalBalance,
)


class CoaTemplate(Base):
    """One versioned COA template (general base or industry overlay)."""

    __tablename__ = "coa_template"
    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_coa_template_key_version"),
        Index("ix_coa_template_key", "key"),
        Index("ix_coa_template_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    # "general" or "industry:<industry_value>" — uniquely identifies a
    # template "track"; the (key, version) pair is what's globally unique.
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[CoaTemplateKind] = mapped_column(
        SAEnum(
            CoaTemplateKind,
            name="coa_template_kind",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    # NULL for the general base; the industry enum value for overlays.
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[CoaTemplateStatus] = mapped_column(
        SAEnum(
            CoaTemplateStatus,
            name="coa_template_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=CoaTemplateStatus.DRAFT,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    nodes: Mapped[list[CoaTemplateNode]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="CoaTemplateNode.sort_order",
    )


class CoaTemplateNode(Base):
    """One node inside a versioned COA template."""

    __tablename__ = "coa_template_node"
    __table_args__ = (
        UniqueConstraint("template_id", "code", name="uq_coa_node_template_code"),
        Index("ix_coa_node_template_id", "template_id"),
        Index("ix_coa_node_parent_code", "template_id", "parent_code"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("coa_template.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        SAEnum(
            AccountType,
            name="account_type",
            values_callable=lambda x: [e.value for e in x],
            create_type=False,
        ),
        nullable=False,
    )
    normal_balance: Mapped[NormalBalance] = mapped_column(
        SAEnum(
            NormalBalance,
            name="normal_balance",
            values_callable=lambda x: [e.value for e in x],
            create_type=False,
        ),
        nullable=False,
    )
    # Reporting classification within `account_type` — copied verbatim onto
    # `chart_of_accounts.sub_type` when the template is instantiated.
    sub_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # `parent_code` may point at a code in the SAME template (general base)
    # or at a code in the general base (industry overlays). It's a string
    # rather than an FK so overlay nodes can reference general nodes without
    # creating a cross-row dependency at insert time.
    parent_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    depth: Mapped[int] = mapped_column(nullable=False, default=0)
    is_leaf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    template: Mapped[CoaTemplate] = relationship(back_populates="nodes")


__all__ = ["CoaTemplate", "CoaTemplateNode"]
