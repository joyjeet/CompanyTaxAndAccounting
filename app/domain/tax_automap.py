"""Heuristic auto-mapper: chart-of-accounts row -> tax_form_line.

PURPOSE
-------
A reviewer should not have to hand-pick a tax line for every COA row before
the first worksheet can be generated. This module produces a deterministic
"proposed" mapping per account using:

  1) Account-name keyword rules (highest precedence, form-specific).
  2) Account-code numeric range fallback (4xxx -> revenue line, 5xxx -> COGS,
     6xxx-9xxx -> a deduction line).
  3) "Other income" / "Other deductions" catch-all if no rule fires.

The output is a list of `MappingProposal`s plus a "skipped" list for accounts
that the heuristic deliberately ignores (Cash, AR, AP, Equity, Suspense — no
P&L impact). Skipped accounts are not written to the DB.

This is intentionally a small, readable lookup table — not a model — so the
mappings are reproducible, debuggable, and easy for a reviewer to override.
The reviewer still has to APPROVE each proposed row before it counts toward
a worksheet.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.domain.tax_service import MappingProposal
from app.models.accounting import ChartOfAccounts, TaxFormLine
from app.models.enums import AccountType, TaxFormCode, TaxLineSign


# --------------------------------------------------------------------------- #
# Rule shape
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _Rule:
    """Keyword -> tax line code rule.

    The keyword is matched case-insensitively against the account name with a
    word-boundary regex (so 'rent' does not match 'parental'). Short keywords
    ALSO require word boundaries.
    """

    keyword: str
    line_code: str
    sign: TaxLineSign = TaxLineSign.POSITIVE


# --------------------------------------------------------------------------- #
# Per-form keyword rules (account name -> line code)
# --------------------------------------------------------------------------- #
# Form 1120 (C-Corp) keyword rules.
_F1120_RULES: tuple[_Rule, ...] = (
    # Income
    _Rule("dividend", "4"),
    _Rule("interest income", "5"),
    _Rule("rent income", "6"),
    _Rule("rental income", "6"),
    _Rule("royalty", "7"),
    _Rule("royalties", "7"),
    _Rule("capital gain", "8"),
    _Rule("sales return", "1b", TaxLineSign.NEGATIVE),
    _Rule("sales returns", "1b", TaxLineSign.NEGATIVE),
    _Rule("returns and allowance", "1b", TaxLineSign.NEGATIVE),
    _Rule("returns and allowances", "1b", TaxLineSign.NEGATIVE),
    _Rule("sales discount", "1b", TaxLineSign.NEGATIVE),
    _Rule("sales discounts", "1b", TaxLineSign.NEGATIVE),
    # Deductions
    _Rule("officer", "12"),
    _Rule("salaries", "13"),
    _Rule("salary", "13"),
    _Rule("wages", "13"),
    _Rule("payroll", "13"),
    _Rule("repair", "14"),
    _Rule("maintenance", "14"),
    _Rule("bad debt", "15"),
    _Rule("rent expense", "16"),
    _Rule("rent", "16"),
    _Rule("lease", "16"),
    _Rule("tax expense", "17"),
    _Rule("taxes", "17"),
    _Rule("license", "17"),
    _Rule("interest expense", "18"),
    _Rule("loan interest", "18"),
    _Rule("charitable", "19"),
    _Rule("donation", "19"),
    _Rule("depreciation", "20"),
    _Rule("amortization", "20"),
    _Rule("depletion", "21"),
    _Rule("advertising", "22"),
    _Rule("marketing", "22"),
    _Rule("pension", "23"),
    _Rule("retirement", "23"),
    _Rule("401k", "23"),
    _Rule("benefit", "24"),
    _Rule("insurance", "24"),
    _Rule("health", "24"),
)

# Form 1120-S (S-Corp). Same shape as 1120 but renumbered.
_F1120S_RULES: tuple[_Rule, ...] = (
    _Rule("net gain", "4"),
    _Rule("officer", "7"),
    _Rule("salaries", "8"),
    _Rule("salary", "8"),
    _Rule("wages", "8"),
    _Rule("payroll", "8"),
    _Rule("repair", "9"),
    _Rule("maintenance", "9"),
    _Rule("bad debt", "10"),
    _Rule("rent expense", "11"),
    _Rule("rent", "11"),
    _Rule("lease", "11"),
    _Rule("tax expense", "12"),
    _Rule("taxes", "12"),
    _Rule("license", "12"),
    _Rule("interest expense", "13"),
    _Rule("depreciation", "14"),
    _Rule("depletion", "15"),
    _Rule("advertising", "16"),
    _Rule("marketing", "16"),
    _Rule("pension", "17"),
    _Rule("retirement", "17"),
    _Rule("benefit", "18"),
    _Rule("insurance", "18"),
)

# Form 1065 (Partnership).
_F1065_RULES: tuple[_Rule, ...] = (
    _Rule("salaries", "9"),
    _Rule("salary", "9"),
    _Rule("wages", "9"),
    _Rule("payroll", "9"),
    _Rule("guaranteed payment", "10"),
    _Rule("repair", "11"),
    _Rule("maintenance", "11"),
    _Rule("bad debt", "12"),
    _Rule("rent expense", "13"),
    _Rule("rent", "13"),
    _Rule("lease", "13"),
    _Rule("tax expense", "14"),
    _Rule("taxes", "14"),
    _Rule("license", "14"),
    _Rule("interest expense", "15"),
    _Rule("depreciation", "16"),
    _Rule("depletion", "17"),
    _Rule("retirement", "18"),
    _Rule("pension", "18"),
    _Rule("benefit", "19"),
    _Rule("insurance", "19"),
)

# Form 1040 Schedule C (Sole Prop).
_F1040SC_RULES: tuple[_Rule, ...] = (
    _Rule("advertising", "8"),
    _Rule("marketing", "8"),
    _Rule("car", "9"),
    _Rule("truck", "9"),
    _Rule("vehicle", "9"),
    _Rule("fuel", "9"),
    _Rule("commission", "10"),
    _Rule("contract labor", "11"),
    _Rule("contractor", "11"),
    _Rule("freelance", "11"),
    _Rule("depletion", "12"),
    _Rule("depreciation", "13"),
    _Rule("amortization", "13"),
    _Rule("benefit", "14"),
    _Rule("health", "14"),
    _Rule("insurance", "15"),
    _Rule("mortgage", "16a"),
    _Rule("loan interest", "16b"),
    _Rule("interest expense", "16b"),
    _Rule("legal", "17"),
    _Rule("professional", "17"),
    _Rule("accounting", "17"),
    _Rule("supplies", "22"),
    _Rule("office", "18"),
    _Rule("pension", "19"),
    _Rule("retirement", "19"),
    _Rule("rent", "20b"),
    _Rule("lease", "20b"),
    _Rule("repair", "21"),
    _Rule("maintenance", "21"),
    _Rule("tax expense", "23"),
    _Rule("taxes", "23"),
    _Rule("license", "23"),
    _Rule("travel", "24a"),
    _Rule("meals", "24b"),
    _Rule("utilities", "25"),
    _Rule("electric", "25"),
    _Rule("water", "25"),
    _Rule("gas bill", "25"),
    _Rule("wages", "26"),
    _Rule("salaries", "26"),
    _Rule("salary", "26"),
    _Rule("payroll", "26"),
)


# --------------------------------------------------------------------------- #
# Per-form fallback codes (when no keyword matches)
# --------------------------------------------------------------------------- #
# (revenue_default, cogs_default, deduction_default, other_income_fallback)
_FALLBACKS: dict[TaxFormCode, dict[str, str]] = {
    TaxFormCode.F1120:   {"revenue": "1a", "cogs": "2",  "deduction": "26", "other_income": "10"},
    TaxFormCode.F1120S:  {"revenue": "1a", "cogs": "2",  "deduction": "19", "other_income": "5"},
    TaxFormCode.F1065:   {"revenue": "1a", "cogs": "2",  "deduction": "20", "other_income": "7"},
    TaxFormCode.F1040SC: {"revenue": "1",  "cogs": "4",  "deduction": "27a", "other_income": "6"},
}

_RULES_BY_FORM: dict[TaxFormCode, tuple[_Rule, ...]] = {
    TaxFormCode.F1120:   _F1120_RULES,
    TaxFormCode.F1120S:  _F1120S_RULES,
    TaxFormCode.F1065:   _F1065_RULES,
    TaxFormCode.F1040SC: _F1040SC_RULES,
}


# --------------------------------------------------------------------------- #
# Public proposal API
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AutoMapResult:
    proposals: tuple[MappingProposal, ...]
    skipped: tuple[tuple[str, str, str], ...]  # (code, name, reason)


# Account types that NEVER appear on the income-statement portion of a tax
# return; we deliberately skip them.
_NON_PNL_TYPES: frozenset[AccountType] = frozenset(
    {AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY}
)

# Account codes that are control / suspense rows; always skip even if the
# type happens to be P&L.
_SKIP_CODES: frozenset[str] = frozenset({"9999"})


def _line_for_account(
    account: ChartOfAccounts,
    rules: Sequence[_Rule],
    fallback: dict[str, str],
) -> tuple[str, TaxLineSign]:
    """Return (line_code, sign) for one account."""
    name_lc = (account.name or "").lower()
    for rule in rules:
        kw = rule.keyword.lower()
        # Word-boundary match so 'rent' doesn't hit 'parental'.
        if re.search(rf"\b{re.escape(kw)}\b", name_lc):
            return rule.line_code, rule.sign

    # No keyword match -> use type + code-range fallback.
    if account.account_type is AccountType.REVENUE:
        return fallback["revenue"], TaxLineSign.POSITIVE
    if account.account_type is AccountType.EXPENSE:
        # By convention 5000-5099 is COGS in the seeded COA. Higher 5xxx and
        # all 6xxx-9xxx fall through to "other deductions".
        code = account.code or ""
        if code.startswith("50") and len(code) >= 4 and code[2:].isdigit():
            return fallback["cogs"], TaxLineSign.POSITIVE
        return fallback["deduction"], TaxLineSign.POSITIVE

    # Should not get here because non-P&L types are filtered above.
    return fallback["deduction"], TaxLineSign.POSITIVE


def auto_propose_mappings(
    *,
    form_code: TaxFormCode,
    accounts: Iterable[ChartOfAccounts],
    lines: Iterable[TaxFormLine],
) -> AutoMapResult:
    """Compute proposed mappings for `accounts` against `lines` on `form_code`.

    Returns:
        AutoMapResult.proposals  — one MappingProposal per P&L account.
        AutoMapResult.skipped    — (code, name, reason) for non-P&L / suspense.

    The caller is responsible for calling `propose_mapping(...)` on each
    proposal inside a transaction and skipping duplicates (an existing DRAFT
    or APPROVED row for the same triplet is left untouched).
    """
    rules = _RULES_BY_FORM.get(form_code)
    fallback = _FALLBACKS.get(form_code)
    if rules is None or fallback is None:
        raise ValueError(f"No auto-map rules for form {form_code.value}")

    # Index lines by code for O(1) lookup.
    line_by_code: dict[str, TaxFormLine] = {ln.code: ln for ln in lines}

    proposals: list[MappingProposal] = []
    skipped: list[tuple[str, str, str]] = []

    for acct in accounts:
        if (acct.code or "") in _SKIP_CODES:
            skipped.append((acct.code or "", acct.name or "", "suspense / control account"))
            continue
        if acct.account_type in _NON_PNL_TYPES:
            skipped.append((acct.code or "", acct.name or "", "balance-sheet account"))
            continue

        line_code, sign = _line_for_account(acct, rules, fallback)
        line = line_by_code.get(line_code)
        if line is None:
            skipped.append(
                (acct.code or "", acct.name or "", f"line {line_code} not in catalog")
            )
            continue

        proposals.append(
            MappingProposal(
                account_id=acct.id,
                line_id=line.id,
                sign=sign,
                notes=f"auto-proposed by heuristic ({form_code.value} → line {line_code})",
            )
        )

    return AutoMapResult(proposals=tuple(proposals), skipped=tuple(skipped))


__all__ = ["AutoMapResult", "auto_propose_mappings"]
