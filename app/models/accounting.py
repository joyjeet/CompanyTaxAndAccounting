"""Double-entry accounting ORM.

Conventions
-----------
* All money is `Numeric(20, 4)` and surfaced in Python as `Decimal`. No floats.
* Every tenant-scoped table carries `firm_id` and `client_id`. RLS policies are
  attached in the Alembic migration (DDL run as the schema owner).
* The `firm` table itself is NOT tenant-scoped (it IS the tenant root); access
  is controlled at the application layer.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    AccountType,
    AssetStatus,
    AuditAction,
    DraftKind,
    DraftStatus,
    JournalEntryStatus,
    NormalBalance,
    OcrStatus,
    ReconciliationStatus,
)


# --------------------------------------------------------------------------- #
# Firm — tenant root. NOT RLS protected (it is the partition key).
# --------------------------------------------------------------------------- #
class Firm(Base):
    __tablename__ = "firm"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    clients: Mapped[list[Client]] = relationship(back_populates="firm")


# --------------------------------------------------------------------------- #
# Client — a business the firm serves.
# --------------------------------------------------------------------------- #
class Client(Base):
    __tablename__ = "client"
    __table_args__ = (
        UniqueConstraint("firm_id", "external_code", name="uq_client_firm_external_code"),
        Index("ix_client_firm_id", "firm_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("firm.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    firm: Mapped[Firm] = relationship(back_populates="clients")


# --------------------------------------------------------------------------- #
# Chart of Accounts
# --------------------------------------------------------------------------- #
class ChartOfAccounts(Base):
    __tablename__ = "chart_of_accounts"
    __table_args__ = (
        UniqueConstraint("client_id", "code", name="uq_coa_client_code"),
        Index("ix_coa_firm_id", "firm_id"),
        Index("ix_coa_client_id", "client_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        SAEnum(
            AccountType,
            name="account_type",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    normal_balance: Mapped[NormalBalance] = mapped_column(
        SAEnum(
            NormalBalance,
            name="normal_balance",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- #
# Accounting Period (lockable)
# --------------------------------------------------------------------------- #
class AccountingPeriod(Base):
    __tablename__ = "accounting_period"
    __table_args__ = (
        UniqueConstraint("client_id", "start_date", "end_date", name="uq_period_client_dates"),
        Index("ix_period_firm_id", "firm_id"),
        Index("ix_period_client_id", "client_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- #
# Journal Entry (header) and Journal Line (debit/credit rows)
# --------------------------------------------------------------------------- #
class JournalEntry(Base):
    __tablename__ = "journal_entry"
    __table_args__ = (
        Index("ix_je_firm_id", "firm_id"),
        Index("ix_je_client_id", "client_id"),
        Index("ix_je_period_id", "period_id"),
        Index("ix_je_entry_date", "entry_date"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    period_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounting_period.id", ondelete="RESTRICT"),
        nullable=False,
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[JournalEntryStatus] = mapped_column(
        SAEnum(
            JournalEntryStatus,
            name="journal_entry_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=JournalEntryStatus.DRAFT,
    )
    source_document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("source_document.id", ondelete="SET NULL"),
        nullable=True,
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lines: Mapped[list[JournalLine]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="JournalLine.line_no",
    )


class JournalLine(Base):
    __tablename__ = "journal_line"
    __table_args__ = (
        Index("ix_jl_firm_id", "firm_id"),
        Index("ix_jl_client_id", "client_id"),
        Index("ix_jl_entry_id", "entry_id"),
        Index("ix_jl_account_id", "account_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entry_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("journal_entry.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(nullable=False)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    debit: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0")
    )
    credit: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")


# --------------------------------------------------------------------------- #
# Bank Transaction (raw feed, before matched to a journal entry)
# --------------------------------------------------------------------------- #
class BankTransaction(Base):
    __tablename__ = "bank_transaction"
    __table_args__ = (
        Index("ix_bt_firm_id", "firm_id"),
        Index("ix_bt_client_id", "client_id"),
        Index("ix_bt_account_id", "account_id"),
        Index("ix_bt_txn_date", "txn_date"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Signed amount as the bank statement reports it: positive=deposit, negative=withdrawal.
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    matched_journal_line_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("journal_line.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- #
# Asset (fixed asset register; depreciation engine arrives later)
# --------------------------------------------------------------------------- #
class Asset(Base):
    __tablename__ = "asset"
    __table_args__ = (
        Index("ix_asset_firm_id", "firm_id"),
        Index("ix_asset_client_id", "client_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    acquisition_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    useful_life_months: Mapped[int | None] = mapped_column(nullable=True)
    salvage_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0")
    )
    status: Mapped[AssetStatus] = mapped_column(
        SAEnum(
            AssetStatus,
            name="asset_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=AssetStatus.ACTIVE,
    )
    asset_account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    accum_depr_account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    depr_expense_account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #
class Reconciliation(Base):
    __tablename__ = "reconciliation"
    __table_args__ = (
        Index("ix_recon_firm_id", "firm_id"),
        Index("ix_recon_client_id", "client_id"),
        Index("ix_recon_account_id", "account_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    statement_balance: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    ledger_balance: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    difference: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    status: Mapped[ReconciliationStatus] = mapped_column(
        SAEnum(
            ReconciliationStatus,
            name="reconciliation_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- #
# Source Document (invoice, receipt, bank stmt). Stub interface to blob store.
# --------------------------------------------------------------------------- #
class SourceDocument(Base):
    __tablename__ = "source_document"
    __table_args__ = (
        Index("ix_src_firm_id", "firm_id"),
        Index("ix_src_client_id", "client_id"),
        Index("ix_src_client_sha256", "client_id", "sha256"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extracted: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ocr_status: Mapped[OcrStatus] = mapped_column(
        SAEnum(
            OcrStatus,
            name="ocr_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=OcrStatus.PENDING,
    )
    ocr_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ocr_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- #
# Audit Event — append-only log of every state change.
# --------------------------------------------------------------------------- #
class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_firm_id", "firm_id"),
        Index("ix_audit_client_id", "client_id"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_at", "at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(
            AuditAction,
            name="audit_action",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --------------------------------------------------------------------------- #
# Draft Classification — staging area for AI output. Nothing here is ever
# automatically written to journal_entry / journal_line. Promotion happens
# only via promote_draft() which calls the LedgerService (balance invariant
# enforced).
# --------------------------------------------------------------------------- #
class DraftClassification(Base):
    __tablename__ = "draft_classification"
    __table_args__ = (
        Index("ix_draft_firm_id", "firm_id"),
        Index("ix_draft_client_id", "client_id"),
        Index("ix_draft_source_id", "source_document_id"),
        Index("ix_draft_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    firm_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    client_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("source_document.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[DraftKind] = mapped_column(
        SAEnum(
            DraftKind,
            name="draft_kind",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    status: Mapped[DraftStatus] = mapped_column(
        SAEnum(
            DraftStatus,
            name="draft_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=DraftStatus.PENDING_REVIEW,
    )
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    high_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    promoted_journal_entry_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("journal_entry.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
