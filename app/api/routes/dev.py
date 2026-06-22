"""Dev / demo helper routes.

These endpoints exist to make the demo demoable without hand-running SQL.
They are mounted only when the server is NOT in `prod` env. Production
deployments should never expose this router.

Routes
------
POST /dev/seed-defaults?client_id=...
    Idempotently provisions a starter chart of accounts and an open accounting
    period for the given client, then optionally auto-promotes any existing
    high-confidence drafts and posts a couple of sample journal entries so the
    trial balance is non-empty out of the box.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.core.config import get_settings
from app.db.tenant import AccessScope
from app.domain.ledger import LedgerService, LineInput
from app.models.accounting import (
    AccountingPeriod,
    ChartOfAccounts,
    Client,
)
from app.models.enums import AccountType, NormalBalance

router = APIRouter(prefix="/dev", tags=["dev"])


class SeedOut(BaseModel):
    client_id: UUID
    accounts_created: list[str]
    accounts_existing: list[str]
    period_id: UUID
    period_created: bool
    sample_entries_posted: int
    reports_published: int = 0
    notes: list[str]


class ResetOut(BaseModel):
    """Counts of rows deleted by `/dev/reset-client`."""

    client_id: UUID
    deleted: dict[str, int]
    notes: list[str]


# --------------------------------------------------------------------------- #
# Seed catalog. Codes follow the standard 1xxx/2xxx/.../5xxx/9xxx convention.
# --------------------------------------------------------------------------- #
_SEED_ACCOUNTS: tuple[tuple[str, str, AccountType, NormalBalance], ...] = (
    ("1000", "Cash", AccountType.ASSET, NormalBalance.DEBIT),
    ("1100", "Accounts Receivable", AccountType.ASSET, NormalBalance.DEBIT),
    ("1200", "Office Supplies", AccountType.ASSET, NormalBalance.DEBIT),
    ("2000", "Accounts Payable", AccountType.LIABILITY, NormalBalance.CREDIT),
    ("3000", "Owner's Equity", AccountType.EQUITY, NormalBalance.CREDIT),
    ("4000", "Sales Revenue", AccountType.REVENUE, NormalBalance.CREDIT),
    ("5000", "Office Expense", AccountType.EXPENSE, NormalBalance.DEBIT),
    ("5100", "Bank Fees", AccountType.EXPENSE, NormalBalance.DEBIT),
    ("5200", "Rent Expense", AccountType.EXPENSE, NormalBalance.DEBIT),
    ("9999", "Suspense", AccountType.ASSET, NormalBalance.DEBIT),
)


@router.post(
    "/seed-defaults",
    response_model=SeedOut,
    status_code=status.HTTP_200_OK,
)
def seed_defaults(
    client_id: UUID,
    post_samples: bool = True,
    seed_reports: bool = True,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> SeedOut:
    """Seed COA + open period for the given client. Idempotent.

    If `post_samples=True` and the trial balance is currently empty, posts a
    handful of representative journal entries so the demo statements look
    real.

    If `seed_reports=True` and the client currently has no published
    artifacts, generates a P&L + Balance Sheet (FINALIZED) and a Cash Flow
    (DRAFT) so the client portal's "My reports" page shows real content.
    """
    settings = get_settings()
    if settings.app_env == "prod":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not available in production",
        )
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="firm-scope access required",
        )

    client = sess.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="client not found"
        )

    notes: list[str] = []

    # ---- Accounts ---- #
    existing = (
        sess.execute(
            select(ChartOfAccounts).where(ChartOfAccounts.client_id == client_id)
        )
        .scalars()
        .all()
    )
    existing_codes = {a.code for a in existing}
    code_to_account: dict[str, ChartOfAccounts] = {a.code: a for a in existing}

    created_codes: list[str] = []
    for code, name, atype, normal in _SEED_ACCOUNTS:
        if code in existing_codes:
            continue
        acct = ChartOfAccounts(
            id=uuid4(),
            firm_id=identity.firm_id,
            client_id=client_id,
            code=code,
            name=name,
            account_type=atype,
            normal_balance=normal,
            is_active=True,
        )
        sess.add(acct)
        code_to_account[code] = acct
        created_codes.append(code)
    if created_codes:
        sess.flush()

    # ---- Period (current calendar year) ---- #
    today = date.today()
    year = today.year
    period_start = date(year, 1, 1)
    period_end = date(year, 12, 31)
    period = (
        sess.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.client_id == client_id,
                AccountingPeriod.start_date == period_start,
                AccountingPeriod.end_date == period_end,
            )
        )
        .scalars()
        .first()
    )
    period_created = False
    if period is None:
        period = AccountingPeriod(
            id=uuid4(),
            firm_id=identity.firm_id,
            client_id=client_id,
            name=f"FY {year}",
            start_date=period_start,
            end_date=period_end,
        )
        sess.add(period)
        sess.flush()
        period_created = True
    elif period.is_locked:
        notes.append(
            f"Period {period.name} exists but is locked; sample entries will be skipped."
        )

    # ---- Sample entries (only if no entries exist yet for this client) ---- #
    samples_posted = 0
    if post_samples and not period.is_locked:
        from app.models.accounting import JournalEntry  # local import to avoid cycle

        already_has_entries = (
            sess.execute(
                select(JournalEntry.id).where(JournalEntry.client_id == client_id).limit(1)
            )
            .scalar_one_or_none()
            is not None
        )
        if not already_has_entries:
            samples_posted = _post_sample_entries(
                sess,
                firm_id=identity.firm_id,
                client_id=client_id,
                actor=identity.subject,
                period_id=period.id,
                entry_date=_clamp_entry_date(today, period_start, period_end),
                accounts=code_to_account,
            )
            notes.append(
                f"Posted {samples_posted} sample journal entries to make the trial balance non-empty."
            )
        else:
            notes.append("Client already has journal entries; skipped sample posting.")

    # ---- Reports (for the client portal demo) ---- #
    reports_published = 0
    if seed_reports and not period.is_locked:
        reports_published = _seed_demo_reports(
            sess,
            firm_id=identity.firm_id,
            client_id=client_id,
            actor=identity.subject,
            scope=identity.scope,
            period_id=period.id,
            notes=notes,
        )

    return SeedOut(
        client_id=client_id,
        accounts_created=created_codes,
        accounts_existing=sorted(existing_codes),
        period_id=period.id,
        period_created=period_created,
        sample_entries_posted=samples_posted,
        reports_published=reports_published,
        notes=notes,
    )


def _clamp_entry_date(d: date, start: date, end: date) -> date:
    if d < start:
        return start
    if d > end:
        return end
    return d


def _seed_demo_reports(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    period_id: UUID,
    notes: list[str],
) -> int:
    """Generate a P&L + Balance Sheet (FINALIZED) and a Cash Flow (DRAFT).

    Skips entirely when the client already has any non-superseded artifact
    for this period, so the function stays idempotent across re-seeds.

    Returns count of artifacts created.
    """
    # Local imports keep the dev module light when the demo seed is unused.
    from app.domain.artifact_service import (
        ArtifactStateError,
        ExportBlockedByPendingDraftsError,
        GenerateStatementRequest,
        finalize_artifact,
        generate_statement_artifact,
    )
    from app.models.accounting import GeneratedArtifact
    from app.models.enums import (
        ArtifactFormat,
        ArtifactKind,
        ArtifactStatus,
    )

    existing = sess.execute(
        select(GeneratedArtifact).where(
            GeneratedArtifact.client_id == client_id,
            GeneratedArtifact.period_id == period_id,
            GeneratedArtifact.status != ArtifactStatus.SUPERSEDED,
        )
    ).scalars().first()
    if existing is not None:
        notes.append(
            "Client already has reports for this period; skipped report seeding."
        )
        return 0

    plan: list[tuple[ArtifactKind, bool]] = [
        (ArtifactKind.PROFIT_AND_LOSS, True),   # finalize
        (ArtifactKind.BALANCE_SHEET, True),     # finalize
        (ArtifactKind.CASH_FLOW, False),        # leave as draft (pending)
    ]
    created = 0
    for kind, do_finalize in plan:
        try:
            art = generate_statement_artifact(
                sess,
                firm_id=firm_id,
                client_id=client_id,
                actor=actor,
                scope=scope,
                request=GenerateStatementRequest(
                    period_id=period_id,
                    kind=kind,
                    format=ArtifactFormat.PDF,
                    cash_account_codes=["1000"],
                ),
            )
        except (ArtifactStateError, ExportBlockedByPendingDraftsError) as e:
            notes.append(f"Skipped seeding {kind.value}: {e}")
            continue
        created += 1
        if do_finalize:
            try:
                finalize_artifact(
                    sess,
                    firm_id=firm_id,
                    client_id=client_id,
                    actor=actor,
                    scope=scope,
                    artifact_id=art.id,
                )
            except (ArtifactStateError, ExportBlockedByPendingDraftsError) as e:
                notes.append(
                    f"Generated {kind.value} but could not finalize: {e}"
                )
    if created:
        notes.append(
            f"Generated {created} demo report(s) for the client portal "
            "(2 finalized + 1 draft)."
        )
    return created


def _post_sample_entries(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    period_id: UUID,
    entry_date: date,
    accounts: dict[str, ChartOfAccounts],
) -> int:
    """Post 3 representative entries: opening cash, a sale, an office expense.

    Returns count posted. Returns 0 if a required account is missing.
    """
    ledger = LedgerService(sess, firm_id=firm_id, client_id=client_id, actor=actor)

    required = ("1000", "3000", "4000", "5000")
    if any(c not in accounts for c in required):
        return 0

    posted = 0
    # 1) Owner contributes $10,000 cash.
    ledger.post(
        period_id=period_id,
        entry_date=entry_date,
        memo="Owner contribution (seed)",
        lines=[
            LineInput(account_id=accounts["1000"].id, debit=Decimal("10000.00")),
            LineInput(account_id=accounts["3000"].id, credit=Decimal("10000.00")),
        ],
    )
    posted += 1

    # 2) Cash sale $1,500.
    ledger.post(
        period_id=period_id,
        entry_date=entry_date,
        memo="Sample cash sale (seed)",
        lines=[
            LineInput(account_id=accounts["1000"].id, debit=Decimal("1500.00")),
            LineInput(account_id=accounts["4000"].id, credit=Decimal("1500.00")),
        ],
    )
    posted += 1

    # 3) Office supplies expense $250 paid in cash.
    ledger.post(
        period_id=period_id,
        entry_date=entry_date,
        memo="Sample office supplies (seed)",
        lines=[
            LineInput(account_id=accounts["5000"].id, debit=Decimal("250.00")),
            LineInput(account_id=accounts["1000"].id, credit=Decimal("250.00")),
        ],
    )
    posted += 1

    return posted


# --------------------------------------------------------------------------- #
# Reset (demo cleanup)
# --------------------------------------------------------------------------- #
@router.post(
    "/reset-client",
    response_model=ResetOut,
    status_code=status.HTTP_200_OK,
)
def reset_client(
    client_id: UUID,
    keep_audit: bool = True,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> ResetOut:
    """Wipe transactional data for a client so the demo can start fresh.

    Deletes (in FK-safe order):
      generated_artifact, tax_worksheet (+ lines), tax_account_mapping,
      draft_classification, journal_entry (+ lines), source_document,
      reconciliation, asset, bank_transaction.

    Preserves:
      client, chart_of_accounts, accounting_period, firm.
      Also audit_event by default (set keep_audit=false to nuke).

    Idempotent and safe to re-run. Encrypted blobs in object storage are
    not deleted — they become orphans, which is fine for the demo.
    """
    from sqlalchemy import delete

    from app.models.accounting import (
        Asset,
        AuditEvent,
        BankTransaction,
        DraftClassification,
        GeneratedArtifact,
        JournalEntry,
        Reconciliation,
        SourceDocument,
        TaxAccountMapping,
        TaxWorksheet,
    )

    settings = get_settings()
    if settings.app_env == "prod":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not available in production",
        )
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="firm-scope access required",
        )

    client = sess.get(Client, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="client not found"
        )

    deleted: dict[str, int] = {}

    def _del(model, table_name: str) -> None:
        result = sess.execute(
            delete(model).where(model.client_id == client_id)
        )
        deleted[table_name] = int(result.rowcount or 0)

    # Order matters: respect FK constraints (RESTRICT on tax_worksheet from
    # generated_artifact, RESTRICT on period from journal_entry, etc.).
    _del(GeneratedArtifact, "generated_artifact")
    # tax_worksheet_line cascades from tax_worksheet.
    _del(TaxWorksheet, "tax_worksheet")
    _del(TaxAccountMapping, "tax_account_mapping")
    # draft_classification has FK to source_document with CASCADE — delete
    # drafts first to avoid CASCADE surprises in the journal_entry SET NULL
    # column on draft.promoted_journal_entry_id.
    _del(DraftClassification, "draft_classification")
    # journal_line cascades from journal_entry.
    _del(JournalEntry, "journal_entry")
    _del(SourceDocument, "source_document")
    _del(Reconciliation, "reconciliation")
    _del(Asset, "asset")
    _del(BankTransaction, "bank_transaction")
    if not keep_audit:
        _del(AuditEvent, "audit_event")
    else:
        deleted["audit_event"] = 0

    sess.flush()

    notes = [
        "Chart of accounts and accounting periods preserved.",
        "Encrypted blob objects in object storage are not deleted (orphan, harmless).",
    ]
    if keep_audit:
        notes.append("Audit trail preserved (pass keep_audit=false to delete).")

    return ResetOut(client_id=client_id, deleted=deleted, notes=notes)


__all__: tuple[Literal["router"], ...] = ("router",)
