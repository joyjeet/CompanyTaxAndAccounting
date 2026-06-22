"""Unit tests for `app.domain.tax_automap`: heuristic COA -> tax-line mapper.

No DB required — we feed in plain `SimpleNamespace`s that quack like
ChartOfAccounts / TaxFormLine for the duration of the function call.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.tax_automap import auto_propose_mappings
from app.models.enums import AccountType, TaxFormCode, TaxLineSign


def _acct(code: str, name: str, atype: AccountType) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), code=code, name=name, account_type=atype)


def _line(code: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), code=code)


def _lines_for_f1120() -> list[SimpleNamespace]:
    # Every line referenced by the F1120 heuristic.
    return [
        _line(c) for c in [
            "1a", "1b", "2", "4", "5", "6", "7", "8", "9", "10",
            "12", "13", "14", "15", "16", "17", "18", "19", "20",
            "21", "22", "23", "24", "26",
        ]
    ]


def _lines_for_f1040sc() -> list[SimpleNamespace]:
    return [
        _line(c) for c in [
            "1", "2", "4", "6", "8", "9", "10", "11", "12", "13",
            "14", "15", "16a", "16b", "17", "18", "19", "20a", "20b",
            "21", "22", "23", "24a", "24b", "25", "26", "27a",
        ]
    ]


# --------------------------------------------------------------------------- #
# Skipping rules
# --------------------------------------------------------------------------- #
def test_balance_sheet_accounts_are_skipped() -> None:
    accounts = [
        _acct("1000", "Cash", AccountType.ASSET),
        _acct("1100", "Accounts Receivable", AccountType.ASSET),
        _acct("2000", "Accounts Payable", AccountType.LIABILITY),
        _acct("3000", "Owner's Equity", AccountType.EQUITY),
    ]
    r = auto_propose_mappings(
        form_code=TaxFormCode.F1120, accounts=accounts, lines=_lines_for_f1120(),
    )
    assert r.proposals == ()
    assert {s[0] for s in r.skipped} == {"1000", "1100", "2000", "3000"}
    for _, _, reason in r.skipped:
        assert "balance-sheet" in reason


def test_suspense_account_is_skipped_even_if_asset() -> None:
    accounts = [_acct("9999", "Suspense", AccountType.ASSET)]
    r = auto_propose_mappings(
        form_code=TaxFormCode.F1120, accounts=accounts, lines=_lines_for_f1120(),
    )
    assert r.proposals == ()
    assert len(r.skipped) == 1
    assert r.skipped[0][0] == "9999"
    assert "suspense" in r.skipped[0][2].lower()


# --------------------------------------------------------------------------- #
# F1120 — keyword + fallback paths
# --------------------------------------------------------------------------- #
def test_revenue_falls_back_to_line_1a_on_f1120() -> None:
    accounts = [_acct("4000", "Sales Revenue", AccountType.REVENUE)]
    r = auto_propose_mappings(
        form_code=TaxFormCode.F1120, accounts=accounts, lines=_lines_for_f1120(),
    )
    assert len(r.proposals) == 1
    p = r.proposals[0]
    assert p.sign is TaxLineSign.POSITIVE
    # Resolve line code by id back through the lines list.
    line_map = {ln.id: ln.code for ln in _lines_for_f1120()}
    # The line in the proposal came from a DIFFERENT _line() instance than
    # the lookup map above, so resolve via the actual line list we passed in.
    # Easier: re-run with a single explicit line.


def test_revenue_falls_back_to_1a() -> None:
    lines = _lines_for_f1120()
    accounts = [_acct("4000", "Sales Revenue", AccountType.REVENUE)]
    r = auto_propose_mappings(
        form_code=TaxFormCode.F1120, accounts=accounts, lines=lines,
    )
    assert len(r.proposals) == 1
    proposed_line_id = r.proposals[0].line_id
    line_code = next(ln.code for ln in lines if ln.id == proposed_line_id)
    assert line_code == "1a"


def test_expense_5xxx_falls_back_to_cogs_line_2() -> None:
    lines = _lines_for_f1120()
    accounts = [_acct("5050", "Cost of Goods Sold", AccountType.EXPENSE)]
    r = auto_propose_mappings(
        form_code=TaxFormCode.F1120, accounts=accounts, lines=lines,
    )
    assert len(r.proposals) == 1
    line_code = next(ln.code for ln in lines if ln.id == r.proposals[0].line_id)
    assert line_code == "2"


def test_expense_5100plus_falls_back_to_other_deductions() -> None:
    """5100+ is not COGS by convention — it's general expense."""
    lines = _lines_for_f1120()
    accounts = [_acct("5500", "Random Expense", AccountType.EXPENSE)]
    r = auto_propose_mappings(
        form_code=TaxFormCode.F1120, accounts=accounts, lines=lines,
    )
    assert len(r.proposals) == 1
    line_code = next(ln.code for ln in lines if ln.id == r.proposals[0].line_id)
    assert line_code == "26"


