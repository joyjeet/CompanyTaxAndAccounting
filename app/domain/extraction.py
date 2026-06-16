"""OCR extraction stage.

Pulls the bytes back out of storage, calls the configured DocumentExtractor,
persists the structured `extracted` JSON onto SourceDocument, and enqueues
classification.

The extractor is allowed to fail. When it does we set `ocr_status=FAILED`,
record the error, and do NOT enqueue classification. A separate retry/replay
mechanism (later) will re-trigger.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.audit import write_audit
from app.integrations.ocr import DocumentExtractor
from app.integrations.storage import StorageService
from app.models.accounting import SourceDocument
from app.models.enums import AuditAction, OcrStatus
from app.workers.queue import JobQueue


def run_extraction(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    source_document_id: UUID,
    kind_hint: str,
    storage: StorageService,
    extractor: DocumentExtractor,
    queue: JobQueue,
    queue_name: str = "classify",
) -> bool:
    """Run OCR for `source_document_id`. Returns True on success.

    Caller is responsible for opening the tenant_session with matching
    (firm_id, client_id, scope). RLS will hide rows that don't belong.
    """
    doc = sess.get(SourceDocument, source_document_id)
    if doc is None:
        # Either the row was deleted or RLS hid it. Either way, nothing to do.
        return False

    # Mark in-progress so the UI can show progress.
    doc.ocr_status = OcrStatus.IN_PROGRESS
    sess.flush()

    try:
        data = storage.get(
            firm_id=firm_id, client_id=client_id, storage_uri=doc.storage_uri
        )
        result = extractor.extract(
            data=data, mime_type=doc.mime_type, kind=kind_hint
        )
    except Exception as e:
        doc.ocr_status = OcrStatus.FAILED
        doc.ocr_error = f"{type(e).__name__}: {e}"
        doc.ocr_completed_at = datetime.now(tz=UTC)
        write_audit(
            sess,
            firm_id=firm_id,
            client_id=client_id,
            actor=actor,
            action=AuditAction.EXTRACT,
            entity_type="source_document",
            entity_id=doc.id,
            details={"status": "failed", "error": doc.ocr_error},
        )
        return False

    doc.extracted = result.to_dict()
    doc.ocr_status = OcrStatus.COMPLETE
    doc.ocr_completed_at = datetime.now(tz=UTC)
    doc.ocr_error = None
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=AuditAction.EXTRACT,
        entity_type="source_document",
        entity_id=doc.id,
        details={
            "status": "complete",
            "model": result.model,
            "page_count": result.page_count,
            "field_count": len(result.fields),
        },
    )

    queue.enqueue(
        queue_name,
        {
            "type": "classify",
            "firm_id": str(firm_id),
            "client_id": str(client_id),
            "scope": "firm",
            "actor": actor,
            "source_document_id": str(doc.id),
            "kind_hint": kind_hint,
        },
    )
    return True


__all__ = ["run_extraction"]
