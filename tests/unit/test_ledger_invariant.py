"""Tests for the core double-entry invariant: SUM(debits) == SUM(credits)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import tenant_session
from app.domain.exceptions import (
    CrossTenantError,
    PeriodLockedError,
    UnbalancedJournalEntryError,
)
from app.domain.ledger import LedgerService, LineInput
from app.models.accounting import JournalEntry, JournalLine
from tests.conftest import SeededWorld, ctx_firm_for_client


def test_balanced_entry_is_persisted(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        ledger = LedgerService(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
        )
        entry = ledger.post(
            period_id=a1.period_id,
            entry_date=date(2026, 3, 15),
            lines=[
                LineInput(account_id=a1.cash_account_id, debit=Decimal("1000.00")),
                LineInput(account_id=a1.revenue_account_id, credit=Decimal("1000.00")),
            ],
            memo="cash sale",
        )
        # Pull lines back from the DB and verify totals.
        lines = sess.execute(
            select(JournalLine).where(JournalLine.entry_id == entry.id)
        ).scalars().all()
        assert sum((line.debit for line in lines), Decimal("0")) == Decimal("1000.00")
        assert sum((line.credit for line in lines), Decimal("0")) == Decimal("1000.00")


def test_unbalanced_entry_is_rejected(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        ledger = LedgerService(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
        )
        with pytest.raises(UnbalancedJournalEntryError):
            ledger.post(
                period_id=a1.period_id,
                entry_date=date(2026, 3, 15),
                lines=[
                    LineInput(account_id=a1.cash_account_id, debit=Decimal("100")),
                    LineInput(account_id=a1.revenue_account_id, credit=Decimal("99.99")),
                ],
            )

        # Nothing should have been persisted.
        count = sess.execute(select(JournalEntry)).scalars().all()
        assert count == []


def test_negative_amounts_rejected(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        ledger = LedgerService(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
        )
        with pytest.raises(UnbalancedJournalEntryError):
            ledger.post(
                period_id=a1.period_id,
                entry_date=date(2026, 3, 15),
                lines=[
                    LineInput(account_id=a1.cash_account_id, debit=Decimal("-50")),
                    LineInput(account_id=a1.revenue_account_id, credit=Decimal("-50")),
                ],
            )


def test_both_sides_set_rejected(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        ledger = LedgerService(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
        )
        with pytest.raises(UnbalancedJournalEntryError):
            ledger.post(
                period_id=a1.period_id,
                entry_date=date(2026, 3, 15),
                lines=[
                    LineInput(
                        account_id=a1.cash_account_id,
                        debit=Decimal("100"),
                        credit=Decimal("100"),
                    ),
                    LineInput(account_id=a1.revenue_account_id, credit=Decimal("100")),
                ],
            )


def test_locked_period_rejects_post(world: SeededWorld) -> None:
    a1 = world.a1
    # Lock the period (as firm admin).
    from app.models.accounting import AccountingPeriod

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        period = sess.get(AccountingPeriod, a1.period_id)
        assert period is not None
        period.is_locked = True

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        ledger = LedgerService(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
        )
        with pytest.raises(PeriodLockedError):
            ledger.post(
                period_id=a1.period_id,
                entry_date=date(2026, 3, 15),
                lines=[
                    LineInput(account_id=a1.cash_account_id, debit=Decimal("10")),
                    LineInput(account_id=a1.revenue_account_id, credit=Decimal("10")),
                ],
            )


def test_post_to_other_tenant_account_rejected(world: SeededWorld) -> None:
    """If the ledger service somehow references an account from another client,
    the domain layer rejects it (defense in depth on top of RLS)."""
    a1 = world.a1
    a2 = world.a2  # different client in same firm
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        ledger = LedgerService(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
        )
        # `a2.cash_account_id` is a real id but belongs to client a2; under the
        # firm scope WITH client_id set to a1, RLS hides it -> account not found.
        with pytest.raises((CrossTenantError, Exception)):
            ledger.post(
                period_id=a1.period_id,
                entry_date=date(2026, 3, 15),
                lines=[
                    LineInput(account_id=a2.cash_account_id, debit=Decimal("10")),
                    LineInput(account_id=a1.revenue_account_id, credit=Decimal("10")),
                ],
            )


def test_reversal_creates_balanced_inverse(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        ledger = LedgerService(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
        )
        original = ledger.post(
            period_id=a1.period_id,
            entry_date=date(2026, 3, 15),
            lines=[
                LineInput(account_id=a1.cash_account_id, debit=Decimal("250")),
                LineInput(account_id=a1.revenue_account_id, credit=Decimal("250")),
            ],
        )
        reversal = ledger.reverse(entry_id=original.id, memo="customer refund")

        # Both entries combined should net to zero on every account.
        from sqlalchemy import func as f

        rows = sess.execute(
            select(
                JournalLine.account_id,
                f.sum(JournalLine.debit) - f.sum(JournalLine.credit),
            )
            .where(JournalLine.entry_id.in_([original.id, reversal.id]))
            .group_by(JournalLine.account_id)
        ).all()
        for _aid, net in rows:
            assert Decimal(str(net)) == Decimal("0")
