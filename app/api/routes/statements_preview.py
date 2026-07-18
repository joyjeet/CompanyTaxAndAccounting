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
    TrialBalance,
    _accounts as _all_accounts_for,
    _balances_for,
)
from app.domain.reports import (
    AccountNotFoundError,
    AgingAccountNotFoundError,
    AgingAccountTypeMismatchError,
    AgingReport,
    AgingService,
    DrillDownResult,
    DrillDownService,
    GeneralLedger,
    GeneralLedgerService,
    RollupNode,
    build_rollup_tree,
)
from app.models.accounting import AccountingPeriod, Client
from app.models.enums import AccountType
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


class TrialBalanceOut(BaseModel):
    kind: Literal["trial_balance"] = "trial_balance"
    as_of: str
    rows: list[AccountBalanceOut]
    total_debits: Decimal
    total_credits: Decimal
    balances: bool


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


def _is_zero(value: Decimal) -> bool:
    return value == Decimal("0")


def _has_nonzero_activity(b: AccountBalance) -> bool:
    return not (_is_zero(b.debit_total) and _is_zero(b.credit_total) and _is_zero(b.signed_balance))


def _has_nonzero_balance(b: AccountBalance) -> bool:
    return not _is_zero(b.signed_balance)


def _pl_out(pl: ProfitAndLoss) -> ProfitAndLossOut:
    revenue = [b for b in pl.revenue if _has_nonzero_balance(b)]
    expenses = [b for b in pl.expenses if _has_nonzero_balance(b)]
    return ProfitAndLossOut(
        period_start=pl.period_start.isoformat(),
        period_end=pl.period_end.isoformat(),
        revenue=[_ab_out(b) for b in revenue],
        expenses=[_ab_out(b) for b in expenses],
        total_revenue=pl.total_revenue,
        total_expenses=pl.total_expenses,
        net_income=pl.net_income,
    )


def _bs_out(bs: BalanceSheet) -> BalanceSheetOut:
    assets = [b for b in bs.assets if _has_nonzero_balance(b)]
    liabilities = [b for b in bs.liabilities if _has_nonzero_balance(b)]
    equity = [b for b in bs.equity if _has_nonzero_balance(b)]
    return BalanceSheetOut(
        as_of=bs.as_of.isoformat(),
        assets=[_ab_out(b) for b in assets],
        liabilities=[_ab_out(b) for b in liabilities],
        equity=[_ab_out(b) for b in equity],
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


def _tb_out(tb: TrialBalance) -> TrialBalanceOut:
    rows = [b for b in tb.rows if _has_nonzero_activity(b)]
    return TrialBalanceOut(
        as_of=tb.as_of.isoformat(),
        rows=[_ab_out(b) for b in rows],
        total_debits=tb.total_debits,
        total_credits=tb.total_credits,
        balances=tb.balances,
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


def _enforce_portal_finalized(identity: AuthIdentity, period: AccountingPeriod) -> None:
    """Portal users see live reports only for FINALIZED (locked) periods.

    Rationale (flagged for CPA review): a non-artifact report is "finalized"
    when its accounting period has been locked by the firm. While the period
    is open, balances can still change as bookkeepers post additional entries
    — exposing that to the client would let pending-draft work leak into a
    client-visible report, which the export rule forbids.

    Firm scope is unaffected (firm reviewers see all reports at all times).
    """
    if identity.scope is AccessScope.CLIENT and not period.is_locked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "report not yet finalized: the period is still open. "
                "Your firm will share this report once the period is closed."
            ),
        )


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
    _enforce_portal_finalized(identity, period)
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
    _enforce_portal_finalized(identity, period)
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
    _enforce_portal_finalized(identity, period)
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


