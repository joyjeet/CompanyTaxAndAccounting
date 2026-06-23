"""Client-facing reports area.

This module exposes the *additional* report shapes beyond the four statements
already implemented in `app.domain.statements` (Trial Balance, P&L, Balance
Sheet, Cash Flow). Everything here is computed deterministically from the
ledger (POSTED `journal_line` rows joined to their `journal_entry`); no AI,
no free-hand math.

What's in here
--------------

* `GeneralLedgerService.general_ledger(...)`
    Per-account list of journal entries within a date range, with a
    running signed balance.

* `AgingService.ar_aging(...)` / `ap_aging(...)`
    Outstanding receivables / payables grouped into 0-30 / 31-60 /
    61-90 / 90+ day buckets by the entry_date of the underlying journal
    line. Because we don't (yet) have an invoice subledger with explicit
    due dates, "age" is computed from the journal entry's `entry_date`.
    Each open journal line is treated as its own outstanding item; lines
    that net to zero on an account (e.g. invoice debited then payment
    credited on the same account) cancel via signed bucket sums. This
    matches what a single-ledger general-ledger system can deduce; a
    richer aging will become possible if/when an invoice/bill subledger
    is added.

* `DrillDownService.account_activity(...)`
    Given an account (leaf OR parent) and a date range, return the
    underlying POSTED journal entries that produced that figure. For
    a parent (rollup) account, the activity is the union of all leaf
    descendants — this is how a report user clicks "Sales: $42,000" and
    sees the individual journal entries that composed it.

* `build_rollup_tree(rows, accounts)`
    Given a flat list of `AccountBalance` rows and the COA, produces a
    hierarchical tree where each parent's subtotal is the sum of its
    leaf descendants' signed_balance. Parent accounts themselves never
    have direct postings (leaf-only posting is enforced by the ledger
    service), so a parent's reported number is *always* the sum of its
    leaves. This is what the UI uses to render expandable rollups.

Portal vs. firm scope
---------------------

These services do not gate on scope themselves — they assume the SQLAlchemy
session already has the correct RLS GUCs set (`app.current_firm`,
`app.current_client`, `app.access_scope`). The API routes are responsible
for the additional "portal only sees finalized (locked) periods" rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.domain.statements import AccountBalance, _signed
from app.models.accounting import (
    ChartOfAccounts,
    JournalEntry,
    JournalLine,
)
from app.models.enums import AccountType, JournalEntryStatus

ZERO = Decimal("0")


# --------------------------------------------------------------------------- #
# General Ledger
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class LedgerEntry:
    entry_id: UUID
    line_id: UUID
    entry_date: date
    memo: str | None
    line_description: str | None
    debit: Decimal
    credit: Decimal
    running_balance: Decimal  # signed (natural-balance) running total


@dataclass(frozen=True, slots=True)
class GeneralLedger:
    account_id: UUID
    account_code: str
    account_name: str
    account_type: AccountType
    period_start: date
    period_end: date
    opening_balance: Decimal  # signed, as-of (period_start - 1)
    closing_balance: Decimal  # signed, as-of period_end
    rows: list[LedgerEntry]


class GeneralLedgerService:
    """Per-account chronological activity with running balances.

    Used by the Reports UI to "open" an account and show every line that
    moved it during the period.
    """

    def __init__(self, sess: Session, *, firm_id: UUID, client_id: UUID):
        self.sess = sess
        self.firm_id = firm_id
        self.client_id = client_id

    def general_ledger(
        self,
        *,
        account_id: UUID,
        period_start: date,
        period_end: date,
    ) -> GeneralLedger:
        # Resolve the account (must belong to this tenant; RLS will hide
        # cross-tenant rows but we also check explicitly to give a clean
        # 404 instead of a silent empty result).
        account = self.sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.id == account_id,
                ChartOfAccounts.firm_id == self.firm_id,
                ChartOfAccounts.client_id == self.client_id,
            )
        ).scalar_one_or_none()
        if account is None:
            raise AccountNotFoundError(
                f"account {account_id} not found for this client",
            )

        # Opening balance = signed balance up to (period_start - 1).
        from datetime import timedelta

        opening_signed = self._signed_balance_through(
            account_id=account_id,
            account_type=account.account_type,
            through=period_start - timedelta(days=1),
        )

        rows_q = (
            select(
                JournalLine.id,
                JournalLine.entry_id,
                JournalEntry.entry_date,
                JournalEntry.memo,
                JournalLine.description,
                JournalLine.debit,
                JournalLine.credit,
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.firm_id == self.firm_id,
                JournalLine.client_id == self.client_id,
                JournalLine.account_id == account_id,
                JournalEntry.status == JournalEntryStatus.POSTED,
                JournalEntry.entry_date >= period_start,
                JournalEntry.entry_date <= period_end,
            )
            .order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.line_no)
        )

        running = opening_signed
        ledger_rows: list[LedgerEntry] = []
        for line_id, entry_id, entry_date, memo, descr, debit, credit in (
            self.sess.execute(rows_q).all()
        ):
            d = Decimal(str(debit))
            c = Decimal(str(credit))
            running = running + _signed(account.account_type, d, c)
            ledger_rows.append(
                LedgerEntry(
                    entry_id=entry_id,
                    line_id=line_id,
                    entry_date=entry_date,
                    memo=memo,
                    line_description=descr,
                    debit=d,
                    credit=c,
                    running_balance=running,
                )
            )

        return GeneralLedger(
            account_id=account.id,
            account_code=account.code,
            account_name=account.name,
            account_type=account.account_type,
            period_start=period_start,
            period_end=period_end,
            opening_balance=opening_signed,
            closing_balance=running,
            rows=ledger_rows,
        )

    def _signed_balance_through(
        self,
        *,
        account_id: UUID,
        account_type: AccountType,
        through: date,
    ) -> Decimal:
        from sqlalchemy import func as _func

        row = self.sess.execute(
            select(
                _func.coalesce(_func.sum(JournalLine.debit), 0),
                _func.coalesce(_func.sum(JournalLine.credit), 0),
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.firm_id == self.firm_id,
                JournalLine.client_id == self.client_id,
                JournalLine.account_id == account_id,
                JournalEntry.status == JournalEntryStatus.POSTED,
                JournalEntry.entry_date <= through,
            )
        ).one()
        return _signed(account_type, Decimal(str(row[0])), Decimal(str(row[1])))


# --------------------------------------------------------------------------- #
# AR / AP Aging
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AgingBucket:
    label: str  # "0-30", "31-60", "61-90", "90+"
    min_days: int
    max_days: int | None  # None == open-ended (90+)
    amount: Decimal


@dataclass(frozen=True, slots=True)
class AgingAccountRow:
    account_id: UUID
    account_code: str
    account_name: str
    total: Decimal
    buckets: list[AgingBucket]


@dataclass(frozen=True, slots=True)
class AgingReport:
    kind: str  # "ar" or "ap"
    as_of: date
    account_codes: list[str]
    rows: list[AgingAccountRow]
    totals_by_bucket: list[AgingBucket]
    grand_total: Decimal


# Standard aging buckets used by both AR and AP.
_BUCKET_SPECS: tuple[tuple[str, int, int | None], ...] = (
    ("0-30", 0, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("90+", 91, None),
)


def _bucket_for(days: int) -> str:
    for label, lo, hi in _BUCKET_SPECS:
        if days >= lo and (hi is None or days <= hi):
            return label
    # Should never happen — days < 0 (post-dated) gets lumped into 0-30.
    return "0-30"


class AgingService:
    """AR / AP aging.

    Strategy
    --------
    Without an invoice/bill subledger, the best we can derive from the
    general ledger is: for each named AR (or AP) account, take every
    POSTED journal line through `as_of`, signed so that a positive
    contribution means "still owed to us" (AR) or "still owed by us"
    (AP), bucket it by `as_of - entry_date`, and sum.

    Lines that net out (e.g. invoice on day 0, payment on day 12) leave
    a zero contribution in their bucket — exactly what you want.

    For AR, the natural balance is debit (asset), so the per-line
    signed contribution is `debit - credit` aged by its entry_date.
    For AP, natural is credit (liability), so it's `credit - debit`.

    Caller passes the list of AR (or AP) leaf account *codes*; we
    resolve them in this tenant and reject any whose AccountType doesn't
    match the report kind.
    """

    def __init__(self, sess: Session, *, firm_id: UUID, client_id: UUID):
        self.sess = sess
        self.firm_id = firm_id
        self.client_id = client_id

    def ar_aging(self, *, as_of: date, account_codes: list[str]) -> AgingReport:
        return self._aging(
            kind="ar",
            as_of=as_of,
            account_codes=account_codes,
            required_type=AccountType.ASSET,
        )

    def ap_aging(self, *, as_of: date, account_codes: list[str]) -> AgingReport:
        return self._aging(
            kind="ap",
            as_of=as_of,
            account_codes=account_codes,
            required_type=AccountType.LIABILITY,
        )

    def _aging(
        self,
        *,
        kind: str,
        as_of: date,
        account_codes: list[str],
        required_type: AccountType,
    ) -> AgingReport:
        if not account_codes:
            raise ValueError(f"{kind}_aging requires at least one account code")

        accounts = list(
            self.sess.execute(
                select(ChartOfAccounts).where(
                    ChartOfAccounts.firm_id == self.firm_id,
                    ChartOfAccounts.client_id == self.client_id,
                    ChartOfAccounts.code.in_(account_codes),
                )
            ).scalars()
        )
        if not accounts:
            raise AgingAccountNotFoundError(
                f"no matching accounts for codes {account_codes}",
            )
        wrong = [a for a in accounts if a.account_type is not required_type]
        if wrong:
            raise AgingAccountTypeMismatchError(
                f"{kind}_aging requires {required_type.value} accounts; "
                f"got: {[(a.code, a.account_type.value) for a in wrong]}",
            )

        # Pull all POSTED lines through as_of, ordered by entry_date.
        rows = list(
            self.sess.execute(
                select(
                    JournalLine.account_id,
                    JournalEntry.entry_date,
                    JournalLine.debit,
                    JournalLine.credit,
                )
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                .where(
                    JournalLine.firm_id == self.firm_id,
                    JournalLine.client_id == self.client_id,
                    JournalLine.account_id.in_([a.id for a in accounts]),
                    JournalEntry.status == JournalEntryStatus.POSTED,
                    JournalEntry.entry_date <= as_of,
                )
            ).all()
        )

        # Per-account, per-bucket signed sums.
        by_acct_bucket: dict[UUID, dict[str, Decimal]] = {
            a.id: {label: ZERO for label, _, _ in _BUCKET_SPECS} for a in accounts
        }
        for account_id, entry_date, debit, credit in rows:
            days = (as_of - entry_date).days
            if days < 0:
                # Post-dated entry (shouldn't normally happen for AR/AP);
                # treat as current.
                days = 0
            bucket = _bucket_for(days)
            signed = _signed(required_type, Decimal(str(debit)), Decimal(str(credit)))
            by_acct_bucket[account_id][bucket] += signed

        # Assemble per-account rows; skip accounts that net to zero entirely.
        report_rows: list[AgingAccountRow] = []
        for a in sorted(accounts, key=lambda x: x.code):
            buckets = [
                AgingBucket(
                    label=label,
                    min_days=lo,
                    max_days=hi,
                    amount=by_acct_bucket[a.id][label],
                )
                for label, lo, hi in _BUCKET_SPECS
            ]
            total = sum((b.amount for b in buckets), start=ZERO)
            if total == ZERO and all(b.amount == ZERO for b in buckets):
                continue
            report_rows.append(
                AgingAccountRow(
                    account_id=a.id,
                    account_code=a.code,
                    account_name=a.name,
                    total=total,
                    buckets=buckets,
                )
            )

        # Totals across all listed accounts.
        totals_by_bucket = [
            AgingBucket(
                label=label,
                min_days=lo,
                max_days=hi,
                amount=sum(
                    (by_acct_bucket[a.id][label] for a in accounts),
                    start=ZERO,
                ),
            )
            for label, lo, hi in _BUCKET_SPECS
        ]
        grand_total = sum((b.amount for b in totals_by_bucket), start=ZERO)

        return AgingReport(
            kind=kind,
            as_of=as_of,
            account_codes=[a.code for a in sorted(accounts, key=lambda x: x.code)],
            rows=report_rows,
            totals_by_bucket=totals_by_bucket,
            grand_total=grand_total,
        )


# --------------------------------------------------------------------------- #
# Drill-down (figure -> source entries)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class DrillDownLine:
    entry_id: UUID
    line_id: UUID
    entry_date: date
    account_id: UUID
    account_code: str
    account_name: str
    memo: str | None
    line_description: str | None
    debit: Decimal
    credit: Decimal
    source_document_id: UUID | None


@dataclass(frozen=True, slots=True)
class DrillDownResult:
    account_id: UUID
    account_code: str
    account_name: str
    is_rollup: bool  # True if the account has children (parent / non-leaf)
    leaf_account_ids: list[UUID]  # what we actually summed
    period_start: date
    period_end: date
    lines: list[DrillDownLine]
    total_debit: Decimal
    total_credit: Decimal
    signed_total: Decimal


class DrillDownService:
    """Trace any report figure back to its underlying journal lines.

    Given an account_id and a date range, return the individual journal
    lines (POSTED only) that produced the displayed number. If the
    account is a *parent* (rollup), expand to all leaf descendants and
    return their lines — the user clicks "Expenses: $1.2M" on a P&L and
    sees every expense line in the period.
    """

    def __init__(self, sess: Session, *, firm_id: UUID, client_id: UUID):
        self.sess = sess
        self.firm_id = firm_id
        self.client_id = client_id

    def account_activity(
        self,
        *,
        account_id: UUID,
        period_start: date,
        period_end: date,
    ) -> DrillDownResult:
        account = self.sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.id == account_id,
                ChartOfAccounts.firm_id == self.firm_id,
                ChartOfAccounts.client_id == self.client_id,
            )
        ).scalar_one_or_none()
        if account is None:
            raise AccountNotFoundError(
                f"account {account_id} not found for this client",
            )

        # Resolve which leaf accounts to actually sum. If the requested
        # account is a leaf, that's just itself. Otherwise expand via
        # the materialized `path` column ("1000>1010>...").
        if account.is_leaf:
            leaf_accounts = [account]
        else:
            prefix = f"{account.path}>" if account.path else f"{account.code}>"
            leaf_accounts = list(
                self.sess.execute(
                    select(ChartOfAccounts).where(
                        ChartOfAccounts.firm_id == self.firm_id,
                        ChartOfAccounts.client_id == self.client_id,
                        ChartOfAccounts.is_leaf.is_(True),
                        ChartOfAccounts.path.like(f"{prefix}%"),
                    )
                ).scalars()
            )

        leaf_ids = [a.id for a in leaf_accounts]
        if not leaf_ids:
            # Parent with no leaf descendants — possible for an empty
            # rollup node. Return an empty result rather than 500.
            return DrillDownResult(
                account_id=account.id,
                account_code=account.code,
                account_name=account.name,
                is_rollup=not account.is_leaf,
                leaf_account_ids=[],
                period_start=period_start,
                period_end=period_end,
                lines=[],
                total_debit=ZERO,
                total_credit=ZERO,
                signed_total=ZERO,
            )

        # Pre-build {leaf_id: (code, name, type)} for fast assembly.
        leaf_meta: dict[UUID, tuple[str, str, AccountType]] = {
            a.id: (a.code, a.name, a.account_type) for a in leaf_accounts
        }

        rows = self.sess.execute(
            select(
                JournalLine.id,
                JournalLine.entry_id,
                JournalEntry.entry_date,
                JournalLine.account_id,
                JournalEntry.memo,
                JournalLine.description,
                JournalLine.debit,
                JournalLine.credit,
                JournalEntry.source_document_id,
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                and_(
                    JournalLine.firm_id == self.firm_id,
                    JournalLine.client_id == self.client_id,
                    JournalLine.account_id.in_(leaf_ids),
                    JournalEntry.status == JournalEntryStatus.POSTED,
                    JournalEntry.entry_date >= period_start,
                    JournalEntry.entry_date <= period_end,
                )
            )
            .order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.line_no)
        ).all()

        lines: list[DrillDownLine] = []
        total_d = ZERO
        total_c = ZERO
        signed_total = ZERO
        for (
            line_id,
            entry_id,
            entry_date,
            line_account_id,
            memo,
            descr,
            debit,
            credit,
            source_doc_id,
        ) in rows:
            code, name, atype = leaf_meta[line_account_id]
            d = Decimal(str(debit))
            c = Decimal(str(credit))
            lines.append(
                DrillDownLine(
                    entry_id=entry_id,
                    line_id=line_id,
                    entry_date=entry_date,
                    account_id=line_account_id,
                    account_code=code,
                    account_name=name,
                    memo=memo,
                    line_description=descr,
                    debit=d,
                    credit=c,
                    source_document_id=source_doc_id,
                )
            )
            total_d += d
            total_c += c
            signed_total += _signed(atype, d, c)

        return DrillDownResult(
            account_id=account.id,
            account_code=account.code,
            account_name=account.name,
            is_rollup=not account.is_leaf,
            leaf_account_ids=leaf_ids,
            period_start=period_start,
            period_end=period_end,
            lines=lines,
            total_debit=total_d,
            total_credit=total_c,
            signed_total=signed_total,
        )


# --------------------------------------------------------------------------- #
# Rollup tree (parent subtotals from leaf rows)
# --------------------------------------------------------------------------- #
@dataclass
class RollupNode:
    account_id: UUID
    code: str
    name: str
    account_type: AccountType
    depth: int
    is_leaf: bool
    debit_total: Decimal
    credit_total: Decimal
    signed_balance: Decimal  # for leaves: own balance; for parents: sum of leaf descendants
    children: list["RollupNode"]


def build_rollup_tree(
    balances: list[AccountBalance],
    accounts: list[ChartOfAccounts],
) -> list[RollupNode]:
    """Build a parent/child tree of `RollupNode` from flat balances.

    Why this exists: a flat list of `AccountBalance` rows shows leaves
    only (well, technically it shows every COA row, but since leaf-only
    posting is enforced, parents will be all zeros). The UI wants to see
    parent subtotals — e.g. "5000 Expenses (rollup) $1.2M" expandable to
    "5010 Rent $400k", "5020 Salaries $800k". This walks the COA tree
    and sums each parent's leaf descendants' `signed_balance`.

    Invariant: for every parent `p`,
        p.signed_balance == sum(leaf.signed_balance for leaf in descendants(p))
    """
    bal_by_id: dict[UUID, AccountBalance] = {b.account_id: b for b in balances}
    acct_by_id: dict[UUID, ChartOfAccounts] = {a.id: a for a in accounts}

    # Pre-build child map.
    children_of: dict[UUID | None, list[ChartOfAccounts]] = {}
    for a in accounts:
        children_of.setdefault(a.parent_account_id, []).append(a)
    for kids in children_of.values():
        kids.sort(key=lambda x: x.code)

    def build(account: ChartOfAccounts) -> RollupNode:
        kids = [build(c) for c in children_of.get(account.id, [])]
        bal = bal_by_id.get(account.id)
        if account.is_leaf:
            debit = bal.debit_total if bal else ZERO
            credit = bal.credit_total if bal else ZERO
            signed = bal.signed_balance if bal else ZERO
        else:
            # Parent: aggregate from leaf descendants.
            debit = sum(
                (k.debit_total for k in kids if k.is_leaf),
                start=ZERO,
            ) + sum(
                (k.debit_total for k in kids if not k.is_leaf),
                start=ZERO,
            )
            credit = sum(
                (k.credit_total for k in kids if k.is_leaf),
                start=ZERO,
            ) + sum(
                (k.credit_total for k in kids if not k.is_leaf),
                start=ZERO,
            )
            signed = sum((k.signed_balance for k in kids), start=ZERO)
        return RollupNode(
            account_id=account.id,
            code=account.code,
            name=account.name,
            account_type=account.account_type,
            depth=account.depth,
            is_leaf=account.is_leaf,
            debit_total=debit,
            credit_total=credit,
            signed_balance=signed,
            children=kids,
        )

    # Roots in the universe we were given.
    root_accounts = [a for a in accounts if a.parent_account_id is None]
    root_accounts.sort(key=lambda x: x.code)
    # But only include roots that we actually have in `acct_by_id` (defensive).
    return [build(r) for r in root_accounts if r.id in acct_by_id]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class ReportsError(Exception):
    """Base for reports-domain errors."""


class AccountNotFoundError(ReportsError):
    pass


class AgingAccountNotFoundError(ReportsError):
    pass


class AgingAccountTypeMismatchError(ReportsError):
    pass


__all__ = [
    "AgingBucket",
    "AgingAccountRow",
    "AgingReport",
    "AgingService",
    "AgingAccountNotFoundError",
    "AgingAccountTypeMismatchError",
    "DrillDownLine",
    "DrillDownResult",
    "DrillDownService",
    "AccountNotFoundError",
    "GeneralLedger",
    "GeneralLedgerService",
    "LedgerEntry",
    "ReportsError",
    "RollupNode",
    "build_rollup_tree",
]
