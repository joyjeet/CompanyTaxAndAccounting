"""Bank reconciliation.

Computes the ledger balance for an account as of a date and compares it to a
provided statement balance. Persists a `reconciliation` row and writes an
audit event. Matching individual transactions to journal lines is left to a
future module — this is the deterministic balance-vs-balance check.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.audit import write_audit
from app.domain.exceptions import CrossTenantError, InvalidAccountError
from app.models.accounting import (
    ChartOfAccounts,
    JournalEntry,
    JournalLine,
    Reconciliation,
)
from app.models.enums import (
    AccountType,
    AuditAction,
    JournalEntryStatus,
    ReconciliationStatus,
)


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    reconciliation_id: UUID
    account_id: UUID
    as_of: date
    statement_balance: Decimal
    ledger_balance: Decimal
    difference: Decimal
    status: ReconciliationStatus


def reconcile_account(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    account_id: UUID,
    as_of: date,
    statement_balance: Decimal,
    notes: str | None = None,
    tolerance: Decimal = Decimal("0.00"),
) -> ReconciliationResult:
    if not isinstance(statement_balance, Decimal):
        statement_balance = Decimal(str(statement_balance))

    account = sess.get(ChartOfAccounts, account_id)
    if account is None:
        raise CrossTenantError("Account not found in this tenant.")
    if account.firm_id != firm_id or account.client_id != client_id:
        raise CrossTenantError("Account belongs to another tenant.")
    if account.account_type != AccountType.ASSET:
        raise InvalidAccountError(
            "Reconciliation requires a cash/bank asset account."
        )

    # Ledger balance = signed (debit - credit) for an asset, posted only.
    row = sess.execute(
        select(
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalLine.firm_id == firm_id,
            JournalLine.client_id == client_id,
            JournalLine.account_id == account_id,
            JournalEntry.status == JournalEntryStatus.POSTED,
            JournalEntry.entry_date <= as_of,
        )
    ).one()
    ledger_balance = Decimal(str(row[0])) - Decimal(str(row[1]))
    difference = statement_balance - ledger_balance

    status = (
        ReconciliationStatus.COMPLETE
        if abs(difference) <= tolerance
        else ReconciliationStatus.DISCREPANCY
    )

    rec = Reconciliation(
        firm_id=firm_id,
        client_id=client_id,
        account_id=account_id,
        as_of_date=as_of,
        statement_balance=statement_balance,
        ledger_balance=ledger_balance,
        difference=difference,
        status=status,
        notes=notes,
    )
    sess.add(rec)
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=AuditAction.RECONCILE,
        entity_type="reconciliation",
        entity_id=rec.id,
        details={
            "account_id": str(account_id),
            "as_of": as_of.isoformat(),
            "statement_balance": str(statement_balance),
            "ledger_balance": str(ledger_balance),
            "difference": str(difference),
            "status": status.value,
        },
    )

    return ReconciliationResult(
        reconciliation_id=rec.id,
        account_id=account_id,
        as_of=as_of,
        statement_balance=statement_balance,
        ledger_balance=ledger_balance,
        difference=difference,
        status=status,
    )