def test_expense_6xxx_falls_back_to_other_deductions_26() -> None:
    lines = _lines_for_f1120()
    accounts = [_acct("6900", "Miscellaneous", AccountType.EXPENSE)]
    r = auto_propose_mappings(
        form_code=TaxFormCode.F1120, accounts=accounts, lines=lines,
    )
    assert len(r.proposals) == 1
    line_code = next(ln.code for ln in lines if ln.id == r.proposals[0].line_id)
    assert line_code == "26"


@pytest.mark.parametrize("acct_name,expected_line", [
    ("Rent Expense", "16"),
    ("Office Rent", "16"),
    ("Building Lease", "16"),
    ("Advertising & Marketing", "22"),
    ("Salaries & Wages", "13"),
    ("Payroll Expense", "13"),
    ("Depreciation Expense", "20"),
    ("Repairs and Maintenance", "14"),
    ("Charitable Donations", "19"),
    ("Officer Compensation", "12"),
    ("State Income Taxes", "17"),
    ("Bank Loan Interest Expense", "18"),
    ("Health Insurance", "24"),
    ("401k Match", "23"),
    ("Bad Debt Expense", "15"),
])
def test_f1120_keyword_rules(acct_name: str, expected_line: str) -> None:
    lines = _lines_for_f1120()
    accounts = [_acct("6100", acct_name, AccountType.EXPENSE)]
    r = auto_propose_mappings(
        form_code=TaxFormCode.F1120, accounts=accounts, lines=lines,
    )
    assert len(r.proposals) == 1, f"no proposal for {acct_name!r}"
    line_code = next(ln.code for ln in lines if ln.id == r.proposals[0].line_id)
    assert line_code == expected_line, (
        f"{acct_name!r} mapped to line {line_code}, expected {expected_line}"
    )


def test_returns_and_allowances_get_negative_sign_on_1b() -> None:
    lines = _lines_for_f1120()
    accounts = [_acct("4100", "Sales Returns", AccountType.REVENUE)]
    r = auto_propose_mappings(
        form_code=TaxFormCode.F1120, accounts=accounts, lines=lines,
    )
    assert len(r.proposals) == 1
    p = r.proposals[0]
    assert p.sign is TaxLineSign.NEGATIVE
    line_code = next(ln.code for ln in lines if ln.id == p.line_id)
    assert line_code == "1b"


# --------------------------------------------------------------------------- #
# F1040 Schedule C — keyword rules
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("acct_name,expected_line", [
    ("Advertising", "8"),
    ("Vehicle Expense", "9"),
    ("Legal Services", "17"),
    ("Office Expense", "18"),
    ("Travel", "24a"),
    ("Meals", "24b"),
    ("Utilities", "25"),
    ("Mortgage Interest", "16a"),
    ("Office Supplies", "22"),
])
def test_f1040sc_keyword_rules(acct_name: str, expected_line: str) -> None:
    lines = _lines_for_f1040sc()
    accounts = [_acct("6100", acct_name, AccountType.EXPENSE)]
    r = auto_propose_mappings(
        form_code=TaxFormCode.F1040SC, accounts=accounts, lines=lines,
    )
    assert len(r.proposals) == 1, f"no proposal for {acct_name!r}"
    line_code = next(ln.code for ln in lines if ln.id == r.proposals[0].line_id)
    assert line_code == expected_line


# --------------------------------------------------------------------------- #
# Catalog mismatch
# --------------------------------------------------------------------------- #
def test_account_for_missing_line_in_catalog_is_skipped_gracefully() -> None:
    # If the catalog is missing some line the heuristic wants, the account
    # is reported as skipped with a clear reason — NOT raised.
    lines = [_line("1a")]  # only revenue line exists
    accounts = [_acct("6200", "Rent Expense", AccountType.EXPENSE)]
    r = auto_propose_mappings(
        form_code=TaxFormCode.F1120, accounts=accounts, lines=lines,
    )
    assert r.proposals == ()
    assert len(r.skipped) == 1
    assert "line 16 not in catalog" in r.skipped[0][2]


def test_unknown_form_code_raises_value_error() -> None:
    class _Fake:
        value = "F-FAKE"

    with pytest.raises(ValueError, match="No auto-map rules"):
        auto_propose_mappings(
            form_code=_Fake(),  # type: ignore[arg-type]
            accounts=[],
            lines=[],
        )
