"""Tests for the financial statement generators.

Build a small known set of journal entries, then assert each statement is
exactly what we expect. The Balance Sheet must satisfy A = L + E.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.session import tenant_session
from app.domain.ledger import LedgerService, LineInput
from app.domain.statements import StatementsService
from tests.conftest import SeededWorld, ctx_firm_for_client

D = Decimal


def _post(sess, sc, lines, when=date(2026, 3, 15), memo=None):
    LedgerService(sess, firm_id=sc.firm_id, client_id=sc.client_id, actor="t").post(
        period_id=sc.period_id, entry_date=when, lines=lines, memo=memo,
    )


def test_pl_and_balance_sheet_from_known_entries(world: SeededWorld) -> None:
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)

    with tenant_session(ctx) as sess:
        # Owner contributes 5,000 cash as opening capital.
        _post(
            sess, a1,
            [
                LineInput(account_id=a1.cash_account_id, debit=D("5000")),
                LineInput(account_id=a1.equity_account_id, credit=D("5000")),
            ],
            when=date(2026, 1, 5),
            memo="opening capital",
        )
        # Service revenue on credit: 1,200 to A/R, 1,200 to Revenue.
        _post(
            sess, a1,
            [
                LineInput(account_id=a1.ar_account_id, debit=D("1200")),
                LineInput(account_id=a1.revenue_account_id, credit=D("1200")),
            ],
            when=date(2026, 2, 10),
            memo="invoice #1",
        )
        # Customer pays 800 of it.
        _post(
            sess, a1,
            [
                LineInput(account_id=a1.cash_account_id, debit=D("800")),
                LineInput(account_id=a1.ar_account_id, credit=D("800")),
            ],
            when=date(2026, 2, 25),
            memo="receipt against invoice #1",
        )
        # Office expense paid in cash: 300.
        _post(
            sess, a1,
            [
                LineInput(account_id=a1.expense_account_id, debit=D("300")),
                LineInput(account_id=a1.cash_account_id, credit=D("300")),
            ],
            when=date(2026, 3, 1),
            memo="office supplies",
        )
        # Bill incurred on credit: 200 to expense, 200 to A/P.
        _post(
            sess, a1,
            [
                LineInput(account_id=a1.expense_account_id, debit=D("200")),
                LineInput(account_id=a1.ap_account_id, credit=D("200")),
            ],
            when=date(2026, 3, 10),
            memo="bill",
        )

    # Now compute statements.
    with tenant_session(ctx) as sess:
        stmts = StatementsService(sess, firm_id=a1.firm_id, client_id=a1.client_id)

        pl = stmts.profit_and_loss(
            period_start=date(2026, 1, 1), period_end=date(2026, 3, 31)
        )
        assert pl.total_revenue == D("1200")
        assert pl.total_expenses == D("500")
        assert pl.net_income == D("700")

        bs = stmts.balance_sheet(as_of=date(2026, 3, 31))
        # Cash: 5000 + 800 - 300 = 5500
        # A/R:  1200 - 800        = 400
        # A/P:                      200
        # Equity contributed:       5000
        # Retained earnings:        700
        assert bs.total_assets == D("5900")  # 5500 + 400
        assert bs.total_liabilities == D("200")
        assert bs.total_equity == D("5700")  # 5000 + 700
        assert bs.retained_earnings_to_date == D("700")
        assert bs.balances is True
        assert bs.total_assets == bs.total_liabilities + bs.total_equity


def test_cash_flow_matches_change_in_cash(world: SeededWorld) -> None:
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)

    with tenant_session(ctx) as sess:
        _post(
            sess, a1,
            [
                LineInput(account_id=a1.cash_account_id, debit=D("1000")),
                LineInput(account_id=a1.equity_account_id, credit=D("1000")),
            ],
            when=date(2026, 1, 1),
        )
        _post(
            sess, a1,
            [
                LineInput(account_id=a1.cash_account_id, debit=D("400")),
                LineInput(account_id=a1.revenue_account_id, credit=D("400")),
            ],
            when=date(2026, 2, 1),
        )
        _post(
            sess, a1,
            [
                LineInput(account_id=a1.expense_account_id, debit=D("250")),
                LineInput(account_id=a1.cash_account_id, credit=D("250")),
            ],
            when=date(2026, 2, 15),
        )

    with tenant_session(ctx) as sess:
        stmts = StatementsService(sess, firm_id=a1.firm_id, client_id=a1.client_id)
        cf = stmts.cash_flow(
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
            cash_account_codes=["1000"],
        )
        assert cf.opening_cash == D("1000")
        assert cf.closing_cash == D("1150")
        assert cf.inflows == D("400")
        assert cf.outflows == D("250")
        assert cf.net_change == D("150")
        assert cf.closing_cash - cf.opening_cash == cf.net_change
