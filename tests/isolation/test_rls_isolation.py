"""Cross-tenant isolation tests.

These tests are the contract that the entire platform leans on. Treat any
cross-tenant leak as a hard failure.

Coverage:
  * Read isolation under FIRM scope: firm A staff cannot see firm B clients/COA/JEs.
  * Read isolation under CLIENT scope: portal user for client A1 cannot see A2's data.
  * Cross-firm INSERT: firm A staff cannot insert a row tagged with firm B id.
  * Cross-client INSERT under CLIENT scope: A1 portal cannot insert into A2.
  * Cross-firm UPDATE: cannot move a row to another firm.
  * Cross-firm DELETE: cannot delete another firm's rows.
  * No-context: with no GUCs set, no rows are visible (fail closed).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.db.session import tenant_session, unscoped_session
from app.domain.exceptions import CrossTenantError, InvalidAccountError
from app.domain.ledger import LedgerService, LineInput
from app.models.accounting import (
    AccountingPeriod,
    ChartOfAccounts,
    Client,
    JournalEntry,
    JournalLine,
)
from app.models.enums import AccountType, NormalBalance
from tests.conftest import (
    SeededWorld,
    ctx_client,
    ctx_firm,
    ctx_firm_for_client,
)

D = Decimal


# --------------------------------------------------------------------------- #
# Helper: post a journal entry into a given client to give the isolation tests
# something to (fail to) read.
# --------------------------------------------------------------------------- #
def _seed_je(world: SeededWorld) -> None:
    for sc in (world.a1, world.a2, world.b1):
        with tenant_session(ctx_firm_for_client(sc.firm_id, sc.client_id)) as sess:
            LedgerService(
                sess, firm_id=sc.firm_id, client_id=sc.client_id, actor="seed"
            ).post(
                period_id=sc.period_id,
                entry_date=date(2026, 1, 10),
                lines=[
                    LineInput(account_id=sc.cash_account_id, debit=D("100")),
                    LineInput(account_id=sc.revenue_account_id, credit=D("100")),
                ],
                memo=f"seed-{sc.client_id}",
            )


# --------------------------------------------------------------------------- #
# 1. READ ISOLATION
# --------------------------------------------------------------------------- #
def test_firm_scope_cannot_see_other_firms_clients(world: SeededWorld) -> None:
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        clients = sess.execute(select(Client)).scalars().all()
        # Firm A has 2 clients; firm B has 1. We should see only firm A's two.
        ids = {c.id for c in clients}
        assert ids == {world.a1.client_id, world.a2.client_id}, ids


def test_firm_scope_cannot_see_other_firms_coa_or_periods(world: SeededWorld) -> None:
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        coas = sess.execute(select(ChartOfAccounts)).scalars().all()
        for c in coas:
            assert c.firm_id == world.firm_a, "Cross-firm leak in chart_of_accounts!"
        periods = sess.execute(select(AccountingPeriod)).scalars().all()
        for p in periods:
            assert p.firm_id == world.firm_a, "Cross-firm leak in accounting_period!"


def test_firm_scope_cannot_see_other_firms_journal_entries(
    world: SeededWorld,
) -> None:
    _seed_je(world)
    with tenant_session(ctx_firm(world.firm_b)) as sess:
        jes = sess.execute(select(JournalEntry)).scalars().all()
        # Firm B should see only its own one entry.
        assert len(jes) == 1
        assert jes[0].firm_id == world.firm_b
        # No journal_line from another firm visible.
        lines = sess.execute(select(JournalLine)).scalars().all()
        for line in lines:
            assert line.firm_id == world.firm_b


def test_client_scope_cannot_see_sibling_client(world: SeededWorld) -> None:
    """A1 portal user must not see A2's data, even though both are in firm A."""
    _seed_je(world)
    with tenant_session(ctx_client(world.firm_a, world.a1.client_id)) as sess:
        clients = sess.execute(select(Client)).scalars().all()
        assert {c.id for c in clients} == {world.a1.client_id}

        coas = sess.execute(select(ChartOfAccounts)).scalars().all()
        for c in coas:
            assert c.client_id == world.a1.client_id

        jes = sess.execute(select(JournalEntry)).scalars().all()
        for j in jes:
            assert j.client_id == world.a1.client_id


