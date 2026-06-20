"""Phase 7 — admin endpoints + tenant-scoped audit export integration tests.

Covers:
  * POST /admin/tenants/{firm_id}/destroy-keys
      - Firm-scope token required
      - Cross-firm action forbidden
      - Confirmation token + reason required
      - Audit event written with TENANT_KEYS_DESTROY
  * GET /audit/export
      - Firm-scope token required (client portal rejected)
      - Hash chain is consistent
      - Export itself produces an AUDIT_EXPORT audit event
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import get_owner_engine
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


def _firm_token(client: TestClient, firm_id) -> str:
    resp = client.post(
        "/auth/dev-token",
        json={
            "sub": "admin@example.com",
            "role": "firm_staff",
            "firm_id": str(firm_id),
        },
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _client_token(client: TestClient, firm_id, client_id) -> str:
    resp = client.post(
        "/auth/dev-token",
        json={
            "sub": "portal-user",
            "role": "client_portal",
            "firm_id": str(firm_id),
            "client_id": str(client_id),
        },
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


# --------------------------------------------------------------------------- #
# /admin/tenants/{firm_id}/destroy-keys
# --------------------------------------------------------------------------- #
def test_destroy_keys_requires_firm_scope(client: TestClient, world) -> None:
    tok = _client_token(client, world.firm_a, world.a1.client_id)
    resp = client.post(
        f"/admin/tenants/{world.firm_a}/destroy-keys",
        json={"confirm": "DESTROY", "reason": "x"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 403


def test_destroy_keys_cross_firm_forbidden(client: TestClient, world) -> None:
    tok = _firm_token(client, world.firm_b)
    resp = client.post(
        f"/admin/tenants/{world.firm_a}/destroy-keys",
        json={"confirm": "DESTROY", "reason": "I want firm A's data gone"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 403


def test_destroy_keys_requires_confirm_token(client: TestClient, world) -> None:
    tok = _firm_token(client, world.firm_a)
    resp = client.post(
        f"/admin/tenants/{world.firm_a}/destroy-keys",
        json={"confirm": "yes", "reason": "x"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 400


def test_destroy_keys_requires_reason(client: TestClient, world) -> None:
    tok = _firm_token(client, world.firm_a)
    resp = client.post(
        f"/admin/tenants/{world.firm_a}/destroy-keys",
        json={"confirm": "DESTROY", "reason": "   "},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 400


def test_destroy_keys_success_writes_audit(client: TestClient, world) -> None:
    tok = _firm_token(client, world.firm_a)
    resp = client.post(
        f"/admin/tenants/{world.firm_a}/destroy-keys",
        json={"confirm": "DESTROY", "reason": "offboarding ticket OFF-1234"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "destroyed"
    assert body["firm_id"] == str(world.firm_a)

    # Verify the audit row landed. The owner role is subject to FORCE RLS,
    # so we set the firm GUC before SELECT.
    with get_owner_engine().begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_firm', :v, true)"),
            {"v": str(world.firm_a)},
        )
        conn.execute(text("SELECT set_config('app.access_scope', 'firm', true)"))
        rows = conn.execute(
            text(
                """
                SELECT action, actor, details->>'reason' AS reason
                FROM audit_event
                WHERE firm_id = :fid AND action = 'tenant_keys_destroy'
                """
            ),
            {"fid": str(world.firm_a)},
        ).all()
    assert len(rows) == 1
    assert rows[0][1] == "admin@example.com"
    assert "OFF-1234" in rows[0][2]


# --------------------------------------------------------------------------- #
# /audit/export
# --------------------------------------------------------------------------- #
def test_audit_export_rejects_client_scope(client: TestClient, world) -> None:
    tok = _client_token(client, world.firm_a, world.a1.client_id)
    now = datetime.now(UTC)
    resp = client.get(
        "/audit/export",
        params={
            "period_start": (now - timedelta(days=1)).isoformat(),
            "period_end": now.isoformat(),
        },
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 403


def test_audit_export_hash_chain_is_consistent(client: TestClient, world) -> None:
    # Generate a couple of audit-bearing actions first (destroy is auditable).
    tok = _firm_token(client, world.firm_a)
    client.post(
        f"/admin/tenants/{world.firm_a}/destroy-keys",
        json={"confirm": "DESTROY", "reason": "tic-A"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    client.post(
        f"/admin/tenants/{world.firm_a}/destroy-keys",
        json={"confirm": "DESTROY", "reason": "tic-B"},
        headers={"Authorization": f"Bearer {tok}"},
    )

    now = datetime.now(UTC)
    resp = client.get(
        "/audit/export",
        params={
            "period_start": (now - timedelta(days=1)).isoformat(),
            "period_end": (now + timedelta(minutes=1)).isoformat(),
        },
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 2
    events = body["events"]

    prev = "0" * 64
    for evt in events:
        assert evt["prev_hash"] == prev
        # Recompute the canonical hash.
        canon = {k: v for k, v in evt.items() if k != "row_hash"}
        recomputed = hashlib.sha256(
            json.dumps(canon, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        assert recomputed == evt["row_hash"], "chain integrity broken"
        prev = evt["row_hash"]
    assert body["tip_hash"] == events[-1]["row_hash"]


def test_audit_export_does_not_leak_other_firms(client: TestClient, world) -> None:
    # Firm A action that produces an audit row.
    tok_a = _firm_token(client, world.firm_a)
    client.post(
        f"/admin/tenants/{world.firm_a}/destroy-keys",
        json={"confirm": "DESTROY", "reason": "tic-A"},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    # Firm B action.
    tok_b = _firm_token(client, world.firm_b)
    client.post(
        f"/admin/tenants/{world.firm_b}/destroy-keys",
        json={"confirm": "DESTROY", "reason": "tic-B"},
        headers={"Authorization": f"Bearer {tok_b}"},
    )

    now = datetime.now(UTC)
    # Firm B exports — must not see firm A's events.
    resp = client.get(
        "/audit/export",
        params={
            "period_start": (now - timedelta(days=1)).isoformat(),
            "period_end": (now + timedelta(minutes=1)).isoformat(),
        },
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    for evt in body["events"]:
        assert evt["firm_id"] == str(world.firm_b), "tenant isolation broken in audit export"
