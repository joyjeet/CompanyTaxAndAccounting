"""Integration tests for the new firm-staff CRUD endpoints in `clients.py`:
GET/POST /clients, /clients/{id}/periods, /clients/{id}/chart-of-accounts.
"""
from __future__ import annotations

from datetime import date
from uuid import uuid4

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
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# --------------------------------------------------------------------------- #
# GET /clients/{id}
# --------------------------------------------------------------------------- #
def test_get_client_firm_staff_ok(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.get(f"/clients/{world.a1.client_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == str(world.a1.client_id)
    assert r.json()["name"] == "ClientA1"


def test_get_client_cross_firm_returns_404(client: TestClient, world) -> None:
    # Firm A staff trying to read a firm B client → RLS hides → 404.
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.get(f"/clients/{world.b1.client_id}", headers=headers)
    assert r.status_code == 404


def test_get_client_portal_cannot_read_other_client(client: TestClient, world) -> None:
    # Portal user for a1 tries to read a2 → 403.
    headers = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    r = client.get(f"/clients/{world.a2.client_id}", headers=headers)
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# POST /clients
# --------------------------------------------------------------------------- #
def test_create_client_firm_staff_ok(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        "/clients",
        headers=headers,
        json={"name": "NewCo", "external_code": "NC-001"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "NewCo"
    assert body["firm_id"] == str(world.firm_a)


def test_create_client_portal_forbidden(client: TestClient, world) -> None:
    headers = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    r = client.post("/clients", headers=headers, json={"name": "X"})
    assert r.status_code == 403


def test_create_client_seeds_a_default_chart_of_accounts(
    client: TestClient, world
) -> None:
    """A brand-new client must be postable without a second setup step."""
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        "/clients",
        headers=headers,
        json={"name": "SeededCo", "industry": "generic"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["coa_seeded"] is True
    assert body["coa_seed_error"] is None

    coa = client.get(
        f"/clients/{body['id']}/chart-of-accounts", headers=headers
    )
    assert coa.status_code == 200, coa.text
    accounts = coa.json()
    assert accounts, "new client should not start with an empty chart"
    # One code series per statement group.
    by_type: dict[str, set[str]] = {}
    for a in accounts:
        by_type.setdefault(a["account_type"], set()).add(a["code"][0])
    assert by_type["asset"] == {"1"}
    assert by_type["liability"] == {"2"}
    assert by_type["equity"] == {"3"}
    assert by_type["revenue"] == {"4"}


def test_create_client_can_opt_out_of_coa_seeding(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        "/clients",
        headers=headers,
        json={"name": "BareCo", "seed_coa": False},
    )
    assert r.status_code == 201, r.text
    assert r.json()["coa_seeded"] is False

    coa = client.get(
        f"/clients/{r.json()['id']}/chart-of-accounts", headers=headers
    )
    assert coa.json() == []


def test_create_client_persists_the_supplied_profile(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        "/clients",
        headers=headers,
        json={
            "name": "ProfileCo",
            "external_code": "PC-1",
            "industry": "construction",
            "entity_type": "s_corp",
            "tax_year": 2026,
            "home_state": "TX",
            "fiscal_year_end_month": 6,
            "business_legal_name": "ProfileCo LLC",
            "ein": "12-3456789",
            "email": "owner@profileco.example",
            "city": "Austin",
            "address_state": "TX",
            "postal_code": "78701",
        },
    )
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]

    prof = client.get(f"/clients/{new_id}/profile", headers=headers)
    assert prof.status_code == 200, prof.text
    body = prof.json()
    assert body["entity_type"] == "s_corp"
    assert body["industry"] == "construction"
    assert body["tax_year"] == 2026
    assert body["home_state"] == "TX"
    assert body["fiscal_year_end_month"] == 6
    assert body["business_legal_name"] == "ProfileCo LLC"


def test_create_client_rejects_an_invalid_profile_field(
    client: TestClient, world
) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        "/clients",
        headers=headers,
        json={"name": "BadCo", "home_state": "T"},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Periods
# --------------------------------------------------------------------------- #
def test_list_periods_returns_seeded(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.get(f"/clients/{world.a1.client_id}/periods", headers=headers)
    assert r.status_code == 200
    periods = r.json()
    assert len(periods) == 1
    assert periods[0]["name"] == "2026"


def test_create_period_ok(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        f"/clients/{world.a1.client_id}/periods",
        headers=headers,
        json={
            "name": "2027",
            "start_date": "2027-01-01",
            "end_date": "2027-12-31",
        },
    )
    assert r.status_code == 201
    assert r.json()["name"] == "2027"


def test_create_period_rejects_inverted_dates(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        f"/clients/{world.a1.client_id}/periods",
        headers=headers,
        json={
            "name": "bad",
            "start_date": "2027-12-31",
            "end_date": "2027-01-01",
        },
    )
    assert r.status_code == 400


def test_list_periods_cross_firm_404(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.get(f"/clients/{world.b1.client_id}/periods", headers=headers)
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# COA
# --------------------------------------------------------------------------- #
def test_list_coa_returns_seeded(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.get(
        f"/clients/{world.a1.client_id}/chart-of-accounts", headers=headers
    )
    assert r.status_code == 200
    codes = {a["code"] for a in r.json()}
    assert {"1000", "1100", "2000", "3000", "4000", "5000"}.issubset(codes)


def test_create_coa_ok(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        f"/clients/{world.a1.client_id}/chart-of-accounts",
        headers=headers,
        json={
            "code": "6000",
            "name": "Marketing",
            "account_type": "expense",
            "normal_balance": "debit",
        },
    )
    assert r.status_code == 201
    assert r.json()["code"] == "6000"


def test_create_coa_portal_forbidden(client: TestClient, world) -> None:
    headers = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    r = client.post(
        f"/clients/{world.a1.client_id}/chart-of-accounts",
        headers=headers,
        json={
            "code": "9999",
            "name": "X",
            "account_type": "expense",
            "normal_balance": "debit",
        },
    )
    assert r.status_code == 403


def test_portal_can_read_own_coa(client: TestClient, world) -> None:
    headers = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    r = client.get(
        f"/clients/{world.a1.client_id}/chart-of-accounts", headers=headers
    )
    assert r.status_code == 200
    assert len(r.json()) >= 6
