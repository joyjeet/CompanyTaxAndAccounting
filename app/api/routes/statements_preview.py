"""Inline statement preview: returns rendered P&L / Balance Sheet / Cash Flow
as JSON without persisting an artifact. The artifact endpoints in
`app.api.routes.reports` are still the right call when you want a permanent,
encrypted, finalizable output; this endpoint exists so the UI can render the
financial tables interactively.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.db.tenant import AccessScope
from app.domain.statements import (
    AccountBalance,
    BalanceSheet,
    CashFlowStatement,
    ProfitAndLoss,
    StatementsService,
)
from app.models.accounting import AccountingPeriod, Client

router = APIRouter(prefix="/statements", tags=["statements"])


# --------------------------------------------------------------------------- #
class AccountBalanceOut(BaseModel):
    account_id: UUID
    code: str
    name: str
    account_type: str
    debit_total: Decimal
    credit_total: Decimal
    signed_balance: Decimal


class ProfitAndLossOut(BaseModel):
    kind: Literal["profit_and_loss"] = "profit_and_loss"
    period_start: str
    period_end: str
    revenue: list[AccountBalanceOut]
    expenses: list[AccountBalanceOut]
    total_revenue: Decimal
    total_expenses: Decimal
    net_income: Decimal


class BalanceSheetOut(BaseModel):
    kind: Literal["balance_sheet"] = "balance_sheet"
    as_of: str
    assets: list[AccountBalanceOut]
    liabilities: list[AccountBalanceOut]
    equity: list[AccountBalanceOut]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    retained_earnings_to_date: Decimal
    balances: bool


class CashFlowOut(BaseModel):
    kind: Literal["cash_flow"] = "cash_flow"
    period_start: str
    period_end: str
    cash_account_codes: list[str]
    opening_cash: Decimal
    closing_cash: Decimal
    net_change: Decimal
    inflows: Decimal
    outflows: Decimal


def _ab_out(b: AccountBalance) -> AccountBalanceOut:
    return AccountBalanceOut(
        account_id=b.account_id,
        code=b.code,
        name=b.name,
        account_type=b.account_type.value,
        debit_total=b.debit_total,
        credit_total=b.credit_total,
        signed_balance=b.signed_balance,
    )


def _pl_out(pl: ProfitAndLoss) -> ProfitAndLossOut:
    return ProfitAndLossOut(
        period_start=pl.period_start.isoformat(),
        period_end=pl.period_end.isoformat(),
        revenue=[_ab_out(b) for b in pl.revenue],
        expenses=[_ab_out(b) for b in pl.expenses],
        total_revenue=pl.total_revenue,
        total_expenses=pl.total_expenses,
        net_income=pl.net_income,
    )


def _bs_out(bs: BalanceSheet) -> BalanceSheetOut:
    return BalanceSheetOut(
        as_of=bs.as_of.isoformat(),
        assets=[_ab_out(b) for b in bs.assets],
        liabilities=[_ab_out(b) for b in bs.liabilities],
        equity=[_ab_out(b) for b in bs.equity],
        total_assets=bs.total_assets,
        total_liabilities=bs.total_liabilities,
        total_equity=bs.total_equity,
        retained_earnings_to_date=bs.retained_earnings_to_date,
        balances=bs.balances,
    )


def _cf_out(cf: CashFlowStatement) -> CashFlowOut:
    return CashFlowOut(
        period_start=cf.period_start.isoformat(),
        period_end=cf.period_end.isoformat(),
        cash_account_codes=cf.cash_account_codes,
        opening_cash=cf.opening_cash,
        closing_cash=cf.closing_cash,
        net_change=cf.net_change,
        inflows=cf.inflows,
        outflows=cf.outflows,
    )


# --------------------------------------------------------------------------- #
def _require_client_access(identity: AuthIdentity, client_id: UUID) -> None:
    if identity.scope is AccessScope.CLIENT and identity.client_id != client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cross-client access denied",
        )


def _load_period(sess: Session, client_id: UUID, period_id: UUID) -> AccountingPeriod:
    p = sess.get(AccountingPeriod, period_id)
    if p is None or p.client_id != client_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="period not found for this client",
        )
    return p


# --------------------------------------------------------------------------- #
@router.get(
    "/profit-and-loss",
    response_model=ProfitAndLossOut,
)
def get_pl(
    client_id: UUID = Query(...),
    period_id: UUID = Query(...),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> ProfitAndLossOut:
    _require_client_access(identity, client_id)
    if sess.get(Client, client_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client not found")
    period = _load_period(sess, client_id, period_id)
    svc = StatementsService(sess, firm_id=identity.firm_id, client_id=client_id)
    pl = svc.profit_and_loss(period_start=period.start_date, period_end=period.end_date)
    return _pl_out(pl)


@router.get(
    "/balance-sheet",
    response_model=BalanceSheetOut,
)
def get_bs(
    client_id: UUID = Query(...),
    period_id: UUID = Query(...),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> BalanceSheetOut:
    _require_client_access(identity, client_id)
    if sess.get(Client, client_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client not found")
    period = _load_period(sess, client_id, period_id)
    svc = StatementsService(sess, firm_id=identity.firm_id, client_id=client_id)
    bs = svc.balance_sheet(as_of=period.end_date)
    return _bs_out(bs)


@router.get(
    "/cash-flow",
    response_model=CashFlowOut,
)
def get_cf(
    client_id: UUID = Query(...),
    period_id: UUID = Query(...),
    cash_account_codes: str | None = Query(
        default=None,
        description="comma-separated COA codes treated as cash; defaults to '1000'",
    ),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> CashFlowOut:
    _require_client_access(identity, client_id)
    if sess.get(Client, client_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client not found")
    period = _load_period(sess, client_id, period_id)
    codes = (
        [c.strip() for c in cash_account_codes.split(",") if c.strip()]
        if cash_account_codes
        else ["1000"]
    )
    svc = StatementsService(sess, firm_id=identity.firm_id, client_id=client_id)
    cf = svc.cash_flow(
        period_start=period.start_date,
        period_end=period.end_date,
        cash_account_codes=codes,
    )
    return _cf_out(cf)
