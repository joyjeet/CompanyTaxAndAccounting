"""Bank reconciliation tests."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.session import tenant_session
from app.domain.ledger import LedgerService, LineInput
from app.domain.reconciliation import reconcile_account
from app.models.enums import ReconciliationStatus
from tests.conftest import SeededWorld, ctx_firm_for_client

D = Decimal


def test_reconcile_match(world: SeededWorld) -> None:
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)
    with tenant_session(ctx) as sess:
        ledger = LedgerService(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff"
        )
        ledger.post(
            period_id=a1.period_id,
            entry_date=date(2026, 1, 5),
            lines=[
                LineInput(account_id=a1.cash_account_id, debit=D("3000")),
                LineInput(account_id=a1.equity_account_id, credit=D("3000")),
            ],
        )
        ledger.post(
            period_id=a1.period_id,
            entry_date=date(2026, 1, 20),
            lines=[
                LineInput(account_id=a1.expense_account_id, debit=D("125.50")),
                LineInput(account_id=a1.cash_account_id, credit=D("125.50")),
            ],
        )

    with tenant_session(ctx) as sess:
        result = reconcile_account(
            sess,
            firm_id=a1.firm_id, client_id=a1.client_id, actor="staff",
            account_id=a1.cash_account_id,
            as_of=date(2026, 1, 31),
            statement_balance=D("2874.50"),
        )
        assert result.ledger_balance == D("2874.50")
        assert result.difference == D("0.00")
        assert result.status is ReconciliationStatus.COMPLETE


def test_reconcile_discrepancy(world: SeededWorld) -> None:
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)
    with tenant_session(ctx) as sess:
        LedgerService(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff"
        ).post(
            period_id=a1.period_id,
            entry_date=date(2026, 1, 5),
            lines=[
                LineInput(account_id=a1.cash_account_id, debit=D("100")),
                LineInput(account_id=a1.equity_account_id, credit=D("100")),
            ],
        )

    with tenant_session(ctx) as sess:
        result = reconcile_account(
            sess,
            firm_id=a1.firm_id, client_id=a1.client_id, actor="staff",
            account_id=a1.cash_account_id,
            as_of=date(2026, 1, 31),
            statement_balance=D("90"),
        )
        assert result.difference == D("-10")
        assert result.status is ReconciliationStatus.DISCREPANCY
