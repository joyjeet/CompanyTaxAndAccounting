"""Draft -> ledger promotion.

The ONLY path from AI output to the journal_entry/journal_line ledger. Always
goes through `LedgerService.post()` so the balance invariant is enforced and
audit + RLS posture stays uniform.

Access control:
  * Promotion is gated to firm-scope users (`AccessScope.FIRM`). Client-portal
    users (`AccessScope.CLIENT`) cannot promote.
  * The reviewer's identity is recorded on the draft (reviewed_by / reviewed_at).

Idempotency:
  * Trying to promote an already-promoted draft raises `AlreadyPromotedError`.
  * Trying to reject an already-handled draft raises `AlreadyPromotedError`
    (overloaded message — see the error class).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.tenant import AccessScope
from app.domain.audit import write_audit
from app.domain.exceptions import DomainError
from app.domain.ledger import LedgerService, LineInput
from app.models.accounting import DraftClassification
from app.models.enums import AuditAction, DraftStatus


class PromotionForbiddenError(DomainError):
    """Caller's access scope does not permit promotion."""


class AlreadyPromotedError(DomainError):
    """Draft has already been promoted, rejected, or otherwise terminal."""


@dataclass(frozen=True, slots=True)
class PromoteLineInput:
    account_id: UUID
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    description: str | None = None


def promote_draft(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    draft_id: UUID,
    period_id: UUID,
    entry_date: date,
    lines: list[PromoteLineInput],
    memo: str | None = None,
) -> UUID:
    """Promote `draft_id` into a posted journal entry. Returns entry id.

    Refuses if:
      * scope != FIRM
      * draft already in a terminal status
      * draft cross-tenant (RLS would already mask it; we double-check)
      * journal entry would be unbalanced (LedgerService refuses)
    """
    if scope is not AccessScope.FIRM:
        raise PromotionForbiddenError("Only firm-scope users can promote drafts.")

    draft = sess.get(DraftClassification, draft_id)
    if draft is None:
        raise AlreadyPromotedError("Draft not found in this tenant.")
    if draft.firm_id != firm_id or draft.client_id != client_id:
        # RLS should have prevented this; defensive check.
        raise AlreadyPromotedError("Draft belongs to another tenant.")
    if draft.status is not DraftStatus.PENDING_REVIEW:
        raise AlreadyPromotedError(
            f"Draft is in terminal status {draft.status.value}; cannot promote."
        )

    ledger = LedgerService(sess, firm_id=firm_id, client_id=client_id, actor=actor)
    entry = ledger.post(
        period_id=period_id,
        entry_date=entry_date,
        lines=[
            LineInput(
                account_id=ln.account_id,
                debit=ln.debit,
                credit=ln.credit,
                description=ln.description,
            )
            for ln in lines
        ],
        memo=memo,
        source_document_id=draft.source_document_id,
    )

    draft.status = DraftStatus.PROMOTED
    draft.promoted_journal_entry_id = entry.id
    draft.reviewed_at = datetime.now(tz=UTC)
    draft.reviewed_by = actor
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=AuditAction.PROMOTE,
        entity_type="draft_classification",
        entity_id=draft.id,
        details={
            "journal_entry_id": str(entry.id),
            "period_id": str(period_id),
            "memo": memo,
        },
    )
    return entry.id


def reject_draft(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    draft_id: UUID,
    reason: str | None = None,
) -> None:
    if scope is not AccessScope.FIRM:
        raise PromotionForbiddenError("Only firm-scope users can reject drafts.")

    draft = sess.get(DraftClassification, draft_id)
    if draft is None:
        raise AlreadyPromotedError("Draft not found in this tenant.")
    if draft.firm_id != firm_id or draft.client_id != client_id:
        raise AlreadyPromotedError("Draft belongs to another tenant.")
    if draft.status is not DraftStatus.PENDING_REVIEW:
        raise AlreadyPromotedError(
            f"Draft is in terminal status {draft.status.value}; cannot reject."
        )

    draft.status = DraftStatus.REJECTED
    draft.reviewed_at = datetime.now(tz=UTC)
    draft.reviewed_by = actor
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=AuditAction.REJECT,
        entity_type="draft_classification",
        entity_id=draft.id,
        details={"reason": reason},
    )


__all__ = [
    "AlreadyPromotedError",
    "PromoteLineInput",
    "PromotionForbiddenError",
    "promote_draft",
    "reject_draft",
]
