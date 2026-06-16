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
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.db.tenant import AccessScope
from app.domain.ingest import VirusScanError, ingest_document
from app.integrations.registry import get_queue, get_storage
from app.models.accounting import SourceDocument

router = APIRouter(prefix="/documents", tags=["documents"])


class UploadOut(BaseModel):
    source_document_id: UUID
    storage_uri: str
    sha256: str
    deduped: bool
    job_id: str | None


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


@router.post(
    "/upload",
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: UploadFile = File(...),
    kind_hint: str = Form("generic"),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> UploadOut:
    """Upload a single document.

    The caller must be either FIRM-scope (with a client_id selected) or
    CLIENT-scope. We require client_id to be set on the identity so we know
    which client owns the document.
    """
    if identity.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id must be present in identity to upload a document.",
        )
    if identity.scope is AccessScope.CLIENT and identity.client_id != identity.client_id:
        # No-op; left here as the place to add cross-checks if scope semantics evolve.
        pass

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="empty upload",
        )

    try:
        result = ingest_document(
            sess,
            firm_id=identity.firm_id,
            client_id=identity.client_id,
            actor=identity.subject,
            data=data,
            filename=file.filename,
            content_type=file.content_type,
            kind_hint=kind_hint,
            storage=get_storage(),
            queue=get_queue(),
        )
    except VirusScanError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"virus scan rejected upload: {e}",
        ) from e

    return UploadOut(
        source_document_id=result.source_document_id,
        storage_uri=result.storage_uri,
        sha256=result.sha256,
        deduped=result.deduped,
        job_id=result.job_id,
    )
