"""Phase 8b integration tests: FormTemplate finalize gate + worksheet
reject/regenerate flow.

Covers requirements B.1 (template gate on finalize) and B.5 (reject route
and regen auto-supersede).
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from app.db.session import tenant_session
from app.db.tenant import AccessScope
from app.domain.artifact_service import (
    ArtifactStateError,
    download_artifact,
    finalize_artifact,
    generate_tax_worksheet_artifact,
)
from app.domain.form_template import (
    activate_template,
    register_template,
    verify_template,
)
from app.domain.ledger import LedgerService, LineInput
from app.domain.tax_service import (
    MappingProposal,
    TaxWorksheetGenerationError,
    approve_mapping,
    approve_worksheet,
    generate_worksheet,
    get_form_by_code,
    propose_mapping,
    reject_worksheet,
)
from app.models.accounting import (
    AccountingPeriod,
    AuditEvent,
    ChartOfAccounts,
    TaxFormLine,
    TaxWorksheet,
)
from app.models.enums import (
    ArtifactFormat,
    ArtifactStatus,
    AuditAction,
    TaxFormCode,
    TaxLineSign,
    TaxWorksheetStatus,
)
from tests.conftest import (
    SeededClient,
    SeededWorld,
    ctx_firm,
    ctx_firm_for_client,
)

D = Decimal


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _post_minimal_baseline(sc: SeededClient) -> None:
    """Post a single revenue + expense pair so a worksheet can compute."""
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        led = LedgerService(
            sess, firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
        )
        # Revenue 4000 credit, cash 1000 debit.
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
        from datetime import date
        led.post(
            memo="rev",
            entry_date=date(2026, 6, 1),
            period_id=sc.period_id,
            lines=[
                LineInput(account_id=cash.id, debit=D("1000")),
                LineInput(account_id=rev.id, credit=D("1000")),
            ],
        )
        led.post(
            memo="exp",
            entry_date=date(2026, 6, 1),
            period_id=sc.period_id,
            lines=[
                LineInput(account_id=exp.id, debit=D("300")),
                LineInput(account_id=cash.id, credit=D("300")),
            ],
        )


def _map_revenue_and_expense(
    sess, sc: SeededClient, form_code: TaxFormCode = TaxFormCode.F1120,
) -> None:
    """Propose+approve both 4000 revenue and 5000 expense mappings."""
    form = get_form_by_code(sess, form_code)
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
    rev_acct = sess.execute(
        select(ChartOfAccounts).where(
            ChartOfAccounts.client_id == sc.client_id,
            ChartOfAccounts.code == "4000",
        )
    ).scalar_one()
    exp_acct = sess.execute(
        select(ChartOfAccounts).where(
            ChartOfAccounts.client_id == sc.client_id,
            ChartOfAccounts.code == "5000",
        )
    ).scalar_one()
    for acct, line in ((rev_acct, rev_line), (exp_acct, ded_line)):
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


def _approve_worksheet_for(
    sc: SeededClient, form_code: TaxFormCode = TaxFormCode.F1120,
) -> UUID:
    """Map + generate + approve a worksheet, returning the worksheet id."""
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        _map_revenue_and_expense(sess, sc, form_code)
        ws = generate_worksheet(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
            scope=AccessScope.FIRM,
            form_code=form_code, period_id=sc.period_id,
        )
        approve_worksheet(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
            scope=AccessScope.FIRM, worksheet_id=ws.id,
        )
        return ws.id


def _activate_form_template(
    firm_id: UUID, form_code: TaxFormCode, tax_year: int,
) -> UUID:
    """Register, verify, and activate a FormTemplate. Returns its id."""
    with tenant_session(ctx_firm(firm_id)) as sess:
        tpl = register_template(
            sess,
            firm_id=firm_id, actor="cpa", scope=AccessScope.FIRM,
            form_code=form_code, tax_year=tax_year,
            revision="r-test",
            local_template_path="/tmp/test-form.pdf",
        )
        verify_template(
            sess,
            firm_id=firm_id, actor="cpa", scope=AccessScope.FIRM,
            template_id=tpl.id,
        )
        activate_template(
            sess,
            firm_id=firm_id, actor="cpa", scope=AccessScope.FIRM,
            template_id=tpl.id,
        )
        return tpl.id


# --------------------------------------------------------------------------- #
# B.1 — FormTemplate finalize gate
# --------------------------------------------------------------------------- #
def test_finalize_pdf_blocked_when_no_active_template(world: SeededWorld) -> None:
    sc = world.a1
    _post_minimal_baseline(sc)
    ws_id = _approve_worksheet_for(sc, TaxFormCode.F1120)

    with tenant_session(ctx_firm_for_client(sc.firm_id, sc.client_id)) as sess:
        art = generate_tax_worksheet_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
            scope=AccessScope.FIRM,
            worksheet_id=ws_id, fmt=ArtifactFormat.PDF,
        )
        assert art.status is ArtifactStatus.DRAFT

        # No active+verified template seeded for F1120/2026 → finalize blocked.
        with pytest.raises(ArtifactStateError, match="template"):
            finalize_artifact(
                sess,
                firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
                scope=AccessScope.FIRM, artifact_id=art.id,
            )


def test_finalize_pdf_succeeds_after_template_activation(
    world: SeededWorld,
) -> None:
    sc = world.a1
    _post_minimal_baseline(sc)
    ws_id = _approve_worksheet_for(sc, TaxFormCode.F1120)
    _activate_form_template(sc.firm_id, TaxFormCode.F1120, tax_year=2026)

    with tenant_session(ctx_firm_for_client(sc.firm_id, sc.client_id)) as sess:
        art = generate_tax_worksheet_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
            scope=AccessScope.FIRM,
            worksheet_id=ws_id, fmt=ArtifactFormat.PDF,
        )
        # Now finalize should succeed.
        finalize_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
            scope=AccessScope.FIRM, artifact_id=art.id,
        )
        sess.refresh(art)
        assert art.status is ArtifactStatus.FINALIZED


def test_finalize_xlsx_not_gated_by_template(world: SeededWorld) -> None:
    """The template gate only applies to the FINAL legal tax PDF — XLSX
    working papers do not require an active IRS form template."""
    sc = world.a1
    _post_minimal_baseline(sc)
    ws_id = _approve_worksheet_for(sc, TaxFormCode.F1120)

    with tenant_session(ctx_firm_for_client(sc.firm_id, sc.client_id)) as sess:
        art = generate_tax_worksheet_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
            scope=AccessScope.FIRM,
            worksheet_id=ws_id, fmt=ArtifactFormat.XLSX,
        )
        finalize_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
            scope=AccessScope.FIRM, artifact_id=art.id,
        )
        sess.refresh(art)
        assert art.status is ArtifactStatus.FINALIZED


# --------------------------------------------------------------------------- #
# B.5 — reject_worksheet + regenerate supersede
# --------------------------------------------------------------------------- #
def test_reject_worksheet_only_works_on_computed(world: SeededWorld) -> None:
    sc = world.a1
    _post_minimal_baseline(sc)
    # Bypass _approve helper — we want the COMPUTED state, not APPROVED.
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        _map_revenue_and_expense(sess, sc)
        ws = generate_worksheet(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
            scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1120, period_id=sc.period_id,
        )
        assert ws.status is TaxWorksheetStatus.COMPUTED

        # Reject works.
        ws = reject_worksheet(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="cpa",
            scope=AccessScope.FIRM, worksheet_id=ws.id,
            reason="numbers look wrong",
        )
        assert ws.status is TaxWorksheetStatus.REJECTED
        assert ws.approved_by == "cpa"

        # Cannot reject an already-rejected one.
        with pytest.raises(TaxWorksheetGenerationError, match="COMPUTED"):
            reject_worksheet(
                sess,
                firm_id=sc.firm_id, client_id=sc.client_id, actor="cpa",
                scope=AccessScope.FIRM, worksheet_id=ws.id,
            )


def test_regenerate_supersedes_prior_approved(world: SeededWorld) -> None:
    sc = world.a1
    _post_minimal_baseline(sc)
    first_ws_id = _approve_worksheet_for(sc, TaxFormCode.F1120)

    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        # Regenerate the same form for the same period.
        new_ws = generate_worksheet(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
            scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1120, period_id=sc.period_id,
        )
        assert new_ws.id != first_ws_id
        assert new_ws.status is TaxWorksheetStatus.COMPUTED

        # Prior worksheet now SUPERSEDED.
        prior = sess.get(TaxWorksheet, first_ws_id)
        assert prior is not None
        assert prior.status is TaxWorksheetStatus.SUPERSEDED

        # Audit row written for the supersession.
        audits = sess.execute(
            select(AuditEvent).where(
                AuditEvent.action == AuditAction.TAX_WORKSHEET_SUPERSEDE,
                AuditEvent.entity_id == first_ws_id,
            )
        ).scalars().all()
        assert len(audits) == 1


def test_regenerate_supersedes_prior_computed(world: SeededWorld) -> None:
    """Regenerate should auto-supersede a prior COMPUTED worksheet too."""
    sc = world.a1
    _post_minimal_baseline(sc)
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)

    with tenant_session(ctx) as sess:
        _map_revenue_and_expense(sess, sc)
        ws1 = generate_worksheet(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
            scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1120, period_id=sc.period_id,
        )
        ws2 = generate_worksheet(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
            scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1120, period_id=sc.period_id,
        )
        assert ws1.id != ws2.id
        sess.refresh(ws1)
        assert ws1.status is TaxWorksheetStatus.SUPERSEDED
        assert ws2.status is TaxWorksheetStatus.COMPUTED
