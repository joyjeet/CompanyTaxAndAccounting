from __future__ import annotations

from uuid import UUID

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


def _auth(
    client: TestClient,
    role: str,
    firm_id: UUID,
    *,
    sub: str,
    client_id: UUID | None = None,
) -> dict[str, str]:
    body: dict[str, object] = {
        "sub": sub,
        "role": role,
        "firm_id": str(firm_id),
        "expires_in_seconds": 3600,
    }
    if client_id is not None:
        body["client_id"] = str(client_id)
    resp = client.post("/auth/dev-token", json=body)
    assert resp.status_code == 200, resp.text
    tok = resp.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def test_team_members_bootstrap_for_firm_staff(client: TestClient, world) -> None:
    headers = _auth(client, "firm_staff", world.firm_a, sub="owner-a")

    resp = client.get("/team/members", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    members = body["members"]
    assert len(members) == 1
    assert members[0]["subject"] == "owner-a"
    assert members[0]["role"] == "firm_owner"
    assert members[0]["status"] == "active"


def test_team_members_reject_client_portal_scope(client: TestClient, world) -> None:
    headers = _auth(
        client,
        "client_portal",
        world.firm_a,
        sub="portal-a1",
        client_id=world.a1.client_id,
    )

    resp = client.get("/team/members", headers=headers)

    assert resp.status_code == 403, resp.text


def test_invite_create_accept_cancel_and_member_updates(client: TestClient, world) -> None:
    owner_headers = _auth(client, "firm_staff", world.firm_a, sub="owner-a")

    create_resp = client.post(
        "/team/invites",
        headers=owner_headers,
        json={"email": "manager@acme.test", "role": "manager", "expires_in_days": 7},
    )
    assert create_resp.status_code == 201, create_resp.text
    invite = create_resp.json()
    invite_id = invite["id"]
    invite_token = invite["invite_token"]

    manager_headers = _auth(client, "firm_staff", world.firm_a, sub="manager-a")
    accept_resp = client.post(
        "/team/invites/accept",
        headers=manager_headers,
        json={"token": invite_token},
    )
    assert accept_resp.status_code == 200, accept_resp.text
    member = accept_resp.json()
    assert member["role"] == "manager"
    assert member["subject"] == "manager-a"

    role_resp = client.post(
        f"/team/members/{member['id']}/role",
        headers=owner_headers,
        json={"role": "staff"},
    )
    assert role_resp.status_code == 200, role_resp.text
    assert role_resp.json()["role"] == "staff"

    status_resp = client.post(
        f"/team/members/{member['id']}/status",
        headers=owner_headers,
        json={"status": "disabled"},
    )
    assert status_resp.status_code == 200, status_resp.text
    assert status_resp.json()["status"] == "disabled"

    cancel_resp = client.post(
        f"/team/invites/{invite_id}/cancel",
        headers=owner_headers,
    )
    assert cancel_resp.status_code == 400, cancel_resp.text



def test_non_admin_member_cannot_create_invites(client: TestClient, world) -> None:
    owner_headers = _auth(client, "firm_staff", world.firm_a, sub="owner-a")

    create_resp = client.post(
        "/team/invites",
        headers=owner_headers,
        json={"email": "staff@acme.test", "role": "staff", "expires_in_days": 7},
    )
    assert create_resp.status_code == 201, create_resp.text
    invite_token = create_resp.json()["invite_token"]

    staff_headers = _auth(client, "firm_staff", world.firm_a, sub="staff-a")
    accept_resp = client.post(
        "/team/invites/accept",
        headers=staff_headers,
        json={"token": invite_token},
    )
    assert accept_resp.status_code == 200, accept_resp.text

    forbidden = client.post(
        "/team/invites",
        headers=staff_headers,
        json={"email": "x@acme.test", "role": "read_only", "expires_in_days": 7},
    )
    assert forbidden.status_code == 403, forbidden.text
