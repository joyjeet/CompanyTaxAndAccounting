"""Document upload + listing API.

* `POST /documents/upload` — bytes go in, a SourceDocument row is written, an
  `extract` job is enqueued, and the caller gets back the source document id.
  The pipeline does NOT post any journal entry here.
* `GET  /documents` — list documents visible under the caller's tenant
  context. RLS does the filtering (firm-scope sees the firm's docs;
  client-scope sees only their own).

Tenant context is taken ONLY from the authenticated identity (via the
`db_session` dependency), so users cannot upload into / read from a tenant
they don't have access to.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.db.session import tenant_session
from app.db.tenant import AccessScope, TenantContext
from app.domain.audit import write_audit
from app.domain.auto_promote import auto_promote_eligible_drafts
from app.domain.ingest import VirusScanError, ingest_document
from app.integrations.registry import get_queue, get_storage
from app.models.accounting import (
    Client,
    DraftClassification,
    JournalEntry,
    SourceDocument,
)
from app.models.enums import AuditAction
from app.workers.inline import drain_in_process

router = APIRouter(prefix="/documents", tags=["documents"])


ALLOWED_DOCUMENT_KINDS = {
    "generic",
    "bank_transaction",
    "invoice",
    "receipt",
    "tax_form",
    "tax_form_w2",
    "tax_form_1099_nec",
    "tax_form_1099_int",
    "tax_form_1098",
}


class UploadOut(BaseModel):
    source_document_id: UUID
    storage_uri: str
    sha256: str
    deduped: bool
    job_id: str | None
    # Demo / single-process deployments: number of journal entries created by
    # auto-promotion of high-confidence drafts. 0 in production (separate
    # worker process) or when no drafts were eligible.
    auto_promoted_count: int = 0


class DocumentOut(BaseModel):
    id: UUID
    client_id: UUID
    kind: str
    filename: str | None
    content_type: str | None
    sha256: str
    ocr_status: str
    ocr_completed_at: datetime | None
    ocr_error: str | None
    received_at: datetime


class DocumentKindUpdateIn(BaseModel):
    kind: str


@router.get("", response_model=list[DocumentOut])
def list_documents(
    sess: Session = Depends(db_session),
) -> list[DocumentOut]:
    """List documents visible under the caller's tenant context.

    RLS does the filtering: firm-scope sees the firm's docs (optionally
    narrowed to a single client when `identity.client_id` is set);
    client-scope sees only its own client.
    """
    rows = (
        sess.execute(
            select(SourceDocument).order_by(SourceDocument.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        DocumentOut(
            id=d.id,
            client_id=d.client_id,
            kind=d.kind,
            filename=d.original_filename,
            content_type=d.mime_type,
            sha256=d.sha256 or "",
            ocr_status=d.ocr_status.value,
            ocr_completed_at=d.ocr_completed_at,
            ocr_error=d.ocr_error,
            received_at=d.created_at,
        )
        for d in rows
    ]


@router.post("/{document_id}/kind", response_model=DocumentOut)
def update_document_kind(
    document_id: UUID,
    body: DocumentKindUpdateIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> DocumentOut:
    """Manually correct a document kind.

    The source document remains in the same tenant/client scope (RLS enforced).
    """
    kind = (body.kind or "").strip().lower()
    if kind not in ALLOWED_DOCUMENT_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid kind: {body.kind}",
        )

    doc = sess.get(SourceDocument, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="document not found",
        )

    previous_kind = doc.kind
    doc.kind = kind
    sess.flush()

    if previous_kind != kind:
        write_audit(
            sess,
            firm_id=identity.firm_id,
            client_id=doc.client_id,
            actor=identity.subject,
            action=AuditAction.UPDATE,
            entity_type="source_document",
            entity_id=doc.id,
            details={
                "field": "kind",
                "from": previous_kind,
                "to": kind,
            },
        )

    return DocumentOut(
        id=doc.id,
        client_id=doc.client_id,
        kind=doc.kind,
        filename=doc.original_filename,
        content_type=doc.mime_type,
        sha256=doc.sha256 or "",
        ocr_status=doc.ocr_status.value,
        ocr_completed_at=doc.ocr_completed_at,
        ocr_error=doc.ocr_error,
        received_at=doc.created_at,
    )


@router.post(
    "/upload",
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: UploadFile = File(...),
    kind_hint: str = Form("generic"),
    client_id: UUID | None = Form(None),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> UploadOut:
    """Upload a single document.

    Resolution of which client owns the upload:
      * If `client_id` is supplied as a form field, it is authoritative.
        - For FIRM scope, the client must belong to the caller's firm (RLS
          enforces this; we additionally return 404 with a clear message).
        - For CLIENT scope, the supplied value must equal the identity's
          client_id (else 403). This guards against a client portal user
          accidentally targeting another tenant.
      * Otherwise we fall back to `identity.client_id`. Sessions minted
        with the client_id baked in (the historical path) continue to work
        unchanged.
    """
    # 1. Resolve the effective client_id.
    if client_id is not None:
        if (
            identity.scope is AccessScope.CLIENT
            and client_id != identity.client_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="client_id does not match authenticated client identity",
            )
        effective_client_id = client_id
    else:
        if identity.client_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "client_id is required: pass it as a form field, or sign in "
                    "with a client_id-scoped token."
                ),
            )
        effective_client_id = identity.client_id

    # 2. For FIRM scope, verify the client is visible under this firm's RLS
    #    context. (CLIENT scope already validated above.)
    if identity.scope is AccessScope.FIRM:
        exists = sess.execute(
            select(Client.id).where(Client.id == effective_client_id)
        ).scalar_one_or_none()
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"client {effective_client_id} not found in this firm",
            )

    # 3. Read and validate the upload bytes.
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty upload",
        )

    queue = get_queue()
    try:
        result = ingest_document(
            sess,
            firm_id=identity.firm_id,
            client_id=effective_client_id,
            actor=identity.subject,
            data=data,
            filename=file.filename,
            content_type=file.content_type,
            kind_hint=kind_hint,
            storage=get_storage(),
            queue=queue,
        )
    except VirusScanError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"virus scan rejected upload: {e}",
        ) from e

    # In deployments without a separate worker process (the demo), drain the
    # in-memory queue inline so extraction + classification finish inside
    # this request and a draft is immediately visible in the Review Queue.
    # For Redis-backed deployments this is a no-op; the real worker handles
    # the jobs asynchronously.
    auto_promoted_count = 0
    if not result.deduped:
        # Commit so the inline dispatcher's fresh tenant_session sees the
        # SourceDocument row we just wrote. The outer dependency commit
        # afterwards is a safe no-op on an already-clean session.
        sess.commit()
        drain_in_process(queue)
        # After classify, try to auto-post high-confidence drafts. We open a
        # fresh tenant_session because the outer `sess`'s SET LOCAL RLS vars
        # are scoped to its already-committed transaction; a query here would
        # silently return zero rows.
        if identity.scope is AccessScope.FIRM:
            ctx = TenantContext(
                firm_id=identity.firm_id,
                client_id=effective_client_id,
                scope=AccessScope.FIRM,
            )
            with tenant_session(ctx) as ap_sess:
                posted = auto_promote_eligible_drafts(
                    ap_sess,
                    firm_id=identity.firm_id,
                    client_id=effective_client_id,
                )
            auto_promoted_count = len(posted)

    return UploadOut(
        source_document_id=result.source_document_id,
        storage_uri=result.storage_uri,
        sha256=result.sha256,
        deduped=result.deduped,
        job_id=result.job_id,
        auto_promoted_count=auto_promoted_count,
    )


# --------------------------------------------------------------------------- #
# Document detail + download (for the "click an upload to see what's in it"
# UX so reviewers can cross-check numbers).
# --------------------------------------------------------------------------- #
class DraftRef(BaseModel):
    id: UUID
    kind: str
    status: str
    confidence: str
    promoted_journal_entry_id: UUID | None


class JournalEntryRef(BaseModel):
    id: UUID
    entry_date: str
    memo: str | None
    status: str


class DocumentDetailOut(BaseModel):
    id: UUID
    client_id: UUID
    kind: str
    filename: str | None
    content_type: str | None
    sha256: str
    storage_uri: str
    size_bytes: int | None
    ocr_status: str
    ocr_completed_at: datetime | None
    ocr_error: str | None
    received_at: datetime
    uploaded_by: str | None
    extracted: dict[str, Any] | None
    drafts: list[DraftRef]
    journal_entries: list[JournalEntryRef]


@router.get("/{document_id}", response_model=DocumentDetailOut)
def get_document(
    document_id: UUID,
    sess: Session = Depends(db_session),
) -> DocumentDetailOut:
    """Return everything we know about an uploaded document so a reviewer
    can cross-check numbers: OCR text + fields, file metadata, and the
    drafts / journal entries that were derived from it.

    Tenant isolation is enforced by RLS on the underlying session.
    """
    doc = sess.get(SourceDocument, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="document not found",
        )

    drafts = (
        sess.execute(
            select(DraftClassification)
            .where(DraftClassification.source_document_id == document_id)
            .order_by(DraftClassification.created_at.asc())
        )
        .scalars()
        .all()
    )

    entries = (
        sess.execute(
            select(JournalEntry)
            .where(JournalEntry.source_document_id == document_id)
            .order_by(JournalEntry.entry_date.asc())
        )
        .scalars()
        .all()
    )

    extracted = doc.extracted if isinstance(doc.extracted, dict) else None
    size_bytes: int | None = None
    if extracted is not None:
        sb = extracted.get("size_bytes")
        if isinstance(sb, int):
            size_bytes = sb

    return DocumentDetailOut(
        id=doc.id,
        client_id=doc.client_id,
        kind=doc.kind,
        filename=doc.original_filename,
        content_type=doc.mime_type,
        sha256=doc.sha256 or "",
        storage_uri=doc.storage_uri,
        size_bytes=size_bytes,
        ocr_status=doc.ocr_status.value,
        ocr_completed_at=doc.ocr_completed_at,
        ocr_error=doc.ocr_error,
        received_at=doc.created_at,
        uploaded_by=doc.uploaded_by,
        extracted=extracted,
        drafts=[
            DraftRef(
                id=d.id,
                kind=d.kind.value,
                status=d.status.value,
                confidence=str(d.confidence),
                promoted_journal_entry_id=d.promoted_journal_entry_id,
            )
            for d in drafts
        ],
        journal_entries=[
            JournalEntryRef(
                id=e.id,
                entry_date=e.entry_date.isoformat(),
                memo=e.memo,
                status=e.status.value,
            )
            for e in entries
        ],
    )


@router.get("/{document_id}/download")
def download_document(
    document_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> Response:
    """Stream the original uploaded file bytes back to the caller so the
    user can preview the source (PDF / image / text) that drove a draft.

    Access is gated by RLS on `sess.get(SourceDocument, ...)`. The storage
    layer additionally re-checks that the storage_uri belongs to the
    caller's firm+client tenant prefix.
    """
    doc = sess.get(SourceDocument, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="document not found",
        )

    storage = get_storage()
    try:
        data = storage.get(
            firm_id=identity.firm_id,
            client_id=doc.client_id,
            storage_uri=doc.storage_uri,
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(e)
        ) from e
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="document bytes not found in storage",
        ) from e

    filename = doc.original_filename or f"{doc.id}"
    return Response(
        content=data,
        media_type=doc.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=60",
        },
    )
