"""API tests for Phase 4 additions: /auth/dev-token and GET /documents."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.security.auth import mint_test_token, reset_identity_provider


@pytest.fixture(autouse=True)
def _reset_identity():
    reset_identity_provider()
    yield
    reset_identity_provider()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


# --------------------------------------------------------------------------- #
# /auth/dev-token
# --------------------------------------------------------------------------- #
def test_dev_token_mints_firm_token(client: TestClient, world) -> None:
    resp = client.post(
        "/auth/dev-token",
        json={
            "sub": "alice@example.com",
            "role": "firm_staff",
            "firm_id": str(world.firm_a),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    # Token must be acceptable to the live API.
    auth = {"Authorization": f"Bearer {body['access_token']}"}
    listed = client.get("/clients", headers=auth)
    assert listed.status_code == 200, listed.text
    # firm A has 2 seeded clients.
    assert len(listed.json()) == 2


def test_dev_token_mints_client_token(client: TestClient, world) -> None:
    resp = client.post(
        "/auth/dev-token",
        json={
            "sub": "client-bob",
            "role": "client_portal",
            "firm_id": str(world.firm_a),
            "client_id": str(world.a1.client_id),
        },
    )
    assert resp.status_code == 200
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    listed = client.get("/clients", headers=auth)
    assert listed.status_code == 200
    # Portal user sees only their own client.
    assert {c["id"] for c in listed.json()} == {str(world.a1.client_id)}


def test_dev_token_client_role_requires_client_id(client: TestClient) -> None:
    resp = client.post(
        "/auth/dev-token",
        json={
            "sub": "x",
            "role": "client_portal",
            "firm_id": str(uuid4()),
        },
    )
    assert resp.status_code == 400


def test_dev_login_options_lists_firms_and_clients(client: TestClient, world) -> None:
    resp = client.get("/auth/dev-login-options")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "firms" in body
    # World fixture seeds 2 firms total.
    assert len(body["firms"]) >= 2
    # At least one firm contains client options.
    assert any(len(f.get("clients", [])) > 0 for f in body["firms"])


def test_dev_token_can_default_firm_and_client_ids(client: TestClient, world) -> None:
    # No firm_id/client_id in request body.
    resp = client.post(
        "/auth/dev-token",
        json={
            "sub": "auto-resolve-user",
            "role": "client_portal",
        },
    )
    assert resp.status_code == 200, resp.text
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    listed = client.get("/clients", headers=auth)
    assert listed.status_code == 200, listed.text
    # Client portal token should be scoped to exactly one client.
    assert len(listed.json()) == 1


def test_dev_token_rejects_unknown_role(client: TestClient) -> None:
    resp = client.post(
        "/auth/dev-token",
        json={"sub": "x", "role": "janitor", "firm_id": str(uuid4())},
    )
    # pydantic Literal validation -> 422
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# GET /documents
# --------------------------------------------------------------------------- #
def test_get_documents_requires_auth(client: TestClient) -> None:
    resp = client.get("/documents")
    assert resp.status_code == 401


def test_get_documents_returns_only_visible_docs(
    client: TestClient, world, fake_integrations
) -> None:
    """Firm A staff can see firm A's docs; firm B's are invisible. Portal
    users see only their own client's."""
    # Seed: upload one doc for each client of firm A, and one for firm B.
    a1_token = mint_test_token(
        sub="firm-a-staff", firm_id=world.firm_a, role="firm_staff",
        client_id=world.a1.client_id,
    )
    a2_token = mint_test_token(
        sub="firm-a-staff", firm_id=world.firm_a, role="firm_staff",
        client_id=world.a2.client_id,
    )
    b1_token = mint_test_token(
        sub="firm-b-staff", firm_id=world.firm_b, role="firm_staff",
        client_id=world.b1.client_id,
    )
    for tok, name in ((a1_token, "a1.pdf"), (a2_token, "a2.pdf"), (b1_token, "b1.pdf")):
        r = client.post(
            "/documents/upload",
            headers={"Authorization": f"Bearer {tok}"},
            files={"file": (name, b"hello %s" % name.encode(), "application/pdf")},
            data={"kind_hint": "generic"},
        )
        assert r.status_code == 201, r.text

    # Firm A staff scoped to client a1 — sees only a1.pdf via RLS.
    listed = client.get(
        "/documents", headers={"Authorization": f"Bearer {a1_token}"}
    ).json()
    assert {d["filename"] for d in listed} == {"a1.pdf"}

    # Firm B staff sees only b1.pdf.
    listed_b = client.get(
        "/documents", headers={"Authorization": f"Bearer {b1_token}"}
    ).json()
    assert {d["filename"] for d in listed_b} == {"b1.pdf"}

    # Portal user for client a1 sees only a1.pdf.
    portal_token = mint_test_token(
        sub="portal-a1", firm_id=world.firm_a, role="client_portal",
        client_id=world.a1.client_id,
    )
    listed_portal = client.get(
        "/documents", headers={"Authorization": f"Bearer {portal_token}"}
    ).json()
    assert {d["filename"] for d in listed_portal} == {"a1.pdf"}


