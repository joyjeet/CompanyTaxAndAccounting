"""Phase 6 output-layer integration tests.

Covers:
* PDF / XLSX statement render + decrypt round-trip with sha verification.
* Variance presentation (current vs prior).
* Narrative deterministic template + safety check (foreign-number rejection).
* Audit-package gating (refuses while drafts pending, refuses with missing
  FINALIZED dependencies; succeeds when all deps satisfied).
* Finalize gating refuses with PENDING_REVIEW drafts; supersedes prior
  FINALIZED of the same kind/format/period.
* Portal scope cannot download DRAFT artifacts.
* Cross-firm isolation: artifact created in client A's context is invisible
  to client B's context (RLS).
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.session import tenant_session
from app.db.tenant import AccessScope
from app.domain.artifact_service import (
    ArtifactNotFoundError,
    ExportBlockedByPendingDraftsError,
    GenerateNarrativeRequest,
    GenerateStatementRequest,
    download_artifact,
    finalize_artifact,
    generate_narrative_artifact,
    generate_statement_artifact,
    generate_tax_worksheet_artifact,
    list_artifacts,
)
from app.domain.audit_package import (
    AuditPackageMissingDependencyError,
    generate_audit_package,
)
from app.domain.ledger import LedgerService, LineInput
from app.domain.narrative import (
    build_allowed_numbers,
    template_narrative,
    verify_narrative_safety,
)
from app.domain.presentation import (
    PresentationRules,
    present_balance_sheet,
    present_profit_and_loss,
)
from app.domain.statements import StatementsService
from app.domain.tax_service import (
    MappingProposal,
    approve_mapping,
    approve_worksheet,
    generate_worksheet,
    get_form_by_code,
    propose_mapping,
)
from app.models.accounting import (
    AccountingPeriod,
    ChartOfAccounts,
    DraftClassification,
    GeneratedArtifact,
    SourceDocument,
    TaxFormLine,
)
from app.models.enums import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactStatus,
    DraftKind,
    DraftStatus,
    TaxFormCode,
    TaxLineSign,
)
from tests.conftest import (
    SeededClient,
    SeededWorld,
    ctx_client,
    ctx_firm_for_client,
)

D = Decimal


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _post_baseline(sc: SeededClient) -> None:
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        led = LedgerService(
            sess, firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
        )
        led.post(
            period_id=sc.period_id, entry_date=date(2026, 1, 5),
            lines=[
                LineInput(account_id=sc.cash_account_id, debit=D("5000")),
                LineInput(account_id=sc.equity_account_id, credit=D("5000")),
            ],
            memo="opening capital",
        )
        led.post(
            period_id=sc.period_id, entry_date=date(2026, 2, 10),
            lines=[
                LineInput(account_id=sc.cash_account_id, debit=D("1200")),
                LineInput(account_id=sc.revenue_account_id, credit=D("1200")),
            ],
            memo="invoice paid in cash",
        )
        led.post(
            period_id=sc.period_id, entry_date=date(2026, 3, 1),
            lines=[
                LineInput(account_id=sc.expense_account_id, debit=D("300")),
                LineInput(account_id=sc.cash_account_id, credit=D("300")),
            ],
            memo="office supplies",
        )


def _add_prior_period(sc: SeededClient) -> tuple[int, AccountingPeriod]:
    """Add a 2025 period and post a small amount of activity in it (so we
    have a non-trivial prior).
    """
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    prior_id = uuid4()
    with tenant_session(ctx) as sess:
        prior = AccountingPeriod(
            id=prior_id, firm_id=sc.firm_id, client_id=sc.client_id,
            name="2025", start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
        )
        sess.add(prior)
        sess.flush()
        led = LedgerService(
            sess, firm_id=sc.firm_id, client_id=sc.client_id, actor="t",
        )
        led.post(
            period_id=prior_id, entry_date=date(2025, 6, 1),
            lines=[
                LineInput(account_id=sc.cash_account_id, debit=D("1000")),
                LineInput(account_id=sc.revenue_account_id, credit=D("1000")),
            ],
            memo="prior revenue",
        )
        led.post(
            period_id=prior_id, entry_date=date(2025, 6, 5),
            lines=[
                LineInput(account_id=sc.expense_account_id, debit=D("200")),
                LineInput(account_id=sc.cash_account_id, credit=D("200")),
            ],
            memo="prior expense",
        )
    return prior_id, None  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Render round-trip
# --------------------------------------------------------------------------- #
def test_pdf_pl_renders_and_decrypts(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        art = generate_statement_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="reviewer",
            scope=AccessScope.FIRM,
            request=GenerateStatementRequest(
                period_id=sc.period_id,
                kind=ArtifactKind.PROFIT_AND_LOSS,
                format=ArtifactFormat.PDF,
            ),
        )
        assert art.status is ArtifactStatus.DRAFT
        assert art.size_bytes > 100
        body = download_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="reviewer",
            scope=AccessScope.FIRM, artifact_id=art.id,
        )
    assert body.body.startswith(b"%PDF")
    assert body.content_type == "application/pdf"


def test_xlsx_bs_has_sum_formula(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        art = generate_statement_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="reviewer",
            scope=AccessScope.FIRM,
            request=GenerateStatementRequest(
                period_id=sc.period_id,
                kind=ArtifactKind.BALANCE_SHEET,
                format=ArtifactFormat.XLSX,
            ),
        )
        body = download_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="reviewer",
            scope=AccessScope.FIRM, artifact_id=art.id,
        ).body
    # XLSX = zip; inspect contents for at least one SUM formula somewhere.
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        sheet_xml = b""
        for n in zf.namelist():
            if n.endswith(".xml") and "sheet" in n:
                sheet_xml += zf.read(n)
        assert b"SUM(" in sheet_xml, "XLSX must contain at least one =SUM formula"


def test_cash_flow_requires_cash_codes(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        from app.domain.artifact_service import ArtifactStateError
        with pytest.raises(ArtifactStateError):
            generate_statement_artifact(
                sess,
                firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
                scope=AccessScope.FIRM,
                request=GenerateStatementRequest(
                    period_id=sc.period_id,
                    kind=ArtifactKind.CASH_FLOW,
                    format=ArtifactFormat.PDF,
                ),
            )


def test_cash_flow_renders_with_cash_codes(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        art = generate_statement_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            request=GenerateStatementRequest(
                period_id=sc.period_id,
                kind=ArtifactKind.CASH_FLOW,
                format=ArtifactFormat.PDF,
                cash_account_codes=["1000"],
            ),
        )
        assert art.kind is ArtifactKind.CASH_FLOW
        body = download_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM, artifact_id=art.id,
        ).body
    assert body.startswith(b"%PDF")


# --------------------------------------------------------------------------- #
# Variance presentation
# --------------------------------------------------------------------------- #
def test_variance_pct_when_prior_is_nonzero(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    prior_id, _ = _add_prior_period(sc)
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        svc = StatementsService(sess, firm_id=sc.firm_id, client_id=sc.client_id)
        cur_pl = svc.profit_and_loss(
            period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
        )
        prior_pl = svc.profit_and_loss(
            period_start=date(2025, 1, 1), period_end=date(2025, 12, 31),
        )
    pres = present_profit_and_loss(
        cur_pl, rules=PresentationRules(), prior=prior_pl,
    )
    assert pres.revenue.subtotal == D("1200")
    var = pres.revenue.subtotal_variance
    assert var is not None
    assert var.current == D("1200")
    assert var.prior == D("1000")
    assert var.delta == D("200")
    assert var.pct == D("20.00")


# --------------------------------------------------------------------------- #
# Narrative + safety
# --------------------------------------------------------------------------- #
def test_template_narrative_passes_safety(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        svc = StatementsService(sess, firm_id=sc.firm_id, client_id=sc.client_id)
        pl = present_profit_and_loss(
            svc.profit_and_loss(
                period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
            ),
            rules=PresentationRules(),
        )
        bs = present_balance_sheet(
            svc.balance_sheet(as_of=date(2026, 12, 31)),
            rules=PresentationRules(),
        )
    prose = template_narrative(client_name="ClientA1", pl=pl, bs=bs)
    allowed = build_allowed_numbers(pl=pl, bs=bs)
    report = verify_narrative_safety(prose, allowed=allowed)
    assert report.ok, f"template narrative failed safety: {report}"


def test_safety_rejects_foreign_number() -> None:
    allowed = {D("1200.00"), D("300.00"), D("900.00")}
    prose = "Revenue was $1,200.00 but a typo says $9,999.99 also."
    report = verify_narrative_safety(prose, allowed=allowed)
    assert not report.ok
    foreign_values = {v for _, v in report.foreign_numbers}
    assert D("9999.99") in foreign_values


def test_generate_narrative_artifact_persists_md(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        result = generate_narrative_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            request=GenerateNarrativeRequest(
                period_id=sc.period_id, cash_account_codes=["1000"],
            ),
        )
        assert result.safety_report.ok
        assert not result.used_fallback
        body = download_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM, artifact_id=result.artifact.id,
        ).body
    assert body.startswith(b"# Financial summary")


# --------------------------------------------------------------------------- #
# Finalize gating
# --------------------------------------------------------------------------- #
def _add_pending_draft(sc: SeededClient) -> None:
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        doc_id = uuid4()
        sess.add(
            SourceDocument(
                id=doc_id, firm_id=sc.firm_id, client_id=sc.client_id,
                kind="bank_transaction",
                storage_uri="local://test/doc",
                mime_type="text/plain",
                sha256="a" * 64,
                uploaded_by="t",
            )
        )
        sess.flush()
        sess.add(
            DraftClassification(
                firm_id=sc.firm_id, client_id=sc.client_id,
                source_document_id=doc_id,
                kind=DraftKind.BANK_TRANSACTION,
                status=DraftStatus.PENDING_REVIEW,
                confidence=D("0.5"),
                payload={},
                model="t", prompt_version="t",
                needs_review=True,
            )
        )


def test_finalize_refuses_with_pending_drafts(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    _add_pending_draft(sc)
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        art = generate_statement_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            request=GenerateStatementRequest(
                period_id=sc.period_id,
                kind=ArtifactKind.PROFIT_AND_LOSS,
                format=ArtifactFormat.PDF,
            ),
        )
        with pytest.raises(ExportBlockedByPendingDraftsError):
            finalize_artifact(
                sess,
                firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
                scope=AccessScope.FIRM,
                artifact_id=art.id,
            )


def test_finalize_supersedes_prior_finalized(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        a1 = generate_statement_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            request=GenerateStatementRequest(
                period_id=sc.period_id,
                kind=ArtifactKind.PROFIT_AND_LOSS,
                format=ArtifactFormat.PDF,
            ),
        )
        finalize_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM, artifact_id=a1.id,
        )
        a2 = generate_statement_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            request=GenerateStatementRequest(
                period_id=sc.period_id,
                kind=ArtifactKind.PROFIT_AND_LOSS,
                format=ArtifactFormat.PDF,
            ),
        )
        finalize_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM, artifact_id=a2.id,
        )
        a1_refreshed = sess.get(GeneratedArtifact, a1.id)
        a2_refreshed = sess.get(GeneratedArtifact, a2.id)
        assert a1_refreshed.status is ArtifactStatus.SUPERSEDED
        assert a2_refreshed.status is ArtifactStatus.FINALIZED
        assert a2_refreshed.supersedes_id == a1.id


# --------------------------------------------------------------------------- #
# Portal scope
# --------------------------------------------------------------------------- #
def test_portal_cannot_download_draft(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    firm_ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(firm_ctx) as sess:
        art = generate_statement_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            request=GenerateStatementRequest(
                period_id=sc.period_id,
                kind=ArtifactKind.PROFIT_AND_LOSS,
                format=ArtifactFormat.PDF,
            ),
        )
        art_id = art.id
    portal_ctx = ctx_client(sc.firm_id, sc.client_id)
    with tenant_session(portal_ctx) as sess:
        with pytest.raises(ArtifactNotFoundError):
            download_artifact(
                sess,
                firm_id=sc.firm_id, client_id=sc.client_id, actor="portal-user",
                scope=AccessScope.CLIENT, artifact_id=art_id,
            )
        # list_artifacts must hide drafts from portal.
        rows = list_artifacts(sess, scope=AccessScope.CLIENT)
        assert all(r.status is ArtifactStatus.FINALIZED for r in rows)


def test_portal_can_download_after_finalize(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    firm_ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(firm_ctx) as sess:
        art = generate_statement_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            request=GenerateStatementRequest(
                period_id=sc.period_id,
                kind=ArtifactKind.PROFIT_AND_LOSS,
                format=ArtifactFormat.PDF,
            ),
        )
        finalize_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM, artifact_id=art.id,
        )
        art_id = art.id
    portal_ctx = ctx_client(sc.firm_id, sc.client_id)
    with tenant_session(portal_ctx) as sess:
        body = download_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="portal",
            scope=AccessScope.CLIENT, artifact_id=art_id,
        ).body
        assert body.startswith(b"%PDF")


# --------------------------------------------------------------------------- #
# Cross-firm isolation (RLS)
# --------------------------------------------------------------------------- #
def test_cross_firm_isolation(world: SeededWorld) -> None:
    """An artifact created in client A1 is invisible from client B1."""
    sc_a = world.a1
    sc_b = world.b1
    _post_baseline(sc_a)
    with tenant_session(ctx_firm_for_client(sc_a.firm_id, sc_a.client_id)) as sess:
        art = generate_statement_artifact(
            sess,
            firm_id=sc_a.firm_id, client_id=sc_a.client_id, actor="r",
            scope=AccessScope.FIRM,
            request=GenerateStatementRequest(
                period_id=sc_a.period_id,
                kind=ArtifactKind.PROFIT_AND_LOSS,
                format=ArtifactFormat.PDF,
            ),
        )
        art_id = art.id
    # From firm B's tenant context, the artifact must not be visible.
    with tenant_session(ctx_firm_for_client(sc_b.firm_id, sc_b.client_id)) as sess:
        row = sess.get(GeneratedArtifact, art_id)
        assert row is None, "RLS leak: artifact visible across firms"


# --------------------------------------------------------------------------- #
# Audit-ready package
# --------------------------------------------------------------------------- #
def _finalize_all_required(sc: SeededClient, sess) -> list:
    out = []
    for kind, fmt in [
        (ArtifactKind.PROFIT_AND_LOSS, ArtifactFormat.PDF),
        (ArtifactKind.PROFIT_AND_LOSS, ArtifactFormat.XLSX),
        (ArtifactKind.BALANCE_SHEET, ArtifactFormat.PDF),
        (ArtifactKind.BALANCE_SHEET, ArtifactFormat.XLSX),
        (ArtifactKind.CASH_FLOW, ArtifactFormat.PDF),
        (ArtifactKind.CASH_FLOW, ArtifactFormat.XLSX),
    ]:
        cash_codes = ["1000"] if kind is ArtifactKind.CASH_FLOW else None
        art = generate_statement_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            request=GenerateStatementRequest(
                period_id=sc.period_id, kind=kind, format=fmt,
                cash_account_codes=cash_codes,
            ),
        )
        finalize_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM, artifact_id=art.id,
        )
        out.append(art.id)
    narrative = generate_narrative_artifact(
        sess,
        firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
        scope=AccessScope.FIRM,
        request=GenerateNarrativeRequest(
            period_id=sc.period_id, cash_account_codes=["1000"],
        ),
    )
    finalize_artifact(
        sess,
        firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
        scope=AccessScope.FIRM, artifact_id=narrative.artifact.id,
    )
    out.append(narrative.artifact.id)
    return out


def test_audit_package_requires_finalized_statements(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    with tenant_session(ctx_firm_for_client(sc.firm_id, sc.client_id)) as sess:
        with pytest.raises(AuditPackageMissingDependencyError):
            generate_audit_package(
                sess,
                firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
                scope=AccessScope.FIRM,
                period_id=sc.period_id,
            )


def test_audit_package_assembles_and_manifest_verifies(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    with tenant_session(ctx_firm_for_client(sc.firm_id, sc.client_id)) as sess:
        _finalize_all_required(sc, sess)
        result = generate_audit_package(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            period_id=sc.period_id,
        )
        assert result.artifact.kind is ArtifactKind.AUDIT_PACKAGE
        body = download_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM, artifact_id=result.artifact.id,
        ).body
    # Inspect zip + verify manifest sha256s.
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "audit_events.json" in names
        assert "statements/profit_and_loss.pdf" in names
        assert "statements/profit_and_loss.xlsx" in names
        assert "statements/balance_sheet.pdf" in names
        assert "statements/balance_sheet.xlsx" in names
        assert "statements/cash_flow.pdf" in names
        assert "statements/cash_flow.xlsx" in names
        assert "narrative.md" in names
        manifest = json.loads(zf.read("manifest.json"))
        for member in manifest["members"]:
            data = zf.read(member["path"])
            import hashlib
            actual = hashlib.sha256(data).hexdigest()
            assert actual == member["plaintext_sha256"], (
                f"sha mismatch for {member['path']}"
            )


def test_audit_package_refuses_with_pending_drafts(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    # Finalize everything FIRST (before the pending draft exists), then add
    # the draft. The package step must still refuse.
    with tenant_session(ctx_firm_for_client(sc.firm_id, sc.client_id)) as sess:
        _finalize_all_required(sc, sess)
    _add_pending_draft(sc)
    with tenant_session(ctx_firm_for_client(sc.firm_id, sc.client_id)) as sess:
        with pytest.raises(ExportBlockedByPendingDraftsError):
            generate_audit_package(
                sess,
                firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
                scope=AccessScope.FIRM,
                period_id=sc.period_id,
            )


# --------------------------------------------------------------------------- #
# Tax worksheet artifact integration
# --------------------------------------------------------------------------- #
def test_tax_worksheet_render(world: SeededWorld) -> None:
    sc = world.a1
    _post_baseline(sc)
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        form = get_form_by_code(sess, TaxFormCode.F1120)
        rev_line = sess.execute(
            select(TaxFormLine).where(
                TaxFormLine.form_id == form.id, TaxFormLine.code == "1a"
            )
        ).scalar_one()
        deduction_line = sess.execute(
            select(TaxFormLine).where(
                TaxFormLine.form_id == form.id, TaxFormLine.code == "26"
            )
        ).scalar_one_or_none() or sess.execute(
            select(TaxFormLine).where(
                TaxFormLine.form_id == form.id,
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

        m1 = propose_mapping(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            form_id=form.id,
            proposal=MappingProposal(
                account_id=rev_acct.id,
                line_id=rev_line.id, sign=TaxLineSign.POSITIVE,
            ),
        )
        approve_mapping(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM, mapping_id=m1.id,
        )
        m2 = propose_mapping(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            form_id=form.id,
            proposal=MappingProposal(
                account_id=exp_acct.id,
                line_id=deduction_line.id, sign=TaxLineSign.POSITIVE,
            ),
        )
        approve_mapping(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM, mapping_id=m2.id,
        )
        ws = generate_worksheet(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            form_code=TaxFormCode.F1120, period_id=sc.period_id,
        )
        approve_worksheet(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM, worksheet_id=ws.id,
        )
        art = generate_tax_worksheet_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM,
            worksheet_id=ws.id, fmt=ArtifactFormat.XLSX,
        )
        body = download_artifact(
            sess,
            firm_id=sc.firm_id, client_id=sc.client_id, actor="r",
            scope=AccessScope.FIRM, artifact_id=art.id,
        ).body
    assert body[:2] == b"PK"  # XLSX is a zip
