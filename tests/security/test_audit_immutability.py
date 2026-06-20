"""Phase 7 — audit_event append-only enforcement test.

`migrations/versions/0002_audit_append_only.py` REVOKEs UPDATE and DELETE
on `audit_event` from the runtime `app_user` (and `app_user_test`) role.
This test connects as that role and proves the REVOKE is real: UPDATE
and DELETE must error, INSERT must succeed.

Owner-role connections are deliberately NOT exercised here: owner can
mutate the row by design (DDL ops, manual data fixes), and that's
constrained by the platform's separate change-management process.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import SessionLocal


@pytest.fixture
def app_role_engine():  # type: ignore[no-untyped-def]
    """A connection as the runtime app role (not the owner)."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _seed_audit_row(sess) -> str:  # type: ignore[no-untyped-def]
    firm = str(uuid4())
    client = str(uuid4())
    row_id = str(uuid4())
    sess.begin()
    sess.execute(text("SELECT set_config('app.current_firm', :v, true)"), {"v": firm})
    sess.execute(text("SELECT set_config('app.current_client', :v, true)"), {"v": client})
    sess.execute(text("SELECT set_config('app.access_scope', 'firm', true)"))
    sess.execute(
        text(
            """
            INSERT INTO audit_event (id, firm_id, client_id, actor, action, entity_type, entity_id, details)
            VALUES (:id, :firm, :client, 'tester', 'create', 'test_entity', NULL, '{}'::jsonb)
            """
        ),
        {"id": row_id, "firm": firm, "client": client},
    )
    sess.commit()
    return row_id


def test_app_role_can_insert_audit_event(app_role_engine) -> None:  # type: ignore[no-untyped-def]
    rid = _seed_audit_row(app_role_engine)
    assert rid  # got here without raising


def test_app_role_cannot_update_audit_event(app_role_engine) -> None:  # type: ignore[no-untyped-def]
    rid = _seed_audit_row(app_role_engine)
    with pytest.raises(Exception) as excinfo:
        app_role_engine.begin()
        app_role_engine.execute(
            text("UPDATE audit_event SET actor='tampered' WHERE id = :id"),
            {"id": rid},
        )
        app_role_engine.commit()
    msg = str(excinfo.value).lower()
    assert "permission denied" in msg or "denied" in msg


def test_app_role_cannot_delete_audit_event(app_role_engine) -> None:  # type: ignore[no-untyped-def]
    rid = _seed_audit_row(app_role_engine)
    with pytest.raises(Exception) as excinfo:
        app_role_engine.begin()
        app_role_engine.execute(
            text("DELETE FROM audit_event WHERE id = :id"), {"id": rid}
        )
        app_role_engine.commit()
    msg = str(excinfo.value).lower()
    assert "permission denied" in msg or "denied" in msg


def test_app_role_is_not_superuser_and_not_bypassrls(app_role_engine) -> None:  # type: ignore[no-untyped-def]
    """Defence in depth: the role used by the app must not be able to bypass RLS."""
    if os.environ.get("CI") == "true":
        # CI seeds via the workflow; assume the role exists.
        pass
    app_role_engine.begin()
    row = app_role_engine.execute(
        text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
    ).first()
    app_role_engine.commit()
    assert row is not None, "current_user should resolve"
    assert row[0] is False, "app role must not be superuser"
    assert row[1] is False, "app role must not have BYPASSRLS"
