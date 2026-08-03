"""Sub-type classification and the statement bucketing that depends on it.

The regression these lock down: the presentation layer used to bucket P&L
lines by comparing account-code strings against hard-coded ranges
(`other_expense_code_min = "6000"`). The shipped chart of accounts puts
every operating expense in 6xxx-9xxx, so all of them were pushed below the
operating-income line -- Operating Expenses rendered empty and Operating
Income always equalled Gross Profit.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from uuid import uuid4

import pytest

from app.domain.account_classification import coerce_sub_type, infer_sub_type
from app.domain.presentation import present_profit_and_loss
from app.domain.statements import AccountBalance, ProfitAndLoss
from app.models.enums import AccountSubType, AccountType

ZERO = D("0")


def _bal(code: str, account_type: AccountType, amount: D) -> AccountBalance:
    return AccountBalance(
        account_id=uuid4(),
        code=code,
        name=f"Account {code}",
        account_type=account_type,
        debit_total=ZERO,
        credit_total=ZERO,
        signed_balance=amount,
        sub_type=infer_sub_type(code, account_type),
    )


# --------------------------------------------------------------------------- #
# infer_sub_type
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("code", "account_type", "expected"),
    [
        ("1000", AccountType.ASSET, AccountSubType.CURRENT_ASSET),
        ("1499", AccountType.ASSET, AccountSubType.CURRENT_ASSET),
        ("1500", AccountType.ASSET, AccountSubType.FIXED_ASSET),
        ("1700", AccountType.ASSET, AccountSubType.INTANGIBLE_ASSET),
        ("1900", AccountType.ASSET, AccountSubType.OTHER_ASSET),
        ("2000", AccountType.LIABILITY, AccountSubType.CURRENT_LIABILITY),
        ("2500", AccountType.LIABILITY, AccountSubType.LONG_TERM_LIABILITY),
        ("3000", AccountType.EQUITY, AccountSubType.EQUITY),
        ("4000", AccountType.REVENUE, AccountSubType.OPERATING_REVENUE),
        ("4510", AccountType.REVENUE, AccountSubType.OTHER_INCOME),
        ("5000", AccountType.EXPENSE, AccountSubType.COGS),
        ("6100", AccountType.EXPENSE, AccountSubType.OPERATING_EXPENSE),
        ("8500", AccountType.EXPENSE, AccountSubType.OPERATING_EXPENSE),
        ("9100", AccountType.EXPENSE, AccountSubType.OTHER_EXPENSE),
        ("9500", AccountType.EXPENSE, AccountSubType.INCOME_TAX),
    ],
)
def test_infer_sub_type_follows_the_shipped_code_ranges(
    code: str, account_type: AccountType, expected: AccountSubType,
) -> None:
    assert infer_sub_type(code, account_type) is expected


def test_non_numeric_code_falls_back_to_the_type_default() -> None:
    """A CoA that does not follow the numbering convention must not raise."""
    assert infer_sub_type("CASH-A", AccountType.ASSET) is AccountSubType.CURRENT_ASSET
    assert infer_sub_type("", AccountType.EXPENSE) is AccountSubType.OPERATING_EXPENSE


def test_coerce_keeps_a_recorded_sub_type_and_infers_a_missing_one() -> None:
    # An explicitly recorded classification wins over the code range.
    assert (
        coerce_sub_type(
            "other_expense", code="6100", account_type=AccountType.EXPENSE
        )
        is AccountSubType.OTHER_EXPENSE
    )
    # Legacy rows (pre-migration 0012) carry NULL and fall back to the code.
    assert (
        coerce_sub_type(None, code="5010", account_type=AccountType.EXPENSE)
        is AccountSubType.COGS
    )


# --------------------------------------------------------------------------- #
# P&L bucketing
# --------------------------------------------------------------------------- #
def _sample_pl() -> ProfitAndLoss:
    revenue = [
        _bal("4000", AccountType.REVENUE, D("1000")),   # operating
        _bal("4510", AccountType.REVENUE, D("50")),     # interest -> other income
    ]
    expenses = [
        _bal("5010", AccountType.EXPENSE, D("400")),    # COGS
        _bal("6100", AccountType.EXPENSE, D("200")),    # payroll   -> operating
        _bal("7100", AccountType.EXPENSE, D("100")),    # rent      -> operating
        _bal("8500", AccountType.EXPENSE, D("60")),     # G&A       -> operating
        _bal("9100", AccountType.EXPENSE, D("30")),     # interest  -> other
        _bal("9500", AccountType.EXPENSE, D("20")),     # income tax-> other
    ]
    return ProfitAndLoss(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        revenue=revenue,
        expenses=expenses,
        total_revenue=D("1050"),
        total_expenses=D("810"),
        net_income=D("240"),
    )


def test_operating_expenses_are_not_pushed_below_the_operating_income_line() -> None:
    pres = present_profit_and_loss(_sample_pl())

    op_exp_codes = [ln.code for ln in pres.operating_expenses.lines]
    assert op_exp_codes == ["6100", "7100", "8500"]
    assert pres.operating_expenses.subtotal == D("360")

    assert [ln.code for ln in pres.cogs.lines] == ["5010"]
    assert [ln.code for ln in pres.other_expenses.lines] == ["9100", "9500"]


def test_other_income_is_split_out_of_operating_revenue() -> None:
    pres = present_profit_and_loss(_sample_pl())

    assert [ln.code for ln in pres.revenue.lines] == ["4000"]
    assert pres.revenue.subtotal == D("1000")
    assert [ln.code for ln in pres.other_income.lines] == ["4510"]


def test_operating_income_is_gross_profit_less_operating_expenses() -> None:
    pres = present_profit_and_loss(_sample_pl())

    assert pres.gross_profit == D("600")          # 1000 revenue - 400 COGS
    # The bug made this equal to gross_profit because opex was empty.
    assert pres.operating_income == D("240")      # 600 - 360 opex
    assert pres.operating_income != pres.gross_profit
    assert pres.net_income == D("240")            # 240 + 50 other inc - 50 other exp
