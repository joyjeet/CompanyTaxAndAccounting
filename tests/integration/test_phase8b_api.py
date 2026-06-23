"""Phase 8b API integration tests:
  * GET/PUT /clients/{id}/profile
  * POST /tax/worksheets — fail-closed (needs_ruleset) and ruleset-gated
  * POST /tax/worksheets/{id}/reject
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import tenant_session
from app.db.tenant import AccessScope
from app.domain.entity_form_ruleset import activate_ruleset
from app.domain.tax_service import (
    MappingProposal,
    approve_mapping,
    approve_worksheet,
    generate_worksheet,
    get_form_by_code,
    propose_mapping,
)
from app.domain.ledger import LedgerService, LineInput
from app.main import create_app
from app.models.accounting import ChartOfAccounts, TaxFormLine
from app.models.entity_form_ruleset import EntityFormRuleset
from app.models.enums import (
    EntityFormRulesetStatus,
    TaxFormCode,
    TaxLineSign,
    TaxWorksheetStatus,
)
from app.security.auth import reset_identity_provider
from tests.conftest import SeededClient, ctx_firm, ctx_firm_for_client


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


def _activate_seeded_ruleset(firm_id, entity_type: str) -> None:
    with tenant_session(ctx_firm(firm_id)) as sess:
        r = sess.execute(
            select(EntityFormRuleset).where(
                EntityFormRuleset.entity_type == entity_type,
                EntityFormRuleset.tax_year == 2025,
                EntityFormRuleset.status == EntityFormRulesetStatus.DRAFT,
            )
        ).scalar_one()
        activate_ruleset(
            sess,
            firm_id=firm_id, actor="api-test", scope=AccessScope.FIRM,
            ruleset_id=r.id,
        )


# --------------------------------------------------------------------------- #
# GET/PUT /clients/{id}/profile
# --------------------------------------------------------------------------- #
def test_get_profile_404_when_unset(api_client: TestClient, world) -> None:
    headers = _auth(api_client, "firm_staff", world.firm_a)
    r = api_client.get(f"/clients/{world.a1.client_id}/profile", headers=headers)
    assert r.status_code == 404


def test_put_profile_then_get_round_trip(api_client: TestClient, world) -> None:
    headers = _auth(api_client, "firm_staff", world.firm_a)
    payload = {
        "entity_type": "c_corp",
        "tax_year": 2025,
        "industry": "professional_services",
        "home_state": "ca",
        "additional_states": ["ny"],
        "fiscal_year_end_month": 12,
        "entity_attributes": {"ein_on_file": True},
    }
    r = api_client.put(
        f"/clients/{world.a1.client_id}/profile",
        headers=headers, json=payload,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_type"] == "c_corp"
    assert body["home_state"] == "CA"  # normalized
    assert body["additional_states"] == ["NY"]

    r = api_client.get(
        f"/clients/{world.a1.client_id}/profile", headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["entity_type"] == "c_corp"


def test_put_profile_accepts_portal_self_edit(
    api_client: TestClient, world
) -> None:
    """Phase 8c: a client portal user can update their own profile
    (entity type self-attestation + contact info). RLS still ensures
    they cannot reach another client's profile.
    """
    headers = _auth(
        api_client, "client_portal", world.firm_a, world.a1.client_id,
    )
    r = api_client.put(
        f"/clients/{world.a1.client_id}/profile",
        headers=headers,
        json={
            "entity_type": "s_corp",
            "tax_year": 2025,
            "business_legal_name": "Acme LLC",
            "phone": "555-987-6543",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_type"] == "s_corp"
    assert body["business_legal_name"] == "Acme LLC"
    assert body["phone"] == "555-987-6543"


def test_put_profile_validation_error(api_client: TestClient, world) -> None:
    headers = _auth(api_client, "firm_staff", world.firm_a)
    r = api_client.put(
        f"/clients/{world.a1.client_id}/profile",
        headers=headers,
        json={"entity_type": "not_a_real_type", "tax_year": 2025},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# POST /tax/worksheets — fail-closed when no ruleset
# --------------------------------------------------------------------------- #
def _post_baseline_and_map(sc: SeededClient) -> None:
    """Post one rev + one expense entry, then propose+approve both mappings.

    Leaves the worksheet ungenerated so the API call is what creates it.
    """
    from datetime import date
    from decimal import Decimal as _D
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        rev = sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.client_id == sc.client_id,
                ChartOfAccounts.code == "4000",
            )
        ).scalar_one()
        cash = sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.client_id == sc.client_id,
                ChartOfAccounts.code == "1000",
            )
        ).scalar_one()
        exp = sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.client_id == sc.client_id,
                ChartOfAccounts.code == "5000",
            )
        ).scalar_one()
        led = LedgerService(
            sess, firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
        )
        led.post(
            memo="rev",
            entry_date=date(2026, 6, 1),
            period_id=sc.period_id,
            lines=[
                LineInput(account_id=cash.id, debit=_D("1000")),
                LineInput(account_id=rev.id, credit=_D("1000")),
            ],
        )
        led.post(
            memo="exp",
            entry_date=date(2026, 6, 1),
            period_id=sc.period_id,
            lines=[
                LineInput(account_id=exp.id, debit=_D("300")),
                LineInput(account_id=cash.id, credit=_D("300")),
            ],
        )

        form = get_form_by_code(sess, TaxFormCode.F1120)
        rev_line = sess.execute(
            select(TaxFormLine).where(
                TaxFormLine.form_id == form.id, TaxFormLine.code == "1a",
            )
        ).scalar_one()
        ded_line = sess.execute(
            select(TaxFormLine).where(
                TaxFormLine.form_id == form.id, TaxFormLine.code != "1a",
            ).limit(1)
        ).scalar_one()
        for acct, line in ((rev, rev_line), (exp, ded_line)):
            m = propose_mapping(
                sess,
                firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
                scope=AccessScope.FIRM,
                form_id=form.id,
                proposal=MappingProposal(
                    account_id=acct.id, line_id=line.id,
                    sign=TaxLineSign.POSITIVE,
                ),
            )
            approve_mapping(
                sess,
                firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
                scope=AccessScope.FIRM, mapping_id=m.id,
            )


def test_generate_endpoint_fails_closed_without_ruleset(
    api_client: TestClient, world,
) -> None:
    sc = world.a1
    _post_baseline_and_map(sc)
    headers = _auth(
        api_client, "firm_staff", world.firm_a, sc.client_id,
    )

    # Client has no profile yet → 409 needs_ruleset.
    r = api_client.post(
        "/tax/worksheets",
        headers=headers,
        json={
            "form_code": "F1120",
            "period_id": str(sc.period_id),
        },
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "needs_ruleset"


def test_generate_endpoint_rejects_form_not_in_ruleset(
    api_client: TestClient, world,
) -> None:
    """If the client's ruleset doesn't include F1120 (e.g. they're S-corp),
    requesting F1120 should 422 with the allowed_forms list."""
    sc = world.a1
    _post_baseline_and_map(sc)

    # Make this client an S-corp so their ruleset returns [F1120S], not F1120.
    scoped_headers = _auth(
        api_client, "firm_staff", world.firm_a, sc.client_id,
    )
    pr = api_client.put(
        f"/clients/{sc.client_id}/profile",
        headers=scoped_headers,
        json={"entity_type": "s_corp", "tax_year": 2025},
    )
    assert pr.status_code == 200, pr.text
    _activate_seeded_ruleset(world.firm_a, "s_corp")

    r = api_client.post(
        "/tax/worksheets",
        headers=scoped_headers,
        json={
            "form_code": "F1120",
            "period_id": str(sc.period_id),
        },
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "F1120S" in detail["allowed_forms"]


def test_generate_endpoint_succeeds_with_active_ruleset(
    api_client: TestClient, world,
) -> None:
    sc = world.a1
    _post_baseline_and_map(sc)
    scoped_headers = _auth(
        api_client, "firm_staff", world.firm_a, sc.client_id,
    )
    pr = api_client.put(
        f"/clients/{sc.client_id}/profile",
        headers=scoped_headers,
        json={"entity_type": "c_corp", "tax_year": 2025},
    )
    assert pr.status_code == 200, pr.text
    _activate_seeded_ruleset(world.firm_a, "c_corp")

    r = api_client.post(
        "/tax/worksheets",
        headers=scoped_headers,
        json={
            "form_code": "F1120",
            "period_id": str(sc.period_id),
        },
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["status"] == "computed"


# --------------------------------------------------------------------------- #
# POST /tax/worksheets/{id}/reject
# --------------------------------------------------------------------------- #
def test_reject_worksheet_endpoint(api_client: TestClient, world) -> None:
    sc = world.a1
    _post_baseline_and_map(sc)

    # Generate a worksheet via the domain so we have an id.
    with tenant_session(ctx_firm_for_client(sc.firm_id, sc.client_id)) as sess:
        ws = generate_worksheet(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
            scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1120, period_id=sc.period_id,
        )
        ws_id = ws.id

    headers = _auth(
        api_client, "firm_staff", world.firm_a, sc.client_id,
    )
    r = api_client.post(
        f"/tax/worksheets/{ws_id}/reject",
        headers=headers,
        json={"reason": "looks wrong"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
