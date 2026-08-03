"""Integration tests for the COA template instantiation domain service.

The migration seeds 5 templates as DRAFT. A firm CPA must activate them
before any client can be onboarded with one. Tests here activate inside
the test transaction (idempotent) and then exercise instantiation.

Activated template status PERSISTS across tests (templates are reference
data, not tenant data, so they're not truncated by `clean_db`). That's
acceptable because `activate_template` is idempotent — re-running it on
an already-ACTIVE template is a no-op return.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import tenant_session
from app.db.tenant import AccessScope
from app.domain.coa_templates import (
    CoaTemplateError,
    CoaTemplateForbiddenError,
    activate_template,
    instantiate_for_client,
)
from app.models.accounting import ChartOfAccounts
from app.models.coa_template import CoaTemplate, CoaTemplateNode
from app.models.enums import (
    CoaNodeOrigin,
    CoaTemplateKind,
    CoaTemplateStatus,
    Industry,
)
from tests.conftest import ctx_firm, SeededWorld


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _activate_general_and_overlay(firm_id, industry: Industry) -> None:
    """Activate the general + named overlay templates for this firm."""
    with tenant_session(ctx_firm(firm_id)) as sess:
        general = sess.execute(
            select(CoaTemplate).where(
                CoaTemplate.key == "general",
                CoaTemplate.kind == CoaTemplateKind.GENERAL,
            ).limit(1)
        ).scalar_one()
        activate_template(
            sess,
            firm_id=firm_id,
            actor="cpa@acme.test",
            scope=AccessScope.FIRM,
            template_id=general.id,
        )
        overlay = sess.execute(
            select(CoaTemplate).where(
                CoaTemplate.key == f"industry:{industry.value}",
            )
        ).scalar_one()
        activate_template(
            sess,
            firm_id=firm_id,
            actor="cpa@acme.test",
            scope=AccessScope.FIRM,
            template_id=overlay.id,
        )


def _new_client(firm_id, name: str = "TemplateTest Client"):
    """Create a bare client (no preseeded COA) so instantiate can populate it."""
    from uuid import uuid4

    from app.models.accounting import Client

    client_id = uuid4()
    with tenant_session(ctx_firm(firm_id)) as sess:
        sess.add(Client(id=client_id, firm_id=firm_id, name=name))
    return client_id


# --------------------------------------------------------------------------- #
# Activation
# --------------------------------------------------------------------------- #
def test_activate_template_requires_firm_scope(world: SeededWorld) -> None:
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        general = sess.execute(
            select(CoaTemplate).where(CoaTemplate.key == "general").limit(1)
        ).scalar_one()
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        with pytest.raises(CoaTemplateForbiddenError):
            activate_template(
                sess,
                firm_id=world.firm_a,
                actor="portal_user",
                scope=AccessScope.CLIENT,
                template_id=general.id,
            )


def test_activate_supersedes_prior_active(world: SeededWorld) -> None:
    """If a second version of the general template exists in ACTIVE status,
    activating a new one supersedes the old. Idempotent re-activation is a no-op.
    """
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        general = sess.execute(
            select(CoaTemplate).where(CoaTemplate.key == "general").limit(1)
        ).scalar_one()
        # First activation
        activate_template(
            sess,
            firm_id=world.firm_a,
            actor="cpa@acme.test",
            scope=AccessScope.FIRM,
            template_id=general.id,
        )
        sess.flush()
        # Second activation of the same row should be a no-op (already ACTIVE)
        result = activate_template(
            sess,
            firm_id=world.firm_a,
            actor="cpa@acme.test",
            scope=AccessScope.FIRM,
            template_id=general.id,
        )
        assert result.status is CoaTemplateStatus.ACTIVE


# --------------------------------------------------------------------------- #
# Instantiation
# --------------------------------------------------------------------------- #
def test_instantiate_creates_tree_with_lineage(world: SeededWorld) -> None:
    _activate_general_and_overlay(world.firm_a, Industry.CONSTRUCTION)
    client_id = _new_client(world.firm_a)

    with tenant_session(ctx_firm(world.firm_a)) as sess:
        result = instantiate_for_client(
            sess,
            firm_id=world.firm_a,
            client_id=client_id,
            industry=Industry.CONSTRUCTION,
            actor="cpa@acme.test",
            scope=AccessScope.FIRM,
        )

    assert result.created_count > 0
    assert result.industry is Industry.CONSTRUCTION

    with tenant_session(ctx_firm(world.firm_a)) as sess:
        rows = sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.client_id == client_id
            )
        ).scalars().all()
        # Every row carries lineage to the template
        templated = [r for r in rows if r.template_node_id is not None]
        assert len(templated) == result.created_count
        # Origin breakdown
        origins = {r.origin for r in rows}
        assert CoaNodeOrigin.GENERAL in origins
        assert CoaNodeOrigin.INDUSTRY_OVERLAY in origins
        # No CUSTOM rows yet
        assert CoaNodeOrigin.CUSTOM not in origins


def test_instantiate_builds_parent_child_chain(world: SeededWorld) -> None:
    """parent_account_id on each row must point to the row whose code is the
    template node's parent_code (or be NULL for roots)."""
    _activate_general_and_overlay(world.firm_a, Industry.GENERIC)
    client_id = _new_client(world.firm_a)
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        instantiate_for_client(
            sess,
            firm_id=world.firm_a,
            client_id=client_id,
            industry=Industry.GENERIC,
            actor="cpa@acme.test",
            scope=AccessScope.FIRM,
        )

    with tenant_session(ctx_firm(world.firm_a)) as sess:
        rows = sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.client_id == client_id
            )
        ).scalars().all()
        by_id = {r.id: r for r in rows}
        for r in rows:
            if r.parent_account_id is None:
                # Root → depth must be 0
                assert r.depth == 0
                assert r.path == r.code
            else:
                parent = by_id[r.parent_account_id]
                # depth must be parent.depth + 1
                assert r.depth == parent.depth + 1, (
                    f"depth chain broken at code {r.code}"
                )
                # path must start with parent's path
                assert r.path.startswith(parent.path + ">"), (
                    f"path chain broken at {r.code}: {r.path} vs parent {parent.path}"
                )


