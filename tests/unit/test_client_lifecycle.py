"""Domain-level tests for archive / restore / delete."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.db.session import tenant_session
from app.domain.client_lifecycle import (
    ClientHasDataError,
    ClientNotFoundError,
    archive_client,
    client_data_counts,
    delete_client,
    restore_client,
)
from app.domain.exceptions import ClientArchivedError
from app.domain.ledger import LedgerService, LineInput
from app.models.accounting import AuditEvent, ChartOfAccounts, Client
from app.models.enums import AuditAction
from tests.conftest import SeededWorld, ctx_firm_for_client


def _post(sess, seeded) -> None:
    LedgerService(
        sess, firm_id=seeded.firm_id, client_id=seeded.client_id, actor="staff@acme"
    ).post(
        period_id=seeded.period_id,
        entry_date=date(2026, 3, 15),
        lines=[
            LineInput(account_id=seeded.cash_account_id, debit=Decimal("50.00")),
            LineInput(account_id=seeded.revenue_account_id, credit=Decimal("50.00")),
        ],
    )


def test_archive_then_restore_round_trips(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        c = archive_client(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
        )
        assert c.is_active is False and c.archived_at is not None

        # Archiving twice is a no-op, not an error.
        archive_client(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
        )

        c = restore_client(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
        )
        assert c.is_active is True and c.archived_at is None

        actions = sess.execute(
            select(AuditEvent.action).where(AuditEvent.client_id == a1.client_id)
        ).scalars().all()
        assert actions.count(AuditAction.CLIENT_ARCHIVE) == 1
        assert actions.count(AuditAction.CLIENT_RESTORE) == 1


def test_archived_client_refuses_postings(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        archive_client(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
        )
        with pytest.raises(ClientArchivedError, match="archived"):
            _post(sess, a1)


def test_unknown_client_raises_not_found(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        with pytest.raises(ClientNotFoundError):
            archive_client(
                sess, firm_id=a1.firm_id, client_id=uuid4(), actor="staff@acme"
            )


def test_a_seeded_chart_does_not_count_as_books(world: SeededWorld) -> None:
    """The whole point: a brand-new client is still deletable."""
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        assert client_data_counts(sess, client_id=a1.client_id) == {}


def test_delete_removes_setup_rows_but_keeps_the_audit_trail(
    world: SeededWorld,
) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        delete_client(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
        )

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        assert sess.get(Client, a1.client_id) is None
        remaining = sess.execute(
            select(func.count())
            .select_from(ChartOfAccounts)
            .where(ChartOfAccounts.client_id == a1.client_id)
        ).scalar_one()
        assert remaining == 0

        # The record that the client existed and was removed survives.
        events = sess.execute(
            select(AuditEvent)
            .where(AuditEvent.client_id == a1.client_id)
            .where(AuditEvent.action == AuditAction.CLIENT_DELETE)
        ).scalars().all()
        assert len(events) == 1
        assert events[0].details["name"] == "ClientA1"


def test_delete_refuses_once_there_are_entries(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        _post(sess, a1)

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        assert client_data_counts(sess, client_id=a1.client_id) == {"journal entry": 1}
        with pytest.raises(ClientHasDataError, match="1 journal entry"):
            delete_client(
                sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="staff@acme"
            )

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        assert sess.get(Client, a1.client_id) is not None
