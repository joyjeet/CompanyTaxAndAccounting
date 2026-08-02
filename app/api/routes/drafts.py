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
    learn_statement_rule,
    promote_draft,
    promote_statement_draft,
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


def _resolve_promote_client_id(
    sess: Session,
    *,
    draft_id: UUID,
    identity: AuthIdentity,
    body_client_id: UUID | None,
) -> UUID:
    if identity.client_id is not None:
        return identity.client_id
    if body_client_id is not None:
        return body_client_id

    draft = sess.get(DraftClassification, draft_id)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="draft not found",
        )
    return draft.client_id


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
    client_id: UUID | None = None
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
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only firm-scope users can promote drafts.",
        )

    client_id = _resolve_promote_client_id(
        sess,
        draft_id=draft_id,
        identity=identity,
        body_client_id=body.client_id,
    )

    try:
        je_id = promote_draft(
            sess,
            firm_id=identity.firm_id,
            client_id=client_id,
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
# Statement promote-all — one balanced JE per transaction in payload.transactions.
class StatementPromoteIn(BaseModel):
    client_id: UUID | None = None
    period_id: UUID
    cash_account_code: str = "1000"
    # Optional remap: {"3": "4100", "7": "5200"} — transaction index -> code.
    # Keyed as strings so JSON-from-the-wire stays clean.
    account_overrides: dict[str, str] | None = None
    # Optional row decisions from the review UI.
    accepted_indexes: list[int] | None = None
    rejected_indexes: list[int] | None = None


class StatementPromoteOut(BaseModel):
    journal_entry_ids: list[UUID]
    skipped: list[dict[str, str]]
    posted_indexes: list[int]
    excluded_indexes: list[int]
    pending_indexes: list[int]
    review_complete: bool
    learned_rule_count: int


class LearnRuleIn(BaseModel):
    client_id: UUID | None = None
    transaction_index: int
    target_account_code: str


class LearnRuleOut(BaseModel):
    learned_rule_count: int


@router.post("/{draft_id}/promote-all", response_model=StatementPromoteOut)
def promote_all(
    draft_id: UUID,
    body: StatementPromoteIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> StatementPromoteOut:
    """Post every transaction in a bank-statement draft as its own JE."""
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only firm-scope users can promote drafts.",
        )

    client_id = _resolve_promote_client_id(
        sess,
        draft_id=draft_id,
        identity=identity,
        body_client_id=body.client_id,
    )

    # Coerce string keys -> int.
    overrides: dict[int, str] | None = None
    if body.account_overrides:
        overrides = {}
        for k, v in body.account_overrides.items():
            try:
                overrides[int(k)] = v
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"account_overrides keys must be integers; got '{k}'.",
                ) from None

    try:
        result = promote_statement_draft(
            sess,
            firm_id=identity.firm_id,
            client_id=client_id,
            actor=identity.subject,
            scope=identity.scope,
            draft_id=draft_id,
            period_id=body.period_id,
            cash_account_code=body.cash_account_code,
            account_overrides=overrides,
            accepted_indexes=set(body.accepted_indexes or []),
            rejected_indexes=set(body.rejected_indexes or []),
        )
    except PromotionForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except AlreadyPromotedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return StatementPromoteOut(
        journal_entry_ids=result.journal_entry_ids,
        skipped=result.skipped,
        posted_indexes=result.posted_indexes,
        excluded_indexes=result.excluded_indexes,
        pending_indexes=result.pending_indexes,
        review_complete=result.review_complete,
        learned_rule_count=result.learned_rule_count,
    )


@router.post("/{draft_id}/learn-rule", response_model=LearnRuleOut)
def learn_rule(
    draft_id: UUID,
    body: LearnRuleIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> LearnRuleOut:
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only firm-scope users can learn rules.",
        )

    client_id = _resolve_promote_client_id(
        sess,
        draft_id=draft_id,
        identity=identity,
        body_client_id=body.client_id,
    )

    try:
        learned = learn_statement_rule(
            sess,
            firm_id=identity.firm_id,
            client_id=client_id,
            scope=identity.scope,
            draft_id=draft_id,
            transaction_index=body.transaction_index,
            target_account_code=body.target_account_code,
        )
    except PromotionForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except AlreadyPromotedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    return LearnRuleOut(learned_rule_count=learned)


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
