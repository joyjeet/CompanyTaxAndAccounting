"""Static tax-form catalog.

The shape (form_code, line_code, section, label, sequence) is fixed code that
ships with the application; the catalog is seeded into the database in the
0005 migration and ALSO available as a Python constant for offline use.

DESIGN NOTES (flagged assumptions to confirm with the firm):

  * v1 covers the INCOME STATEMENT portion of each return: gross receipts,
    returns/allowances, COGS, other income, total income; and the major
    deduction lines through "Total deductions" -> "Taxable income before NOL".
    Balance-sheet schedules (Schedule L on 1120/1120-S, similar on 1065),
    M-1 / M-2 reconciliations, and partner/shareholder K-1 allocations are
    OUT OF SCOPE for v1. Adding them is mechanical: append rows here, bump
    the catalog version, run the migration.
  * Line codes follow the IRS line numbering on the most recent published
    revisions of each form as of the build date. They are stable strings,
    not display labels; consumers should render `label` instead.
  * Sign convention: every account is mapped with a `TaxLineSign`. For nearly
    every account the right answer is POSITIVE (revenue contributes to an
    income line; expense contributes to a deduction line; both yield a
    positive amount on the worksheet). NEGATIVE exists for contra accounts
    (sales returns, sales discounts) that live on a deduction line on the
    income side.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.models.enums import TaxFormCode, TaxFormSection

CATALOG_VERSION = "2026.1"


@dataclass(frozen=True, slots=True)
class TaxLineSpec:
    code: str           # e.g. "1a"
    label: str          # human-readable
    section: TaxFormSection
    sequence: int       # display order within section
    description: str | None = None


@dataclass(frozen=True, slots=True)
class TaxFormSpec:
    code: TaxFormCode
    label: str
    jurisdiction: str   # "US-federal"
    lines: Sequence[TaxLineSpec]


# --------------------------------------------------------------------------- #
# Form 1120 — US C-Corporation Income Tax Return (income-stmt portion)
# --------------------------------------------------------------------------- #
_F1120_LINES: tuple[TaxLineSpec, ...] = (
    # Income (Lines 1–11) -> Total income line 11
    TaxLineSpec("1a", "Gross receipts or sales", TaxFormSection.INCOME, 10),
    TaxLineSpec("1b", "Returns and allowances", TaxFormSection.INCOME, 20),
    TaxLineSpec("2",  "Cost of goods sold (from Form 1125-A)", TaxFormSection.COGS, 30),
    TaxLineSpec("4",  "Dividends and inclusions", TaxFormSection.INCOME, 40),
    TaxLineSpec("5",  "Interest income", TaxFormSection.INCOME, 50),
    TaxLineSpec("6",  "Gross rents", TaxFormSection.INCOME, 60),
    TaxLineSpec("7",  "Gross royalties", TaxFormSection.INCOME, 70),
    TaxLineSpec("8",  "Capital gain net income", TaxFormSection.INCOME, 80),
    TaxLineSpec("9",  "Net gain (loss) from Form 4797", TaxFormSection.INCOME, 90),
    TaxLineSpec("10", "Other income", TaxFormSection.INCOME, 100),
    # Deductions (Lines 12–26) -> Total deductions line 27 -> Taxable income line 28/30
    TaxLineSpec("12", "Compensation of officers", TaxFormSection.DEDUCTIONS, 200),
    TaxLineSpec("13", "Salaries and wages (less employment credits)", TaxFormSection.DEDUCTIONS, 210),
    TaxLineSpec("14", "Repairs and maintenance", TaxFormSection.DEDUCTIONS, 220),
    TaxLineSpec("15", "Bad debts", TaxFormSection.DEDUCTIONS, 230),
    TaxLineSpec("16", "Rents", TaxFormSection.DEDUCTIONS, 240),
    TaxLineSpec("17", "Taxes and licenses", TaxFormSection.DEDUCTIONS, 250),
    TaxLineSpec("18", "Interest expense", TaxFormSection.DEDUCTIONS, 260),
    TaxLineSpec("19", "Charitable contributions", TaxFormSection.DEDUCTIONS, 270),
    TaxLineSpec("20", "Depreciation (Form 4562)", TaxFormSection.DEDUCTIONS, 280),
    TaxLineSpec("21", "Depletion", TaxFormSection.DEDUCTIONS, 290),
    TaxLineSpec("22", "Advertising", TaxFormSection.DEDUCTIONS, 300),
    TaxLineSpec("23", "Pension, profit-sharing, etc., plans", TaxFormSection.DEDUCTIONS, 310),
    TaxLineSpec("24", "Employee benefit programs", TaxFormSection.DEDUCTIONS, 320),
    TaxLineSpec("26", "Other deductions", TaxFormSection.DEDUCTIONS, 330),
)


# --------------------------------------------------------------------------- #
# Form 1120-S — US S-Corporation Income Tax Return (income-stmt portion)
# --------------------------------------------------------------------------- #
_F1120S_LINES: tuple[TaxLineSpec, ...] = (
    TaxLineSpec("1a", "Gross receipts or sales", TaxFormSection.INCOME, 10),
    TaxLineSpec("1b", "Returns and allowances", TaxFormSection.INCOME, 20),
    TaxLineSpec("2",  "Cost of goods sold (from Form 1125-A)", TaxFormSection.COGS, 30),
    TaxLineSpec("4",  "Net gain (loss) from Form 4797", TaxFormSection.INCOME, 40),
    TaxLineSpec("5",  "Other income (loss)", TaxFormSection.INCOME, 50),
    TaxLineSpec("7",  "Compensation of officers", TaxFormSection.DEDUCTIONS, 200),
    TaxLineSpec("8",  "Salaries and wages (less employment credits)", TaxFormSection.DEDUCTIONS, 210),
    TaxLineSpec("9",  "Repairs and maintenance", TaxFormSection.DEDUCTIONS, 220),
    TaxLineSpec("10", "Bad debts", TaxFormSection.DEDUCTIONS, 230),
    TaxLineSpec("11", "Rents", TaxFormSection.DEDUCTIONS, 240),
    TaxLineSpec("12", "Taxes and licenses", TaxFormSection.DEDUCTIONS, 250),
    TaxLineSpec("13", "Interest expense", TaxFormSection.DEDUCTIONS, 260),
    TaxLineSpec("14", "Depreciation (Form 4562)", TaxFormSection.DEDUCTIONS, 270),
    TaxLineSpec("15", "Depletion", TaxFormSection.DEDUCTIONS, 280),
    TaxLineSpec("16", "Advertising", TaxFormSection.DEDUCTIONS, 290),
    TaxLineSpec("17", "Pension, profit-sharing, etc., plans", TaxFormSection.DEDUCTIONS, 300),
    TaxLineSpec("18", "Employee benefit programs", TaxFormSection.DEDUCTIONS, 310),
    TaxLineSpec("19", "Other deductions", TaxFormSection.DEDUCTIONS, 320),
)


# --------------------------------------------------------------------------- #
# Form 1065 — US Return of Partnership Income (income-stmt portion)
# --------------------------------------------------------------------------- #
_F1065_LINES: tuple[TaxLineSpec, ...] = (
    TaxLineSpec("1a", "Gross receipts or sales", TaxFormSection.INCOME, 10),
    TaxLineSpec("1b", "Returns and allowances", TaxFormSection.INCOME, 20),
    TaxLineSpec("2",  "Cost of goods sold (from Form 1125-A)", TaxFormSection.COGS, 30),
    TaxLineSpec("4",  "Ordinary income (loss) from other partnerships, estates, trusts", TaxFormSection.INCOME, 40),
    TaxLineSpec("5",  "Net farm profit (loss)", TaxFormSection.INCOME, 50),
    TaxLineSpec("6",  "Net gain (loss) from Form 4797", TaxFormSection.INCOME, 60),
    TaxLineSpec("7",  "Other income (loss)", TaxFormSection.INCOME, 70),
    TaxLineSpec("9",  "Salaries and wages (other than to partners)", TaxFormSection.DEDUCTIONS, 200),
    TaxLineSpec("10", "Guaranteed payments to partners", TaxFormSection.DEDUCTIONS, 210),
    TaxLineSpec("11", "Repairs and maintenance", TaxFormSection.DEDUCTIONS, 220),
    TaxLineSpec("12", "Bad debts", TaxFormSection.DEDUCTIONS, 230),
    TaxLineSpec("13", "Rent", TaxFormSection.DEDUCTIONS, 240),
    TaxLineSpec("14", "Taxes and licenses", TaxFormSection.DEDUCTIONS, 250),
    TaxLineSpec("15", "Interest expense", TaxFormSection.DEDUCTIONS, 260),
    TaxLineSpec("16", "Depreciation (Form 4562)", TaxFormSection.DEDUCTIONS, 270),
    TaxLineSpec("17", "Depletion", TaxFormSection.DEDUCTIONS, 280),
    TaxLineSpec("18", "Retirement plans, etc.", TaxFormSection.DEDUCTIONS, 290),
    TaxLineSpec("19", "Employee benefit programs", TaxFormSection.DEDUCTIONS, 300),
    TaxLineSpec("20", "Other deductions", TaxFormSection.DEDUCTIONS, 310),
)


# --------------------------------------------------------------------------- #
# Form 1040 Schedule C — Profit or Loss From Business (sole proprietor / SMLLC)
# --------------------------------------------------------------------------- #
_F1040SC_LINES: tuple[TaxLineSpec, ...] = (
    # Part I — Income
    TaxLineSpec("1",  "Gross receipts or sales", TaxFormSection.INCOME, 10),
    TaxLineSpec("2",  "Returns and allowances", TaxFormSection.INCOME, 20),
    TaxLineSpec("4",  "Cost of goods sold (from line 42)", TaxFormSection.COGS, 30),
    TaxLineSpec("6",  "Other income", TaxFormSection.INCOME, 40),
    # Part II — Expenses
    TaxLineSpec("8",  "Advertising", TaxFormSection.DEDUCTIONS, 200),
    TaxLineSpec("9",  "Car and truck expenses", TaxFormSection.DEDUCTIONS, 210),
    TaxLineSpec("10", "Commissions and fees", TaxFormSection.DEDUCTIONS, 220),
    TaxLineSpec("11", "Contract labor", TaxFormSection.DEDUCTIONS, 230),
    TaxLineSpec("12", "Depletion", TaxFormSection.DEDUCTIONS, 240),
    TaxLineSpec("13", "Depreciation and section 179", TaxFormSection.DEDUCTIONS, 250),
    TaxLineSpec("14", "Employee benefit programs", TaxFormSection.DEDUCTIONS, 260),
    TaxLineSpec("15", "Insurance (other than health)", TaxFormSection.DEDUCTIONS, 270),
    TaxLineSpec("16a", "Mortgage interest (paid to banks, etc.)", TaxFormSection.DEDUCTIONS, 280),
    TaxLineSpec("16b", "Other interest expense", TaxFormSection.DEDUCTIONS, 290),
    TaxLineSpec("17", "Legal and professional services", TaxFormSection.DEDUCTIONS, 300),
    TaxLineSpec("18", "Office expense", TaxFormSection.DEDUCTIONS, 310),
    TaxLineSpec("19", "Pension and profit-sharing plans", TaxFormSection.DEDUCTIONS, 320),
    TaxLineSpec("20a", "Rent or lease — vehicles, machinery, equipment", TaxFormSection.DEDUCTIONS, 330),
    TaxLineSpec("20b", "Rent or lease — other business property", TaxFormSection.DEDUCTIONS, 340),
    TaxLineSpec("21", "Repairs and maintenance", TaxFormSection.DEDUCTIONS, 350),
    TaxLineSpec("22", "Supplies", TaxFormSection.DEDUCTIONS, 360),
    TaxLineSpec("23", "Taxes and licenses", TaxFormSection.DEDUCTIONS, 370),
    TaxLineSpec("24a", "Travel", TaxFormSection.DEDUCTIONS, 380),
    TaxLineSpec("24b", "Deductible meals", TaxFormSection.DEDUCTIONS, 390),
    TaxLineSpec("25", "Utilities", TaxFormSection.DEDUCTIONS, 400),
    TaxLineSpec("26", "Wages (less employment credits)", TaxFormSection.DEDUCTIONS, 410),
    TaxLineSpec("27a", "Other expenses", TaxFormSection.DEDUCTIONS, 420),
)


CATALOG: tuple[TaxFormSpec, ...] = (
    TaxFormSpec(TaxFormCode.F1120, "Form 1120 — US C-Corporation",
                "US-federal", _F1120_LINES),
    TaxFormSpec(TaxFormCode.F1120S, "Form 1120-S — US S-Corporation",
                "US-federal", _F1120S_LINES),
    TaxFormSpec(TaxFormCode.F1065, "Form 1065 — US Partnership",
                "US-federal", _F1065_LINES),
    TaxFormSpec(TaxFormCode.F1040SC, "Form 1040 Schedule C — Sole Proprietor",
                "US-federal", _F1040SC_LINES),
)


def form_spec(code: TaxFormCode) -> TaxFormSpec:
    for f in CATALOG:
        if f.code is code:
            return f
    raise KeyError(f"Unknown tax form: {code}")


__all__ = [
    "CATALOG",
    "CATALOG_VERSION",
    "TaxFormSpec",
    "TaxLineSpec",
    "form_spec",
]
