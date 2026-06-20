"""Phase 5 tax module tests: catalog, mapping workflow, worksheet generation,
gating, RLS, portal read-only.

These tests use the existing `world` fixture: firm A with two clients (a1, a2),
firm B with one client (b1). Each seeded client has a 6-account chart of
accounts and a 2026 accounting period.

We post a few journal entries through `LedgerService` to give every test
real ledger activity, then exercise the tax module against it.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.session import tenant_session
from app.db.tenant import AccessScope
from app.domain.ledger import LedgerService, LineInput
from app.domain.tax_service import (
    MappingProposal,
    TaxAccessForbiddenError,
    TaxMappingError,
    TaxWorksheetGenerationError,
    UnmappedAccountsError,
    approve_mapping,
    approve_worksheet,
    generate_worksheet,
    get_form_by_code,
    propose_mapping,
    reject_mapping,
)
from app.models.accounting import (
    AuditEvent,
    TaxAccountMapping,
    TaxForm,
    TaxFormLine,
    TaxWorksheet,
    TaxWorksheetLine,
)
from app.models.enums import (
    AuditAction,
    TaxFormCode,
    TaxLineSign,
    TaxMappingStatus,
    TaxWorksheetStatus,
)
from tests.conftest import SeededClient, SeededWorld, ctx_client, ctx_firm_for_client

D = Decimal


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _post_baseline_activity(sc: SeededClient) -> None:
    """Post simple, balanced JEs: opening capital + revenue + expense.

    After posting:
      * revenue_account: 1,200 credit -> signed_balance +1,200
      * expense_account:   300 debit  -> signed_balance +300
      * net income:                       +900
    """
    ctx = ctx_firm_for_client(sc.firm_id, sc.client_id)
    with tenant_session(ctx) as sess:
        ledger = LedgerService(sess, firm_id=sc.firm_id, client_id=sc.client_id, actor="t")
        ledger.post(
            period_id=sc.period_id, entry_date=date(2026, 1, 5),
            lines=[
                LineInput(account_id=sc.cash_account_id, debit=D("5000")),
                LineInput(account_id=sc.equity_account_id, credit=D("5000")),
            ],
            memo="opening capital",
        )
        ledger.post(
            period_id=sc.period_id, entry_date=date(2026, 2, 10),
            lines=[
                LineInput(account_id=sc.cash_account_id, debit=D("1200")),
                LineInput(account_id=sc.revenue_account_id, credit=D("1200")),
            ],
            memo="invoice paid in cash",
        )
        ledger.post(
            period_id=sc.period_id, entry_date=date(2026, 3, 1),
            lines=[
                LineInput(account_id=sc.expense_account_id, debit=D("300")),
                LineInput(account_id=sc.cash_account_id, credit=D("300")),
            ],
            memo="office supplies",
        )


def _line_id(sess, form_code: TaxFormCode, line_code: str):
    form = get_form_by_code(sess, form_code)
    row = sess.execute(
        select(TaxFormLine).where(
            TaxFormLine.form_id == form.id, TaxFormLine.code == line_code,
        )
    ).scalar_one()
    return row.id, form.id


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
def test_catalog_has_all_four_forms(world: SeededWorld) -> None:
    with tenant_session(ctx_firm_for_client(world.firm_a, world.a1.client_id)) as sess:
        codes = {
            f.code.value
            for f in sess.execute(select(TaxForm)).scalars()
        }
    assert codes == {"F1120", "F1120S", "F1065", "F1040SC"}


def test_form_1120_has_expected_lines(world: SeededWorld) -> None:
    with tenant_session(ctx_firm_for_client(world.firm_a, world.a1.client_id)) as sess:
        form = sess.execute(
            select(TaxForm).where(TaxForm.code == TaxFormCode.F1120)
        ).scalar_one()
        lines = sess.execute(
            select(TaxFormLine).where(TaxFormLine.form_id == form.id)
            .order_by(TaxFormLine.sequence)
        ).scalars().all()
    codes = [ln.code for ln in lines]
    # Gross receipts, COGS, total deductions surface lines.
    assert codes[0] == "1a"
    assert "2" in codes        # COGS
    assert "26" in codes       # Other deductions
    # Total per-form line count for the 1120 spec we ship.
    assert len(lines) == 24


# --------------------------------------------------------------------------- #
# Mapping flow
# --------------------------------------------------------------------------- #
def test_propose_and_approve_mapping_writes_audit(world: SeededWorld) -> None:
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)
    with tenant_session(ctx) as sess:
        line_id, form_id = _line_id(sess, TaxFormCode.F1120, "1a")
        m = propose_mapping(
            sess,
            firm_id=a1.firm_id, client_id=a1.client_id,
            actor="alice", scope=AccessScope.FIRM,
            form_id=form_id,
            proposal=MappingProposal(
                account_id=a1.revenue_account_id, line_id=line_id,
                sign=TaxLineSign.POSITIVE, notes="service revenue -> gross receipts",
            ),
        )
        assert m.status is TaxMappingStatus.DRAFT
        mid = m.id
        approve_mapping(
            sess,
            firm_id=a1.firm_id, client_id=a1.client_id,
            actor="bob", scope=AccessScope.FIRM,
            mapping_id=mid,
        )
    # Re-fetch to assert persistence + audit.
    with tenant_session(ctx) as sess:
        row = sess.get(TaxAccountMapping, mid)
        assert row is not None
        assert row.status is TaxMappingStatus.APPROVED
        assert row.proposed_by == "alice"
        assert row.reviewed_by == "bob"

        actions = {
            e.action
            for e in sess.execute(
                select(AuditEvent).where(AuditEvent.entity_id == mid)
            ).scalars()
        }
        assert AuditAction.TAX_MAP_PROPOSE in actions
        assert AuditAction.TAX_MAP_APPROVE in actions


def test_reject_mapping(world: SeededWorld) -> None:
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)
    with tenant_session(ctx) as sess:
        line_id, form_id = _line_id(sess, TaxFormCode.F1120, "1a")
        m = propose_mapping(
            sess,
            firm_id=a1.firm_id, client_id=a1.client_id,
            actor="alice", scope=AccessScope.FIRM,
            form_id=form_id,
            proposal=MappingProposal(
                account_id=a1.revenue_account_id, line_id=line_id,
            ),
        )
        reject_mapping(
            sess,
            firm_id=a1.firm_id, client_id=a1.client_id,
            actor="bob", scope=AccessScope.FIRM,
            mapping_id=m.id, reason="wrong line",
        )
    with tenant_session(ctx) as sess:
        row = sess.get(TaxAccountMapping, m.id)
        assert row.status is TaxMappingStatus.REJECTED


def test_cannot_approve_already_terminal_mapping(world: SeededWorld) -> None:
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)
    with tenant_session(ctx) as sess:
        line_id, form_id = _line_id(sess, TaxFormCode.F1120, "1a")
        m = propose_mapping(
            sess,
            firm_id=a1.firm_id, client_id=a1.client_id,
            actor="a", scope=AccessScope.FIRM,
            form_id=form_id,
            proposal=MappingProposal(account_id=a1.revenue_account_id, line_id=line_id),
        )
        approve_mapping(
            sess,
            firm_id=a1.firm_id, client_id=a1.client_id,
            actor="b", scope=AccessScope.FIRM,
            mapping_id=m.id,
        )
    with tenant_session(ctx) as sess:
        with pytest.raises(TaxMappingError):
            approve_mapping(
                sess,
                firm_id=a1.firm_id, client_id=a1.client_id,
                actor="b", scope=AccessScope.FIRM,
                mapping_id=m.id,
            )


def test_approving_a_new_mapping_supersedes_prior_approved(world: SeededWorld) -> None:
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)
    with tenant_session(ctx) as sess:
        line_id_1a, form_id = _line_id(sess, TaxFormCode.F1120, "1a")
        line_id_10, _ = _line_id(sess, TaxFormCode.F1120, "10")
        m1 = propose_mapping(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="a", scope=AccessScope.FIRM, form_id=form_id,
            proposal=MappingProposal(account_id=a1.revenue_account_id, line_id=line_id_1a),
        )
        approve_mapping(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="b", scope=AccessScope.FIRM, mapping_id=m1.id,
        )
        m1_id = m1.id
        m2 = propose_mapping(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="a", scope=AccessScope.FIRM, form_id=form_id,
            proposal=MappingProposal(account_id=a1.revenue_account_id, line_id=line_id_10),
        )
        approve_mapping(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="b", scope=AccessScope.FIRM, mapping_id=m2.id,
        )
    with tenant_session(ctx) as sess:
        row1 = sess.get(TaxAccountMapping, m1_id)
        row2 = sess.get(TaxAccountMapping, m2.id)
        assert row1.status is TaxMappingStatus.SUPERSEDED
        assert row2.status is TaxMappingStatus.APPROVED


def test_portal_cannot_propose_mapping(world: SeededWorld) -> None:
    a1 = world.a1
    portal = ctx_client(a1.firm_id, a1.client_id)
    with tenant_session(portal) as sess:
        line_id, form_id = _line_id(sess, TaxFormCode.F1120, "1a")
        with pytest.raises(TaxAccessForbiddenError):
            propose_mapping(
                sess,
                firm_id=a1.firm_id, client_id=a1.client_id,
                actor="portal-user", scope=AccessScope.CLIENT,
                form_id=form_id,
                proposal=MappingProposal(
                    account_id=a1.revenue_account_id, line_id=line_id,
                ),
            )


def test_duplicate_open_draft_rejected(world: SeededWorld) -> None:
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)
    with tenant_session(ctx) as sess:
        line_id, form_id = _line_id(sess, TaxFormCode.F1120, "1a")
        propose_mapping(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="a", scope=AccessScope.FIRM, form_id=form_id,
            proposal=MappingProposal(account_id=a1.revenue_account_id, line_id=line_id),
        )
        with pytest.raises(TaxMappingError):
            propose_mapping(
                sess, firm_id=a1.firm_id, client_id=a1.client_id,
                actor="a", scope=AccessScope.FIRM, form_id=form_id,
                proposal=MappingProposal(account_id=a1.revenue_account_id, line_id=line_id),
            )


# --------------------------------------------------------------------------- #
# Worksheet generation
# --------------------------------------------------------------------------- #
def _approve_baseline_mappings_for_a1(world: SeededWorld) -> tuple:
    """Approve mappings so a1's revenue+expense both have a tax line on 1120.

    Returns (line_id_for_revenue, line_id_for_expense, form_id).
    """
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)
    with tenant_session(ctx) as sess:
        rev_line_id, form_id = _line_id(sess, TaxFormCode.F1120, "1a")
        exp_line_id, _ = _line_id(sess, TaxFormCode.F1120, "26")  # Other deductions
        m_rev = propose_mapping(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="a", scope=AccessScope.FIRM, form_id=form_id,
            proposal=MappingProposal(account_id=a1.revenue_account_id, line_id=rev_line_id),
        )
        m_exp = propose_mapping(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="a", scope=AccessScope.FIRM, form_id=form_id,
            proposal=MappingProposal(account_id=a1.expense_account_id, line_id=exp_line_id),
        )
        approve_mapping(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="b", scope=AccessScope.FIRM, mapping_id=m_rev.id,
        )
        approve_mapping(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="b", scope=AccessScope.FIRM, mapping_id=m_exp.id,
        )
    return rev_line_id, exp_line_id, form_id


def test_worksheet_blocks_when_active_account_unmapped(world: SeededWorld) -> None:
    _post_baseline_activity(world.a1)  # revenue + expense both have activity
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)
    with tenant_session(ctx) as sess:
        # Only map revenue, leave expense unmapped.
        rev_line_id, form_id = _line_id(sess, TaxFormCode.F1120, "1a")
        m_rev = propose_mapping(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="a", scope=AccessScope.FIRM, form_id=form_id,
            proposal=MappingProposal(account_id=a1.revenue_account_id, line_id=rev_line_id),
        )
        approve_mapping(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="b", scope=AccessScope.FIRM, mapping_id=m_rev.id,
        )
    with tenant_session(ctx) as sess:
        with pytest.raises(UnmappedAccountsError) as exc_info:
            generate_worksheet(
                sess, firm_id=a1.firm_id, client_id=a1.client_id,
                actor="b", scope=AccessScope.FIRM,
                period_id=a1.period_id, form_code=TaxFormCode.F1120,
            )
        # The unmapped expense account must be in the error payload.
        unmapped_codes = {code for _, code, _ in exc_info.value.accounts}
        assert "5000" in unmapped_codes


def test_worksheet_blocks_when_drafts_pending(world: SeededWorld) -> None:
    _post_baseline_activity(world.a1)
    _approve_baseline_mappings_for_a1(world)

    # Seed a pending draft directly. We do not need the full ingest pipeline
    # for this; just the row.
    from datetime import UTC, datetime

    from app.models.accounting import DraftClassification, SourceDocument
    from app.models.enums import DraftKind, DraftStatus, OcrStatus

    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)
    with tenant_session(ctx) as sess:
        src_id = uuid4()
        sess.add(
            SourceDocument(
                id=src_id, firm_id=a1.firm_id, client_id=a1.client_id,
                kind="generic", storage_uri="memory://x", sha256="abc",
                ocr_status=OcrStatus.COMPLETE,
                ocr_completed_at=datetime.now(tz=UTC),
            )
        )
        sess.flush()
        sess.add(
            DraftClassification(
                firm_id=a1.firm_id, client_id=a1.client_id,
                source_document_id=src_id,
                kind=DraftKind.GENERIC, status=DraftStatus.PENDING_REVIEW,
                needs_review=True, high_confidence=False,
                confidence=Decimal("0.5"),
                model="mock", prompt_version="v1",
                payload={},
            )
        )
    with tenant_session(ctx) as sess:
        with pytest.raises(TaxWorksheetGenerationError):
            generate_worksheet(
                sess, firm_id=a1.firm_id, client_id=a1.client_id,
                actor="b", scope=AccessScope.FIRM,
                period_id=a1.period_id, form_code=TaxFormCode.F1120,
            )


def test_worksheet_amounts_tie_to_ledger(world: SeededWorld) -> None:
    _post_baseline_activity(world.a1)
    rev_line_id, exp_line_id, form_id = _approve_baseline_mappings_for_a1(world)
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)

    with tenant_session(ctx) as sess:
        ws = generate_worksheet(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="b", scope=AccessScope.FIRM,
            period_id=a1.period_id, form_code=TaxFormCode.F1120,
        )
        ws_id = ws.id

    with tenant_session(ctx) as sess:
        ws = sess.get(TaxWorksheet, ws_id)
        lines = sess.execute(
            select(TaxWorksheetLine).where(TaxWorksheetLine.worksheet_id == ws_id)
        ).scalars().all()
        amounts_by_code = {ln.line_code: ln.amount for ln in lines}
        # Revenue 1,200 -> line 1a (gross receipts).
        assert amounts_by_code["1a"] == D("1200")
        # Expense 300 -> line 26 (other deductions).
        assert amounts_by_code["26"] == D("300")
        # All other lines must be zero.
        for code, amt in amounts_by_code.items():
            if code not in {"1a", "26"}:
                assert amt == D("0"), f"line {code} should be 0, got {amt}"
        # Totals roll up correctly.
        assert ws.total_income == D("1200")
        assert ws.total_deductions == D("300")
        assert ws.taxable_income == D("900")
        # Supporting accounts are attached.
        rev_line = next(ln for ln in lines if ln.line_code == "1a")
        assert len(rev_line.contributing_accounts) == 1
        assert rev_line.contributing_accounts[0]["code"] == "4000"
        assert Decimal(rev_line.contributing_accounts[0]["contribution"]) == D("1200")


def test_worksheet_hash_is_deterministic(world: SeededWorld) -> None:
    _post_baseline_activity(world.a1)
    _approve_baseline_mappings_for_a1(world)
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)

    with tenant_session(ctx) as sess:
        ws1 = generate_worksheet(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="r1", scope=AccessScope.FIRM,
            period_id=a1.period_id, form_code=TaxFormCode.F1120,
        )
        ws2 = generate_worksheet(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="r2", scope=AccessScope.FIRM,
            period_id=a1.period_id, form_code=TaxFormCode.F1120,
        )
    assert ws1.sha256 == ws2.sha256


def test_approve_worksheet(world: SeededWorld) -> None:
    _post_baseline_activity(world.a1)
    _approve_baseline_mappings_for_a1(world)
    a1 = world.a1
    ctx = ctx_firm_for_client(a1.firm_id, a1.client_id)

    with tenant_session(ctx) as sess:
        ws = generate_worksheet(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="r", scope=AccessScope.FIRM,
            period_id=a1.period_id, form_code=TaxFormCode.F1120,
        )
        ws_id = ws.id
        approve_worksheet(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="approver", scope=AccessScope.FIRM,
            worksheet_id=ws_id,
        )
    with tenant_session(ctx) as sess:
        ws = sess.get(TaxWorksheet, ws_id)
        assert ws.status is TaxWorksheetStatus.APPROVED
        assert ws.approved_by == "approver"


def test_portal_cannot_generate_worksheet(world: SeededWorld) -> None:
    _post_baseline_activity(world.a1)
    _approve_baseline_mappings_for_a1(world)
    a1 = world.a1
    with tenant_session(ctx_client(a1.firm_id, a1.client_id)) as sess:
        with pytest.raises(TaxAccessForbiddenError):
            generate_worksheet(
                sess, firm_id=a1.firm_id, client_id=a1.client_id,
                actor="portal", scope=AccessScope.CLIENT,
                period_id=a1.period_id, form_code=TaxFormCode.F1120,
            )


# --------------------------------------------------------------------------- #
# Isolation
# --------------------------------------------------------------------------- #
def test_firm_b_cannot_see_firm_a_mappings_or_worksheets(world: SeededWorld) -> None:
    _post_baseline_activity(world.a1)
    _approve_baseline_mappings_for_a1(world)
    a1 = world.a1
    ctx_a = ctx_firm_for_client(a1.firm_id, a1.client_id)
    with tenant_session(ctx_a) as sess:
        ws = generate_worksheet(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="r", scope=AccessScope.FIRM,
            period_id=a1.period_id, form_code=TaxFormCode.F1120,
        )
        ws_id = ws.id

    # Firm B staff — must see nothing.
    b1 = world.b1
    ctx_b = ctx_firm_for_client(b1.firm_id, b1.client_id)
    with tenant_session(ctx_b) as sess:
        assert sess.get(TaxWorksheet, ws_id) is None
        # No mapping rows from firm A leak in.
        rows = sess.execute(select(TaxAccountMapping)).scalars().all()
        assert rows == []


def test_portal_cannot_read_other_clients_worksheet(world: SeededWorld) -> None:
    _post_baseline_activity(world.a1)
    _approve_baseline_mappings_for_a1(world)
    a1 = world.a1
    a2 = world.a2
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        ws = generate_worksheet(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="r", scope=AccessScope.FIRM,
            period_id=a1.period_id, form_code=TaxFormCode.F1120,
        )
        ws_id = ws.id
        approve_worksheet(
            sess, firm_id=a1.firm_id, client_id=a1.client_id,
            actor="r", scope=AccessScope.FIRM,
            worksheet_id=ws_id,
        )
    # Portal user attached to client a2 — must not see a1's worksheet.
    with tenant_session(ctx_client(a2.firm_id, a2.client_id)) as sess:
        assert sess.get(TaxWorksheet, ws_id) is None
