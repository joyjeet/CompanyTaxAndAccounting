"""Auto-promote high-confidence drafts into journal entries.

Runs after `run_classification` writes a `DraftClassification` with
status=PENDING_REVIEW. If the draft is high-confidence AND the client has
the accounts + open period needed to post a sensible journal entry, this
module promotes the draft automatically via `promote_draft()`.

This is demo / convenience plumbing — it does NOT replace the CPA review
flow:
  * Low-confidence drafts are never auto-promoted.
  * Drafts where the proposed account is missing from the client's chart of
    accounts are never auto-promoted (the draft stays PENDING_REVIEW).
  * Auto-promotion uses `actor="system:auto-promote"` so the audit trail
    distinguishes auto-posts from human-promoted ones.

Heuristics (kept intentionally narrow):
  * `bank_transaction` with `proposed_account_code` + numeric `amount`:
    - amount >= 0 (debit / outflow): DR proposed / CR 1000 (Cash)
    - amount <  0 (credit / inflow): DR 1000 (Cash) / CR proposed
  * `invoice` with numeric `total`:  DR 5000 (Office Expense) / CR 2000 (A/P)
  * `receipt` with numeric `total`:  DR 5000 (Office Expense) / CR 1000 (Cash)
  * Anything else: not auto-promoted.

The amount must be parseable as a positive Decimal; a missing/zero amount
skips auto-promotion (draft stays for human review).
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tenant import AccessScope
from app.domain.promotion import PromoteLineInput, promote_draft
from app.models.accounting import (
    AccountingPeriod,
    ChartOfAccounts,
    DraftClassification,
)
from app.models.enums import DraftKind, DraftStatus

logger = logging.getLogger(__name__)

# Confidence threshold for auto-promotion. Mirrors classification.py.
AUTO_PROMOTE_THRESHOLD = Decimal("0.85")

CASH_CODE = "1000"
AP_CODE = "2000"
EXPENSE_DEFAULT_CODE = "5000"


def auto_promote_eligible_drafts(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
) -> list[UUID]:
    """Find pending high-confidence drafts for this client and promote them.

    Returns the list of newly-posted journal-entry ids. Drafts that don't
    meet the heuristics are left in PENDING_REVIEW so the CPA can handle
    them. Failures during promotion are logged but never re-raised.
    """
    drafts = (
        sess.execute(
            select(DraftClassification)
            .where(
                DraftClassification.client_id == client_id,
                DraftClassification.status == DraftStatus.PENDING_REVIEW,
                DraftClassification.high_confidence.is_(True),
                DraftClassification.confidence >= AUTO_PROMOTE_THRESHOLD,
            )
        )
        .scalars()
        .all()
    )
    if not drafts:
        return []

    accounts = _load_accounts_by_code(sess, client_id=client_id)
    period = _open_period_for(sess, client_id=client_id, on=date.today())
    if period is None:
        logger.info(
            "auto_promote: no open period for client; %d drafts left for review",
            len(drafts),
            extra={"client_id": str(client_id)},
        )
        return []

    posted_ids: list[UUID] = []
    for draft in drafts:
        try:
            je_id = _try_promote(
                sess,
                firm_id=firm_id,
                client_id=client_id,
                draft=draft,
                accounts=accounts,
                period=period,
            )
        except Exception:  # noqa: BLE001 — never let auto-promote break upload
            logger.exception(
                "auto_promote failed for draft",
                extra={"draft_id": str(draft.id), "client_id": str(client_id)},
            )
            continue
        if je_id is not None:
            posted_ids.append(je_id)
    return posted_ids


# --------------------------------------------------------------------------- #
def _load_accounts_by_code(
    sess: Session, *, client_id: UUID
) -> dict[str, ChartOfAccounts]:
    rows = (
        sess.execute(
            select(ChartOfAccounts).where(
                ChartOfAccounts.client_id == client_id,
                ChartOfAccounts.is_active.is_(True),
            )
        )
        .scalars()
        .all()
    )
    return {a.code: a for a in rows}


def _open_period_for(
    sess: Session, *, client_id: UUID, on: date
) -> AccountingPeriod | None:
    return (
        sess.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.client_id == client_id,
                AccountingPeriod.is_locked.is_(False),
                AccountingPeriod.start_date <= on,
                AccountingPeriod.end_date >= on,
            )
        )
        .scalars()
        .first()
    )


def _clamp_to_period(d: date, period: AccountingPeriod) -> date:
    if d < period.start_date:
        return period.start_date
    if d > period.end_date:
        return period.end_date
    return d


def _try_promote(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    draft: DraftClassification,
    accounts: dict[str, ChartOfAccounts],
    period: AccountingPeriod,
) -> UUID | None:
    """Apply the heuristic and call promote_draft. Returns je_id or None."""
    payload = draft.payload or {}
    today = date.today()
    entry_date = _clamp_to_period(today, period)

    pair = _propose_lines(draft.kind, payload, accounts)
    if pair is None:
        return None
    debit_code, credit_code, amount, memo = pair

    debit_acct = accounts.get(debit_code)
    credit_acct = accounts.get(credit_code)
    if debit_acct is None or credit_acct is None:
        logger.info(
            "auto_promote skipped: missing account",
            extra={
                "draft_id": str(draft.id),
                "debit_code": debit_code,
                "credit_code": credit_code,
                "have_codes": sorted(accounts.keys()),
            },
        )
        return None

    je_id = promote_draft(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor="system:auto-promote",
        scope=AccessScope.FIRM,
        draft_id=draft.id,
        period_id=period.id,
        entry_date=entry_date,
        lines=[
            PromoteLineInput(account_id=debit_acct.id, debit=amount),
            PromoteLineInput(account_id=credit_acct.id, credit=amount),
        ],
        memo=memo,
    )

    # Stamp the draft with a hint that this was auto-promoted (extra metadata
    # for the UI). DraftClassification.payload is mutable JSON.
    draft.payload = {
        **(draft.payload or {}),
        "_auto_promoted": True,
        "_auto_promoted_at": datetime.now(tz=UTC).isoformat(),
    }
    sess.flush()
    return je_id


def _propose_lines(
    kind: DraftKind,
    payload: dict,
    accounts: dict[str, ChartOfAccounts],
) -> tuple[str, str, Decimal, str] | None:
    """Return (debit_code, credit_code, amount, memo) or None to skip."""
    if kind is DraftKind.BANK_TRANSACTION:
        code = (payload.get("proposed_account_code") or "").strip()
        if not code:
            return None
        amount = _parse_amount(payload.get("amount"))
        if amount is None or amount == 0:
            return None
        memo = payload.get("memo") or payload.get("merchant") or "Bank transaction (auto)"
        if amount > 0:
            # Outflow: DR expense / CR Cash
            return (code, CASH_CODE, amount, str(memo))
        # Inflow: DR Cash / CR account (revenue or AR offset)
        return (CASH_CODE, code, -amount, str(memo))

    if kind is DraftKind.INVOICE:
        amount = _parse_amount(payload.get("total"))
        if amount is None or amount <= 0:
            return None
        vendor = payload.get("vendor") or "Invoice"
        memo = f"Invoice from {vendor} (auto)"
        return (EXPENSE_DEFAULT_CODE, AP_CODE, amount, memo)

    if kind is DraftKind.RECEIPT:
        amount = _parse_amount(payload.get("total"))
        if amount is None or amount <= 0:
            return None
        memo = payload.get("merchant") or "Receipt (auto)"
        return (EXPENSE_DEFAULT_CODE, CASH_CODE, amount, str(memo))

    return None


def _parse_amount(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


__all__ = [
    "AUTO_PROMOTE_THRESHOLD",
    "auto_promote_eligible_drafts",
]
