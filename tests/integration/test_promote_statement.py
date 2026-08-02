"""Tests for `promote_statement_draft`.

Covers the multi-transaction bank-statement promotion path: one balanced
JE per row in `payload.transactions`, with skipped rows surfaced rather
than aborting the batch.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.session import tenant_session
from app.db.tenant import AccessScope
from app.domain.promotion import (
    AlreadyPromotedError,
    promote_statement_draft,
)
from app.integrations.account_categorizer import load_rules_from_file
from app.models.accounting import (
    AccountingPeriod,
    DraftClassification,
    JournalEntry,
    JournalLine,
    SourceDocument,
)
from app.models.enums import (
    DraftKind,
    DraftStatus,
    OcrStatus,
)
from tests.conftest import SeededWorld, ctx_firm_for_client


def _seed_statement_draft(
    a1, *, transactions: list[dict]
) -> tuple[object, object]:
    """Insert a SourceDocument + statement-shaped DraftClassification.

    Returns (document_id, draft_id).
    """
    doc_id = uuid4()
    draft_id = uuid4()
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        sess.add(
            SourceDocument(
                id=doc_id,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                kind=DraftKind.BANK_TRANSACTION.value,
                original_filename="statement.pdf",
                mime_type="application/pdf",
                sha256="0" * 64,
                storage_uri="mock://test/statement.pdf",
                ocr_status=OcrStatus.COMPLETE,
                uploaded_by="tester",
            )
        )
        sess.flush()
        sess.add(
            DraftClassification(
                id=draft_id,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                source_document_id=doc_id,
                kind=DraftKind.BANK_TRANSACTION,
                status=DraftStatus.PENDING_REVIEW,
                needs_review=True,
                high_confidence=False,
                confidence=Decimal("0.80"),
                model="mock-bank-statement",
                prompt_version="mock-v1",
                payload={
                    "is_statement": True,
                    "account_holder": "Test LLC",
                    "statement_period": "Jul 01 2026 - Jul 31 2026",
                    "beginning_balance": "1000.00",
                    "ending_balance": "1500.00",
                    "transactions": transactions,
                    "_reasons": ["unit-test seed"],
                },
            )
        )
    return doc_id, draft_id


def test_promote_statement_posts_one_je_per_transaction(
    world: SeededWorld,
) -> None:
    a1 = world.a1
    txns = [
        {
            "date": "2026-07-05",
            "raw_date": "07/05",
            "description": "Square deposit",
            "amount": "500.00",
            "direction": "deposit",
            "section": "deposits",
            "proposed_account_code": "4000",  # Revenue
        },
        {
            "date": "2026-07-15",
            "raw_date": "07/15",
            "description": "Office supplies",
            "amount": "40.00",
            "direction": "payment",
            "section": "electronic payments",
            "proposed_account_code": "5000",  # Office Expense
        },
    ]
    _, draft_id = _seed_statement_draft(a1, transactions=txns)

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        result = promote_statement_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="reviewer",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
            cash_account_code="1000",
        )

    assert len(result.journal_entry_ids) == 2
    assert result.skipped == []

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        entries = (
            sess.execute(
                select(JournalEntry).where(
                    JournalEntry.id.in_(result.journal_entry_ids)
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) == 2
        for je in entries:
            lines = (
                sess.execute(
                    select(JournalLine).where(JournalLine.entry_id == je.id)
                )
                .scalars()
                .all()
            )
            debit = sum((ln.debit for ln in lines), Decimal("0"))
            credit = sum((ln.credit for ln in lines), Decimal("0"))
            assert debit == credit > 0

        # Deposit (DR Cash 500 / CR Revenue 500)
        je_deposit = next(je for je in entries if je.memo == "Square deposit")
        deposit_lines = (
            sess.execute(
                select(JournalLine)
                .where(JournalLine.entry_id == je_deposit.id)
                .order_by(JournalLine.debit.desc())
            )
            .scalars()
            .all()
        )
        assert deposit_lines[0].account_id == a1.cash_account_id
        assert deposit_lines[0].debit == Decimal("500.00")
        assert deposit_lines[1].account_id == a1.revenue_account_id
        assert deposit_lines[1].credit == Decimal("500.00")

        # Payment (DR Expense 40 / CR Cash 40)
        je_payment = next(je for je in entries if je.memo == "Office supplies")
        payment_lines = (
            sess.execute(
                select(JournalLine)
                .where(JournalLine.entry_id == je_payment.id)
                .order_by(JournalLine.debit.desc())
            )
            .scalars()
            .all()
        )
        assert payment_lines[0].account_id == a1.expense_account_id
        assert payment_lines[0].debit == Decimal("40.00")
        assert payment_lines[1].account_id == a1.cash_account_id
        assert payment_lines[1].credit == Decimal("40.00")

        # Draft marked PROMOTED with both IDs recorded in payload.
        d = sess.get(DraftClassification, draft_id)
        assert d is not None
        assert d.status is DraftStatus.PROMOTED
        assert d.promoted_journal_entry_id == result.journal_entry_ids[0]
        assert d.payload["_posted_count"] == 2
        assert len(d.payload["_posted_journal_entry_ids"]) == 2


def test_promote_statement_skips_unknown_account_codes(
    world: SeededWorld,
) -> None:
    a1 = world.a1
    txns = [
        {
            "date": "2026-07-05",
            "raw_date": "07/05",
            "description": "Square deposit",
            "amount": "500.00",
            "direction": "deposit",
            "proposed_account_code": "4000",  # exists
        },
        {
            "date": "2026-07-10",
            "raw_date": "07/10",
            "description": "Mystery transfer",
            "amount": "75.00",
            "direction": "payment",
            "proposed_account_code": "9999",  # NOT in seed COA
        },
    ]
    _, draft_id = _seed_statement_draft(a1, transactions=txns)

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        result = promote_statement_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="reviewer",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
        )

    assert len(result.journal_entry_ids) == 1
    assert len(result.skipped) == 1
    assert result.skipped[0]["index"] == "1"
    assert "9999" in result.skipped[0]["reason"]


def test_promote_statement_account_overrides(world: SeededWorld) -> None:
    a1 = world.a1
    txns = [
        {
            "date": "2026-07-05",
            "raw_date": "07/05",
            "description": "Misrouted to suspense",
            "amount": "100.00",
            "direction": "payment",
            "proposed_account_code": "9999",  # Reviewer must remap this.
        },
    ]
    _, draft_id = _seed_statement_draft(a1, transactions=txns)

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        result = promote_statement_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="reviewer",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
            account_overrides={0: "5000"},  # Reviewer picks Office Expense.
        )

    assert len(result.journal_entry_ids) == 1
    assert result.skipped == []


def test_promote_statement_honors_accept_reject_indexes(
    world: SeededWorld,
) -> None:
    a1 = world.a1
    txns = [
        {
            "date": "2026-07-05",
            "raw_date": "07/05",
            "description": "Accepted deposit",
            "amount": "100.00",
            "direction": "deposit",
            "proposed_account_code": "4000",
        },
        {
            "date": "2026-07-06",
            "raw_date": "07/06",
            "description": "Rejected payment",
            "amount": "25.00",
            "direction": "payment",
            "proposed_account_code": "5000",
        },
    ]
    _, draft_id = _seed_statement_draft(a1, transactions=txns)

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        result = promote_statement_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="reviewer",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
            accepted_indexes={0},
            rejected_indexes={1},
        )

    assert len(result.journal_entry_ids) == 1
    assert len(result.skipped) == 1
    assert result.skipped[0]["index"] == "1"
    assert "rejected by reviewer" in result.skipped[0]["reason"]


def test_promote_statement_explicit_accept_confirms_low_confidence_row(
    world: SeededWorld,
) -> None:
    a1 = world.a1
    txns = [
        {
            "date": "2026-07-05",
            "raw_date": "07/05",
            "description": "Low confidence payment",
            "amount": "100.00",
            "direction": "payment",
            "proposed_account_code": "5000",
            "_categorizer_needs_review": True,
            "_categorizer_confidence": 0.45,
        },
    ]
    _, draft_id = _seed_statement_draft(a1, transactions=txns)

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        result = promote_statement_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="reviewer",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
            accepted_indexes={0},
        )

    assert len(result.journal_entry_ids) == 1
    assert result.skipped == []


def test_promote_statement_persists_override_into_rules_file(
    world: SeededWorld,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a1 = world.a1
    txns = [
        {
            "date": "2026-07-05",
            "raw_date": "07/05",
            "description": "Staples order 123",
            "amount": "45.00",
            "direction": "payment",
            "proposed_account_code": "9999",
        },
    ]
    _, draft_id = _seed_statement_draft(a1, transactions=txns)

    rules_file = tmp_path / "categorization_rules.yaml"
    rules_file.write_text(
        (
            "rules:\n"
            "  - name: Existing\n"
            "    target_code: \"4000\"\n"
            "    match: all\n"
            "    conditions:\n"
            "      - field: description\n"
            "        operator: contains\n"
            "        value: square\n"
        ),
        encoding="utf-8",
    )

    class _Settings:
        app_categorizer_backend = "xero_rule_engine"
        app_categorizer_rules_file = str(rules_file)

    monkeypatch.setattr("app.domain.promotion.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.domain.promotion._reload_rules_runtime", lambda: None)

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        result = promote_statement_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="reviewer",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
            account_overrides={0: "5000"},
        )

    assert len(result.journal_entry_ids) == 1

    learned = load_rules_from_file(rules_file)
    assert learned[0].target_code == "5000"
    assert learned[0].conditions[0].field == "direction"
    assert learned[0].conditions[0].operator == "equals"
    assert learned[0].conditions[0].value == "payment"
    assert learned[0].conditions[1].field == "description"
    assert learned[0].conditions[1].operator == "contains"
    assert learned[0].conditions[1].value == "staples order"


def test_promote_statement_uses_open_period_for_transaction_date(
    world: SeededWorld,
) -> None:
    """Rows post against the open period that covers each transaction date."""
    a1 = world.a1

    period_2025_id = uuid4()
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        sess.add(
            AccountingPeriod(
                id=period_2025_id,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                name="2025",
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
                is_locked=False,
            )
        )

    txns = [
        {
            "date": "2026-07-05",  # inside the period
            "description": "Square deposit",
            "amount": "500.00",
            "direction": "deposit",
            "proposed_account_code": "4000",
        },
        {
            "date": "2025-12-28",  # outside selected period, but in open 2025 period
            "description": "Prior-year payment",
            "amount": "60.00",
            "direction": "payment",
            "proposed_account_code": "5000",
        },
    ]
    _, draft_id = _seed_statement_draft(a1, transactions=txns)

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        result = promote_statement_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="reviewer",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
        )

    assert len(result.journal_entry_ids) == 2
    assert result.skipped == []

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        entries = (
            sess.execute(
                select(JournalEntry).where(
                    JournalEntry.id.in_(result.journal_entry_ids)
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) == 2
        by_date = {je.entry_date: je for je in entries}
        assert date(2026, 7, 5) in by_date
        assert date(2025, 12, 28) in by_date

        je_2026 = by_date[date(2026, 7, 5)]
        je_2025 = by_date[date(2025, 12, 28)]
        assert je_2026.period_id == a1.period_id
        assert je_2025.period_id == period_2025_id


def test_promote_statement_falls_back_to_selected_period_when_no_open_period_covers_dates(
    world: SeededWorld,
) -> None:
    """A wholly-mismatched date range still posts via selected-period fallback."""
    a1 = world.a1
    txns = [
        {
            "date": "2025-07-05",
            "description": "Square deposit",
            "amount": "500.00",
            "direction": "deposit",
            "proposed_account_code": "4000",
        },
        {
            "date": "2025-07-15",
            "description": "Office supplies",
            "amount": "40.00",
            "direction": "payment",
            "proposed_account_code": "5000",
        },
    ]
    _, draft_id = _seed_statement_draft(a1, transactions=txns)

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        result = promote_statement_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="reviewer",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
        )

    assert len(result.journal_entry_ids) == 2
    assert result.skipped == []

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        entries = (
            sess.execute(
                select(JournalEntry).where(
                    JournalEntry.id.in_(result.journal_entry_ids)
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) == 2
        assert all(je.period_id == a1.period_id for je in entries)
        # Both 2025 dates clamp to selected period start (2026-01-01).
        assert all(je.entry_date == date(2026, 1, 1) for je in entries)


def test_promote_statement_skips_unparseable_dates(world: SeededWorld) -> None:
    a1 = world.a1
    txns = [
        {
            "date": "07/05/2026",  # not ISO 8601
            "description": "Square deposit",
            "amount": "500.00",
            "direction": "deposit",
            "proposed_account_code": "4000",
        },
    ]
    _, draft_id = _seed_statement_draft(a1, transactions=txns)

    with pytest.raises(AlreadyPromotedError):
        with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
            promote_statement_draft(
                sess,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                actor="reviewer",
                scope=AccessScope.FIRM,
                draft_id=draft_id,
                period_id=a1.period_id,
            )


def test_promote_statement_undated_row_falls_back_to_period_start(
    world: SeededWorld,
) -> None:
    """A row the parser could not date still posts, at the period start.

    `bank_statement._format_date` yields "" when the statement header carries
    no inferable year. Skipping those would make such a statement post
    nothing, so the fallback is deliberate — it is the one remaining case
    where the posted date is not the transaction's own.
    """
    a1 = world.a1
    txns = [
        {
            "date": "",
            "raw_date": "07/05",
            "description": "Undated deposit",
            "amount": "500.00",
            "direction": "deposit",
            "proposed_account_code": "4000",
        },
    ]
    _, draft_id = _seed_statement_draft(a1, transactions=txns)

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        result = promote_statement_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="reviewer",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
        )

    assert len(result.journal_entry_ids) == 1
    assert result.skipped == []

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        je = sess.get(JournalEntry, result.journal_entry_ids[0])
        assert je is not None
        assert je.entry_date == date(2026, 1, 1)


def test_promote_statement_rejects_non_statement_draft(
    world: SeededWorld,
) -> None:
    a1 = world.a1
    # Build a draft WITHOUT is_statement (single-transaction shape).
    doc_id = uuid4()
    draft_id = uuid4()
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        sess.add(
            SourceDocument(
                id=doc_id,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                kind=DraftKind.BANK_TRANSACTION.value,
                original_filename="r.pdf",
                mime_type="application/pdf",
                sha256="0" * 64,
                storage_uri="mock://test/r.pdf",
                ocr_status=OcrStatus.COMPLETE,
                uploaded_by="tester",
            )
        )
        sess.flush()
        sess.add(
            DraftClassification(
                id=draft_id,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                source_document_id=doc_id,
                kind=DraftKind.BANK_TRANSACTION,
                status=DraftStatus.PENDING_REVIEW,
                needs_review=True,
                high_confidence=False,
                confidence=Decimal("0.80"),
                model="mock",
                prompt_version="mock-v1",
                payload={
                    "date": "2026-07-05",
                    "amount": "4.25",
                    "proposed_account_code": "5000",
                    "memo": "Coffee",
                },
            )
        )

    with pytest.raises(AlreadyPromotedError) as exc:
        with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
            promote_statement_draft(
                sess,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                actor="r",
                scope=AccessScope.FIRM,
                draft_id=draft_id,
                period_id=a1.period_id,
            )
    assert "not a bank statement" in str(exc.value)
