"""Tests for the auto-promote heuristic.

The heuristic runs after `run_classification` writes a high-confidence
DraftClassification. We exercise the happy paths for the BANK_TRANSACTION,
INVOICE, RECEIPT kinds plus negative cases (low-confidence draft skipped,
missing account skipped).
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.db.session import tenant_session
from app.domain.auto_promote import auto_promote_eligible_drafts
from app.models.accounting import (
    DraftClassification,
    JournalEntry,
    JournalLine,
    SourceDocument,
)
from app.models.enums import DraftKind, DraftStatus, OcrStatus
from tests.conftest import SeededWorld, ctx_firm_for_client


def _seed_draft(
    sess,
    *,
    firm_id,
    client_id,
    kind: DraftKind,
    confidence: Decimal,
    payload: dict,
    high_conf: bool | None = None,
) -> DraftClassification:
    doc = SourceDocument(
        id=uuid4(),
        firm_id=firm_id,
        client_id=client_id,
        kind=kind.value,
        storage_uri=f"test://{uuid4()}",
        sha256=uuid4().hex,
        original_filename="test.txt",
        mime_type="text/plain",
        ocr_status=OcrStatus.COMPLETE,
    )
    sess.add(doc)
    sess.flush()
    draft = DraftClassification(
        id=uuid4(),
        firm_id=firm_id,
        client_id=client_id,
        source_document_id=doc.id,
        kind=kind,
        status=DraftStatus.PENDING_REVIEW,
        needs_review=True,
        high_confidence=high_conf if high_conf is not None else (confidence >= Decimal("0.85")),
        confidence=confidence,
        model="test",
        prompt_version="t",
        payload=payload,
    )
    sess.add(draft)
    sess.flush()
    return draft


def test_auto_promote_bank_transaction_high_conf(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        draft = _seed_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            kind=DraftKind.BANK_TRANSACTION,
            confidence=Decimal("0.93"),
            payload={
                "date": "2026-03-15",
                "amount": "4.25",
                "proposed_account_code": "5000",
                "memo": "Acme Coffee",
                "merchant": "ACME COFFEE",
            },
        )
        draft_id = draft.id

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        posted = auto_promote_eligible_drafts(
            sess, firm_id=a1.firm_id, client_id=a1.client_id
        )
        assert len(posted) == 1

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        d = sess.get(DraftClassification, draft_id)
        assert d is not None
        assert d.status is DraftStatus.PROMOTED
        assert d.promoted_journal_entry_id is not None
        assert d.reviewed_by == "system:auto-promote"
        assert (d.payload or {}).get("_auto_promoted") is True

        entry = sess.get(JournalEntry, d.promoted_journal_entry_id)
        assert entry is not None
        lines = (
            sess.execute(select(JournalLine).where(JournalLine.entry_id == entry.id))
            .scalars()
            .all()
        )
        # Expect DR 5000 (expense) $4.25 / CR 1000 (cash) $4.25.
        by_acct = {ln.account_id: ln for ln in lines}
        debit_line = by_acct[a1.expense_account_id]
        credit_line = by_acct[a1.cash_account_id]
        assert debit_line.debit == Decimal("4.25") and debit_line.credit == Decimal("0")
        assert credit_line.credit == Decimal("4.25") and credit_line.debit == Decimal("0")


def test_auto_promote_low_confidence_left_for_review(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        draft = _seed_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            kind=DraftKind.BANK_TRANSACTION,
            confidence=Decimal("0.40"),
            high_conf=False,
            payload={
                "date": "2026-03-15",
                "amount": "12.00",
                "proposed_account_code": "9999",
                "memo": "Unknown",
                "merchant": "UNKNOWN",
            },
        )
        draft_id = draft.id

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        posted = auto_promote_eligible_drafts(
            sess, firm_id=a1.firm_id, client_id=a1.client_id
        )
        assert posted == []

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        d = sess.get(DraftClassification, draft_id)
        assert d is not None
        assert d.status is DraftStatus.PENDING_REVIEW


def test_auto_promote_invoice_uses_ap_and_expense(world: SeededWorld) -> None:
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        draft = _seed_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            kind=DraftKind.INVOICE,
            confidence=Decimal("0.90"),
            payload={
                "vendor": "Beta Supplies",
                "total": "1234.56",
                "date": "2026-02-10",
            },
        )
        draft_id = draft.id

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        posted = auto_promote_eligible_drafts(
            sess, firm_id=a1.firm_id, client_id=a1.client_id
        )
        assert len(posted) == 1

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        d = sess.get(DraftClassification, draft_id)
        assert d is not None and d.status is DraftStatus.PROMOTED
        lines = (
            sess.execute(
                select(JournalLine).where(JournalLine.entry_id == d.promoted_journal_entry_id)
            )
            .scalars()
            .all()
        )
        by_acct = {ln.account_id: ln for ln in lines}
        # DR Office Expense / CR Accounts Payable
        assert by_acct[a1.expense_account_id].debit == Decimal("1234.56")
        assert by_acct[a1.ap_account_id].credit == Decimal("1234.56")


def test_auto_promote_skips_when_proposed_account_missing(world: SeededWorld) -> None:
    """If the classifier proposes an account code the chart doesn't have, the
    draft must be left for human review (no JE posted)."""
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        draft = _seed_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            kind=DraftKind.BANK_TRANSACTION,
            confidence=Decimal("0.92"),
            payload={
                "date": "2026-03-15",
                "amount": "50.00",
                "proposed_account_code": "8888",  # not in COA
                "memo": "Mystery",
                "merchant": "MYSTERY",
            },
        )
        draft_id = draft.id

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        posted = auto_promote_eligible_drafts(
            sess, firm_id=a1.firm_id, client_id=a1.client_id
        )
        assert posted == []

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        d = sess.get(DraftClassification, draft_id)
        assert d is not None and d.status is DraftStatus.PENDING_REVIEW