def test_firm_scope_with_client_filter_only_sees_that_client(
    world: SeededWorld,
) -> None:
    """When a firm-staff session is scoped to a single client, they should
    only see that client's rows even though they're FIRM scope."""
    _seed_je(world)
    ctx = ctx_firm_for_client(world.firm_a, world.a1.client_id)
    with tenant_session(ctx) as sess:
        coas = sess.execute(select(ChartOfAccounts)).scalars().all()
        for c in coas:
            assert c.client_id == world.a1.client_id


# --------------------------------------------------------------------------- #
# 2. WRITE ISOLATION (the hard part — RLS WITH CHECK)
# --------------------------------------------------------------------------- #
def test_cannot_insert_client_into_another_firm(world: SeededWorld) -> None:
    """Firm A staff tagging a row with firm B's id must fail RLS WITH CHECK."""
    with pytest.raises(ProgrammingError):
        with tenant_session(ctx_firm(world.firm_a)) as sess:
            sess.add(Client(id=uuid4(), firm_id=world.firm_b, name="evil"))
            sess.flush()  # forces the INSERT — RLS WITH CHECK rejects


def test_cannot_insert_coa_into_another_clients_account(world: SeededWorld) -> None:
    """A1 portal user attempting to insert a COA row tagged with A2's client_id."""
    with pytest.raises(ProgrammingError):
        with tenant_session(ctx_client(world.firm_a, world.a1.client_id)) as sess:
            sess.add(
                ChartOfAccounts(
                    id=uuid4(),
                    firm_id=world.firm_a,
                    client_id=world.a2.client_id,  # cross-client!
                    code="9999",
                    name="evil",
                    account_type=AccountType.EXPENSE,
                    normal_balance=NormalBalance.DEBIT,
                )
            )
            sess.flush()


def test_cannot_insert_journal_line_for_other_clients_account(
    world: SeededWorld,
) -> None:
    """Even if the account_id of another client were known, posting against it
    under our context must be rejected — both by domain code and, ultimately,
    by RLS WITH CHECK on the line itself when tagged with our client_id."""
    a1 = world.a1
    a2 = world.a2

    # Try to write a line tagged for our client a1 but referencing a2's account.
    # The FK is intra-DB so it resolves; but the line carries client_id = a1,
    # so account_id must belong to a1 — which it doesn't. The domain layer
    # rejects this; if the domain layer were bypassed, the FK would still
    # connect, but RLS on the journal_entry insert would also have triggered
    # before reaching here. We assert the domain rejection cleanly.
    with pytest.raises((CrossTenantError, InvalidAccountError, ProgrammingError)):
        with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
            LedgerService(
                sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="x"
            ).post(
                period_id=a1.period_id,
                entry_date=date(2026, 3, 15),
                lines=[
                    LineInput(account_id=a2.cash_account_id, debit=D("10")),
                    LineInput(account_id=a1.revenue_account_id, credit=D("10")),
                ],
            )


def test_cannot_update_to_move_row_across_firms(world: SeededWorld) -> None:
    """Even if you have a row visible to you, you cannot UPDATE its firm_id to
    another firm — RLS WITH CHECK rejects."""
    _seed_je(world)
    with pytest.raises(ProgrammingError):
        with tenant_session(ctx_firm(world.firm_a)) as sess:
            coa = sess.execute(select(ChartOfAccounts).limit(1)).scalars().first()
            assert coa is not None
            coa.firm_id = world.firm_b
            sess.flush()


