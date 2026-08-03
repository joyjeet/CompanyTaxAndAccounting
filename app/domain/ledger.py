"""Double-entry ledger service.

Core invariant (enforced in code, then redundantly by the DB CHECK constraints):

    For every journal_entry, SUM(debits) == SUM(credits).
    Every line has exactly one of debit/credit > 0; the other is 0.
    No negative debits or credits.

The service refuses to persist anything unbalanced: it raises
`UnbalancedJournalEntryError` *before* SQL is emitted, and even if a caller
bypassed the service, the DB would still reject negative or both-sides-set
lines via CHECK constraints, and the engine's post step verifies the sum after
flush as a belt-and-suspenders check.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.audit import write_audit
from app.domain.exceptions import (
    CrossTenantError,
    InvalidAccountError,
    UnbalancedJournalEntryError,
)
from app.models.accounting import (
    AccountingPeriod,
    ChartOfAccounts,
    JournalEntry,
    JournalLine,
)
from app.models.enums import AuditAction, JournalEntryStatus

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class LineInput:
    """Input record for a journal line. Exactly one of debit/credit must be > 0."""

    account_id: UUID
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    description: str | None = None

    def __post_init__(self) -> None:
        # Coerce to Decimal defensively (rejects floats by design via Decimal(str(...))).
        if not isinstance(self.debit, Decimal):
            object.__setattr__(self, "debit", Decimal(str(self.debit)))
        if not isinstance(self.credit, Decimal):
            object.__setattr__(self, "credit", Decimal(str(self.credit)))


@dataclass(slots=True)
class _Validated:
    debit_total: Decimal = field(default=ZERO)
    credit_total: Decimal = field(default=ZERO)


def _validate_lines(lines: list[LineInput]) -> _Validated:
    if len(lines) < 2:
        raise UnbalancedJournalEntryError(
            "A journal entry must have at least two lines."
        )

    v = _Validated()
    for i, line in enumerate(lines):
        if line.debit < ZERO or line.credit < ZERO:
            raise UnbalancedJournalEntryError(
                f"Line {i}: debit and credit must both be >= 0."
            )
        if (line.debit > ZERO) == (line.credit > ZERO):
            raise UnbalancedJournalEntryError(
                f"Line {i}: exactly one of debit/credit must be > 0 (got "
                f"debit={line.debit}, credit={line.credit})."
            )
        v.debit_total += line.debit
        v.credit_total += line.credit

    if v.debit_total != v.credit_total:
        raise UnbalancedJournalEntryError(
            f"Journal entry is unbalanced: debits={v.debit_total}, "
            f"credits={v.credit_total}, diff={v.debit_total - v.credit_total}"
        )
    if v.debit_total == ZERO:
        raise UnbalancedJournalEntryError("Journal entry totals are zero.")
    return v


class LedgerService:
    """All journal posting goes through this class."""

    def __init__(self, sess: Session, *, firm_id: UUID, client_id: UUID, actor: str):
        self.sess = sess
        self.firm_id = firm_id
        self.client_id = client_id
        self.actor = actor

    # -------------------------------------------------------------------- #
    def _period_for_date(self, entry_date: date) -> AccountingPeriod:
        """Find (or create) the accounting period bucket for `entry_date`.

        Per the CPA who owns this system, the books are *continuous*: entries
        are filed by their real date and are never blocked by period bounds or
        locks. `journal_entry.period_id` is still a NOT NULL FK and periods
        remain useful for reporting, so we derive the bucket from the date
        instead of asking the user for one — auto-creating a calendar-year
        period the first time a year is posted to.
        """
        period = self.sess.execute(
            select(AccountingPeriod)
            .where(
                AccountingPeriod.firm_id == self.firm_id,
                AccountingPeriod.client_id == self.client_id,
                AccountingPeriod.start_date <= entry_date,
                AccountingPeriod.end_date >= entry_date,
            )
            .order_by(AccountingPeriod.start_date.desc())
        ).scalars().first()
        if period is not None:
            return period

        year = entry_date.year
        period = AccountingPeriod(
            firm_id=self.firm_id,
            client_id=self.client_id,
            name=str(year),
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31),
        )
        self.sess.add(period)
        self.sess.flush()  # need period.id
        return period

    # -------------------------------------------------------------------- #
    def post(
        self,
        *,
        period_id: UUID | None = None,
        entry_date: date,
        lines: list[LineInput],
        memo: str | None = None,
        source_document_id: UUID | None = None,
    ) -> JournalEntry:
        """Validate and post a balanced journal entry. Returns the persisted entry.

        Refuses to write anything if the entry is unbalanced. `period_id` is
        optional: when omitted the period is derived from `entry_date`.
        """
        v = _validate_lines(lines)

        if period_id is None:
            period = self._period_for_date(entry_date)
        else:
            # Explicit period: still verify tenancy (defense in depth — RLS
            # should already prevent cross-tenant reads).
            period = self.sess.get(AccountingPeriod, period_id)
            if period is None:
                # Could be missing OR hidden by RLS. Either way, treat as not found.
                raise CrossTenantError("Accounting period not found in this tenant.")
            if period.firm_id != self.firm_id or period.client_id != self.client_id:
                raise CrossTenantError("Accounting period belongs to another tenant.")
            # If the caller's period doesn't actually cover the entry date, the
            # date wins — file the entry in the period that matches it.
            if not (period.start_date <= entry_date <= period.end_date):
                period = self._period_for_date(entry_date)

        # Verify every account exists in this tenant. (RLS would also block.)
        account_ids = {line.account_id for line in lines}
        accounts = self.sess.execute(
            select(ChartOfAccounts).where(ChartOfAccounts.id.in_(account_ids))
        ).scalars().all()
        if len(accounts) != len(account_ids):
            raise InvalidAccountError(
                "One or more accounts are missing or not visible to this tenant."
            )
        for acct in accounts:
            if acct.firm_id != self.firm_id or acct.client_id != self.client_id:
                raise CrossTenantError(
                    f"Account {acct.id} belongs to another tenant."
                )
            if not acct.is_active:
                raise InvalidAccountError(f"Account {acct.code} is inactive.")
            # Leaf-only posting: parents/rollups are computed, never posted to.
            # This protects statement-rollup integrity (Phase 8b carry-over).
            if not acct.is_leaf:
                raise InvalidAccountError(
                    f"Account {acct.code} ({acct.name}) is a parent/rollup; "
                    "journal entries may only post to leaf accounts."
                )

        # Persist header.
        entry = JournalEntry(
            firm_id=self.firm_id,
            client_id=self.client_id,
            period_id=period.id,
            entry_date=entry_date,
            memo=memo,
            status=JournalEntryStatus.POSTED,
            source_document_id=source_document_id,
            posted_at=datetime.now(tz=UTC),
        )
        self.sess.add(entry)
        self.sess.flush()  # need entry.id

        # Persist lines.
        for i, line in enumerate(lines, start=1):
            self.sess.add(
                JournalLine(
                    firm_id=self.firm_id,
                    client_id=self.client_id,
                    entry_id=entry.id,
                    line_no=i,
                    account_id=line.account_id,
                    debit=line.debit,
                    credit=line.credit,
                    description=line.description,
                )
            )
        self.sess.flush()

        # Belt-and-suspenders: re-aggregate from DB and re-check the invariant.
        from sqlalchemy import func as _f

        totals = self.sess.execute(
            select(_f.coalesce(_f.sum(JournalLine.debit), 0),
                   _f.coalesce(_f.sum(JournalLine.credit), 0))
            .where(JournalLine.entry_id == entry.id)
        ).one()
        db_debits, db_credits = (Decimal(str(totals[0])), Decimal(str(totals[1])))
        if db_debits != db_credits or db_debits != v.debit_total:
            # Should be impossible, but if it ever happens, fail loudly.
            raise UnbalancedJournalEntryError(
                f"Post-flush invariant violated: db_debits={db_debits}, "
                f"db_credits={db_credits}, expected={v.debit_total}"
            )

        write_audit(
            self.sess,
            firm_id=self.firm_id,
            client_id=self.client_id,
            actor=self.actor,
            action=AuditAction.POST,
            entity_type="journal_entry",
            entity_id=entry.id,
            details={
                "entry_date": entry_date.isoformat(),
                "memo": memo,
                "total": str(v.debit_total),
                "line_count": len(lines),
            },
        )
        return entry

    # -------------------------------------------------------------------- #
    def reverse(self, *, entry_id: UUID, memo: str | None = None) -> JournalEntry:
        """Post a reversing entry that flips debits/credits of an existing entry."""
        original = self.sess.get(JournalEntry, entry_id)
        if original is None:
            raise CrossTenantError("Journal entry not found in this tenant.")
        if original.firm_id != self.firm_id or original.client_id != self.client_id:
            raise CrossTenantError("Journal entry belongs to another tenant.")
        if original.status != JournalEntryStatus.POSTED:
            raise UnbalancedJournalEntryError(
                f"Cannot reverse entry with status {original.status.value}."
            )

        reversal_lines = [
            LineInput(
                account_id=line.account_id,
                debit=line.credit,
                credit=line.debit,
                description=f"Reversal of line {line.line_no}",
            )
            for line in original.lines
        ]
        reversal = self.post(
            period_id=original.period_id,
            entry_date=original.entry_date,
            lines=reversal_lines,
            memo=memo or f"Reversal of {original.id}",
            source_document_id=original.source_document_id,
        )
        original.status = JournalEntryStatus.REVERSED
        self.sess.flush()
        write_audit(
            self.sess,
            firm_id=self.firm_id,
            client_id=self.client_id,
            actor=self.actor,
            action=AuditAction.REVERSE,
            entity_type="journal_entry",
            entity_id=original.id,
            details={"reversal_id": str(reversal.id)},
        )
        return reversal


# Convenience function for callers that don't want to construct a service.
def post_journal_entry(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    entry_date: date,
    lines: list[LineInput],
    period_id: UUID | None = None,
    memo: str | None = None,
    source_document_id: UUID | None = None,
) -> JournalEntry:
    return LedgerService(sess, firm_id=firm_id, client_id=client_id, actor=actor).post(
        period_id=period_id,
        entry_date=entry_date,
        lines=lines,
        memo=memo,
        source_document_id=source_document_id,
    )
