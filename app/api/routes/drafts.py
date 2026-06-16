"""Draft review + promotion API.

GET  /drafts                -> list drafts pending review for this tenant
POST /drafts/{id}/promote   -> human-approved post (FIRM scope only)
POST /drafts/{id}/reject    -> dismiss a draft     (FIRM scope only)

Posting only happens via `promote_draft()`, which routes through
`LedgerService.post()`, which enforces SUM(debits) == SUM(credits).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.db.tenant import AccessScope
from app.domain.promotion import (
    AlreadyPromotedError,
    PromoteLineInput,
    PromotionForbiddenError,
    promote_draft,
    reject_draft,
)
from app.models.accounting import DraftClassification
from app.models.enums import DraftStatus

router = APIRouter(prefix="/drafts", tags=["drafts"])


# --------------------------------------------------------------------------- #
class DraftOut(BaseModel):
    id: UUID
    source_document_id: UUID
    kind: str
    status: str
    confidence: Decimal
    high_confidence: bool
    needs_review: bool
    model: str
    prompt_version: str
    payload: dict


@router.get("", response_model=list[DraftOut])
def list_drafts(
    pending_only: bool = True,
    sess: Session = Depends(db_session),
) -> list[DraftOut]:
    q = select(DraftClassification)
    if pending_only:
        q = q.where(DraftClassification.status == DraftStatus.PENDING_REVIEW)
    rows = sess.execute(q).scalars().all()
    return [
        DraftOut(
            id=d.id,
            source_document_id=d.source_document_id,
            kind=d.kind.value,
            status=d.status.value,
            confidence=d.confidence,
            high_confidence=d.high_confidence,
            needs_review=d.needs_review,
            model=d.model,
            prompt_version=d.prompt_version,
            payload=d.payload,
        )
        for d in rows
    ]


# --------------------------------------------------------------------------- #
class PromoteLineIn(BaseModel):
    account_id: UUID
    debit: Decimal = Field(default=Decimal("0"))
    credit: Decimal = Field(default=Decimal("0"))
    description: str | None = None


class PromoteIn(BaseModel):
    period_id: UUID
    entry_date: date
    memo: str | None = None
    lines: list[PromoteLineIn]


class PromoteOut(BaseModel):
    journal_entry_id: UUID


@router.post("/{draft_id}/promote", response_model=PromoteOut)
def promote(
    draft_id: UUID,
    body: PromoteIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> PromoteOut:
    if identity.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id must be present in identity to promote a draft.",
        )
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only firm-scope users can promote drafts.",
        )

    try:
        je_id = promote_draft(
            sess,
            firm_id=identity.firm_id,
            client_id=identity.client_id,
            actor=identity.subject,
            scope=identity.scope,
            draft_id=draft_id,
            period_id=body.period_id,
            entry_date=body.entry_date,
            lines=[
                PromoteLineInput(
                    account_id=ln.account_id,
                    debit=ln.debit,
                    credit=ln.credit,
                    description=ln.description,
                )
                for ln in body.lines
            ],
            memo=body.memo,
        )
    except PromotionForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except AlreadyPromotedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return PromoteOut(journal_entry_id=je_id)


# --------------------------------------------------------------------------- #
class RejectIn(BaseModel):
    reason: str | None = None


@router.post("/{draft_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject(
    draft_id: UUID,
    body: RejectIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> None:
    if identity.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id must be present in identity to reject a draft.",
        )
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only firm-scope users can reject drafts.",
        )

    try:
        reject_draft(
            sess,
            firm_id=identity.firm_id,
            client_id=identity.client_id,
            actor=identity.subject,
            scope=identity.scope,
            draft_id=draft_id,
            reason=body.reason,
        )
    except PromotionForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except AlreadyPromotedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
