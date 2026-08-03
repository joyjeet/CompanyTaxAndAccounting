"""Integration tests for /journal-entries: list, get, and manual posting.

Verifies balanced/unbalanced validation, period-lock enforcement,
cross-tenant RLS, and portal-vs-firm scope rules.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.session import tenant_session
from app.db.tenant import AccessScope, TenantContext
from app.main import create_app
from app.models.accounting import AccountingPeriod
from app.security.auth import reset_identity_provider


@pytest.fixture(autouse=True)
def _reset_identity():
    reset_identity_provider()
    yield
    reset_identity_provider()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _auth(client: TestClient, role: str, firm_id, client_id=None) -> dict:
    body = {"sub": "tester", "role": role, "firm_id": str(firm_id)}
    if client_id is not None:
        body["client_id"] = str(client_id)
    resp = client.post("/auth/dev-token", json=body)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _balanced_lines(world_client) -> list[dict]:
    return [
        {
            "account_id": str(world_client.cash_account_id),
            "debit": "100.00",
            "credit": "0",
            "description": "deposit",
        },
        {
            "account_id": str(world_client.revenue_account_id),
            "debit": "0",
            "credit": "100.00",
            "description": "service rev",
        },
    ]


# --------------------------------------------------------------------------- #
# Posting
# --------------------------------------------------------------------------- #
def test_post_balanced_entry_ok(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "entry_date": "2026-06-15",
            "memo": "consulting",
            "lines": _balanced_lines(world.a1),
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "posted"
    assert len(body["lines"]) == 2


def test_post_unbalanced_entry_returns_400(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    bad = _balanced_lines(world.a1)
    bad[1]["credit"] = "50.00"  # debits 100, credits 50 -> unbalanced
    r = client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "entry_date": "2026-06-15",
            "lines": bad,
        },
    )
    assert r.status_code == 400


def test_post_to_locked_period_still_succeeds(client: TestClient, world) -> None:
    """Books are continuous: `is_locked` does not gate posting."""
    # Lock the period via tenant_session so the firm-admin context satisfies RLS.
    ctx = TenantContext(firm_id=world.firm_a, scope=AccessScope.FIRM)
    with tenant_session(ctx) as sess:
        period = sess.get(AccountingPeriod, world.a1.period_id)
        assert period is not None
        period.is_locked = True
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "entry_date": "2026-06-15",
            "lines": _balanced_lines(world.a1),
        },
    )
    assert r.status_code == 201
    assert r.json()["entry_date"] == "2026-06-15"


def test_post_without_period_id_derives_from_entry_date(
    client: TestClient, world
) -> None:
    """`period_id` is optional — the bucket follows the date the user picked."""
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(world.a1.client_id),
            "entry_date": "2023-11-02",
            "lines": _balanced_lines(world.a1),
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["entry_date"] == "2023-11-02"
    assert body["period_id"] != str(world.a1.period_id)


def test_post_with_cross_tenant_account_400(client: TestClient, world) -> None:
    """An account belonging to a different client should be rejected."""
    headers = _auth(client, "firm_staff", world.firm_a)
    lines = [
        {
            "account_id": str(world.a1.cash_account_id),
            "debit": "10.00",
            "credit": "0",
        },
        {
            # account from a DIFFERENT client in the same firm
            "account_id": str(world.a2.revenue_account_id),
            "debit": "0",
            "credit": "10.00",
        },
    ]
    r = client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "entry_date": "2026-06-15",
            "lines": lines,
        },
    )
    assert r.status_code == 400


def test_portal_cannot_post(client: TestClient, world) -> None:
    headers = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    r = client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "entry_date": "2026-06-15",
            "lines": _balanced_lines(world.a1),
        },
    )
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #
def test_list_entries_filters_by_client(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    # Post one entry for a1
    client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "entry_date": "2026-06-15",
            "lines": _balanced_lines(world.a1),
        },
    )
    r1 = client.get(
        "/journal-entries", headers=headers, params={"client_id": str(world.a1.client_id)}
    )
    assert r1.status_code == 200
    assert len(r1.json()) == 1
    r2 = client.get(
        "/journal-entries", headers=headers, params={"client_id": str(world.a2.client_id)}
    )
    assert r2.status_code == 200
    assert r2.json() == []


def test_list_entries_cross_tenant_404(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.get(
        "/journal-entries", headers=headers, params={"client_id": str(world.b1.client_id)}
    )
    assert r.status_code == 404


def _post_on(client: TestClient, headers: dict, world_client, entry_date: str) -> None:
    r = client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(world_client.client_id),
            "period_id": str(world_client.period_id),
            "entry_date": entry_date,
            "lines": _balanced_lines(world_client),
        },
    )
    assert r.status_code == 201, r.text


def test_list_entries_filters_by_date_range(client: TestClient, world) -> None:
    """The date picker's range must actually narrow the returned entries."""
    headers = _auth(client, "firm_staff", world.firm_a)
    for day in ("2026-03-10", "2026-06-15", "2026-09-20"):
        _post_on(client, headers, world.a1, day)

    r = client.get(
        "/journal-entries",
        headers=headers,
        params={
            "client_id": str(world.a1.client_id),
            "date_from": "2026-06-01",
            "date_to": "2026-06-30",
        },
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [e["entry_date"] for e in rows] == ["2026-06-15"]


def test_list_entries_date_bounds_are_inclusive(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    for day in ("2026-03-10", "2026-06-15", "2026-09-20"):
        _post_on(client, headers, world.a1, day)

    r = client.get(
        "/journal-entries",
        headers=headers,
        params={
            "client_id": str(world.a1.client_id),
            "date_from": "2026-03-10",
            "date_to": "2026-09-20",
        },
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 3


def test_list_entries_open_ended_date_range(client: TestClient, world) -> None:
    """Only one bound supplied still filters (the other side stays open)."""
    headers = _auth(client, "firm_staff", world.firm_a)
    for day in ("2026-03-10", "2026-06-15", "2026-09-20"):
        _post_on(client, headers, world.a1, day)

    r = client.get(
        "/journal-entries",
        headers=headers,
        params={"client_id": str(world.a1.client_id), "date_from": "2026-06-16"},
    )
    assert r.status_code == 200, r.text
    assert [e["entry_date"] for e in r.json()] == ["2026-09-20"]


def test_list_entries_inverted_date_range_400(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.get(
        "/journal-entries",
        headers=headers,
        params={
            "client_id": str(world.a1.client_id),
            "date_from": "2026-09-01",
            "date_to": "2026-01-01",
        },
    )
    assert r.status_code == 400, r.text


def test_portal_cannot_list_other_client(client: TestClient, world) -> None:
    headers = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    r = client.get(
        "/journal-entries", headers=headers, params={"client_id": str(world.a2.client_id)}
    )
    assert r.status_code == 403
