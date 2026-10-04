"""Tests for the bank-statement parser."""
from __future__ import annotations

from app.integrations.bank_statement import (
    looks_like_bank_statement,
    parse_statement,
)

# Synthetic TD-style statement covering the headers and line shapes the
# parser cares about. Includes deposits, electronic deposits, electronic
# payments (single-line + multi-line continuation), plus a daily-balance
# noise section that must be ignored.
_STMT = """
ABC LLC
STATEMENT OF ACCOUNT
Statement Period: Jul 01 2025-Jul 31 2025

Account Summary
Beginning Balance         1,000.00
Ending Balance            1,250.00

Deposits
07/05 Cash deposit        500.00

Electronic Deposits
07/10 ACH SQUARE INC      200.00

Electronic Payments
07/15 DROPBOX subscription  10.00
07/20 DEBIT POS AP, AUT 071925
DDA PURCHASE AP STAPLES 123
HICKSVILLE * NY                40.00

Daily Balance Summary
07/05 1,500.00
07/31 1,250.00
"""


def test_looks_like_bank_statement_positive_and_negative() -> None:
    assert looks_like_bank_statement(_STMT) is True
    assert looks_like_bank_statement("Invoice #1234 from Acme") is False
    assert looks_like_bank_statement(None) is False
    assert looks_like_bank_statement("") is False


def test_parse_extracts_header_balances_and_period() -> None:
    r = parse_statement(_STMT)
    assert r["is_statement"] is True
    assert r["statement_period"] == "Jul 01 2025 - Jul 31 2025"
    assert r["beginning_balance"] == "1000.00"
    assert r["ending_balance"] == "1250.00"


def test_parse_finds_all_transactions_with_correct_directions() -> None:
    r = parse_statement(_STMT)
    txns = r["transactions"]
    assert len(txns) == 4
    # Order is preserved
    assert txns[0]["amount"] == "500.00"
    assert txns[0]["direction"] == "deposit"
    assert txns[0]["section"] == "deposits"
    assert txns[1]["amount"] == "200.00"
    assert txns[1]["direction"] == "deposit"
    assert "SQUARE" in txns[1]["description"]
    assert txns[2]["amount"] == "10.00"
    assert txns[2]["direction"] == "payment"
    assert "DROPBOX" in txns[2]["description"]
    # Multi-line continuation: amount sits two lines below the date.
    assert txns[3]["amount"] == "40.00"
    assert txns[3]["direction"] == "payment"
    assert "STAPLES" in txns[3]["description"]


def test_proposed_account_codes_use_vendor_heuristics() -> None:
    r = parse_statement(_STMT)
    by_desc = {t["description"]: t["proposed_account_code"] for t in r["transactions"]}
    # SQUARE -> Sales Revenue
    assert any(code == "4000" for desc, code in by_desc.items() if "SQUARE" in desc)
    # DROPBOX -> Office Expense
    assert any(code == "5000" for desc, code in by_desc.items() if "DROPBOX" in desc)
    # STAPLES -> Office Expense
    assert any(code == "5000" for desc, code in by_desc.items() if "STAPLES" in desc)


def test_iso_date_inferred_from_period_year() -> None:
    r = parse_statement(_STMT)
    # Year 2025 from the Statement Period header.
    for t in r["transactions"]:
        assert t["date"].startswith("2025-")
        assert t["raw_date"].startswith("07/")


def test_parse_resolves_cross_year_period_continuously() -> None:
    stmt = """
    STATEMENT OF ACCOUNT
    Statement Period: Dec 20 2025-Jan 10 2026
    Beginning Balance 1,000.00
    Ending Balance 900.00

    Electronic Payments
    12/29 BILL PAYMENT 50.00
    01/03 CARD PURCHASE 50.00
    """
    r = parse_statement(stmt)
    txns = r["transactions"]
    assert len(txns) == 2
    assert txns[0]["date"] == "2025-12-29"
    assert txns[1]["date"] == "2026-01-03"


def test_parse_uses_sequence_continuity_when_year_missing() -> None:
    stmt = """
    STATEMENT OF ACCOUNT
    Beginning Balance 1,000.00
    Ending Balance 900.00

    Electronic Payments
    12/31/2025 YEAR END PAYMENT 10.00
    01/01 NEW YEAR PAYMENT 15.00
    """
    r = parse_statement(stmt)
    txns = r["transactions"]
    assert len(txns) == 2
    assert txns[0]["date"] == "2025-12-31"
    assert txns[1]["date"] == "2026-01-01"


def test_parse_returns_empty_for_non_statement_text() -> None:
    r = parse_statement("Invoice #1234. Total: $500.00")
    assert r == {"is_statement": False}


def test_daily_balance_section_is_skipped() -> None:
    r = parse_statement(_STMT)
    # 07/31 with amount 1,250.00 would have been a false positive if the
    # parser walked the daily-balance section.
    for t in r["transactions"]:
        assert t["raw_date"] != "07/31"


def test_loan_description_maps_to_loan_payable_code() -> None:
    stmt = """
    STATEMENT OF ACCOUNT
    Statement Period: Jul 01 2025-Jul 31 2025
    Beginning Balance 1,000.00
    Ending Balance 900.00

    Electronic Payments
    07/22 LOAN PAYMENT TO SBA 100.00
    """
    r = parse_statement(stmt)
    assert r["is_statement"] is True
    assert len(r["transactions"]) == 1
    assert r["transactions"][0]["proposed_account_code"] == "2400"
