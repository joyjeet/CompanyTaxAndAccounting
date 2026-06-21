"""Integration tests for /statements/{profit-and-loss,balance-sheet,cash-flow}.

Posts a small but real chart of activity and verifies the rendered numbers
plus tenant boundaries.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
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
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _post(client: TestClient, headers: dict, *, world_client, period_id, lines) -> None:
    r = client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(world_client.client_id),
            "period_id": str(period_id),
            "entry_date": "2026-06-15",
            "lines": lines,
        },
    )
    assert r.status_code == 201, r.text


def _seed_activity(client: TestClient, headers: dict, world_client, period_id) -> None:
    # Owner invests $5,000 cash.
    _post(
        client,
        headers,
        world_client=world_client,
        period_id=period_id,
        lines=[
            {"account_id": str(world_client.cash_account_id), "debit": "5000", "credit": "0"},
            {"account_id": str(world_client.equity_account_id), "debit": "0", "credit": "5000"},
        ],
    )
    # Earn $1,500 of service revenue (collected in cash).
    _post(
        client,
        headers,
        world_client=world_client,
        period_id=period_id,
        lines=[
            {"account_id": str(world_client.cash_account_id), "debit": "1500", "credit": "0"},
            {"account_id": str(world_client.revenue_account_id), "debit": "0", "credit": "1500"},
        ],
    )
    # Pay $300 of office expense in cash.
    _post(
        client,
        headers,
        world_client=world_client,
        period_id=period_id,
        lines=[
            {"account_id": str(world_client.expense_account_id), "debit": "300", "credit": "0"},
            {"account_id": str(world_client.cash_account_id), "debit": "0", "credit": "300"},
        ],
    )


# --------------------------------------------------------------------------- #
def test_profit_and_loss_numbers(client: TestClient, world) -> None:
    h = _auth(client, "firm_staff", world.firm_a)
    _seed_activity(client, h, world.a1, world.a1.period_id)
    r = client.get(
        "/statements/profit-and-loss",
        headers=h,
        params={"client_id": str(world.a1.client_id), "period_id": str(world.a1.period_id)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["total_revenue"]) == Decimal("1500")
    assert Decimal(body["total_expenses"]) == Decimal("300")
    assert Decimal(body["net_income"]) == Decimal("1200")


def test_balance_sheet_balances(client: TestClient, world) -> None:
    h = _auth(client, "firm_staff", world.firm_a)
    _seed_activity(client, h, world.a1, world.a1.period_id)
    r = client.get(
        "/statements/balance-sheet",
        headers=h,
        params={"client_id": str(world.a1.client_id), "period_id": str(world.a1.period_id)},
    )
    assert r.status_code == 200
    body = r.json()
    # Assets: cash 5000+1500-300 = 6200.
    # Equity = posted equity (5000) + retained earnings to date (1200) = 6200.
    assert Decimal(body["total_assets"]) == Decimal("6200")
    assert Decimal(body["total_liabilities"]) == Decimal("0")
    assert Decimal(body["total_equity"]) == Decimal("6200")
    assert Decimal(body["retained_earnings_to_date"]) == Decimal("1200")
    assert body["balances"] is True


def test_cash_flow_numbers(client: TestClient, world) -> None:
    h = _auth(client, "firm_staff", world.firm_a)
    _seed_activity(client, h, world.a1, world.a1.period_id)
    r = client.get(
        "/statements/cash-flow",
        headers=h,
        params={"client_id": str(world.a1.client_id), "period_id": str(world.a1.period_id)},
    )
    assert r.status_code == 200
    body = r.json()
    assert Decimal(body["opening_cash"]) == Decimal("0")
    assert Decimal(body["closing_cash"]) == Decimal("6200")
    assert Decimal(body["net_change"]) == Decimal("6200")
    assert Decimal(body["inflows"]) == Decimal("6500")
    assert Decimal(body["outflows"]) == Decimal("300")
    assert body["cash_account_codes"] == ["1000"]


def test_pl_cross_firm_404(client: TestClient, world) -> None:
    h = _auth(client, "firm_staff", world.firm_a)
    r = client.get(
        "/statements/profit-and-loss",
        headers=h,
        params={"client_id": str(world.b1.client_id), "period_id": str(world.b1.period_id)},
    )
    assert r.status_code == 404


def test_pl_portal_other_client_403(client: TestClient, world) -> None:
    h = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    r = client.get(
        "/statements/profit-and-loss",
        headers=h,
        params={"client_id": str(world.a2.client_id), "period_id": str(world.a2.period_id)},
    )
    assert r.status_code == 403


def test_pl_mismatched_period_404(client: TestClient, world) -> None:
    """Asking for client a1's stmt with a2's period must 404."""
    h = _auth(client, "firm_staff", world.firm_a)
    r = client.get(
        "/statements/profit-and-loss",
        headers=h,
        params={"client_id": str(world.a1.client_id), "period_id": str(world.a2.period_id)},
    )
    assert r.status_code == 404


def test_portal_can_view_own_pl(client: TestClient, world) -> None:
    firm_h = _auth(client, "firm_staff", world.firm_a)
    _seed_activity(client, firm_h, world.a1, world.a1.period_id)
    portal_h = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    r = client.get(
        "/statements/profit-and-loss",
        headers=portal_h,
        params={"client_id": str(world.a1.client_id), "period_id": str(world.a1.period_id)},
    )
    assert r.status_code == 200
    assert Decimal(r.json()["net_income"]) == Decimal("1200")
