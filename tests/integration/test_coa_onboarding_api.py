"""Integration tests for the COA template onboarding endpoints.

Covers:
  * GET /clients/coa-templates (firm-only, status filter)
  * POST /clients/{id}/coa/instantiate (firm-only, 412 if no active template,
    409 on second call, 403 for portal scope)
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import tenant_session
from app.db.tenant import AccessScope
from app.domain.coa_templates import activate_template
from app.main import create_app
from app.models.coa_template import CoaTemplate
from app.models.enums import CoaTemplateStatus, Industry
from app.security.auth import reset_identity_provider
from tests.conftest import ctx_firm


@pytest.fixture(autouse=True)
def _reset_identity():
    reset_identity_provider()
    yield
    reset_identity_provider()


@pytest.fixture
def api_client() -> TestClient:
    return TestClient(create_app())


def _auth(api_client: TestClient, role: str, firm_id, client_id=None) -> dict:
    body = {"sub": "tester", "role": role, "firm_id": str(firm_id)}
    if client_id is not None:
        body["client_id"] = str(client_id)
    resp = api_client.post("/auth/dev-token", json=body)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _activate_general_and_overlay(firm_id, industry: Industry) -> None:
    with tenant_session(ctx_firm(firm_id)) as sess:
        general = sess.execute(
            select(CoaTemplate).where(CoaTemplate.key == "general").limit(1)
        ).scalar_one()
        activate_template(
            sess,
            firm_id=firm_id,
            actor="api-test",
            scope=AccessScope.FIRM,
            template_id=general.id,
        )
        ov = sess.execute(
            select(CoaTemplate).where(
                CoaTemplate.key == f"industry:{industry.value}"
            )
        ).scalar_one()
        activate_template(
            sess,
            firm_id=firm_id,
            actor="api-test",
            scope=AccessScope.FIRM,
            template_id=ov.id,
        )


# --------------------------------------------------------------------------- #
# GET /clients/coa-templates
# --------------------------------------------------------------------------- #
def test_list_templates_firm_staff_ok(api_client: TestClient, world) -> None:
    headers = _auth(api_client, "firm_staff", world.firm_a)
    r = api_client.get("/clients/coa-templates", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    keys = {t["key"] for t in body}
    assert "general" in keys
    assert any(k.startswith("industry:") for k in keys)


def test_list_templates_portal_forbidden(api_client: TestClient, world) -> None:
    headers = _auth(
        api_client, "client_portal", world.firm_a, world.a1.client_id
    )
    r = api_client.get("/clients/coa-templates", headers=headers)
    assert r.status_code == 403, r.text


def test_list_templates_status_filter(api_client: TestClient, world) -> None:
    headers = _auth(api_client, "firm_staff", world.firm_a)
    r = api_client.get(
        "/clients/coa-templates?status_filter=draft", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert all(t["status"] == "draft" for t in body)


def test_list_templates_invalid_status_filter(
    api_client: TestClient, world
) -> None:
    headers = _auth(api_client, "firm_staff", world.firm_a)
    r = api_client.get(
        "/clients/coa-templates?status_filter=bogus", headers=headers
    )
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# POST /clients/coa-templates/{id}/activate
# --------------------------------------------------------------------------- #
def test_activate_template_endpoint_flips_draft_to_active(
    api_client: TestClient, world
) -> None:
    """The CPA sign-off that unblocks onboarding is reachable over HTTP.

    Without this endpoint a fresh deployment can never onboard anyone: every
    template ships as DRAFT and there'd be no way to approve one.
    """
    headers = _auth(api_client, "firm_staff", world.firm_a)
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        general = sess.execute(
            select(CoaTemplate).where(CoaTemplate.key == "general").limit(1)
        ).scalar_one()
        general.status = CoaTemplateStatus.DRAFT
        general.activated_at = None
        general.activated_by = None
        sess.flush()
        template_id = str(general.id)

    r = api_client.post(
        f"/clients/coa-templates/{template_id}/activate", headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"

    # Idempotent — activating again is a no-op, not a 409.
    r2 = api_client.post(
        f"/clients/coa-templates/{template_id}/activate", headers=headers
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "active"


def test_activate_template_portal_forbidden(
    api_client: TestClient, world
) -> None:
    headers = _auth(
        api_client, "client_portal", world.firm_a, world.a1.client_id
    )
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        general = sess.execute(
            select(CoaTemplate).where(CoaTemplate.key == "general").limit(1)
        ).scalar_one()
        template_id = str(general.id)
    r = api_client.post(
        f"/clients/coa-templates/{template_id}/activate", headers=headers
    )
    assert r.status_code == 403, r.text


def test_activate_unknown_template_404(api_client: TestClient, world) -> None:
    headers = _auth(api_client, "firm_staff", world.firm_a)
    r = api_client.post(
        f"/clients/coa-templates/{uuid4()}/activate", headers=headers
    )
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- #
# POST /clients/{id}/coa/instantiate
# --------------------------------------------------------------------------- #
def test_instantiate_endpoint_creates_rows(
    api_client: TestClient, world
) -> None:
    _activate_general_and_overlay(world.firm_a, Industry.RETAIL_ECOMMERCE)
    # Use a fresh client so we don't trip on pre-seeded flat COA rows.
    from app.models.accounting import Client
    new_id = uuid4()
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        sess.add(Client(id=new_id, firm_id=world.firm_a, name="retail co"))

    headers = _auth(api_client, "firm_staff", world.firm_a)
    r = api_client.post(
        f"/clients/{new_id}/coa/instantiate",
        json={"industry": "retail_ecommerce"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["industry"] == "retail_ecommerce"
    assert body["created_count"] > 0
    assert body["general_template_id"]
    assert body["overlay_template_id"]


def test_instantiate_endpoint_portal_forbidden(
    api_client: TestClient, world
) -> None:
    _activate_general_and_overlay(world.firm_a, Industry.GENERIC)
    headers = _auth(
        api_client, "client_portal", world.firm_a, world.a1.client_id
    )
    r = api_client.post(
        f"/clients/{world.a1.client_id}/coa/instantiate",
        json={"industry": "generic"},
        headers=headers,
    )
    assert r.status_code == 403


def test_instantiate_endpoint_second_call_409(
    api_client: TestClient, world
) -> None:
    _activate_general_and_overlay(world.firm_a, Industry.PROFESSIONAL_SERVICES)
    from app.models.accounting import Client
    new_id = uuid4()
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        sess.add(Client(id=new_id, firm_id=world.firm_a, name="prof co"))

    headers = _auth(api_client, "firm_staff", world.firm_a)
    r1 = api_client.post(
        f"/clients/{new_id}/coa/instantiate",
        json={"industry": "professional_services"},
        headers=headers,
    )
    assert r1.status_code == 201, r1.text

    r2 = api_client.post(
        f"/clients/{new_id}/coa/instantiate",
        json={"industry": "professional_services"},
        headers=headers,
    )
    assert r2.status_code == 409, r2.text
