"""Integration tests for the ClientProfile + EntityFormRuleset domain
services (Phase 8b).

Covers:
  * ClientProfile upsert / get + validation + RLS isolation
  * Portal scope cannot upsert
  * EntityFormRuleset activation + supersession
  * get_form_set_for_client happy path and fail-closed semantics
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import tenant_session
from app.db.tenant import AccessScope
from app.domain.client_profile import (
    ClientProfileForbiddenError,
    ClientProfileValidationError,
    get_profile_for_client,
    upsert_profile,
)
from app.domain.entity_form_ruleset import (
    NeedsRulesetError,
    activate_ruleset,
    get_form_set_for_client,
)
from app.models.client_profile import ClientProfile
from app.models.entity_form_ruleset import EntityFormRuleset
from app.models.enums import (
    EntityFormRulesetStatus,
    EntityType,
    Industry,
    TaxFormCode,
)
from tests.conftest import ctx_client, ctx_firm, ctx_firm_for_client


# --------------------------------------------------------------------------- #
# ClientProfile
# --------------------------------------------------------------------------- #
def test_upsert_creates_then_updates(world) -> None:
    firm = world.firm_a
    client = world.a1.client_id

    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        row = upsert_profile(
            sess,
            firm_id=firm, client_id=client,
            actor="cpa@firm.test", scope=AccessScope.FIRM,
            entity_type=EntityType.C_CORP, tax_year=2025,
            industry=Industry.PROFESSIONAL_SERVICES,
            home_state="ca",
            additional_states=["ny", "tx"],
            fiscal_year_end_month=12,
            entity_attributes={"ein_on_file": True},
        )
        assert row.entity_type == "c_corp"
        assert row.home_state == "CA"
        assert row.additional_states == ["NY", "TX"]
        assert row.fiscal_year_end_month == 12

    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        # Update: change entity_type to S-corp.
        row = upsert_profile(
            sess,
            firm_id=firm, client_id=client,
            actor="cpa@firm.test", scope=AccessScope.FIRM,
            entity_type="s_corp", tax_year=2025,
        )
        assert row.entity_type == "s_corp"
        # Still only one row (1:1).
        rows = sess.execute(
            select(ClientProfile).where(ClientProfile.client_id == client)
        ).scalars().all()
        assert len(rows) == 1


def test_upsert_rejected_for_portal_scope(world) -> None:
    firm = world.firm_a
    client = world.a1.client_id

    with tenant_session(ctx_client(firm, client)) as sess:
        with pytest.raises(ClientProfileForbiddenError):
            upsert_profile(
                sess,
                firm_id=firm, client_id=client,
                actor="portal@firm.test", scope=AccessScope.CLIENT,
                entity_type=EntityType.SOLE_PROP, tax_year=2025,
            )


def test_upsert_validates_inputs(world) -> None:
    firm = world.firm_a
    client = world.a1.client_id

    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        with pytest.raises(ClientProfileValidationError, match="entity_type"):
            upsert_profile(
                sess,
                firm_id=firm, client_id=client,
                actor="cpa", scope=AccessScope.FIRM,
                entity_type="not_a_real_type", tax_year=2025,
            )

    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        with pytest.raises(ClientProfileValidationError, match="State code"):
            upsert_profile(
                sess,
                firm_id=firm, client_id=client,
                actor="cpa", scope=AccessScope.FIRM,
                entity_type=EntityType.C_CORP, tax_year=2025,
                home_state="California",  # too long
            )

    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        with pytest.raises(ClientProfileValidationError, match="month"):
            upsert_profile(
                sess,
                firm_id=firm, client_id=client,
                actor="cpa", scope=AccessScope.FIRM,
                entity_type=EntityType.C_CORP, tax_year=2025,
                fiscal_year_end_month=13,
            )


def test_profile_rls_isolation(world) -> None:
    """A profile created under firm_a is invisible to firm_b."""
    firm_a = world.firm_a
    firm_b = world.firm_b
    client_a1 = world.a1.client_id
    client_b1 = world.b1.client_id

    with tenant_session(ctx_firm_for_client(firm_a, client_a1)) as sess:
        upsert_profile(
            sess,
            firm_id=firm_a, client_id=client_a1,
            actor="cpa-a", scope=AccessScope.FIRM,
            entity_type=EntityType.C_CORP, tax_year=2025,
        )

    # firm_b cannot see firm_a's row even when asking for client_a1.
    with tenant_session(ctx_firm_for_client(firm_b, client_b1)) as sess:
        leaked = sess.execute(
            select(ClientProfile).where(ClientProfile.client_id == client_a1)
        ).scalar_one_or_none()
        assert leaked is None


# --------------------------------------------------------------------------- #
# EntityFormRuleset
# --------------------------------------------------------------------------- #
def test_get_form_set_fails_closed_when_no_profile(world) -> None:
    client = world.a1.client_id
    firm = world.firm_a

    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        with pytest.raises(NeedsRulesetError, match="has no profile"):
            get_form_set_for_client(sess, client_id=client)


def test_get_form_set_fails_closed_when_no_active_ruleset(world) -> None:
    """Profile exists but the (entity_type, tax_year) has no ACTIVE ruleset."""
    firm = world.firm_a
    client = world.a1.client_id

    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        upsert_profile(
            sess,
            firm_id=firm, client_id=client,
            actor="cpa", scope=AccessScope.FIRM,
            entity_type=EntityType.C_CORP,
            tax_year=2099,  # nothing seeded for 2099
        )

    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        with pytest.raises(NeedsRulesetError, match="No ACTIVE entity-form ruleset"):
            get_form_set_for_client(sess, client_id=client)


def test_get_form_set_returns_forms_after_activation(world) -> None:
    firm = world.firm_a
    client = world.a1.client_id

    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        upsert_profile(
            sess,
            firm_id=firm, client_id=client,
            actor="cpa", scope=AccessScope.FIRM,
            entity_type=EntityType.S_CORP, tax_year=2025,
        )
    # Activate the seeded DRAFT ruleset for (s_corp, 2025) under firm scope
    # (no client GUC — activation writes audit at NIL client).
    with tenant_session(ctx_firm(firm)) as sess:
        ruleset = sess.execute(
            select(EntityFormRuleset).where(
                EntityFormRuleset.entity_type == "s_corp",
                EntityFormRuleset.tax_year == 2025,
                EntityFormRuleset.status == EntityFormRulesetStatus.DRAFT,
            )
        ).scalar_one()
        activate_ruleset(
            sess,
            firm_id=firm, actor="cpa", scope=AccessScope.FIRM,
            ruleset_id=ruleset.id,
        )

    with tenant_session(ctx_firm_for_client(firm, client)) as sess:
        forms = get_form_set_for_client(sess, client_id=client)
        assert forms == [TaxFormCode.F1120S]


def test_each_entity_type_yields_distinct_forms(world) -> None:
    """Activating each seeded ruleset and verifying its required_forms.

    The seed currently emits one form per entity_type — this test pins
    that mapping so any future change is intentional.
    """
    firm = world.firm_a
    expected: dict[EntityType, list[TaxFormCode]] = {
        EntityType.C_CORP: [TaxFormCode.F1120],
        EntityType.S_CORP: [TaxFormCode.F1120S],
        EntityType.PARTNERSHIP: [TaxFormCode.F1065],
        EntityType.SINGLE_MEMBER_LLC: [TaxFormCode.F1040SC],
        EntityType.SOLE_PROP: [TaxFormCode.F1040SC],
    }

    # Activate every seeded ruleset for 2025 once (firm scope, no client).
    with tenant_session(ctx_firm(firm)) as sess:
        rulesets = sess.execute(
            select(EntityFormRuleset).where(
                EntityFormRuleset.tax_year == 2025,
                EntityFormRuleset.status == EntityFormRulesetStatus.DRAFT,
            )
        ).scalars().all()
        for r in rulesets:
            activate_ruleset(
                sess,
                firm_id=firm, actor="cpa", scope=AccessScope.FIRM,
                ruleset_id=r.id,
            )

    # Create a client for each entity_type (re-using a1) and check forms.
    seen: dict[str, list[TaxFormCode]] = {}
    for et in EntityType:
        with tenant_session(
            ctx_firm_for_client(firm, world.a1.client_id),
        ) as sess:
            upsert_profile(
                sess,
                firm_id=firm, client_id=world.a1.client_id,
                actor="cpa", scope=AccessScope.FIRM,
                entity_type=et, tax_year=2025,
            )
            seen[et.value] = get_form_set_for_client(
                sess, client_id=world.a1.client_id,
            )
    for et, forms in expected.items():
        assert seen[et.value] == forms
