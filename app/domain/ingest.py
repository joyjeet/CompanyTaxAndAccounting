"""Document ingestion.

Boundary between "bytes have arrived from the user" and "we have a tracked
SourceDocument row plus an enqueued extraction job".

Critical safety properties:
  * Bytes are written to per-tenant storage by `StorageService.put()`. The
    storage layer computes the path from the tenant identity, so the caller
    cannot influence where the blob lands.
  * Idempotency: hash(file) is recorded; an upload of identical bytes for the
    same client returns the existing SourceDocument and DOES NOT re-enqueue
    extraction.
  * Virus scan is a stub (`scan_clean()`); the real impl will call Defender /
    Malware Scanning for Storage. We block ingestion on a positive scan.
  * Audit row is written on every successful ingest.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.audit import write_audit
from app.integrations.ocr import azure_model_for
from app.integrations.storage import StorageService, sha256_hex
from app.models.accounting import SourceDocument
from app.models.enums import AuditAction, OcrStatus
from app.workers.queue import JobQueue


# --------------------------------------------------------------------------- #
# Stubs to be replaced by Defender / Microsoft Defender for Storage.
# --------------------------------------------------------------------------- #
class VirusScanError(Exception):
    """Raised when the AV scan flags the bytes as malicious."""


def scan_clean(data: bytes) -> None:
    """Stub virus scanner. Production impl posts to Defender; for tests we
    simply detect the well-known EICAR test string and raise.
    """
    EICAR = (
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    )
    if EICAR in data:
        raise VirusScanError("EICAR test string detected; refusing to store.")


# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class IngestResult:
    source_document_id: UUID
    storage_uri: str
    sha256: str
    deduped: bool  # True if we found an existing SourceDocument for this hash
    job_id: str | None  # None if deduped


# --------------------------------------------------------------------------- #
def ingest_document(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    data: bytes,
    filename: str | None,
    content_type: str | None,
    kind_hint: str = "generic",
    storage: StorageService,
    queue: JobQueue,
    queue_name: str = "extract",
) -> IngestResult:
    """Persist bytes as a SourceDocument and enqueue an extraction job.

    Idempotent on (client_id, sha256). The caller is responsible for the RLS
    context: `sess` MUST already be a tenant_session bound to (firm_id,
    client_id, scope=firm). The function double-checks that the passed
    firm_id/client_id match the GUCs by writing rows that include them; RLS
    policies will reject any mismatch.
    """
    scan_clean(data)
    digest = sha256_hex(data)

    # Idempotency check: have we already stored this (client_id, sha256)?
    existing = sess.execute(
        select(SourceDocument).where(
            SourceDocument.client_id == client_id,
            SourceDocument.sha256 == digest,
        )
    ).scalars().first()
    if existing is not None:
        return IngestResult(
            source_document_id=existing.id,
            storage_uri=existing.storage_uri,
            sha256=digest,
            deduped=True,
            job_id=None,
        )

    # Write blob via StorageService — path computed from tenant identity.
    stored = storage.put(
        firm_id=firm_id,
        client_id=client_id,
        doc_type=_doc_type_for_kind(kind_hint),
        data=data,
        filename=filename,
        content_type=content_type,
    )
    assert stored.sha256 == digest  # storage hashed the same bytes

    src = SourceDocument(
        firm_id=firm_id,
        client_id=client_id,
        kind=kind_hint,
        storage_uri=stored.storage_uri,
        sha256=stored.sha256,
        original_filename=filename,
        mime_type=content_type,
        ocr_status=OcrStatus.PENDING,
        uploaded_by=actor,
    )
    sess.add(src)
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=AuditAction.INGEST,
        entity_type="source_document",
        entity_id=src.id,
        details={
            "storage_uri": stored.storage_uri,
            "sha256": stored.sha256,
            "size": stored.size,
            "kind_hint": kind_hint,
            "azure_model": azure_model_for(kind_hint),
        },
    )

    # Enqueue extraction. Payload carries tenant context so the worker can
    # rebuild the same tenant_session.
    job_id = queue.enqueue(
        queue_name,
        {
            "type": "extract",
            "firm_id": str(firm_id),
            "client_id": str(client_id),
            "scope": "firm",
            "actor": actor,
            "source_document_id": str(src.id),
            "kind_hint": kind_hint,
        },
    )

    return IngestResult(
        source_document_id=src.id,
        storage_uri=stored.storage_uri,
        sha256=stored.sha256,
        deduped=False,
        job_id=job_id,
    )


_KIND_TO_DOC_TYPE = {
    "bank_transaction": "bank",
    "tax_form_w2": "tax",
    "tax_form_1099_nec": "tax",
    "tax_form_1099_int": "tax",
    "tax_form_1098": "tax",
    "invoice": "invoice",
    "receipt": "receipt",
    "generic": "generic",
}


def _doc_type_for_kind(kind: str) -> str:
    return _KIND_TO_DOC_TYPE.get(kind, "generic")


__all__ = [
    "IngestResult",
    "VirusScanError",
    "ingest_document",
    "scan_clean",
]