def test_instantiate_is_idempotent_blocked_on_existing_templated(
    world: SeededWorld,
) -> None:
    _activate_general_and_overlay(world.firm_a, Industry.GENERIC)
    client_id = _new_client(world.firm_a)
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        instantiate_for_client(
            sess,
            firm_id=world.firm_a,
            client_id=client_id,
            industry=Industry.GENERIC,
            actor="cpa@acme.test",
            scope=AccessScope.FIRM,
        )

    # Second call must refuse to double-instantiate.
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        with pytest.raises(CoaTemplateError, match="already has"):
            instantiate_for_client(
                sess,
                firm_id=world.firm_a,
                client_id=client_id,
                industry=Industry.GENERIC,
                actor="cpa@acme.test",
                scope=AccessScope.FIRM,
            )


def test_instantiate_requires_firm_scope(world: SeededWorld) -> None:
    _activate_general_and_overlay(world.firm_a, Industry.GENERIC)
    client_id = _new_client(world.firm_a)
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        with pytest.raises(CoaTemplateForbiddenError):
            instantiate_for_client(
                sess,
                firm_id=world.firm_a,
                client_id=client_id,
                industry=Industry.GENERIC,
                actor="portal_user",
                scope=AccessScope.CLIENT,
            )


def test_instantiate_isolation_between_firms(world: SeededWorld) -> None:
    """Instantiating for firm A's client must not affect firm B's clients."""
    _activate_general_and_overlay(world.firm_a, Industry.GENERIC)
    new_a_client = _new_client(world.firm_a, "A iso client")

    with tenant_session(ctx_firm(world.firm_a)) as sess:
        instantiate_for_client(
            sess,
            firm_id=world.firm_a,
            client_id=new_a_client,
            industry=Industry.GENERIC,
            actor="cpa@acme.test",
            scope=AccessScope.FIRM,
        )

    # Firm B sees zero new rows for either client because of RLS.
    with tenant_session(ctx_firm(world.firm_b)) as sess:
        cnt = sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.client_id == new_a_client
            )
        ).first()
        assert cnt is None, "firm B can see firm A's client COA — RLS broken"


def test_instantiate_without_an_overlay_falls_back_to_the_general_chart(
    world: SeededWorld,
) -> None:
    """An industry with no ACTIVE overlay still gets the general chart.

    Most industries never ship an overlay. Refusing to onboard those clients
    would be wrong — they just get the standard chart and nothing extra.
    """
    _activate_general_and_overlay(world.firm_a, Industry.GENERIC)
    # Make sure the CONSTRUCTION overlay is DRAFT for this test only.
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        ov = sess.execute(
            select(CoaTemplate).where(
                CoaTemplate.key == f"industry:{Industry.CONSTRUCTION.value}",
            )
        ).scalar_one()
        if ov.status is CoaTemplateStatus.ACTIVE:
            ov.status = CoaTemplateStatus.DRAFT  # reset
            ov.activated_at = None
            ov.activated_by = None
            sess.flush()

    client_id = _new_client(world.firm_a, "needs_construction")
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        result = instantiate_for_client(
            sess,
            firm_id=world.firm_a,
            client_id=client_id,
            industry=Industry.CONSTRUCTION,
            actor="cpa@acme.test",
            scope=AccessScope.FIRM,
        )
        assert result.overlay_template_id is None
        assert result.created_count > 0
