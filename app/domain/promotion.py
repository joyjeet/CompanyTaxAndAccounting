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

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.tenant import AccessScope
from app.core.config import get_settings
from app.domain.audit import write_audit
from app.domain.exceptions import DomainError
from app.integrations import registry
from app.integrations.account_categorizer import (
    CategorizationRule,
    RuleCondition,
    load_rules_from_file,
)
from app.domain.ledger import LedgerService, LineInput
from app.models.accounting import AccountingPeriod, ChartOfAccounts, DraftClassification
from app.models.enums import AuditAction, DraftStatus

try:
    import yaml
except ImportError:  # pragma: no cover - available in runtime image
    yaml = None


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
    entry_date: date,
    lines: list[PromoteLineInput],
    period_id: UUID | None = None,
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
    learned_rule_count = _learn_rule_from_single_promote(
        sess,
        draft=draft,
        lines=lines,
        memo=memo,
    )
    draft.payload = {
        **(draft.payload or {}),
        "_learned_rule_count": learned_rule_count,
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
    posted_indexes: list[int]
    excluded_indexes: list[int]
    pending_indexes: list[int]
    review_complete: bool
    learned_rule_count: int


def _resolve_rules_file() -> Path:
    settings = get_settings()
    p = Path(settings.app_categorizer_rules_file)
    if p.is_absolute():
        return p
    return Path.cwd() / p


def _reload_rules_runtime() -> None:
    # Re-wire categorizer/classifier so subsequent classifications pick up
    # newly learned rules immediately.
    registry.set_categorizer(None)
    registry.set_classifier(None)
    registry.bootstrap_from_settings()


def _rules_to_text(rules: list[CategorizationRule]) -> str:
    payload = {
        "rules": [
            {
                "name": r.name,
                "target_code": r.target_code,
                "match": r.match,
                "conditions": [
                    {
                        "field": c.field,
                        "operator": c.operator,
                        "value": c.value,
                    }
                    for c in r.conditions
                ],
            }
            for r in rules
        ]
    }
    if yaml is not None:
        return yaml.safe_dump(payload, sort_keys=False)
    return json.dumps(payload, indent=2)


def _description_rule_key(description: str) -> str:
    """Normalize a reviewer description into a stable matching key."""
    s = description.strip().lower()
    if not s:
        return ""
    # Strip volatile numeric references (check/invoice ids, etc.).
    s = re.sub(r"\b\d+\b", " ", s)
    # Keep simple searchable characters and collapse whitespace.
    s = re.sub(r"[^a-z0-9\s&/-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _learn_rules_from_overrides(
    txns: list[dict],
    overrides: dict[int, str],
) -> int:
    if not overrides:
        return 0

    settings = get_settings()
    if settings.app_categorizer_backend != "xero_rule_engine":
        return 0

    rules_file = _resolve_rules_file()
    existing_rules = list(load_rules_from_file(rules_file))

    learned: list[CategorizationRule] = []
    for idx, code in overrides.items():
        if idx < 0 or idx >= len(txns):
            continue
        txn = txns[idx]
        proposed = str(txn.get("proposed_account_code") or "").strip()
        code = str(code or "").strip()
        if not code or code == proposed:
            continue

        desc = " ".join(str(txn.get("description") or "").split())
        desc_key = _description_rule_key(desc)
        direction = str(txn.get("direction") or "").strip().lower()
        if not desc_key or direction not in {"deposit", "payment"}:
            continue

        learned.append(
            CategorizationRule(
                name=f"Learned from review: {desc[:48]}",
                target_code=code,
                match="all",
                conditions=(
                    RuleCondition("direction", "equals", direction),
                    RuleCondition("description", "contains", desc_key),
                ),
            )
        )

    if not learned:
        return 0

    # Replace any existing exact learned rule for the same direction+description;
    # otherwise prepend so reviewer corrections take precedence.
    new_rules = existing_rules.copy()
    applied = 0
    for lr in learned:
        replaced = False
        for i, r in enumerate(new_rules):
            if len(r.conditions) != 2:
                continue
            d = next((c for c in r.conditions if c.field == "direction" and c.operator == "equals"), None)
            desc = next(
                (
                    c
                    for c in r.conditions
                    if c.field == "description" and c.operator in {"equals", "contains"}
                ),
                None,
            )
            if d and desc:
                if (
                    d.value.lower() == lr.conditions[0].value.lower()
                    and _description_rule_key(desc.value) == lr.conditions[1].value
                ):
                    new_rules[i] = lr
                    replaced = True
                    applied += 1
                    break
        if not replaced:
            new_rules.insert(0, lr)
            applied += 1

    try:
        rules_file.parent.mkdir(parents=True, exist_ok=True)
        rules_file.write_text(_rules_to_text(new_rules), encoding="utf-8")
        _reload_rules_runtime()
    except Exception:
        # Rule-learning is best-effort and must not block JE posting.
        return 0
    return applied


def _learn_rule_from_single_promote(
    sess: Session,
    *,
    draft: DraftClassification,
    lines: list[PromoteLineInput],
    memo: str | None = None,
    cash_account_code: str = "1000",
) -> int:
    payload = draft.payload or {}
    if payload.get("is_statement"):
        return 0

    direction = str(payload.get("direction") or "").strip().lower()
    proposed = str(payload.get("proposed_account_code") or "").strip()
    review_description = next(
        (str(ln.description or "").strip() for ln in lines if str(ln.description or "").strip()),
        "",
    )
    description = (
        review_description
        or str(payload.get("description") or "").strip()
        or str(payload.get("memo") or "").strip()
        or str(payload.get("merchant") or "").strip()
        or str(memo or "").strip()
    )
    if direction not in {"deposit", "payment"} or not proposed or not description:
        return 0

    line_account_ids = [ln.account_id for ln in lines]
    if not line_account_ids:
        return 0

    from sqlalchemy import select as _select  # local import to avoid cycle

    accounts = (
        sess.execute(
            _select(ChartOfAccounts).where(
                ChartOfAccounts.client_id == draft.client_id,
                ChartOfAccounts.id.in_(line_account_ids),
            )
        )
        .scalars()
        .all()
    )
    by_id = {a.id: a for a in accounts}
    chosen_codes = [by_id[aid].code for aid in line_account_ids if aid in by_id]
    chosen_non_cash = [code for code in chosen_codes if code != cash_account_code]
    if not chosen_non_cash:
        return 0

    txns = [
        {
            "description": description,
            "direction": direction,
            "proposed_account_code": proposed,
        }
    ]
    return _learn_rules_from_overrides(txns, {0: chosen_non_cash[0]})


def learn_statement_rule(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    scope: AccessScope,
    draft_id: UUID,
    transaction_index: int,
    target_account_code: str,
) -> int:
    """Learn one categorization rule from a reviewed statement transaction."""
    if scope is not AccessScope.FIRM:
        raise PromotionForbiddenError("Only firm-scope users can learn rules.")

    draft = sess.get(DraftClassification, draft_id)
    if draft is None:
        raise AlreadyPromotedError("Draft not found in this tenant.")
    if draft.firm_id != firm_id or draft.client_id != client_id:
        raise AlreadyPromotedError("Draft belongs to another tenant.")

    payload = draft.payload or {}
    if not payload.get("is_statement"):
        raise PromotionForbiddenError("Only bank-statement drafts support per-row rule learning.")

    txns = payload.get("transactions") or []
    if transaction_index < 0 or transaction_index >= len(txns):
        raise PromotionForbiddenError("Transaction index is out of range for this draft.")

    learned = _learn_rules_from_overrides(
        txns,
        {transaction_index: str(target_account_code or "").strip()},
    )
    if learned <= 0:
        raise PromotionForbiddenError(
            "No rule learned. Ensure the selected account differs from the proposed "
            "account and that the row has a usable description and direction."
        )
    return learned


def promote_statement_draft(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    draft_id: UUID,
    period_id: UUID | None = None,
    cash_account_code: str = "1000",
    account_overrides: dict[int, str] | None = None,
    accepted_indexes: set[int] | None = None,
    rejected_indexes: set[int] | None = None,
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
    chart of accounts) are skipped and surfaced in `skipped[]`. The remaining
    transactions still post — partial success is preferred over
    all-or-nothing for demo realism.

    The selected `period_id` acts as the default for undated rows. Dated rows
    keep their own transaction date and are posted into whichever open
    accounting period contains that date. If no open period covers the date,
    the row still posts into the selected period at that period boundary so
    review flow is never blocked by period setup.

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

    # Load chart of accounts (keyed by code, then by id). `period_id` is
    # optional and only supplies a fallback date for rows whose date the
    # parser could not infer; it never gates or shifts a dated transaction.
    period = None
    if period_id is not None:
        period = sess.get(AccountingPeriod, period_id)
        if period is None or period.client_id != client_id:
            raise PromotionForbiddenError("Period not found in this tenant.")

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
    existing_payload = draft.payload or {}

    def _to_int_set(value: object) -> set[int]:
        out: set[int] = set()
        if not isinstance(value, list):
            return out
        for raw in value:
            try:
                n = int(raw)
            except (TypeError, ValueError):
                continue
            if n >= 0:
                out.add(n)
        return out

    existing_posted_indexes = _to_int_set(existing_payload.get("_posted_indexes"))
    existing_excluded_indexes = _to_int_set(existing_payload.get("_excluded_indexes"))
    decided_indexes = existing_posted_indexes | existing_excluded_indexes

    accepted = {i for i in (accepted_indexes or set()) if i >= 0}
    rejected = {i for i in (rejected_indexes or set()) if i >= 0}

    if accepted & rejected:
        overlap = sorted(accepted & rejected)
        raise PromotionForbiddenError(
            f"accepted_indexes and rejected_indexes overlap: {overlap}"
        )

    all_indexes = set(range(len(txns)))
    if accepted or rejected:
        target_accept = (accepted & all_indexes) - decided_indexes
        target_reject = (rejected & all_indexes) - decided_indexes
    else:
        # Backward-compatible behavior for callers that don't pass decisions:
        # post all still-pending transactions.
        target_accept = all_indexes - decided_indexes
        target_reject = set()

    if not target_accept and not target_reject:
        raise AlreadyPromotedError("No pending transactions left to process.")

    posted_ids: list[UUID] = []
    skipped: list[dict[str, str]] = []
    posted_indexes_this_call: set[int] = set()
    ledger = LedgerService(sess, firm_id=firm_id, client_id=client_id, actor=actor)

    def _resolve_entry_date(txn: dict) -> tuple[date | None, str]:
        """Resolve a transaction's posting date.

        Returns (entry_date, skip_reason). The books are continuous, so the
        transaction's own date is always honoured — it is never clamped into,
        or blocked by, an accounting period.
        """
        iso = (txn.get("date") or "").strip()
        if not iso:
            # The parser could not infer a year for this row — see
            # `bank_statement._format_date`, which yields "" when the statement
            # header carries no year. There is no date to honour, so fall back
            # to the selected period's start, or today if none was given.
            return (period.start_date if period is not None else date.today()), ""
        try:
            return date.fromisoformat(iso), ""
        except ValueError:
            return None, f"unparseable date '{iso}'"

    for idx, txn in enumerate(txns):
        if idx in target_reject:
            skipped.append({"index": str(idx), "reason": "rejected by reviewer"})
            continue
        if idx not in target_accept:
            continue

        code = overrides.get(idx) or txn.get("proposed_account_code") or ""
        code = str(code).strip()
        if not code:
            skipped.append({"index": str(idx), "reason": "no account code"})
            continue
        # If the categorizer flagged this row as needs_review (low confidence)
        # and the reviewer did NOT explicitly accept or override the code,
        # skip — the reviewer must address it before it can post.
        if (
            idx not in overrides
            and idx not in accepted
            and txn.get("_categorizer_needs_review") is True
        ):
            skipped.append(
                {
                    "index": str(idx),
                    "reason": (
                        "categorizer confidence "
                        f"{txn.get('_categorizer_confidence', 0):.2f} below "
                        "threshold — reviewer must confirm code"
                    ),
                }
            )
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

        entry_date, date_reason = _resolve_entry_date(txn)
        if entry_date is None:
            skipped.append({"index": str(idx), "reason": date_reason})
            continue

        memo = (txn.get("description") or "")[:120] or "Bank statement transaction"

        entry = ledger.post(
            entry_date=entry_date,
            lines=lines,
            memo=memo,
            source_document_id=draft.source_document_id,
        )
        posted_ids.append(entry.id)
        posted_indexes_this_call.add(idx)

    if not posted_ids and not target_reject:
        first_reason = skipped[0]["reason"] if skipped else "unknown reason"
        raise AlreadyPromotedError(
            "No transactions could be posted; draft left in pending review. "
            f"First blocking reason: {first_reason}"
        )

    learned_rule_count = _learn_rules_from_overrides(txns, overrides)

    persisted_posted_ids: list[str] = []
    for raw in existing_payload.get("_posted_journal_entry_ids", []):
        if isinstance(raw, str) and raw:
            persisted_posted_ids.append(raw)
    persisted_posted_ids.extend(str(j) for j in posted_ids)

    next_posted_indexes = sorted(existing_posted_indexes | posted_indexes_this_call)
    next_excluded_indexes = sorted(existing_excluded_indexes | target_reject)
    next_pending_indexes = sorted(
        all_indexes - set(next_posted_indexes) - set(next_excluded_indexes)
    )
    review_complete = len(next_pending_indexes) == 0

    if review_complete:
        if persisted_posted_ids:
            draft.status = DraftStatus.PROMOTED
            draft.promoted_journal_entry_id = UUID(persisted_posted_ids[0])
        else:
            draft.status = DraftStatus.REJECTED
            draft.promoted_journal_entry_id = None
        draft.reviewed_at = datetime.now(tz=UTC)
        draft.reviewed_by = actor

    draft.payload = {
        **existing_payload,
        "_posted_journal_entry_ids": persisted_posted_ids,
        "_posted_count": len(persisted_posted_ids),
        "_posted_indexes": next_posted_indexes,
        "_excluded_indexes": next_excluded_indexes,
        "_pending_indexes": next_pending_indexes,
        "_skipped": skipped,
        "_learned_rule_count": learned_rule_count,
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
            "accepted_count": len(target_accept),
            "rejected_count": len(target_reject),
            "pending_count": len(next_pending_indexes),
            "period_id": str(period_id),
            "kind": "bank_statement",
        },
    )

    return StatementPromotionResult(
        journal_entry_ids=posted_ids,
        skipped=skipped,
        posted_indexes=next_posted_indexes,
        excluded_indexes=next_excluded_indexes,
        pending_indexes=next_pending_indexes,
        review_complete=review_complete,
        learned_rule_count=learned_rule_count,
    )


__all__ = [
    "AlreadyPromotedError",
    "learn_statement_rule",
    "PromoteLineInput",
    "PromotionForbiddenError",
    "promote_draft",
    "promote_statement_draft",
    "reject_draft",
]
