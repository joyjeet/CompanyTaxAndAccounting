"""Unit tests for the FormTemplate registry service (Phase 8b)."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.session import tenant_session, unscoped_session
from app.db.tenant import AccessScope, TenantContext
from app.domain.form_template import (
    FormTemplateForbiddenError,
    FormTemplateNotActiveError,
    FormTemplateStateError,
    activate_template,
    get_active_verified,
    register_template,
    verify_template,
)
from app.models.enums import FormTemplateStatus, TaxFormCode
from app.models.form_template import FormTemplate


def _scoped_firm() -> TenantContext:
    # form_template is a reference table — no firm_id column — but the
    # service still requires AccessScope.FIRM for governance. We can use
    # any non-zero UUID as firm_id since the audit row is firm-level.
    from uuid import uuid4
    return TenantContext(firm_id=uuid4(), scope=AccessScope.FIRM)


def _make_firm() -> "UUID":  # type: ignore[name-defined]
    """Create a Firm row + return its id so audit FK is satisfied."""
    from uuid import uuid4

    from app.models.accounting import Firm
    firm_id = uuid4()
    with unscoped_session() as sess:
        sess.add(Firm(id=firm_id, name=f"TmplTestFirm-{firm_id}"))
    return firm_id


def test_register_creates_draft_unverified() -> None:
    firm_id = _make_firm()
    with tenant_session(TenantContext(firm_id=firm_id, scope=AccessScope.FIRM)) as sess:
        row = register_template(
            sess,
            firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1120,
            tax_year=2099,
            revision="2099.test",
            local_template_path="/tmp/not_a_real_path.pdf",
        )
        assert row.status is FormTemplateStatus.DRAFT
        assert row.verified is False
        assert row.sha256 == "0" * 64  # placeholder when file absent


def test_register_duplicate_rejected() -> None:
    firm_id = _make_firm()
    with tenant_session(TenantContext(firm_id=firm_id, scope=AccessScope.FIRM)) as sess:
        register_template(
            sess,
            firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1065,
            tax_year=2099,
            revision="dup",
            local_template_path="/tmp/x.pdf",
        )
        with pytest.raises(FormTemplateStateError, match="already registered"):
            register_template(
                sess,
                firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
                form_code=TaxFormCode.F1065,
                tax_year=2099,
                revision="dup",
                local_template_path="/tmp/x.pdf",
            )


def test_verify_requires_firm_scope() -> None:
    firm_id = _make_firm()
    with tenant_session(TenantContext(firm_id=firm_id, scope=AccessScope.FIRM)) as sess:
        row = register_template(
            sess,
            firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1120S,
            tax_year=2099,
            revision="vscope",
            local_template_path="/tmp/x.pdf",
        )
        row_id = row.id
    from uuid import uuid4
    portal_ctx = TenantContext(
        firm_id=firm_id, client_id=uuid4(), scope=AccessScope.CLIENT,
    )
    with tenant_session(portal_ctx) as sess:
        with pytest.raises(FormTemplateForbiddenError):
            verify_template(
                sess,
                firm_id=firm_id, actor="portal", scope=AccessScope.CLIENT,
                template_id=row_id,
            )


def test_activate_requires_verified() -> None:
    firm_id = _make_firm()
    with tenant_session(TenantContext(firm_id=firm_id, scope=AccessScope.FIRM)) as sess:
        row = register_template(
            sess,
            firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1040SC,
            tax_year=2099,
            revision="activate-unverified",
            local_template_path="/tmp/x.pdf",
        )
        with pytest.raises(FormTemplateStateError, match="verified"):
            activate_template(
                sess,
                firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
                template_id=row.id,
            )


def test_full_lifecycle_register_verify_activate_supersede() -> None:
    firm_id = _make_firm()
    with tenant_session(TenantContext(firm_id=firm_id, scope=AccessScope.FIRM)) as sess:
        # First revision: register -> verify -> activate -> ACTIVE.
        r1 = register_template(
            sess,
            firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1120,
            tax_year=2099,
            revision="r1",
            local_template_path="/tmp/r1.pdf",
        )
        verify_template(
            sess,
            firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
            template_id=r1.id,
        )
        activate_template(
            sess,
            firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
            template_id=r1.id,
        )
        sess.refresh(r1)
        assert r1.status is FormTemplateStatus.ACTIVE
        assert r1.verified is True

        # Lookup finds it.
        found = get_active_verified(
            sess, form_code=TaxFormCode.F1120, tax_year=2099,
        )
        assert found.id == r1.id

        # Second revision: register -> verify -> activate supersedes r1.
        r2 = register_template(
            sess,
            firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1120,
            tax_year=2099,
            revision="r2",
            local_template_path="/tmp/r2.pdf",
        )
        verify_template(
            sess,
            firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
            template_id=r2.id,
        )
        activate_template(
            sess,
            firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
            template_id=r2.id,
        )
        sess.refresh(r1)
        sess.refresh(r2)
        assert r1.status is FormTemplateStatus.SUPERSEDED
        assert r2.status is FormTemplateStatus.ACTIVE

        # Lookup now returns r2.
        found = get_active_verified(
            sess, form_code=TaxFormCode.F1120, tax_year=2099,
        )
        assert found.id == r2.id


def test_get_active_verified_raises_when_none() -> None:
    with unscoped_session() as sess:
        # Use a tax_year nobody has registered.
        with pytest.raises(FormTemplateNotActiveError):
            get_active_verified(
                sess, form_code=TaxFormCode.F1120, tax_year=1900,
            )


def test_get_active_verified_skips_active_but_unverified() -> None:
    """ACTIVE row that's somehow unverified must still be rejected.

    Activation requires verified=True, but the defensive check in
    get_active_verified treats this as a corrupt invariant.
    """
    firm_id = _make_firm()
    with tenant_session(TenantContext(firm_id=firm_id, scope=AccessScope.FIRM)) as sess:
        row = register_template(
            sess,
            firm_id=firm_id, actor="cpa@firm.test", scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1120,
            tax_year=2098,
            revision="manual-active",
            local_template_path="/tmp/x.pdf",
        )
        # Directly flip to ACTIVE without verifying (simulating bad data).
        row.status = FormTemplateStatus.ACTIVE
        sess.flush()
        with pytest.raises(FormTemplateNotActiveError):
            get_active_verified(
                sess, form_code=TaxFormCode.F1120, tax_year=2098,
            )
