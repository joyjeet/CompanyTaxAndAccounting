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
from app.models.accounting import AccountingPeriod, ChartOfAccounts, DraftClassification
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


# --------------------------------------------------------------------------- #
# Bank-statement promotion: a single draft can carry N transactions; each
# becomes its own balanced journal entry.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class StatementPromotionResult:
    journal_entry_ids: list[UUID]
    skipped: list[dict[str, str]]  # [{"index": "3", "reason": "..."}]


def promote_statement_draft(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    draft_id: UUID,
    period_id: UUID,
    cash_account_code: str = "1000",
    account_overrides: dict[int, str] | None = None,
) -> StatementPromotionResult:
    """Post one balanced JE per transaction in a bank-statement draft.

    Payload contract (from `MockLLMClassifier._maybe_classify_bank_statement`):
        payload.is_statement = True
        payload.transactions = [
            {date, raw_date, description, amount, direction,
             proposed_account_code, ...},
            ...
        ]

    For each transaction:
        direction == "deposit" -> DR <cash> / CR <proposed_account_code>
        direction == "payment" -> DR <proposed_account_code> / CR <cash>

    `account_overrides` lets the reviewer remap individual transactions by
    index without re-running OCR (e.g. transaction 0 -> code "4100").

    Transactions whose code can't be resolved (missing from the client's
    chart of accounts) are skipped and surfaced in `skipped[]`. The
    remaining transactions still post — partial success is preferred over
    all-or-nothing for demo realism.

    The draft is marked PROMOTED iff at least one JE was posted, and
    `promoted_journal_entry_id` is set to the first posted entry. All JE
    ids are appended to `payload._posted_journal_entry_ids` for audit.
    """
    if scope is not AccessScope.FIRM:
        raise PromotionForbiddenError("Only firm-scope users can promote drafts.")

    draft = sess.get(DraftClassification, draft_id)
    if draft is None:
        raise AlreadyPromotedError("Draft not found in this tenant.")
    if draft.firm_id != firm_id or draft.client_id != client_id:
        raise AlreadyPromotedError("Draft belongs to another tenant.")
    if draft.status is not DraftStatus.PENDING_REVIEW:
        raise AlreadyPromotedError(
            f"Draft is in terminal status {draft.status.value}; cannot promote."
        )

    payload = draft.payload or {}
    if not payload.get("is_statement"):
        raise AlreadyPromotedError(
            "Draft is not a bank statement; use POST /drafts/{id}/promote instead."
        )
    txns = payload.get("transactions") or []
    if not txns:
        raise AlreadyPromotedError("Statement draft has no transactions to post.")

    # Load period + chart of accounts (keyed by code, then by id).
    period = sess.get(AccountingPeriod, period_id)
    if period is None or period.client_id != client_id:
        raise PromotionForbiddenError("Period not found in this tenant.")
    if period.is_locked:
        raise PromotionForbiddenError("Period is locked; cannot post entries.")

    from sqlalchemy import select as _select  # local import to avoid cycle

    accounts_by_code = {
        a.code: a
        for a in sess.execute(
            _select(ChartOfAccounts).where(
                ChartOfAccounts.client_id == client_id,
                ChartOfAccounts.is_active.is_(True),
            )
        )
        .scalars()
        .all()
    }
    cash_acct = accounts_by_code.get(cash_account_code)
    if cash_acct is None:
        raise PromotionForbiddenError(
            f"Cash account '{cash_account_code}' not found in this client's chart "
            "of accounts."
        )

    overrides = account_overrides or {}
    posted_ids: list[UUID] = []
    skipped: list[dict[str, str]] = []
    ledger = LedgerService(sess, firm_id=firm_id, client_id=client_id, actor=actor)

    def _clamp(d: date) -> date:
        if d < period.start_date:
            return period.start_date
        if d > period.end_date:
            return period.end_date
        return d

    for idx, txn in enumerate(txns):
        code = overrides.get(idx) or txn.get("proposed_account_code") or ""
        code = str(code).strip()
        if not code:
            skipped.append({"index": str(idx), "reason": "no account code"})
            continue
        other_acct = accounts_by_code.get(code)
        if other_acct is None:
            skipped.append(
                {
                    "index": str(idx),
                    "reason": f"account code '{code}' not in chart of accounts",
                }
            )
            continue

        try:
            amount = Decimal(str(txn.get("amount", "0")).replace(",", ""))
        except (ValueError, ArithmeticError):
            skipped.append({"index": str(idx), "reason": "unparseable amount"})
            continue
        if amount <= 0:
            skipped.append({"index": str(idx), "reason": "amount must be > 0"})
            continue

        direction = (txn.get("direction") or "").lower()
        if direction == "deposit":
            lines = [
                LineInput(account_id=cash_acct.id, debit=amount),
                LineInput(account_id=other_acct.id, credit=amount),
            ]
        elif direction == "payment":
            lines = [
                LineInput(account_id=other_acct.id, debit=amount),
                LineInput(account_id=cash_acct.id, credit=amount),
            ]
        else:
            skipped.append(
                {"index": str(idx), "reason": f"unknown direction '{direction}'"}
            )
            continue

        # Parse the txn's ISO date (set by the parser); fall back to period start.
        entry_date = period.start_date
        iso = (txn.get("date") or "").strip()
        if iso:
            try:
                entry_date = _clamp(date.fromisoformat(iso))
            except ValueError:
                pass

        memo = (txn.get("description") or "")[:120] or "Bank statement transaction"

        entry = ledger.post(
            period_id=period_id,
            entry_date=entry_date,
            lines=lines,
            memo=memo,
            source_document_id=draft.source_document_id,
        )
        posted_ids.append(entry.id)

    if not posted_ids:
        raise AlreadyPromotedError(
            "No transactions could be posted; draft left in pending review."
        )

    draft.status = DraftStatus.PROMOTED
    draft.promoted_journal_entry_id = posted_ids[0]
    draft.reviewed_at = datetime.now(tz=UTC)
    draft.reviewed_by = actor
    draft.payload = {
        **(draft.payload or {}),
        "_posted_journal_entry_ids": [str(j) for j in posted_ids],
        "_posted_count": len(posted_ids),
        "_skipped": skipped,
    }
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
            "journal_entry_ids": [str(j) for j in posted_ids],
            "skipped_count": len(skipped),
            "period_id": str(period_id),
            "kind": "bank_statement",
        },
    )

    return StatementPromotionResult(
        journal_entry_ids=posted_ids, skipped=skipped
    )


__all__ = [
    "AlreadyPromotedError",
    "PromoteLineInput",
    "PromotionForbiddenError",
    "promote_draft",
    "promote_statement_draft",
    "reject_draft",
]
