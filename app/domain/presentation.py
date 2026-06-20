"""GAAP-style presentation layer for financial statements.

This module **never** computes ledger math directly. It consumes the
deterministic `StatementsService` outputs in `app/domain/statements.py` and
re-organises them into a polished, GAAP-conventional shape suitable for
client-ready reports.

Three presentations are produced:

* `PresentedProfitAndLoss` — Revenue → Gross Profit → Operating Expenses →
  Operating Income → Other → Net Income. With optional period-over-period
  comparatives (current vs prior) producing `$` and `%` variance per line.

* `PresentedBalanceSheet` — Assets split into CURRENT vs NON-CURRENT;
  Liabilities into CURRENT vs LONG-TERM; Equity (with retained earnings).
  Includes period-over-period comparatives.

* `PresentedCashFlow` — Full O/I/F breakdown built by tracing every posted
  journal entry that touches a configured cash account and classifying the
  contra side. Opening + closing cash MUST tie to the corresponding balance
  sheet line; we assert on every render.

Classification heuristics
-------------------------
Because the schema does NOT carry a per-account "current vs non-current" or
"operating vs investing vs financing" tag, we use deterministic rules based on
the chart-of-accounts code prefix and the `AccountType`. These rules are
encoded once here, documented, and surfaced on every presented payload via
`assumptions: tuple[str, ...]` so the reviewer / reader can verify them.

If a CoA does not match the convention, the affected account falls into a
safe-bucket: assets default to CURRENT; liabilities default to CURRENT;
non-cash side of a cash JE defaults to OPERATING. Defaults never raise.

The conventions are CONFIGURABLE via `PresentationRules` so a future client
who codes their CoA differently can override the prefixes without changing
the engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.domain.statements import (
    AccountBalance,
    BalanceSheet,
    CashFlowStatement,
    ProfitAndLoss,
    StatementsService,
)
from app.models.accounting import (
    ChartOfAccounts,
    JournalEntry,
    JournalLine,
)
from app.models.enums import AccountType, JournalEntryStatus

ZERO = Decimal("0")
HUNDRED = Decimal("100")


# --------------------------------------------------------------------------- #
# Configurable rules
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PresentationRules:
    """Prefix-based classification rules.

    Defaults follow the common US small-business CoA convention used by the
    seeded test world:

      1000-1499 : current assets
      1500-1999 : non-current assets (PP&E, intangibles)
      2000-2499 : current liabilities
      2500-2999 : long-term liabilities
      3000-3999 : equity
      4000-4999 : revenue
      5000-5999 : COGS / operating expenses
      6000-6999 : other expense
      7000-7999 : other income
    """

    current_asset_max_code: str = "1499"
    current_liability_max_code: str = "2499"
    cogs_code_range: tuple[str, str] = ("5000", "5099")
    other_income_code_min: str = "7000"
    other_expense_code_min: str = "6000"

    # Cash flow: code prefixes mapped to a CF section. Account types take
    # priority; codes are used to differentiate within an asset or liability
    # account type.
    long_term_asset_min: str = "1500"
    long_term_liability_min: str = "2500"

    @property
    def assumptions(self) -> tuple[str, ...]:
        return (
            f"Current assets: code <= {self.current_asset_max_code}; "
            f"non-current assets: code >= {self.long_term_asset_min}.",
            f"Current liabilities: code <= {self.current_liability_max_code}; "
            f"long-term liabilities: code >= {self.long_term_liability_min}.",
            f"COGS: code in [{self.cogs_code_range[0]}..{self.cogs_code_range[1]}]; "
            f"all other expense accounts: operating expense.",
            f"Other income: code >= {self.other_income_code_min}; "
            f"other expense: code >= {self.other_expense_code_min}.",
            "Cash-flow classification (operating/investing/financing) is "
            "inferred from the contra account type and code on every cash JE; "
            "see the assumptions list on PresentedCashFlow for the exact rule.",
        )


# --------------------------------------------------------------------------- #
# Variance helpers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Variance:
    current: Decimal
    prior: Decimal
    delta: Decimal       # current - prior
    pct: Decimal | None  # None when prior == 0

    @classmethod
    def of(cls, current: Decimal, prior: Decimal) -> Variance:
        delta = current - prior
        if prior == ZERO:
            pct = None
        else:
            pct = (delta / prior * HUNDRED).quantize(Decimal("0.01"))
        return cls(current=current, prior=prior, delta=delta, pct=pct)


@dataclass(frozen=True, slots=True)
class PresentedLine:
    code: str
    name: str
    amount: Decimal
    variance: Variance | None = None  # set when comparatives are supplied


@dataclass(frozen=True, slots=True)
class PresentedSection:
    label: str
    lines: tuple[PresentedLine, ...]
    subtotal: Decimal
    subtotal_variance: Variance | None = None


# --------------------------------------------------------------------------- #
# Profit & Loss
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PresentedProfitAndLoss:
    period_start: date
    period_end: date
    revenue: PresentedSection
    cogs: PresentedSection
    gross_profit: Decimal
    gross_profit_variance: Variance | None
    operating_expenses: PresentedSection
    operating_income: Decimal
    operating_income_variance: Variance | None
    other_income: PresentedSection
    other_expenses: PresentedSection
    net_income: Decimal
    net_income_variance: Variance | None
    assumptions: tuple[str, ...]
    prior_period_start: date | None = None
    prior_period_end: date | None = None


def _is_cogs(code: str, rules: PresentationRules) -> bool:
    lo, hi = rules.cogs_code_range
    return lo <= code <= hi


def _is_other_income(code: str, rules: PresentationRules) -> bool:
    return code >= rules.other_income_code_min


def _is_other_expense(code: str, rules: PresentationRules) -> bool:
    # Excludes COGS (which is its own bucket).
    return code >= rules.other_expense_code_min and not _is_cogs(code, rules)


def _split_pl(
    pl: ProfitAndLoss,
    rules: PresentationRules,
) -> tuple[
    list[AccountBalance],  # operating revenue
    list[AccountBalance],  # other income
    list[AccountBalance],  # cogs
    list[AccountBalance],  # operating expense
    list[AccountBalance],  # other expense
]:
    op_revenue: list[AccountBalance] = []
    other_inc: list[AccountBalance] = []
    cogs: list[AccountBalance] = []
    op_exp: list[AccountBalance] = []
    other_exp: list[AccountBalance] = []
    for r in pl.revenue:
        (other_inc if _is_other_income(r.code, rules) else op_revenue).append(r)
    for e in pl.expenses:
        if _is_cogs(e.code, rules):
            cogs.append(e)
        elif _is_other_expense(e.code, rules):
            other_exp.append(e)
        else:
            op_exp.append(e)
    return op_revenue, other_inc, cogs, op_exp, other_exp


def _present_section(
    label: str,
    accounts: list[AccountBalance],
    prior_by_code: dict[str, Decimal] | None,
) -> PresentedSection:
    lines: list[PresentedLine] = []
    subtotal = ZERO
    for a in accounts:
        amt = a.signed_balance
        var = None
        if prior_by_code is not None:
            var = Variance.of(amt, prior_by_code.get(a.code, ZERO))
        lines.append(PresentedLine(code=a.code, name=a.name, amount=amt, variance=var))
        subtotal += amt
    sub_var = None
    if prior_by_code is not None:
        prior_sub = sum(
            (prior_by_code.get(a.code, ZERO) for a in accounts),
            start=ZERO,
        )
        sub_var = Variance.of(subtotal, prior_sub)
    return PresentedSection(
        label=label, lines=tuple(lines), subtotal=subtotal, subtotal_variance=sub_var,
    )


def present_profit_and_loss(
    pl: ProfitAndLoss,
    *,
    rules: PresentationRules | None = None,
    prior: ProfitAndLoss | None = None,
) -> PresentedProfitAndLoss:
    rules = rules or PresentationRules()
    op_rev, other_inc, cogs_acc, op_exp, other_exp = _split_pl(pl, rules)

    prior_by_code: dict[str, Decimal] = {}
    if prior is not None:
        for a in (*prior.revenue, *prior.expenses):
            prior_by_code[a.code] = a.signed_balance

    rev_section = _present_section(
        "Revenue", op_rev, prior_by_code if prior else None,
    )
    cogs_section = _present_section(
        "Cost of Goods Sold", cogs_acc, prior_by_code if prior else None,
    )
    op_exp_section = _present_section(
        "Operating Expenses", op_exp, prior_by_code if prior else None,
    )
    other_inc_section = _present_section(
        "Other Income", other_inc, prior_by_code if prior else None,
    )
    other_exp_section = _present_section(
        "Other Expenses", other_exp, prior_by_code if prior else None,
    )

    gross_profit = rev_section.subtotal - cogs_section.subtotal
    operating_income = gross_profit - op_exp_section.subtotal
    net_income = operating_income + other_inc_section.subtotal - other_exp_section.subtotal

    gp_var = oi_var = ni_var = None
    if prior is not None:
        prior_rev = sum(
            (b.signed_balance for b in prior.revenue if not _is_other_income(b.code, rules)),
            start=ZERO,
        )
        prior_cogs = sum(
            (b.signed_balance for b in prior.expenses if _is_cogs(b.code, rules)),
            start=ZERO,
        )
        prior_op_exp = sum(
            (
                b.signed_balance
                for b in prior.expenses
                if not _is_cogs(b.code, rules) and not _is_other_expense(b.code, rules)
            ),
            start=ZERO,
        )
        prior_other_inc = sum(
            (b.signed_balance for b in prior.revenue if _is_other_income(b.code, rules)),
            start=ZERO,
        )
        prior_other_exp = sum(
            (b.signed_balance for b in prior.expenses if _is_other_expense(b.code, rules)),
            start=ZERO,
        )
        prior_gross = prior_rev - prior_cogs
        prior_op_inc = prior_gross - prior_op_exp
        prior_ni = prior_op_inc + prior_other_inc - prior_other_exp
        gp_var = Variance.of(gross_profit, prior_gross)
        oi_var = Variance.of(operating_income, prior_op_inc)
        ni_var = Variance.of(net_income, prior_ni)

    return PresentedProfitAndLoss(
        period_start=pl.period_start,
        period_end=pl.period_end,
        revenue=rev_section,
        cogs=cogs_section,
        gross_profit=gross_profit,
        gross_profit_variance=gp_var,
        operating_expenses=op_exp_section,
        operating_income=operating_income,
        operating_income_variance=oi_var,
        other_income=other_inc_section,
        other_expenses=other_exp_section,
        net_income=net_income,
        net_income_variance=ni_var,
        assumptions=rules.assumptions,
        prior_period_start=prior.period_start if prior else None,
        prior_period_end=prior.period_end if prior else None,
    )


# --------------------------------------------------------------------------- #
# Balance Sheet
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PresentedBalanceSheet:
    as_of: date
    current_assets: PresentedSection
    non_current_assets: PresentedSection
    total_assets: Decimal
    total_assets_variance: Variance | None
    current_liabilities: PresentedSection
    long_term_liabilities: PresentedSection
    total_liabilities: Decimal
    equity: PresentedSection
    retained_earnings: Decimal
    retained_earnings_variance: Variance | None
    total_equity: Decimal
    total_liab_and_equity: Decimal
    balances: bool
    assumptions: tuple[str, ...]
    prior_as_of: date | None = None


def _bs_split_assets(
    accounts: list[AccountBalance], rules: PresentationRules,
) -> tuple[list[AccountBalance], list[AccountBalance]]:
    cur: list[AccountBalance] = []
    non_cur: list[AccountBalance] = []
    for a in accounts:
        if a.code <= rules.current_asset_max_code:
            cur.append(a)
        elif a.code >= rules.long_term_asset_min:
            non_cur.append(a)
        else:
            # Default safe-bucket: current.
            cur.append(a)
    return cur, non_cur


def _bs_split_liabilities(
    accounts: list[AccountBalance], rules: PresentationRules,
) -> tuple[list[AccountBalance], list[AccountBalance]]:
    cur: list[AccountBalance] = []
    lt: list[AccountBalance] = []
    for a in accounts:
        if a.code <= rules.current_liability_max_code:
            cur.append(a)
        elif a.code >= rules.long_term_liability_min:
            lt.append(a)
        else:
            cur.append(a)
    return cur, lt


def present_balance_sheet(
    bs: BalanceSheet,
    *,
    rules: PresentationRules | None = None,
    prior: BalanceSheet | None = None,
) -> PresentedBalanceSheet:
    rules = rules or PresentationRules()

    prior_by_code: dict[str, Decimal] = {}
    if prior is not None:
        for a in (*prior.assets, *prior.liabilities, *prior.equity):
            prior_by_code[a.code] = a.signed_balance

    cur_a, non_cur_a = _bs_split_assets(bs.assets, rules)
    cur_l, lt_l = _bs_split_liabilities(bs.liabilities, rules)

    cur_a_section = _present_section(
        "Current Assets", cur_a, prior_by_code if prior else None,
    )
    non_cur_a_section = _present_section(
        "Non-Current Assets", non_cur_a, prior_by_code if prior else None,
    )
    cur_l_section = _present_section(
        "Current Liabilities", cur_l, prior_by_code if prior else None,
    )
    lt_l_section = _present_section(
        "Long-Term Liabilities", lt_l, prior_by_code if prior else None,
    )
    equity_section = _present_section(
        "Equity", list(bs.equity), prior_by_code if prior else None,
    )

    total_assets = cur_a_section.subtotal + non_cur_a_section.subtotal
    total_liab = cur_l_section.subtotal + lt_l_section.subtotal
    total_equity = equity_section.subtotal + bs.retained_earnings_to_date
    total_le = total_liab + total_equity
    balances = total_assets == total_le
    if not balances:
        raise AssertionError(
            f"Presented balance sheet does not balance: "
            f"assets={total_assets} vs L+E={total_le}"
        )

    ta_var = re_var = None
    if prior is not None:
        ta_var = Variance.of(total_assets, prior.total_assets)
        re_var = Variance.of(bs.retained_earnings_to_date, prior.retained_earnings_to_date)

    return PresentedBalanceSheet(
        as_of=bs.as_of,
        current_assets=cur_a_section,
        non_current_assets=non_cur_a_section,
        total_assets=total_assets,
        total_assets_variance=ta_var,
        current_liabilities=cur_l_section,
        long_term_liabilities=lt_l_section,
        total_liabilities=total_liab,
        equity=equity_section,
        retained_earnings=bs.retained_earnings_to_date,
        retained_earnings_variance=re_var,
        total_equity=total_equity,
        total_liab_and_equity=total_le,
        balances=balances,
        assumptions=rules.assumptions,
        prior_as_of=prior.as_of if prior else None,
    )


# --------------------------------------------------------------------------- #
# Cash Flow (full O/I/F breakdown)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CashFlowSection:
    label: str
    lines: tuple[PresentedLine, ...]
    subtotal: Decimal


@dataclass(frozen=True, slots=True)
class PresentedCashFlow:
    period_start: date
    period_end: date
    cash_account_codes: tuple[str, ...]
    opening_cash: Decimal
    closing_cash: Decimal
    operating: CashFlowSection
    investing: CashFlowSection
    financing: CashFlowSection
    net_change: Decimal
    ties_to_balance_sheet: bool
    assumptions: tuple[str, ...]


def _classify_contra(
    account_type: AccountType, code: str, rules: PresentationRules,
) -> str:
    """Return one of 'operating' | 'investing' | 'financing'.

    Heuristic (flagged in assumptions):
      * REVENUE / EXPENSE                                          -> operating
      * ASSET with code <= current_asset_max_code (current asset)  -> operating
      * ASSET with code >= long_term_asset_min (fixed/long-term)   -> investing
      * LIABILITY with code <= current_liability_max_code          -> operating
      * LIABILITY with code >= long_term_liability_min             -> financing
      * EQUITY                                                     -> financing
    Default safe-bucket: operating.
    """
    if account_type in (AccountType.REVENUE, AccountType.EXPENSE):
        return "operating"
    if account_type is AccountType.ASSET:
        if code <= rules.current_asset_max_code:
            return "operating"
        if code >= rules.long_term_asset_min:
            return "investing"
        return "operating"
    if account_type is AccountType.LIABILITY:
        if code <= rules.current_liability_max_code:
            return "operating"
        if code >= rules.long_term_liability_min:
            return "financing"
        return "operating"
    if account_type is AccountType.EQUITY:
        return "financing"
    return "operating"


def present_cash_flow(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    period_start: date,
    period_end: date,
    cash_account_codes: list[str],
    rules: PresentationRules | None = None,
) -> PresentedCashFlow:
    """Build a full operating/investing/financing cash flow by tracing every
    posted JE that touches a cash account and classifying the contra side.

    Sign convention on cash side: cash debit = inflow (positive), cash credit
    = outflow (negative). Each non-cash line on the same JE picks up the
    OPPOSITE sign for its share so that the per-section subtotals sum to the
    period's net change in cash.
    """
    rules = rules or PresentationRules()
    svc = StatementsService(sess, firm_id=firm_id, client_id=client_id)
    # Reuse deterministic engine to get opening / closing cash + invariant check.
    raw_cf: CashFlowStatement = svc.cash_flow(
        period_start=period_start,
        period_end=period_end,
        cash_account_codes=cash_account_codes,
    )

    # Resolve cash account ids in this tenant.
    cash_rows = list(
        sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.firm_id == firm_id,
                ChartOfAccounts.client_id == client_id,
                ChartOfAccounts.code.in_(cash_account_codes),
                ChartOfAccounts.account_type == AccountType.ASSET,
            )
        ).scalars()
    )
    cash_ids = {a.id for a in cash_rows}

    # Fetch every posted JE in the period that touches a cash account, with
    # all its lines, joined to chart of accounts for type/code lookup.
    je_ids_q = (
        select(JournalEntry.id)
        .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
        .where(
            and_(
                JournalEntry.firm_id == firm_id,
                JournalEntry.client_id == client_id,
                JournalEntry.status == JournalEntryStatus.POSTED,
                JournalEntry.entry_date >= period_start,
                JournalEntry.entry_date <= period_end,
                JournalLine.account_id.in_(cash_ids),
            )
        )
        .group_by(JournalEntry.id)
    )
    je_ids = [r[0] for r in sess.execute(je_ids_q).all()]
    if not je_ids:
        return _empty_cf(
            period_start, period_end, cash_account_codes, raw_cf, rules,
        )

    lines_q = (
        select(JournalLine, ChartOfAccounts)
        .join(ChartOfAccounts, ChartOfAccounts.id == JournalLine.account_id)
        .where(JournalLine.entry_id.in_(je_ids))
    )
    rows = list(sess.execute(lines_q).all())

    # Group lines by JE so we can compute per-entry cash side and split.
    by_je: dict[UUID, list[tuple[JournalLine, ChartOfAccounts]]] = {}
    for jl, ca in rows:
        by_je.setdefault(jl.entry_id, []).append((jl, ca))

    op_buckets: dict[str, tuple[str, Decimal]] = {}
    inv_buckets: dict[str, tuple[str, Decimal]] = {}
    fin_buckets: dict[str, tuple[str, Decimal]] = {}

    for entry_lines in by_je.values():
        # Compute net cash impact (debit-credit) on cash accounts in this JE.
        cash_net = ZERO
        non_cash_signed_total = ZERO
        non_cash_lines: list[tuple[JournalLine, ChartOfAccounts]] = []
        for jl, ca in entry_lines:
            if ca.id in cash_ids:
                cash_net += Decimal(str(jl.debit)) - Decimal(str(jl.credit))
            else:
                signed = Decimal(str(jl.debit)) - Decimal(str(jl.credit))
                non_cash_signed_total += abs(signed)
                non_cash_lines.append((jl, ca))
        if cash_net == ZERO or not non_cash_lines:
            # JE that only moves cash among cash accounts has no CF effect.
            continue
        # Each non-cash line picks up a share of the cash impact proportional
        # to its absolute signed value, with the OPPOSITE sign of the cash
        # side so per-section subtotals reconcile to net change in cash.
        for jl, ca in non_cash_lines:
            signed = Decimal(str(jl.debit)) - Decimal(str(jl.credit))
            if non_cash_signed_total == ZERO:
                share = cash_net  # one non-cash line — gets the whole impact
            else:
                share = (abs(signed) / non_cash_signed_total) * cash_net
            section = _classify_contra(ca.account_type, ca.code, rules)
            bucket = (
                op_buckets if section == "operating"
                else inv_buckets if section == "investing"
                else fin_buckets
            )
            prev_name, prev_amt = bucket.get(ca.code, (ca.name, ZERO))
            bucket[ca.code] = (prev_name, prev_amt + share)

    def _to_section(label: str, b: dict[str, tuple[str, Decimal]]) -> CashFlowSection:
        ordered = sorted(b.items())
        lines = tuple(
            PresentedLine(code=code, name=nm, amount=amt)
            for code, (nm, amt) in ordered
        )
        return CashFlowSection(
            label=label,
            lines=lines,
            subtotal=sum((ln.amount for ln in lines), start=ZERO),
        )

    op = _to_section("Cash from Operating Activities", op_buckets)
    inv = _to_section("Cash from Investing Activities", inv_buckets)
    fin = _to_section("Cash from Financing Activities", fin_buckets)
    net = op.subtotal + inv.subtotal + fin.subtotal

    # Invariant: classified subtotals must equal opening/closing delta.
    expected = raw_cf.closing_cash - raw_cf.opening_cash
    # Allow tiny rounding from proportional splits.
    tie = abs(net - expected) <= Decimal("0.0001")
    if not tie:
        raise AssertionError(
            f"Cash-flow classification does not tie to ledger: "
            f"classified_net={net}, ledger_change={expected}"
        )

    assumptions = (
        *rules.assumptions,
        "Each cash JE's non-cash lines are classified by the contra account's "
        "type and code prefix; the share allocated to each contra line is "
        "proportional to its absolute amount on the entry.",
        "Sub-totals MUST sum to closing_cash - opening_cash; this is asserted "
        "on every render.",
    )

    return PresentedCashFlow(
        period_start=period_start,
        period_end=period_end,
        cash_account_codes=tuple(cash_account_codes),
        opening_cash=raw_cf.opening_cash,
        closing_cash=raw_cf.closing_cash,
        operating=op,
        investing=inv,
        financing=fin,
        net_change=net,
        ties_to_balance_sheet=tie,
        assumptions=assumptions,
    )


def _empty_cf(
    period_start: date,
    period_end: date,
    cash_account_codes: list[str],
    raw_cf: CashFlowStatement,
    rules: PresentationRules,
) -> PresentedCashFlow:
    return PresentedCashFlow(
        period_start=period_start,
        period_end=period_end,
        cash_account_codes=tuple(cash_account_codes),
        opening_cash=raw_cf.opening_cash,
        closing_cash=raw_cf.closing_cash,
        operating=CashFlowSection(label="Cash from Operating Activities", lines=(), subtotal=ZERO),
        investing=CashFlowSection(label="Cash from Investing Activities", lines=(), subtotal=ZERO),
        financing=CashFlowSection(label="Cash from Financing Activities", lines=(), subtotal=ZERO),
        net_change=ZERO,
        ties_to_balance_sheet=raw_cf.opening_cash == raw_cf.closing_cash,
        assumptions=rules.assumptions,
    )


__all__ = [
    "PresentationRules",
    "Variance",
    "PresentedLine",
    "PresentedSection",
    "PresentedProfitAndLoss",
    "PresentedBalanceSheet",
    "PresentedCashFlow",
    "CashFlowSection",
    "present_profit_and_loss",
    "present_balance_sheet",
    "present_cash_flow",
]
