"""Tests for the promotion service.

Carry-forward principle: the only way a draft becomes a journal entry is
through `promote_draft()`, which routes through `LedgerService.post()`. So:
  * Approved + balanced -> entry posted, draft marked promoted.
  * Approved + unbalanced -> LedgerService refuses; nothing posted.
  * Client-portal user -> forbidden.
  * Already-promoted -> conflict.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.session import tenant_session
from app.db.tenant import AccessScope
from app.domain.exceptions import UnbalancedJournalEntryError
from app.domain.ingest import ingest_document
from app.domain.promotion import (
    AlreadyPromotedError,
    PromoteLineInput,
    PromotionForbiddenError,
    promote_draft,
    reject_draft,
)
from app.integrations.account_categorizer import load_rules_from_file
from app.models.accounting import (
    DraftClassification,
    JournalEntry,
    JournalLine,
    SourceDocument,
)
from app.models.enums import DraftKind, DraftStatus, OcrStatus
from app.workers.jobs import dispatch_payload
from tests.conftest import SeededWorld, ctx_firm_for_client


def _seed_draft(world: SeededWorld, fake_integrations):
    a1 = world.a1
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        ingest_document(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="staff",
            data=b"ACME COFFEE 03/15 $4.25",
            filename="r.pdf",
            content_type="application/pdf",
            kind_hint="bank_transaction",
            storage=fake_integrations.storage,
            queue=fake_integrations.queue,
        )
    for payload in [p for _, p in fake_integrations.queue.drain("extract")]:
        dispatch_payload(payload)
    for payload in [p for _, p in fake_integrations.queue.drain("classify")]:
        dispatch_payload(payload)
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        d = sess.execute(select(DraftClassification)).scalars().one()
        return d.id


def test_promote_balanced_creates_journal_entry(
    world: SeededWorld, fake_integrations
) -> None:
    a1 = world.a1
    draft_id = _seed_draft(world, fake_integrations)
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        je_id = promote_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="reviewer@acme",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
            entry_date=date(2026, 3, 15),
            lines=[
                PromoteLineInput(
                    account_id=a1.expense_account_id, debit=Decimal("4.25"),
                    description="Coffee",
                ),
                PromoteLineInput(
                    account_id=a1.cash_account_id, credit=Decimal("4.25"),
                ),
            ],
            memo="Coffee run",
        )

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        je = sess.get(JournalEntry, je_id)
        assert je is not None
        lines = sess.execute(
            select(JournalLine).where(JournalLine.entry_id == je_id)
        ).scalars().all()
        assert sum((ln.debit for ln in lines), Decimal("0")) == Decimal("4.25")
        assert sum((ln.credit for ln in lines), Decimal("0")) == Decimal("4.25")
        d = sess.get(DraftClassification, draft_id)
        assert d is not None
        assert d.status is DraftStatus.PROMOTED
        assert d.promoted_journal_entry_id == je_id


def test_promote_unbalanced_refuses(world: SeededWorld, fake_integrations) -> None:
    a1 = world.a1
    draft_id = _seed_draft(world, fake_integrations)
    with pytest.raises(UnbalancedJournalEntryError):
        with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
            promote_draft(
                sess,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                actor="reviewer@acme",
                scope=AccessScope.FIRM,
                draft_id=draft_id,
                period_id=a1.period_id,
                entry_date=date(2026, 3, 15),
                lines=[
                    PromoteLineInput(
                        account_id=a1.expense_account_id, debit=Decimal("4.25"),
                    ),
                    PromoteLineInput(
                        account_id=a1.cash_account_id, credit=Decimal("4.00"),
                    ),
                ],
            )

    # Draft still pending; no JE was posted.
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        d = sess.get(DraftClassification, draft_id)
        assert d is not None
        assert d.status is DraftStatus.PENDING_REVIEW
        assert sess.execute(select(JournalEntry)).scalars().all() == []


def test_promote_forbidden_for_client_scope(
    world: SeededWorld, fake_integrations
) -> None:
    a1 = world.a1
    draft_id = _seed_draft(world, fake_integrations)
    with pytest.raises(PromotionForbiddenError):
        with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
            promote_draft(
                sess,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                actor="portal-user",
                scope=AccessScope.CLIENT,  # client cannot promote
                draft_id=draft_id,
                period_id=a1.period_id,
                entry_date=date(2026, 3, 15),
                lines=[
                    PromoteLineInput(
                        account_id=a1.expense_account_id, debit=Decimal("4.25"),
                    ),
                    PromoteLineInput(
                        account_id=a1.cash_account_id, credit=Decimal("4.25"),
                    ),
                ],
            )


def test_promote_already_promoted_conflict(
    world: SeededWorld, fake_integrations
) -> None:
    a1 = world.a1
    draft_id = _seed_draft(world, fake_integrations)
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        promote_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="r",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
            entry_date=date(2026, 3, 15),
            lines=[
                PromoteLineInput(
                    account_id=a1.expense_account_id, debit=Decimal("1"),
                ),
                PromoteLineInput(
                    account_id=a1.cash_account_id, credit=Decimal("1"),
                ),
            ],
        )

    with pytest.raises(AlreadyPromotedError):
        with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
            promote_draft(
                sess,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                actor="r",
                scope=AccessScope.FIRM,
                draft_id=draft_id,
                period_id=a1.period_id,
                entry_date=date(2026, 3, 15),
                lines=[
                    PromoteLineInput(
                        account_id=a1.expense_account_id, debit=Decimal("1"),
                    ),
                    PromoteLineInput(
                        account_id=a1.cash_account_id, credit=Decimal("1"),
                    ),
                ],
            )


def test_reject_marks_terminal(world: SeededWorld, fake_integrations) -> None:
    a1 = world.a1
    draft_id = _seed_draft(world, fake_integrations)
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        reject_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="r",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            reason="garbage",
        )
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        d = sess.get(DraftClassification, draft_id)
        assert d is not None
        assert d.status is DraftStatus.REJECTED


def test_promote_single_draft_learns_override_into_rules_yaml(
    world: SeededWorld,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a1 = world.a1
    doc_id = uuid4()
    draft_id = uuid4()
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        sess.add(
            SourceDocument(
                id=doc_id,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                kind=DraftKind.BANK_TRANSACTION.value,
                original_filename="txn.pdf",
                mime_type="application/pdf",
                sha256="0" * 64,
                storage_uri="mock://test/txn.pdf",
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
                confidence=Decimal("0.70"),
                model="mock",
                prompt_version="mock-v1",
                payload={
                    "description": "ACH Payment ACME Services",
                    "amount": "22.00",
                    "direction": "payment",
                    "proposed_account_code": "4000",
                },
            )
        )

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
        _ = promote_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="reviewer",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
            entry_date=date(2026, 3, 15),
            lines=[
                PromoteLineInput(account_id=a1.expense_account_id, debit=Decimal("22.00")),
                PromoteLineInput(account_id=a1.cash_account_id, credit=Decimal("22.00")),
            ],
            memo="Review override",
        )

    learned = load_rules_from_file(rules_file)
    assert learned[0].target_code == "5000"
    assert learned[0].conditions[0].field == "direction"
    assert learned[0].conditions[0].value == "payment"
    assert learned[0].conditions[1].field == "description"
    assert learned[0].conditions[1].operator == "contains"
    assert learned[0].conditions[1].value == "ach payment acme services"
