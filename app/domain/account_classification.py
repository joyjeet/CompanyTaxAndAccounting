"""Canonical mapping from an account code to its reporting sub-type.

This is the single place that knows the numeric conventions of the shipped
chart of accounts:

    1000-1499  current assets          4000-4499  operating revenue
    1500-1699  fixed assets            4500-4999  other (non-operating) income
    1700-1899  intangible assets       5000-5999  cost of goods sold
    1900-1999  other assets            6000-9099  operating expenses
    2000-2499  current liabilities     9100-9499  other (non-operating) expense
    2500-2999  long-term liabilities   9500-9899  income tax expense
    3000-3999  equity                  9900-9999  suspense (operating expense)

Two callers:

* The COA templates stamp `sub_type` onto every node at import time, so the
  classification becomes explicit data on each account.
* The statement builder falls back to this when it meets a row whose
  `sub_type` is NULL (accounts created before migration 0012).

Once an account carries a `sub_type`, renumbering it can no longer move it
on the P&L or balance sheet — which is the whole point. Ranges are a
convenience for authoring, never the source of truth at read time.
"""
from __future__ import annotations

from app.models.enums import (
    DEFAULT_SUBTYPE_FOR,
    AccountSubType,
    AccountType,
)

# (inclusive_low, inclusive_high, sub_type) per account type, first match wins.
_RANGES: dict[AccountType, tuple[tuple[int, int, AccountSubType], ...]] = {
    AccountType.ASSET: (
        (1500, 1699, AccountSubType.FIXED_ASSET),
        (1700, 1899, AccountSubType.INTANGIBLE_ASSET),
        (1900, 1999, AccountSubType.OTHER_ASSET),
    ),
    AccountType.LIABILITY: (
        (2500, 2999, AccountSubType.LONG_TERM_LIABILITY),
    ),
    AccountType.REVENUE: (
        (4500, 4999, AccountSubType.OTHER_INCOME),
    ),
    AccountType.EXPENSE: (
        (5000, 5999, AccountSubType.COGS),
        (9100, 9499, AccountSubType.OTHER_EXPENSE),
        (9500, 9899, AccountSubType.INCOME_TAX),
    ),
}


def infer_sub_type(code: str, account_type: AccountType) -> AccountSubType:
    """Best-effort sub-type for ``code``.

    Non-numeric codes (a firm may use "CASH-01") fall straight through to
    the account-type default, which is always the operating/current bucket.
    """
    numeric: int | None = None
    if code.isdigit():
        numeric = int(code)
    if numeric is not None:
        for low, high, sub_type in _RANGES.get(account_type, ()):
            if low <= numeric <= high:
                return sub_type
    return DEFAULT_SUBTYPE_FOR[account_type]


def coerce_sub_type(
    value: AccountSubType | str | None,
    *,
    code: str,
    account_type: AccountType,
) -> AccountSubType:
    """Normalise a caller-supplied sub-type, inferring when absent.

    Unknown strings are treated as absent rather than raising: the caller
    (API layer) validates user input, and internal callers should not blow
    up on a legacy value that has since been renamed.
    """
    if isinstance(value, AccountSubType):
        return value
    if isinstance(value, str):
        try:
            return AccountSubType(value)
        except ValueError:
            pass
    return infer_sub_type(code, account_type)


__all__ = ["coerce_sub_type", "infer_sub_type"]
