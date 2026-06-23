"""Form template registry ORM (Phase 8b).

A `form_template` row tracks one (form_code, tax_year, revision) of an
official IRS PDF: status, verified flag, local path, sha256 of bytes.
Reference data — NOT tenant-scoped. App role gets SELECT only.

The CPA must:
  1. REGISTER a row (status=DRAFT, verified=False).
  2. VERIFY the row after they've mapped every AcroForm field in
     `irs_form_fields.py` for that form_code (sets verified=True).
  3. ACTIVATE the row (DRAFT→ACTIVE, requires verified=True). Activation
     supersedes any prior ACTIVE row with the same (form_code, tax_year).

A tax PDF may only be FINALIZED when an ACTIVE+verified template exists
for its (form_code, tax_year). DRAFT templates may be test-rendered into
`results/` for review but never produce a FINALIZED GeneratedArtifact.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import FormTemplateStatus, TaxFormCode


class FormTemplate(Base):
    """One (form_code, tax_year, revision) IRS PDF template registration."""

    __tablename__ = "form_template"
    __table_args__ = (
        UniqueConstraint(
            "form_code", "tax_year", "revision",
            name="uq_form_template_code_year_revision",
        ),
        Index(
            "ix_form_template_code_year_status",
            "form_code", "tax_year", "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    form_code: Mapped[TaxFormCode] = mapped_column(
        SAEnum(
            TaxFormCode,
            name="tax_form_code",
            values_callable=lambda x: [e.value for e in x],
            create_type=False,
        ),
        nullable=False,
    )
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    # e.g. "2025.01" — the IRS template revision string (often the year
    # printed on the form plus a sub-revision). Free-form, CPA-chosen.
    revision: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[FormTemplateStatus] = mapped_column(
        SAEnum(
            FormTemplateStatus,
            name="form_template_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=FormTemplateStatus.DRAFT,
    )
    # CPA flips True after they have mapped every AcroForm field in
    # `app/domain/irs_form_fields.py`. Activation requires verified=True.
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Path to the bundled IRS PDF on disk (resolved by irs_form_fields.py
    # at render time). Free-form because the bundle layout may evolve.
    local_template_path: Mapped[str] = mapped_column(String(512), nullable=False)
    # sha256 of the bundled PDF bytes — proves the file the CPA verified
    # is byte-identical to the file the renderer opens at FINALIZE time.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
