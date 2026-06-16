"""End-to-end document ingestion pipeline tests.

The carry-forward principle from Phase 1 is the most important assertion in
this file: ALL these tests must end with `journal_entry` empty. AI never
auto-posts.
"""
from __future__ import annotations

from sqlalchemy import select

from app.db.session import tenant_session
from app.domain.ingest import ingest_document
from app.models.accounting import (
    DraftClassification,
    JournalEntry,
    SourceDocument,
)
from app.models.enums import DraftStatus, OcrStatus
from app.workers.jobs import dispatch_payload
from tests.conftest import SeededWorld, ctx_firm_for_client


def test_full_pipeline_creates_draft_no_journal_entry(
    world: SeededWorld, fake_integrations
) -> None:
    """Upload -> extract -> classify -> draft created. ZERO journal entries."""
    a1 = world.a1
    payload_bytes = b"ACME COFFEE 03/15 $4.25"

    # Step 1: ingest synchronously
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        result = ingest_document(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="staff@acme",
            data=payload_bytes,
            filename="receipt.pdf",
            content_type="application/pdf",
            kind_hint="bank_transaction",
            storage=fake_integrations.storage,
            queue=fake_integrations.queue,
        )

    assert result.deduped is False
    assert result.job_id is not None

    # The queue should have one extract job. Drain and dispatch.
    extract_jobs = fake_integrations.queue.drain("extract")
    assert len(extract_jobs) == 1
    _job_id, payload = extract_jobs[0]
    dispatch_payload(payload)

    # Now there should be a classify job; dispatch it too.
    classify_jobs = fake_integrations.queue.drain("classify")
    assert len(classify_jobs) == 1
    _, classify_payload = classify_jobs[0]
    dispatch_payload(classify_payload)

    # Verify state: source_document is OCR-complete + a draft row exists, NO journal entry.
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        docs = sess.execute(select(SourceDocument)).scalars().all()
        assert len(docs) == 1
        assert docs[0].ocr_status is OcrStatus.COMPLETE
        assert docs[0].extracted is not None

        drafts = sess.execute(select(DraftClassification)).scalars().all()
        assert len(drafts) == 1
        assert drafts[0].status is DraftStatus.PENDING_REVIEW
        assert drafts[0].source_document_id == docs[0].id
        # CRITICAL: no journal entries.
        assert sess.execute(select(JournalEntry)).scalars().all() == []


def test_ingest_is_idempotent_on_identical_bytes(
    world: SeededWorld, fake_integrations
) -> None:
    a1 = world.a1
    data = b"some bytes"
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        first = ingest_document(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="staff",
            data=data,
            filename="x.pdf",
            content_type="application/pdf",
            kind_hint="generic",
            storage=fake_integrations.storage,
            queue=fake_integrations.queue,
        )
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        second = ingest_document(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="staff",
            data=data,
            filename="x.pdf",
            content_type="application/pdf",
            kind_hint="generic",
            storage=fake_integrations.storage,
            queue=fake_integrations.queue,
        )
    assert second.deduped is True
    assert second.source_document_id == first.source_document_id
    assert second.job_id is None  # no second extract job

    # And only ONE source_document exists
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        rows = sess.execute(select(SourceDocument)).scalars().all()
        assert len(rows) == 1


def test_extraction_failure_marks_status_failed_and_no_classify_enqueued(
    world: SeededWorld, fake_integrations
) -> None:
    a1 = world.a1

    # Force the extractor to raise.
    class _BoomExtractor:
        def extract(self, *, data, mime_type, kind):  # noqa: ANN001
            raise RuntimeError("boom")

    from app.integrations import registry

    registry.set_extractor(_BoomExtractor())

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        result = ingest_document(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="staff",
            data=b"will fail",
            filename="x.pdf",
            content_type="application/pdf",
            kind_hint="bank_transaction",
            storage=fake_integrations.storage,
            queue=fake_integrations.queue,
        )

    extract_jobs = fake_integrations.queue.drain("extract")
    assert len(extract_jobs) == 1
    _, payload = extract_jobs[0]
    dispatch_payload(payload)

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        doc = sess.get(SourceDocument, result.source_document_id)
        assert doc is not None
        assert doc.ocr_status is OcrStatus.FAILED
        assert doc.ocr_error is not None
    # No classify job was enqueued.
    assert fake_integrations.queue.drain("classify") == []
