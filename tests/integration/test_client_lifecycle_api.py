"""Archive / restore / delete for clients.

Archive is the reversible everyday action; delete is reserved for a client
created by mistake that never got any books.
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


def _post_entry(client: TestClient, headers: dict, seeded) -> None:
    """Give a client one real journal entry so it is no longer deletable."""
    r = client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(seeded.client_id),
            "period_id": str(seeded.period_id),
            "entry_date": date(2026, 3, 1).isoformat(),
            "memo": "seed",
            "lines": [
                {"account_id": str(seeded.cash_account_id), "debit": "100.00"},
                {"account_id": str(seeded.revenue_account_id), "credit": "100.00"},
            ],
        },
    )
    assert r.status_code in (200, 201), r.text


# --------------------------------------------------------------------------- #
# Archive / restore
# --------------------------------------------------------------------------- #
def test_archived_client_is_hidden_from_the_list(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)

    r = client.post(f"/clients/{world.a1.client_id}/archive", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_active"] is False
    assert body["archived_at"] is not None

    ids = {c["id"] for c in client.get("/clients", headers=headers).json()}
    assert str(world.a1.client_id) not in ids
    assert str(world.a2.client_id) in ids

    ids = {
        c["id"]
        for c in client.get(
            "/clients", headers=headers, params={"include_archived": True}
        ).json()
    }
    assert str(world.a1.client_id) in ids


def test_archive_is_idempotent_and_restore_reverses_it(
    client: TestClient, world
) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    path = f"/clients/{world.a1.client_id}"

    assert client.post(f"{path}/archive", headers=headers).status_code == 200
    again = client.post(f"{path}/archive", headers=headers)
    assert again.status_code == 200
    assert again.json()["is_active"] is False

    restored = client.post(f"{path}/restore", headers=headers)
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_active"] is True
    assert restored.json()["archived_at"] is None

    ids = {c["id"] for c in client.get("/clients", headers=headers).json()}
    assert str(world.a1.client_id) in ids


def test_archiving_keeps_the_books(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    _post_entry(client, headers, world.a1)

    assert (
        client.post(f"/clients/{world.a1.client_id}/archive", headers=headers).status_code
        == 200
    )

    # The entry is still readable through the client-scoped endpoint.
    r = client.get(
        "/journal-entries",
        headers=headers,
        params={"client_id": str(world.a1.client_id)},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) >= 1


def test_posting_to_an_archived_client_is_rejected(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    assert (
        client.post(f"/clients/{world.a1.client_id}/archive", headers=headers).status_code
        == 200
    )

    r = client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "entry_date": date(2026, 3, 1).isoformat(),
            "lines": [
                {"account_id": str(world.a1.cash_account_id), "debit": "10.00"},
                {"account_id": str(world.a1.revenue_account_id), "credit": "10.00"},
            ],
        },
    )
    assert r.status_code == 409, r.text
    assert "archived" in r.json()["detail"].lower()


def test_restored_client_accepts_postings_again(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    path = f"/clients/{world.a1.client_id}"
    client.post(f"{path}/archive", headers=headers)
    client.post(f"{path}/restore", headers=headers)
    _post_entry(client, headers, world.a1)


def test_archive_requires_firm_scope(client: TestClient, world) -> None:
    headers = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    r = client.post(f"/clients/{world.a1.client_id}/archive", headers=headers)
    assert r.status_code == 403


def test_archive_across_firms_is_404(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.post(f"/clients/{world.b1.client_id}/archive", headers=headers)
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Deletability probe
# --------------------------------------------------------------------------- #
def test_deletability_is_true_for_a_client_with_no_books(
    client: TestClient, world
) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.get(f"/clients/{world.a1.client_id}/deletability", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["client_id"] == str(world.a1.client_id)
    assert body["can_delete"] is True
    assert body["blocking_counts"] == {}


def test_deletability_names_what_is_blocking(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    _post_entry(client, headers, world.a1)

    body = client.get(
        f"/clients/{world.a1.client_id}/deletability", headers=headers
    ).json()
    assert body["can_delete"] is False
    assert body["blocking_counts"]["journal entry"] == 1


# --------------------------------------------------------------------------- #
# Delete
# --------------------------------------------------------------------------- #
def test_delete_removes_a_client_created_by_mistake(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    created = client.post(
        "/clients", headers=headers, json={"name": "Typo Co", "external_code": "OOPS"}
    )
    assert created.status_code == 201, created.text
    new_id = created.json()["id"]

    r = client.delete(f"/clients/{new_id}", headers=headers)
    assert r.status_code == 204, r.text

    assert client.get(f"/clients/{new_id}", headers=headers).status_code == 404
    ids = {
        c["id"]
        for c in client.get(
            "/clients", headers=headers, params={"include_archived": True}
        ).json()
    }
    assert new_id not in ids


def test_delete_takes_the_seeded_chart_with_it(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    # a1 comes with a chart of accounts and a period but no entries.
    coa = client.get(
        f"/clients/{world.a1.client_id}/chart-of-accounts", headers=headers
    )
    assert coa.status_code == 200 and len(coa.json()) > 0

    assert client.delete(f"/clients/{world.a1.client_id}", headers=headers).status_code == 204
    assert (
        client.get(f"/clients/{world.a1.client_id}/chart-of-accounts", headers=headers).status_code
        == 404
    )


def test_delete_refuses_a_client_with_books(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    _post_entry(client, headers, world.a1)

    r = client.delete(f"/clients/{world.a1.client_id}", headers=headers)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "1 journal entry" in detail
    assert "archive" in detail.lower()

    # Still there.
    assert client.get(f"/clients/{world.a1.client_id}", headers=headers).status_code == 200


def test_delete_across_firms_is_404(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    r = client.delete(f"/clients/{world.b1.client_id}", headers=headers)
    assert r.status_code == 404

    other = _auth(client, "firm_staff", world.firm_b)
    assert client.get(f"/clients/{world.b1.client_id}", headers=other).status_code == 200


def test_delete_requires_firm_scope(client: TestClient, world) -> None:
    headers = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    r = client.delete(f"/clients/{world.a1.client_id}", headers=headers)
    assert r.status_code == 403


def test_delete_unknown_client_is_404(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a)
    assert client.delete(f"/clients/{uuid4()}", headers=headers).status_code == 404
