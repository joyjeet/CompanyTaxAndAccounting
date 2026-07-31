"""Integration tests for chart-of-accounts mutation:

PATCH/DELETE /clients/{id}/chart-of-accounts/{account_id}, sub-account
creation, and the uniqueness / referential guards that back the UI's
"edit, deactivate, remove" affordances.
"""
from __future__ import annotations

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


def _coa_url(client_id, account_id=None) -> str:
    base = f"/clients/{client_id}/chart-of-accounts"
    return base if account_id is None else f"{base}/{account_id}"


def _create(client, headers, client_id, **body):
    r = client.post(_coa_url(client_id), headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _by_code(client, headers, client_id) -> dict[str, dict]:
    r = client.get(_coa_url(client_id), headers=headers)
    assert r.status_code == 200, r.text
    return {a["code"]: a for a in r.json()}


# --------------------------------------------------------------------------- #
# Uniqueness (UI item 1)
# --------------------------------------------------------------------------- #
def test_duplicate_code_on_create_is_409_not_500(client: TestClient, world) -> None:
    """A duplicate code used to surface as a raw IntegrityError 500."""
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        _coa_url(world.a1.client_id),
        headers=headers,
        json={"code": "1000", "name": "Duplicate Cash", "account_type": "asset"},
    )
    assert r.status_code == 409
    assert "already used" in r.json()["detail"]