@router.get(
    "/trial-balance",
    response_model=TrialBalanceOut,
)
def get_tb(
    client_id: UUID = Query(...),
    period_id: UUID = Query(...),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> TrialBalanceOut:
    """Cumulative debit/credit per account through the period end.

    A trial balance is the accountant's first sanity check: every account
    on the chart, with its total debits and total credits up to a given
    date. The footer asserts `total_debits == total_credits`, which must
    hold for any valid double-entry book.
    """
    _require_client_access(identity, client_id)
    if sess.get(Client, client_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client not found")
    period = _load_period(sess, client_id, period_id)
    _enforce_portal_finalized(identity, period)
    svc = StatementsService(sess, firm_id=identity.firm_id, client_id=client_id)
    tb = svc.trial_balance(as_of=period.end_date)
    return _tb_out(tb)


# --------------------------------------------------------------------------- #
# General Ledger
# --------------------------------------------------------------------------- #
class LedgerEntryOut(BaseModel):
    entry_id: UUID
    line_id: UUID
    entry_date: str
    memo: str | None
    line_description: str | None
    debit: Decimal
    credit: Decimal
    running_balance: Decimal


class GeneralLedgerOut(BaseModel):
    kind: Literal["general_ledger"] = "general_ledger"
    account_id: UUID
    account_code: str
    account_name: str
    account_type: str
    period_start: str
    period_end: str
    opening_balance: Decimal
    closing_balance: Decimal
    rows: list[LedgerEntryOut]


@router.get("/general-ledger", response_model=GeneralLedgerOut)
def get_general_ledger(
    client_id: UUID = Query(...),
    period_id: UUID = Query(...),
    account_id: UUID = Query(...),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> GeneralLedgerOut:
    """Per-account journal entries within a period with running balance.

    Used by the Reports UI to "open" an account row from any other
    report and see exactly which journal lines moved it.
    """
    _require_client_access(identity, client_id)
    if sess.get(Client, client_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client not found")
    period = _load_period(sess, client_id, period_id)
    _enforce_portal_finalized(identity, period)
    svc = GeneralLedgerService(sess, firm_id=identity.firm_id, client_id=client_id)
    try:
        gl = svc.general_ledger(
            account_id=account_id,
            period_start=period.start_date,
            period_end=period.end_date,
        )
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return GeneralLedgerOut(
        account_id=gl.account_id,
        account_code=gl.account_code,
        account_name=gl.account_name,
        account_type=gl.account_type.value,
        period_start=gl.period_start.isoformat(),
        period_end=gl.period_end.isoformat(),
        opening_balance=gl.opening_balance,
        closing_balance=gl.closing_balance,
        rows=[
            LedgerEntryOut(
                entry_id=r.entry_id,
                line_id=r.line_id,
                entry_date=r.entry_date.isoformat(),
                memo=r.memo,
                line_description=r.line_description,
                debit=r.debit,
                credit=r.credit,
                running_balance=r.running_balance,
            )
            for r in gl.rows
        ],
    )


# --------------------------------------------------------------------------- #
# AR / AP Aging
# --------------------------------------------------------------------------- #
class AgingBucketOut(BaseModel):
    label: str
    min_days: int
    max_days: int | None
    amount: Decimal


class AgingAccountRowOut(BaseModel):
    account_id: UUID
    account_code: str
    account_name: str
    total: Decimal
    buckets: list[AgingBucketOut]


class AgingReportOut(BaseModel):
    kind: Literal["ar_aging", "ap_aging"]
    as_of: str
    account_codes: list[str]
    rows: list[AgingAccountRowOut]
    totals_by_bucket: list[AgingBucketOut]
    grand_total: Decimal


def _aging_out(rep: AgingReport) -> AgingReportOut:
    kind: Literal["ar_aging", "ap_aging"] = "ar_aging" if rep.kind == "ar" else "ap_aging"
    return AgingReportOut(
        kind=kind,
        as_of=rep.as_of.isoformat(),
        account_codes=rep.account_codes,
        rows=[
            AgingAccountRowOut(
                account_id=r.account_id,
                account_code=r.account_code,
                account_name=r.account_name,
                total=r.total,
                buckets=[
                    AgingBucketOut(
                        label=b.label,
                        min_days=b.min_days,
                        max_days=b.max_days,
                        amount=b.amount,
                    )
                    for b in r.buckets
                ],
            )
            for r in rep.rows
        ],
        totals_by_bucket=[
            AgingBucketOut(
                label=b.label,
                min_days=b.min_days,
                max_days=b.max_days,
                amount=b.amount,
            )
            for b in rep.totals_by_bucket
        ],
        grand_total=rep.grand_total,
    )


def _aging_endpoint(
    *,
    sess: Session,
    identity: AuthIdentity,
    client_id: UUID,
    period_id: UUID,
    account_codes: str | None,
    default_code: str,
    method_name: Literal["ar_aging", "ap_aging"],
) -> AgingReportOut:
    _require_client_access(identity, client_id)
    if sess.get(Client, client_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client not found")
    period = _load_period(sess, client_id, period_id)
    _enforce_portal_finalized(identity, period)
    codes = (
        [c.strip() for c in account_codes.split(",") if c.strip()]
        if account_codes
        else [default_code]
    )
    svc = AgingService(sess, firm_id=identity.firm_id, client_id=client_id)
    try:
        rep = getattr(svc, method_name)(
            as_of=period.end_date, account_codes=codes,
        )
    except AgingAccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AgingAccountTypeMismatchError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _aging_out(rep)


@router.get("/ar-aging", response_model=AgingReportOut)
def get_ar_aging(
    client_id: UUID = Query(...),
    period_id: UUID = Query(...),
    account_codes: str | None = Query(
        default=None,
        description=(
            "comma-separated COA codes treated as AR; defaults to '1200' "
            "(standard 'Accounts Receivable' in the starter chart)"
        ),
    ),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> AgingReportOut:
    """Receivables aged 0-30 / 31-60 / 61-90 / 90+ days as of period_end."""
    return _aging_endpoint(
        sess=sess,
        identity=identity,
        client_id=client_id,
        period_id=period_id,
        account_codes=account_codes,
        default_code="1200",
        method_name="ar_aging",
    )


@router.get("/ap-aging", response_model=AgingReportOut)
def get_ap_aging(
    client_id: UUID = Query(...),
    period_id: UUID = Query(...),
    account_codes: str | None = Query(
        default=None,
        description=(
            "comma-separated COA codes treated as AP; defaults to '2000' "
            "(standard 'Accounts Payable' in the starter chart)"
        ),
    ),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> AgingReportOut:
    """Payables aged 0-30 / 31-60 / 61-90 / 90+ days as of period_end."""
    return _aging_endpoint(
        sess=sess,
        identity=identity,
        client_id=client_id,
        period_id=period_id,
        account_codes=account_codes,
        default_code="2000",
        method_name="ap_aging",
    )


# --------------------------------------------------------------------------- #
# Drill-down (figure -> source entries)
# --------------------------------------------------------------------------- #
class DrillDownLineOut(BaseModel):
    entry_id: UUID
    line_id: UUID
    entry_date: str
    account_id: UUID
    account_code: str
    account_name: str
    memo: str | None
    line_description: str | None
    debit: Decimal
    credit: Decimal
    source_document_id: UUID | None


class DrillDownOut(BaseModel):
    kind: Literal["account_activity"] = "account_activity"
    account_id: UUID
    account_code: str
    account_name: str
    is_rollup: bool
    leaf_account_ids: list[UUID]
    period_start: str
    period_end: str
    total_debit: Decimal
    total_credit: Decimal
    signed_total: Decimal
    lines: list[DrillDownLineOut]


@router.get("/account-activity", response_model=DrillDownOut)
def get_account_activity(
    client_id: UUID = Query(...),
    period_id: UUID = Query(...),
    account_id: UUID = Query(...),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> DrillDownOut:
    """Drill-down: return the journal lines that produced any report figure.

    Works for leaves (their own lines) and parents (all leaf-descendant lines).
    """
    _require_client_access(identity, client_id)
    if sess.get(Client, client_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client not found")
    period = _load_period(sess, client_id, period_id)
    _enforce_portal_finalized(identity, period)
    svc = DrillDownService(sess, firm_id=identity.firm_id, client_id=client_id)
    try:
        res = svc.account_activity(
            account_id=account_id,
            period_start=period.start_date,
            period_end=period.end_date,
        )
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return DrillDownOut(
        account_id=res.account_id,
        account_code=res.account_code,
        account_name=res.account_name,
        is_rollup=res.is_rollup,
        leaf_account_ids=res.leaf_account_ids,
        period_start=res.period_start.isoformat(),
        period_end=res.period_end.isoformat(),
        total_debit=res.total_debit,
        total_credit=res.total_credit,
        signed_total=res.signed_total,
        lines=[
            DrillDownLineOut(
                entry_id=ln.entry_id,
                line_id=ln.line_id,
                entry_date=ln.entry_date.isoformat(),
                account_id=ln.account_id,
                account_code=ln.account_code,
                account_name=ln.account_name,
                memo=ln.memo,
                line_description=ln.line_description,
                debit=ln.debit,
                credit=ln.credit,
                source_document_id=ln.source_document_id,
            )
            for ln in res.lines
        ],
    )


# --------------------------------------------------------------------------- #
# Account rollup tree (parent subtotals from leaves)
# --------------------------------------------------------------------------- #
class RollupNodeOut(BaseModel):
    account_id: UUID
    code: str
    name: str
    account_type: str
    depth: int
    is_leaf: bool
    debit_total: Decimal
    credit_total: Decimal
    signed_balance: Decimal
    children: list["RollupNodeOut"]


class RollupTreeOut(BaseModel):
    kind: Literal["account_rollup"] = "account_rollup"
    scope: Literal["balance_sheet", "profit_and_loss", "trial_balance"]
    period_start: str | None
    period_end: str
    roots: list[RollupNodeOut]


def _rollup_out(node: RollupNode) -> RollupNodeOut:
    return RollupNodeOut(
        account_id=node.account_id,
        code=node.code,
        name=node.name,
        account_type=node.account_type.value,
        depth=node.depth,
        is_leaf=node.is_leaf,
        debit_total=node.debit_total,
        credit_total=node.credit_total,
        signed_balance=node.signed_balance,
        children=[_rollup_out(c) for c in node.children],
    )


def _rollup_has_nonzero_activity(node: RollupNode) -> bool:
    return not (
        _is_zero(node.debit_total)
        and _is_zero(node.credit_total)
        and _is_zero(node.signed_balance)
    )


def _prune_zero_rollup_nodes(nodes: list[RollupNode]) -> list[RollupNode]:
    kept: list[RollupNode] = []
    for node in nodes:
        pruned_children = _prune_zero_rollup_nodes(node.children)
        if _rollup_has_nonzero_activity(node) or pruned_children:
            kept.append(
                RollupNode(
                    account_id=node.account_id,
                    code=node.code,
                    name=node.name,
                    account_type=node.account_type,
                    depth=node.depth,
                    is_leaf=node.is_leaf,
                    debit_total=node.debit_total,
                    credit_total=node.credit_total,
                    signed_balance=node.signed_balance,
                    children=pruned_children,
                )
            )
    return kept


RollupNodeOut.model_rebuild()


_ROLLUP_TYPES: dict[str, tuple[AccountType, ...]] = {
    "balance_sheet": (AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY),
    "profit_and_loss": (AccountType.REVENUE, AccountType.EXPENSE),
    "trial_balance": (
        AccountType.ASSET,
        AccountType.LIABILITY,
        AccountType.EQUITY,
        AccountType.REVENUE,
        AccountType.EXPENSE,
    ),
}


@router.get("/account-rollup", response_model=RollupTreeOut)
def get_account_rollup(
    client_id: UUID = Query(...),
    period_id: UUID = Query(...),
    scope: Literal["balance_sheet", "profit_and_loss", "trial_balance"] = Query(
        default="trial_balance",
    ),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> RollupTreeOut:
    """COA hierarchy with parent subtotals computed from leaf postings.

    Use `scope=balance_sheet` to get just assets/liabilities/equity (point-in-time
    through period_end), `scope=profit_and_loss` to get revenue/expense over the
    period, or `scope=trial_balance` (default) for everything cumulative.

    Parent subtotals are ALWAYS the sum of their leaf descendants — leaf-only
    posting is enforced by the ledger service, so parents never have direct
    postings to leak.
    """
    _require_client_access(identity, client_id)
    if sess.get(Client, client_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client not found")
    period = _load_period(sess, client_id, period_id)
    _enforce_portal_finalized(identity, period)

    types = _ROLLUP_TYPES[scope]
    start_date = period.start_date if scope == "profit_and_loss" else None
    balances = _balances_for(
        sess,
        firm_id=identity.firm_id,
        client_id=client_id,
        start=start_date,
        end=period.end_date,
        types=types,
    )
    accounts = [
        a
        for a in _all_accounts_for(
            sess, firm_id=identity.firm_id, client_id=client_id,
        )
        if a.account_type in types
    ]
    tree = build_rollup_tree(balances, accounts)
    pruned_tree = _prune_zero_rollup_nodes(tree)
    return RollupTreeOut(
        scope=scope,
        period_start=start_date.isoformat() if start_date is not None else None,
        period_end=period.end_date.isoformat(),
        roots=[_rollup_out(n) for n in pruned_tree],
    )