def test_document_kind_can_be_manually_corrected(
    client: TestClient, world, fake_integrations
) -> None:
    token = mint_test_token(
        sub="firm-a-editor",
        firm_id=world.firm_a,
        role="firm_staff",
        client_id=world.a1.client_id,
    )
    upload = client.post(
        "/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("doc.pdf", b"raw bytes", "application/pdf")},
        data={"kind_hint": "generic"},
    )
    assert upload.status_code == 201, upload.text
    doc_id = upload.json()["source_document_id"]

    updated = client.post(
        f"/documents/{doc_id}/kind",
        headers={"Authorization": f"Bearer {token}"},
        json={"kind": "invoice"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["kind"] == "invoice"

    listed = client.get(
        "/documents", headers={"Authorization": f"Bearer {token}"}
    )
    assert listed.status_code == 200
    assert listed.json()[0]["kind"] == "invoice"


def test_document_kind_update_rejects_unknown_kind(
    client: TestClient, world, fake_integrations
) -> None:
    token = mint_test_token(
        sub="firm-a-editor-2",
        firm_id=world.firm_a,
        role="firm_staff",
        client_id=world.a1.client_id,
    )
    upload = client.post(
        "/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("doc2.pdf", b"raw bytes 2", "application/pdf")},
        data={"kind_hint": "generic"},
    )
    assert upload.status_code == 201, upload.text
    doc_id = upload.json()["source_document_id"]

    bad = client.post(
        f"/documents/{doc_id}/kind",
        headers={"Authorization": f"Bearer {token}"},
        json={"kind": "bank_statement"},
    )
    assert bad.status_code == 400


def test_get_drafts_visible_to_client_portal(
    client: TestClient, world, fake_integrations
) -> None:
    """Phase 4 scope addition: client portal can READ its own drafts."""
    from app.workers.jobs import dispatch_payload

    # Upload a doc as the firm to drive the pipeline through extraction +
    # classification, then drain the in-memory queue to produce a draft.
    firm_token = mint_test_token(
        sub="firm-staff", firm_id=world.firm_a, role="firm_staff",
        client_id=world.a1.client_id,
    )
    r = client.post(
        "/documents/upload",
        headers={"Authorization": f"Bearer {firm_token}"},
        files={"file": ("w2.pdf", b"fake w2 bytes", "application/pdf")},
        data={"kind_hint": "w2"},
    )
    assert r.status_code == 201

    # Drain both queues end-to-end. Extract enqueues classify, so loop until
    # nothing new lands.
    queue = fake_integrations.queue
    while True:
        progressed = False
        for qname in ("extract", "classify"):
            items = queue.drain(qname)
            if items:
                progressed = True
                for _job_id, payload in items:
                    dispatch_payload(payload)
        if not progressed:
            break

    # Portal user for client a1: GET /drafts returns the one we just made.
    portal_token = mint_test_token(
        sub="portal", firm_id=world.firm_a, role="client_portal",
        client_id=world.a1.client_id,
    )
    drafts = client.get(
        "/drafts", headers={"Authorization": f"Bearer {portal_token}"}
    ).json()
    assert len(drafts) == 1

    # And: client cannot promote.
    promote = client.post(
        f"/drafts/{drafts[0]['id']}/promote",
        headers={"Authorization": f"Bearer {portal_token}"},
        json={
            "period_id": str(world.a1.period_id),
            "entry_date": "2026-06-15",
            "lines": [
                {"account_id": str(world.a1.expense_account_id), "debit": "10.00", "credit": "0"},
                {"account_id": str(world.a1.cash_account_id), "debit": "0", "credit": "10.00"},
            ],
        },
    )
    assert promote.status_code == 403


def test_cors_headers_present(client: TestClient) -> None:
    """Preflight from the configured frontend origin must be allowed."""
    resp = client.options(
        "/drafts",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    # 200 with allow-origin echoed, OR 204 — both are valid for CORS preflight.
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_firm_can_promote_with_client_id_in_body_when_token_has_no_client_id(
    client: TestClient,
    world,
    fake_integrations,
) -> None:
    from app.workers.jobs import dispatch_payload

    # 1) Upload + classify as firm scoped to client a1 so we get a draft.
    uploader_token = mint_test_token(
        sub="firm-uploader", firm_id=world.firm_a, role="firm_staff",
        client_id=world.a1.client_id,
    )
    r = client.post(
        "/documents/upload",
        headers={"Authorization": f"Bearer {uploader_token}"},
        files={"file": ("txn.pdf", b"bank transaction", "application/pdf")},
        data={"kind_hint": "bank_transaction"},
    )
    assert r.status_code == 201

    queue = fake_integrations.queue
    while True:
        progressed = False
        for qname in ("extract", "classify"):
            items = queue.drain(qname)
            if items:
                progressed = True
                for _job_id, payload in items:
                    dispatch_payload(payload)
        if not progressed:
            break

    drafts = client.get(
        "/drafts",
        headers={"Authorization": f"Bearer {uploader_token}"},
    ).json()
    assert drafts, "expected at least one draft"

    # 2) Promote with a firm token that has no client_id claim.
    no_client_token = mint_test_token(
        sub="firm-no-client", firm_id=world.firm_a, role="firm_staff",
    )
    promote = client.post(
        f"/drafts/{drafts[0]['id']}/promote",
        headers={"Authorization": f"Bearer {no_client_token}"},
        json={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "entry_date": "2026-06-15",
            "lines": [
                {
                    "account_id": str(world.a1.expense_account_id),
                    "debit": "10.00",
                    "credit": "0",
                },
                {
                    "account_id": str(world.a1.cash_account_id),
                    "debit": "0",
                    "credit": "10.00",
                },
            ],
        },
    )
    assert promote.status_code == 200, promote.text


def test_firm_can_promote_without_client_id_in_token_or_body_when_draft_exists(
    client: TestClient,
    world,
    fake_integrations,
) -> None:
    from app.workers.jobs import dispatch_payload

    uploader_token = mint_test_token(
        sub="firm-uploader-2", firm_id=world.firm_a, role="firm_staff",
        client_id=world.a1.client_id,
    )
    r = client.post(
        "/documents/upload",
        headers={"Authorization": f"Bearer {uploader_token}"},
        files={"file": ("txn2.pdf", b"bank transaction two", "application/pdf")},
        data={"kind_hint": "bank_transaction"},
    )
    assert r.status_code == 201

    queue = fake_integrations.queue
    while True:
        progressed = False
        for qname in ("extract", "classify"):
            items = queue.drain(qname)
            if items:
                progressed = True
                for _job_id, payload in items:
                    dispatch_payload(payload)
        if not progressed:
            break

    drafts = client.get(
        "/drafts",
        headers={"Authorization": f"Bearer {uploader_token}"},
    ).json()
    assert drafts, "expected at least one draft"

    no_client_token = mint_test_token(
        sub="firm-no-client-2", firm_id=world.firm_a, role="firm_staff",
    )
    promote = client.post(
        f"/drafts/{drafts[-1]['id']}/promote",
        headers={"Authorization": f"Bearer {no_client_token}"},
        json={
            "period_id": str(world.a1.period_id),
            "entry_date": "2026-06-15",
            "lines": [
                {
                    "account_id": str(world.a1.expense_account_id),
                    "debit": "10.00",
                    "credit": "0",
                },
                {
                    "account_id": str(world.a1.cash_account_id),
                    "debit": "0",
                    "credit": "10.00",
                },
            ],
        },
    )
    assert promote.status_code == 200, promote.text