def test_duplicate_code_on_update_is_rejected(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    acct = _create(
        client, headers, world.a1.client_id,
        code="6100", name="Marketing", account_type="expense",
    )
    r = client.patch(
        _coa_url(world.a1.client_id, acct["id"]),
        headers=headers,
        json={"code": "1000"},  # already taken by Cash
    )
    assert r.status_code == 409
    assert "already used" in r.json()["detail"]


def test_recoding_to_its_own_code_is_not_a_conflict(
    client: TestClient, world
) -> None:
    """The uniqueness check must exclude the row being updated."""
    headers = _auth(client, "firm_staff", world.firm_a)
    acct = _create(
        client, headers, world.a1.client_id,
        code="6110", name="Ads", account_type="expense",
    )
    r = client.patch(
        _coa_url(world.a1.client_id, acct["id"]),
        headers=headers,
        json={"code": "6110", "name": "Advertising"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Advertising"


# --------------------------------------------------------------------------- #
# Sub-accounts (UI item 3)
# --------------------------------------------------------------------------- #
def test_create_sub_account_sets_path_and_unleafs_parent(
    client: TestClient, world
) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    parent = _create(
        client, headers, world.a1.client_id,
        code="6200", name="Vehicle", account_type="expense",
    )
    child = _create(
        client, headers, world.a1.client_id,
        code="6210", name="Fuel", account_type="expense",
        parent_account_id=parent["id"],
    )
    assert child["parent_account_id"] == parent["id"]
    assert child["depth"] == 1

    rows = _by_code(client, headers, world.a1.client_id)
    assert rows["6200"]["is_leaf"] is False
    assert rows["6200"]["child_count"] == 1
    assert rows["6210"]["is_leaf"] is True


def test_sub_account_must_match_parent_type(client: TestClient, world) -> None:
    """Nesting an expense under a liability would corrupt subtree rollups."""
    headers = _auth(client, "firm_staff", world.firm_a)
    rows = _by_code(client, headers, world.a1.client_id)
    liability_id = rows["2000"]["id"]

    r = client.post(
        _coa_url(world.a1.client_id),
        headers=headers,
        json={
            "code": "6300",
            "name": "Mismatched",
            "account_type": "expense",
            "parent_account_id": liability_id,
        },
    )
    assert r.status_code == 422
    assert "same type as its parent" in r.json()["detail"]


def test_reparent_under_own_descendant_is_rejected(
    client: TestClient, world
) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    parent = _create(
        client, headers, world.a1.client_id,
        code="6400", name="Travel", account_type="expense",
    )
    child = _create(
        client, headers, world.a1.client_id,
        code="6410", name="Airfare", account_type="expense",
        parent_account_id=parent["id"],
    )
    r = client.patch(
        _coa_url(world.a1.client_id, parent["id"]),
        headers=headers,
        json={"parent_account_id": child["id"]},
    )
    assert r.status_code == 422
    assert "cycle" in r.json()["detail"]


def test_recoding_a_parent_repaths_descendants(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    parent = _create(
        client, headers, world.a1.client_id,
        code="6500", name="Utilities", account_type="expense",
    )
    _create(
        client, headers, world.a1.client_id,
        code="6510", name="Electricity", account_type="expense",
        parent_account_id=parent["id"],
    )
    r = client.patch(
        _coa_url(world.a1.client_id, parent["id"]),
        headers=headers,
        json={"code": "6501"},
    )
    assert r.status_code == 200, r.text

    # The child still resolves under the renamed parent and keeps its depth.
    rows = _by_code(client, headers, world.a1.client_id)
    assert rows["6510"]["parent_account_id"] == parent["id"]
    assert rows["6510"]["depth"] == 1
    assert rows["6501"]["child_count"] == 1


# --------------------------------------------------------------------------- #
# Deactivate (UI item 5) and remove (UI item 4)
# --------------------------------------------------------------------------- #
def test_deactivate_keeps_the_account(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    acct = _create(
        client, headers, world.a1.client_id,
        code="6600", name="Obsolete", account_type="expense",
    )
    r = client.patch(
        _coa_url(world.a1.client_id, acct["id"]),
        headers=headers,
        json={"is_active": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    rows = _by_code(client, headers, world.a1.client_id)
    assert rows["6600"]["is_active"] is False

    # Reactivating is the same call with the flag flipped back.
    r = client.patch(
        _coa_url(world.a1.client_id, acct["id"]),
        headers=headers,
        json={"is_active": True},
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is True


def test_delete_unused_account_succeeds(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    acct = _create(
        client, headers, world.a1.client_id,
        code="6700", name="Scratch", account_type="expense",
    )
    r = client.delete(_coa_url(world.a1.client_id, acct["id"]), headers=headers)
    assert r.status_code == 204
    assert "6700" not in _by_code(client, headers, world.a1.client_id)


def test_delete_account_with_journal_lines_is_refused(
    client: TestClient, world
) -> None:
    """Seeded Cash (1000) is posted to, so it must not be removable."""
    headers = _auth(client, "firm_staff", world.firm_a)
    rows = _by_code(client, headers, world.a1.client_id)
    cash = rows["1000"]

    # Post an entry so the account definitely has history.
    je = client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "entry_date": "2026-03-01",
            "memo": "coa delete guard",
            "lines": [
                {"account_id": cash["id"], "debit": "10.00", "credit": "0"},
                {
                    "account_id": rows["4000"]["id"],
                    "debit": "0",
                    "credit": "10.00",
                },
            ],
        },
    )
    assert je.status_code in (200, 201), je.text

    r = client.delete(_coa_url(world.a1.client_id, cash["id"]), headers=headers)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "journal line" in detail
    assert "Deactivate it instead" in detail

    # And the usage count is visible to the UI without this round-trip.
    assert _by_code(client, headers, world.a1.client_id)["1000"][
        "journal_line_count"
    ] > 0


def test_delete_account_with_children_is_refused(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    parent = _create(
        client, headers, world.a1.client_id,
        code="6800", name="Insurance", account_type="expense",
    )
    _create(
        client, headers, world.a1.client_id,
        code="6810", name="Liability cover", account_type="expense",
        parent_account_id=parent["id"],
    )
    r = client.delete(_coa_url(world.a1.client_id, parent["id"]), headers=headers)
    assert r.status_code == 409
    assert "sub-account" in r.json()["detail"]


def test_deleting_last_child_makes_parent_a_leaf_again(
    client: TestClient, world
) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    parent = _create(
        client, headers, world.a1.client_id,
        code="6900", name="Software", account_type="expense",
    )
    child = _create(
        client, headers, world.a1.client_id,
        code="6910", name="Licences", account_type="expense",
        parent_account_id=parent["id"],
    )
    assert _by_code(client, headers, world.a1.client_id)["6900"]["is_leaf"] is False

    r = client.delete(_coa_url(world.a1.client_id, child["id"]), headers=headers)
    assert r.status_code == 204

    rows = _by_code(client, headers, world.a1.client_id)
    assert rows["6900"]["is_leaf"] is True
    assert rows["6900"]["child_count"] == 0


# --------------------------------------------------------------------------- #
# Type changes
# --------------------------------------------------------------------------- #
def test_retype_derives_normal_balance(client: TestClient, world) -> None:
    """normal_balance is derived, never supplied — so a retype must move it."""
    headers = _auth(client, "firm_staff", world.firm_a)
    acct = _create(
        client, headers, world.a1.client_id,
        code="7000", name="Mis-typed", account_type="expense",
    )
    assert acct["normal_balance"] == "debit"

    r = client.patch(
        _coa_url(world.a1.client_id, acct["id"]),
        headers=headers,
        json={"account_type": "revenue"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["account_type"] == "revenue"
    assert r.json()["normal_balance"] == "credit"


def test_create_ignores_caller_supplied_normal_balance(
    client: TestClient, world
) -> None:
    """Old clients still send normal_balance; it must not win over the rule."""
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(
        _coa_url(world.a1.client_id),
        headers=headers,
        json={
            "code": "7100",
            "name": "Consulting income",
            "account_type": "revenue",
            "normal_balance": "debit",  # wrong on purpose
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["normal_balance"] == "credit"


# --------------------------------------------------------------------------- #
# Access control
# --------------------------------------------------------------------------- #
def test_portal_user_cannot_update_or_delete(client: TestClient, world) -> None:
    firm_headers = _auth(client, "firm_staff", world.firm_a)
    acct = _create(
        client, firm_headers, world.a1.client_id,
        code="7200", name="Portal probe", account_type="expense",
    )
    portal = _auth(client, "client_portal", world.firm_a, world.a1.client_id)

    r = client.patch(
        _coa_url(world.a1.client_id, acct["id"]),
        headers=portal,
        json={"name": "Renamed by portal"},
    )
    assert r.status_code == 403

    r = client.delete(_coa_url(world.a1.client_id, acct["id"]), headers=portal)
    assert r.status_code == 403


def test_cannot_touch_another_clients_account(client: TestClient, world) -> None:
    """a2's account is not reachable through a1's URL."""
    headers = _auth(client, "firm_staff", world.firm_a)
    other = _by_code(client, headers, world.a2.client_id)["1000"]

    r = client.patch(
        _coa_url(world.a1.client_id, other["id"]),
        headers=headers,
        json={"name": "Cross-tenant rename"},
    )
    assert r.status_code == 404

    r = client.delete(_coa_url(world.a1.client_id, other["id"]), headers=headers)
    assert r.status_code == 404
