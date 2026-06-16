"""Financial statement generators.

These functions compute Profit & Loss, Balance Sheet, and Cash Flow ENTIRELY
by aggregating `journal_line` rows in SQL. No free-hand math, no AI.

Sign convention
---------------
For each account, we compute `signed_balance` such that the value is positive
when the account is at its natural normal balance:

    asset, expense   (normal=debit)  -> debit  - credit
    liability, equity, revenue (cred) -> credit - debit

This means "Cash" is positive when there's cash; "Accounts Payable" is positive
when we owe money; "Revenue" is positive when we've earned money.

Balance Sheet identity:
    sum(asset signed_balance)
        == sum(liability signed_balance) + sum(equity signed_balance) + net_income

where net_income = sum(revenue signed) - sum(expense signed)
                 = sum(revenue.credit - revenue.debit) - sum(expense.debit - expense.credit)

We assert this identity in code on every balance sheet generation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.accounting import (
    ChartOfAccounts,
    JournalEntry,
    JournalLine,
)
from app.models.enums import AccountType, JournalEntryStatus

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class AccountBalance:
    account_id: UUID
    code: str
    name: str
    account_type: AccountType
    debit_total: Decimal
    credit_total: Decimal
    signed_balance: Decimal


@dataclass(frozen=True, slots=True)
class ProfitAndLoss:
    period_start: date
    period_end: date
    revenue: list[AccountBalance]
    expenses: list[AccountBalance]
    total_revenue: Decimal
    total_expenses: Decimal
    net_income: Decimal


@dataclass(frozen=True, slots=True)
class BalanceSheet:
    as_of: date
    assets: list[AccountBalance]
    liabilities: list[AccountBalance]
    equity: list[AccountBalance]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    retained_earnings_to_date: Decimal  # cumulative net income up to as_of
    balances: bool  # assets == liabilities + equity (incl. retained earnings)


@dataclass(frozen=True, slots=True)
class CashFlowStatement:
    period_start: date
    period_end: date
    cash_account_codes: list[str]
    opening_cash: Decimal
    closing_cash: Decimal
    net_change: Decimal
    inflows: Decimal
    outflows: Decimal


# --------------------------------------------------------------------------- #
def _balance_query(sess: Session, *, firm_id: UUID, client_id: UUID,
                   start: date | None, end: date) -> dict[UUID, tuple[Decimal, Decimal]]:
    """Return {account_id: (sum_debit, sum_credit)} over the date range, posted only."""
    conds = [
        JournalLine.firm_id == firm_id,
        JournalLine.client_id == client_id,
        JournalEntry.status == JournalEntryStatus.POSTED,
        JournalEntry.entry_date <= end,
    ]
    if start is not None:
        conds.append(JournalEntry.entry_date >= start)

    stmt = (
        select(
            JournalLine.account_id,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(and_(*conds))
        .group_by(JournalLine.account_id)
    )
    rows = sess.execute(stmt).all()
    return {r[0]: (Decimal(str(r[1])), Decimal(str(r[2]))) for r in rows}


def _accounts(sess: Session, *, firm_id: UUID, client_id: UUID) -> list[ChartOfAccounts]:
    return list(
        sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.firm_id == firm_id,
                ChartOfAccounts.client_id == client_id,
            )
        ).scalars()
    )


def _signed(account_type: AccountType, debit: Decimal, credit: Decimal) -> Decimal:
    if account_type in (AccountType.ASSET, AccountType.EXPENSE):
        return debit - credit
    return credit - debit


def _balances_for(
    sess: Session, *, firm_id: UUID, client_id: UUID,
    start: date | None, end: date,
    types: tuple[AccountType, ...] | None = None,
) -> list[AccountBalance]:
    totals = _balance_query(sess, firm_id=firm_id, client_id=client_id, start=start, end=end)
    accounts = _accounts(sess, firm_id=firm_id, client_id=client_id)
    out: list[AccountBalance] = []
    for a in accounts:
        if types is not None and a.account_type not in types:
            continue
        debit, credit = totals.get(a.id, (ZERO, ZERO))
        out.append(
            AccountBalance(
                account_id=a.id,
                code=a.code,
                name=a.name,
                account_type=a.account_type,
                debit_total=debit,
                credit_total=credit,
                signed_balance=_signed(a.account_type, debit, credit),
            )
        )
    out.sort(key=lambda x: x.code)
    return out


# --------------------------------------------------------------------------- #
class StatementsService:
    def __init__(self, sess: Session, *, firm_id: UUID, client_id: UUID):
        self.sess = sess
        self.firm_id = firm_id
        self.client_id = client_id

    # ---- P&L ----------------------------------------------------------- #
    def profit_and_loss(self, *, period_start: date, period_end: date) -> ProfitAndLoss:
        revenue = _balances_for(
            self.sess, firm_id=self.firm_id, client_id=self.client_id,
            start=period_start, end=period_end, types=(AccountType.REVENUE,),
        )
        expenses = _balances_for(
            self.sess, firm_id=self.firm_id, client_id=self.client_id,
            start=period_start, end=period_end, types=(AccountType.EXPENSE,),
        )
        total_rev = sum((b.signed_balance for b in revenue), start=ZERO)
        total_exp = sum((b.signed_balance for b in expenses), start=ZERO)
        return ProfitAndLoss(
            period_start=period_start,
            period_end=period_end,
            revenue=revenue,
            expenses=expenses,
            total_revenue=total_rev,
            total_expenses=total_exp,
            net_income=total_rev - total_exp,
        )

    # ---- Balance Sheet ------------------------------------------------- #
    def balance_sheet(self, *, as_of: date) -> BalanceSheet:
        # Cumulative balances up to as_of for B/S accounts.
        assets = _balances_for(
            self.sess, firm_id=self.firm_id, client_id=self.client_id,
            start=None, end=as_of, types=(AccountType.ASSET,),
        )
        liabilities = _balances_for(
            self.sess, firm_id=self.firm_id, client_id=self.client_id,
            start=None, end=as_of, types=(AccountType.LIABILITY,),
        )
        equity = _balances_for(
            self.sess, firm_id=self.firm_id, client_id=self.client_id,
            start=None, end=as_of, types=(AccountType.EQUITY,),
        )
        # Retained earnings = cumulative net income from inception through as_of.
        revenue_to_date = _balances_for(
            self.sess, firm_id=self.firm_id, client_id=self.client_id,
            start=None, end=as_of, types=(AccountType.REVENUE,),
        )
        expense_to_date = _balances_for(
            self.sess, firm_id=self.firm_id, client_id=self.client_id,
            start=None, end=as_of, types=(AccountType.EXPENSE,),
        )
        retained = (
            sum((b.signed_balance for b in revenue_to_date), start=ZERO)
            - sum((b.signed_balance for b in expense_to_date), start=ZERO)
        )
        total_a = sum((b.signed_balance for b in assets), start=ZERO)
        total_l = sum((b.signed_balance for b in liabilities), start=ZERO)
        total_e = sum((b.signed_balance for b in equity), start=ZERO) + retained
        balances = total_a == (total_l + total_e)
        if not balances:  # invariant — must hold for any valid double-entry book
            raise AssertionError(
                f"Balance sheet does not balance: assets={total_a}, "
                f"liabilities+equity={total_l + total_e}, "
                f"diff={total_a - (total_l + total_e)}"
            )
        return BalanceSheet(
            as_of=as_of,
            assets=assets,
            liabilities=liabilities,
            equity=equity,
            total_assets=total_a,
            total_liabilities=total_l,
            total_equity=total_e,
            retained_earnings_to_date=retained,
            balances=balances,
        )

    # ---- Cash Flow (direct, change-in-cash) ---------------------------- #
    def cash_flow(
        self,
        *,
        period_start: date,
        period_end: date,
        cash_account_codes: list[str],
    ) -> CashFlowStatement:
        """Direct change-in-cash. Sums debits/credits to the listed cash accounts.

        A full operating/investing/financing breakdown will arrive with the
        statement-classification module; this returns the deterministic
        change-in-cash core that everything else builds on.
        """
        # Resolve account codes -> ids in this tenant.
        cash_accounts = list(self.sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.firm_id == self.firm_id,
                ChartOfAccounts.client_id == self.client_id,
                ChartOfAccounts.code.in_(cash_account_codes),
                ChartOfAccounts.account_type == AccountType.ASSET,
            )
        ).scalars())
        if not cash_accounts:
            raise ValueError("No matching cash accounts found.")
        cash_ids = [a.id for a in cash_accounts]

        # Opening cash = balances up to (period_start - 1).
        opening = _opening_or_closing_cash(
            self.sess, firm_id=self.firm_id, client_id=self.client_id,
            cash_ids=cash_ids, end=_prev_day(period_start),
        )
        closing = _opening_or_closing_cash(
            self.sess, firm_id=self.firm_id, client_id=self.client_id,
            cash_ids=cash_ids, end=period_end,
        )

        # Inflows / outflows during period: debit increases cash (asset), credit decreases.
        period_in_out = self.sess.execute(
            select(
                func.coalesce(func.sum(JournalLine.debit), 0),
                func.coalesce(func.sum(JournalLine.credit), 0),
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(
                JournalLine.firm_id == self.firm_id,
                JournalLine.client_id == self.client_id,
                JournalLine.account_id.in_(cash_ids),
                JournalEntry.status == JournalEntryStatus.POSTED,
                JournalEntry.entry_date >= period_start,
                JournalEntry.entry_date <= period_end,
            )
        ).one()
        inflows = Decimal(str(period_in_out[0]))
        outflows = Decimal(str(period_in_out[1]))
        net_change = inflows - outflows
        if closing - opening != net_change:
            raise AssertionError(
                f"Cash-flow invariant violated: opening={opening}, closing={closing}, "
                f"computed change={closing - opening}, sum of period flows={net_change}"
            )
        return CashFlowStatement(
            period_start=period_start,
            period_end=period_end,
            cash_account_codes=cash_account_codes,
            opening_cash=opening,
            closing_cash=closing,
            net_change=net_change,
            inflows=inflows,
            outflows=outflows,
        )


def _prev_day(d: date) -> date:
    from datetime import timedelta

    return d - timedelta(days=1)


def _opening_or_closing_cash(
    sess: Session, *, firm_id: UUID, client_id: UUID,
    cash_ids: list[UUID], end: date,
) -> Decimal:
    row = sess.execute(
        select(
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            JournalLine.firm_id == firm_id,
            JournalLine.client_id == client_id,
            JournalLine.account_id.in_(cash_ids),
            JournalEntry.status == JournalEntryStatus.POSTED,
            JournalEntry.entry_date <= end,
        )
    ).one()
    return Decimal(str(row[0])) - Decimal(str(row[1]))
