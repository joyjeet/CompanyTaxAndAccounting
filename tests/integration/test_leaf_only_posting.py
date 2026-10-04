"""Phase 8b carry-over: enforce leaf-only posting in the ledger.

A JournalLine may only post to a leaf account. Parent/rollup accounts
are computed in statements — posting to them would corrupt subtotals
and double-count children.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.session import tenant_session
from app.domain.exceptions import InvalidAccountError
from app.domain.ledger import LedgerService, LineInput
from app.models.accounting import ChartOfAccounts
from app.models.enums import AccountType, NormalBalance
from tests.conftest import ctx_firm_for_client


def test_post_to_parent_account_rejected(world) -> None:
    """A journal entry whose line targets a non-leaf account is rejected."""
    # Create a parent + a leaf child under firm_a.client a1.
    firm = world.firm_a
    client = world.a1.client_id
    period = world.a1.period_id

    parent_id = uuid4()
    child_id = uuid4()
    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        parent = ChartOfAccounts(
            id=parent_id,
            firm_id=firm,
            client_id=client,
            code="7000",
            name="Occupancy (rollup)",
            account_type=AccountType.EXPENSE,
            normal_balance=NormalBalance.DEBIT,
            is_active=True,
            is_leaf=False,  # explicitly a parent
            path="7000",
            depth=0,
        )
        child = ChartOfAccounts(
            id=child_id,
            firm_id=firm,
            client_id=client,
            code="7010",
            name="Rent",
            account_type=AccountType.EXPENSE,
            normal_balance=NormalBalance.DEBIT,
            is_active=True,
            is_leaf=True,
            parent_account_id=parent_id,
            path="7000>7010",
            depth=1,
        )
        sess.add_all([parent, child])

    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        ledger = LedgerService(
            sess, firm_id=firm, client_id=client, actor="cpa@acme.test"
        )
        with pytest.raises(InvalidAccountError, match="parent/rollup"):
            ledger.post(
                period_id=period,
                entry_date=date(2026, 1, 15),
                lines=[
                    LineInput(account_id=world.a1.cash_account_id, credit=Decimal("100")),
                    LineInput(account_id=parent_id, debit=Decimal("100")),  # ← parent
                ],
                memo="should not be posted",
            )


def test_post_to_leaf_account_succeeds(world) -> None:
    """A journal entry whose lines all target leaf accounts posts normally."""
    firm = world.firm_a
    client = world.a1.client_id
    period = world.a1.period_id

    parent_id = uuid4()
    child_id = uuid4()
    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        parent = ChartOfAccounts(
            id=parent_id,
            firm_id=firm,
            client_id=client,
            code="7100",
            name="Office (rollup)",
            account_type=AccountType.EXPENSE,
            normal_balance=NormalBalance.DEBIT,
            is_active=True,
            is_leaf=False,
            path="7100",
            depth=0,
        )
        child = ChartOfAccounts(
            id=child_id,
            firm_id=firm,
            client_id=client,
            code="7110",
            name="Supplies",
            account_type=AccountType.EXPENSE,
            normal_balance=NormalBalance.DEBIT,
            is_active=True,
            is_leaf=True,
            parent_account_id=parent_id,
            path="7100>7110",
            depth=1,
        )
        sess.add_all([parent, child])

    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        ledger = LedgerService(
            sess, firm_id=firm, client_id=client, actor="cpa@acme.test"
        )
        entry = ledger.post(
            period_id=period,
            entry_date=date(2026, 1, 15),
            lines=[
                LineInput(account_id=world.a1.cash_account_id, credit=Decimal("50")),
                LineInput(account_id=child_id, debit=Decimal("50")),  # leaf
            ],
            memo="legitimate supply purchase",
        )
        assert entry.id is not None
