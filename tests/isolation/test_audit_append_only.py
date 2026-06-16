"""Audit log must be append-only at the database layer."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import ProgrammingError

from app.db.session import tenant_session
from app.domain.ledger import LedgerService, LineInput
from app.models.accounting import AuditEvent
from tests.conftest import SeededWorld, ctx_firm_for_client


def _post_one(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        LedgerService(
            sess, firm_id=a1.firm_id, client_id=a1.client_id, actor="seed"
        ).post(
            period_id=a1.period_id,
            entry_date=date(2026, 3, 15),
            lines=[
                LineInput(account_id=a1.cash_account_id, debit=Decimal("10")),
                LineInput(account_id=a1.revenue_account_id, credit=Decimal("10")),
            ],
            memo="audit test seed",
        )


def test_app_user_cannot_update_audit_event(world: SeededWorld) -> None:
    _post_one(world)
    a1 = world.a1
    with pytest.raises(ProgrammingError):
        with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
            sess.execute(
                update(AuditEvent)
                .where(AuditEvent.firm_id == a1.firm_id)
                .values(actor="tampered")
            )
            sess.flush()


def test_app_user_cannot_delete_audit_event(world: SeededWorld) -> None:
    _post_one(world)
    a1 = world.a1
    with pytest.raises(ProgrammingError):
        with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
            sess.execute(
                delete(AuditEvent).where(AuditEvent.firm_id == a1.firm_id)
            )
            sess.flush()


def test_app_user_can_still_insert_and_select_audit_event(
    world: SeededWorld,
) -> None:
    _post_one(world)
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        rows = sess.execute(
            select(AuditEvent).where(AuditEvent.firm_id == a1.firm_id)
        ).scalars().all()
        assert rows, "expected at least one audit event from the seed POST"
        # And insert is allowed (write_audit() does this routinely).
        sess.add(
            AuditEvent(
                id=uuid4(),
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                actor="ok",
                action=rows[0].action,
                entity_type="probe",
            )
        )
        sess.flush()