def test_update_invisible_row_is_a_no_op(world: SeededWorld) -> None:
    """RLS hides another firm's rows, so a bulk UPDATE matches zero rows
    rather than leaking data. We use raw SQL to bypass identity-map effects."""
    _seed_je(world)
    other_firm_coa_id = None
    # Discover a firm B COA id from a privileged context just to have a real id.
    with tenant_session(ctx_firm(world.firm_b)) as sess:
        coa = sess.execute(select(ChartOfAccounts).limit(1)).scalars().first()
        assert coa is not None
        other_firm_coa_id = coa.id

    with tenant_session(ctx_firm(world.firm_a)) as sess:
        result = sess.execute(
            text("UPDATE chart_of_accounts SET name = 'pwned' WHERE id = :i"),
            {"i": other_firm_coa_id},
        )
        # No rows affected because the row is invisible under firm A's policy.
        assert result.rowcount == 0

    # And the target row is unchanged.
    with tenant_session(ctx_firm(world.firm_b)) as sess:
        coa = sess.get(ChartOfAccounts, other_firm_coa_id)
        assert coa is not None
        assert coa.name != "pwned"


def test_delete_invisible_row_is_a_no_op(world: SeededWorld) -> None:
    _seed_je(world)
    target_id = None
    with tenant_session(ctx_firm(world.firm_b)) as sess:
        coa = sess.execute(select(ChartOfAccounts).limit(1)).scalars().first()
        assert coa is not None
        target_id = coa.id

    with tenant_session(ctx_firm(world.firm_a)) as sess:
        result = sess.execute(
            text("DELETE FROM chart_of_accounts WHERE id = :i"), {"i": target_id}
        )
        assert result.rowcount == 0


# --------------------------------------------------------------------------- #
# 3. NO CONTEXT = NO ROWS
# --------------------------------------------------------------------------- #
def test_no_context_returns_zero_rows(world: SeededWorld) -> None:
    """Without app.current_firm / app.access_scope set, every tenant table
    must return zero rows. Fail closed."""
    _seed_je(world)
    with unscoped_session() as sess:
        for model in (Client, ChartOfAccounts, AccountingPeriod, JournalEntry, JournalLine):
            rows = sess.execute(select(model)).scalars().all()
            assert rows == [], f"{model.__name__} leaked rows under no-context!"


def test_no_context_cannot_insert_tenant_rows(world: SeededWorld) -> None:
    """Inserting any tenant-scoped row without context must be blocked by RLS
    WITH CHECK (the predicate evaluates false because firm_id != NULL)."""
    with pytest.raises(ProgrammingError):
        with unscoped_session() as sess:
            sess.add(
                ChartOfAccounts(
                    id=uuid4(),
                    firm_id=world.firm_a,
                    client_id=world.a1.client_id,
                    code="ZZZ",
                    name="phantom",
                    account_type=AccountType.EXPENSE,
                    normal_balance=NormalBalance.DEBIT,
                )
            )
            sess.flush()


# --------------------------------------------------------------------------- #
# 4. POOLED CONNECTION DOES NOT LEAK CONTEXT
# --------------------------------------------------------------------------- #
def test_pooled_connection_does_not_leak_context(world: SeededWorld) -> None:
    """Use the SAME engine across two transactions that may share a pooled
    connection: the second transaction must NOT inherit GUCs from the first."""
    _seed_je(world)

    # First request: firm A, sees A's clients.
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        ids_a = {c.id for c in sess.execute(select(Client)).scalars()}
        assert world.a1.client_id in ids_a
    # Connection released to pool.

    # Second request on same engine WITH NO CONTEXT — must see no rows even if
    # the same pooled connection is handed back.
    with unscoped_session() as sess:
        rows = sess.execute(select(Client)).scalars().all()
        assert rows == [], (
            "Tenant context leaked across pooled connection! "
            "SET LOCAL must scope GUCs to the transaction only."
        )

    # Third request: firm B, must see only B's clients (no leakage from A).
    with tenant_session(ctx_firm(world.firm_b)) as sess:
        ids_b = {c.id for c in sess.execute(select(Client)).scalars()}
        assert ids_b == {world.b1.client_id}, ids_b
        assert ids_b.isdisjoint(ids_a), "Firm A ids visible from firm B context!"
