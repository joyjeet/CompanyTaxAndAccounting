"""Tax-module domain services: mapping CRUD/approval + worksheet generation.

DESIGN
------
Two services live here, both deterministic and ledger-tied:

1) `TaxMappingService` — manage `tax_account_mapping` rows for a (client, form)
   pair. The reviewer-approval flow mirrors `promote_draft()`:
     * `propose()` writes a DRAFT row (reviewer-staff only; portal cannot).
     * `approve()` flips DRAFT -> APPROVED and supersedes any pre-existing
       APPROVED mapping for the same (client, form, account).
     * `reject()` flips DRAFT -> REJECTED.
   All transitions write an audit_event.

2) `TaxWorksheetService` — produce immutable snapshots.
     * `generate()` is gated:
         (a) No DraftClassification rows for the client+period are still
             PENDING_REVIEW. ("Only finalized data is exportable.")
         (b) Every CoA account with non-zero activity in the period has an
             APPROVED mapping on the chosen form. If not, raise
             `UnmappedAccountsError` listing them; do not write a partial
             worksheet.
     * Computation reuses the same aggregation pattern as
       `app/domain/statements.py`: sum debits/credits over the period (posted
       JE only), convert to signed balance, apply the mapping's `sign` token.
     * The resulting worksheet has a deterministic `sha256` computed over its
       (line_code, amount) pairs so a regenerated worksheet with identical
       inputs has an identical hash — useful for "did the numbers change?"
       checks at the package level.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.tenant import AccessScope
from app.domain.audit import write_audit
from app.domain.exceptions import DomainError
from app.models.accounting import (
    AccountingPeriod,
    ChartOfAccounts,
    DraftClassification,
    JournalEntry,
    JournalLine,
    TaxAccountMapping,
    TaxForm,
    TaxFormLine,
    TaxWorksheet,
    TaxWorksheetLine,
)
from app.models.enums import (
    AccountType,
    AuditAction,
    DraftStatus,
    JournalEntryStatus,
    TaxFormCode,
    TaxFormSection,
    TaxLineSign,
    TaxMappingStatus,
    TaxWorksheetStatus,
)

ZERO = Decimal("0")


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class TaxAccessForbiddenError(DomainError):
    """Caller's scope does not permit this tax-module action."""


class TaxMappingError(DomainError):
    """Invalid mapping mutation (already-approved, not found, etc.)."""


class TaxWorksheetGenerationError(DomainError):
    """Worksheet cannot be generated for the requested period+form."""


@dataclass(frozen=True, slots=True)
class UnmappedAccountsError(TaxWorksheetGenerationError):
    """Raised when one or more active accounts have no APPROVED mapping."""

    accounts: tuple[tuple[UUID, str, str], ...]  # (id, code, name)

    def __str__(self) -> str:
        names = ", ".join(f"{c} {n}" for _, c, n in self.accounts)
        return f"Cannot generate worksheet: unmapped active accounts: {names}"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _signed_balance(account_type: AccountType, debit: Decimal, credit: Decimal) -> Decimal:
    if account_type in (AccountType.ASSET, AccountType.EXPENSE):
        return debit - credit
    return credit - debit


def get_form_by_code(sess: Session, code: TaxFormCode) -> TaxForm:
    form = sess.execute(
        select(TaxForm).where(TaxForm.code == code)
    ).scalar_one_or_none()
    if form is None:
        raise TaxMappingError(f"Unknown tax form: {code.value}")
    return form


# --------------------------------------------------------------------------- #
# Mapping service
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class MappingProposal:
    account_id: UUID
    line_id: UUID
    sign: TaxLineSign = TaxLineSign.POSITIVE
    notes: str | None = None


def propose_mapping(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    form_id: UUID,
    proposal: MappingProposal,
) -> TaxAccountMapping:
    """Write a new DRAFT mapping. Only firm staff may propose."""
    if scope is not AccessScope.FIRM:
        raise TaxAccessForbiddenError("Only firm staff may propose tax mappings.")

    # Reject duplicate active DRAFT for the same (client, form, account):
    # one open proposal at a time.
    existing_draft = sess.execute(
        select(TaxAccountMapping).where(
            TaxAccountMapping.client_id == client_id,
            TaxAccountMapping.form_id == form_id,
            TaxAccountMapping.account_id == proposal.account_id,
            TaxAccountMapping.status == TaxMappingStatus.DRAFT,
        )
    ).scalar_one_or_none()
    if existing_draft is not None:
        raise TaxMappingError(
            "A draft mapping already exists for this account+form; "
            "approve/reject it before proposing a new one."
        )

    row = TaxAccountMapping(
        firm_id=firm_id,
        client_id=client_id,
        form_id=form_id,
        account_id=proposal.account_id,
        line_id=proposal.line_id,
        sign=proposal.sign,
        status=TaxMappingStatus.DRAFT,
        notes=proposal.notes,
        proposed_by=actor,
    )
    sess.add(row)
    sess.flush()
    write_audit(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        action=AuditAction.TAX_MAP_PROPOSE,
        entity_type="tax_account_mapping",
        entity_id=row.id,
        details={
            "form_id": str(form_id),
            "account_id": str(proposal.account_id),
            "line_id": str(proposal.line_id),
            "sign": proposal.sign.value,
        },
    )
    return row


def approve_mapping(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    mapping_id: UUID,
) -> TaxAccountMapping:
    """Flip DRAFT -> APPROVED, superseding any prior approved row for the same
    (client, form, account)."""
    if scope is not AccessScope.FIRM:
        raise TaxAccessForbiddenError("Only firm staff may approve tax mappings.")

    m = sess.get(TaxAccountMapping, mapping_id)
    if m is None or m.firm_id != firm_id or m.client_id != client_id:
        raise TaxMappingError("Mapping not found in this tenant.")
    if m.status is not TaxMappingStatus.DRAFT:
        raise TaxMappingError(
            f"Cannot approve mapping in status {m.status.value}; only DRAFT is approvable."
        )

    # Supersede any earlier APPROVED row for the same triplet.
    prior = sess.execute(
        select(TaxAccountMapping).where(
            TaxAccountMapping.client_id == client_id,
            TaxAccountMapping.form_id == m.form_id,
            TaxAccountMapping.account_id == m.account_id,
            TaxAccountMapping.status == TaxMappingStatus.APPROVED,
            TaxAccountMapping.id != m.id,
        )
    ).scalars().all()
    now = datetime.now(tz=UTC)
    for p in prior:
        p.status = TaxMappingStatus.SUPERSEDED
        p.reviewed_by = actor
        p.reviewed_at = now
    # Flush the supersession FIRST so the unique constraint
    # `uq_tax_map_client_form_acct_status` doesn't transiently see two
    # APPROVED rows for the same (client, form, account) when we flip the
    # new mapping below. Without this flush SQLAlchemy may emit the UPDATEs
    # in either order and the constraint trips intermittently.
    if prior:
        sess.flush()

    m.status = TaxMappingStatus.APPROVED
    m.reviewed_by = actor
    m.reviewed_at = now
    sess.flush()
    write_audit(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        action=AuditAction.TAX_MAP_APPROVE,
        entity_type="tax_account_mapping",
        entity_id=m.id,
        details={
            "form_id": str(m.form_id),
            "account_id": str(m.account_id),
            "line_id": str(m.line_id),
            "superseded_ids": [str(p.id) for p in prior],
        },
    )
    return m


def reject_mapping(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    mapping_id: UUID,
    reason: str | None = None,
) -> TaxAccountMapping:
    if scope is not AccessScope.FIRM:
        raise TaxAccessForbiddenError("Only firm staff may reject tax mappings.")

    m = sess.get(TaxAccountMapping, mapping_id)
    if m is None or m.firm_id != firm_id or m.client_id != client_id:
        raise TaxMappingError("Mapping not found in this tenant.")
    if m.status is not TaxMappingStatus.DRAFT:
        raise TaxMappingError(
            f"Cannot reject mapping in status {m.status.value}; only DRAFT is rejectable."
        )

    m.status = TaxMappingStatus.REJECTED
    m.reviewed_by = actor
    m.reviewed_at = datetime.now(tz=UTC)
    sess.flush()
    write_audit(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        action=AuditAction.TAX_MAP_REJECT,
        entity_type="tax_account_mapping",
        entity_id=m.id,
        details={"reason": reason},
    )
    return m


# --------------------------------------------------------------------------- #
# Auto-mapping orchestration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AutoProposeSummary:
    """Result of one auto-propose run for a (client, form)."""

    form_code: TaxFormCode
    proposed: tuple[UUID, ...]       # mapping_ids newly inserted
    skipped: tuple[tuple[str, str, str], ...]   # (code, name, reason)
    already_existed: tuple[tuple[str, str, str], ...]  # (code, name, status)


def auto_propose_for_form(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    form_code: TaxFormCode,
) -> AutoProposeSummary:
    """Walk the client's COA and write DRAFT mappings for every P&L account
    that does not already have an open DRAFT or APPROVED mapping on this form.

    Uses `app.domain.tax_automap` for the heuristic (account-name keyword
    rules + code-range fallback). Idempotent: re-running this on the same
    client+form will skip accounts that already have an open mapping.
    """
    # Lazy import to break a potential domain<->domain import cycle.
    from app.domain.tax_automap import auto_propose_mappings

    if scope is not AccessScope.FIRM:
        raise TaxAccessForbiddenError("Only firm staff may auto-propose tax mappings.")

    form = get_form_by_code(sess, form_code)

    # Load this client's full COA (RLS already constrains to firm+client when
    # the caller went through db_session, but we re-filter for safety).
    accounts = sess.execute(
        select(ChartOfAccounts).where(
            ChartOfAccounts.firm_id == firm_id,
            ChartOfAccounts.client_id == client_id,
        )
    ).scalars().all()

    lines = sess.execute(
        select(TaxFormLine).where(TaxFormLine.form_id == form.id)
    ).scalars().all()

    # Existing DRAFT/APPROVED mappings to dedupe against.
    existing = sess.execute(
        select(TaxAccountMapping).where(
            TaxAccountMapping.client_id == client_id,
            TaxAccountMapping.form_id == form.id,
            TaxAccountMapping.status.in_(
                (TaxMappingStatus.DRAFT, TaxMappingStatus.APPROVED)
            ),
        )
    ).scalars().all()
    existing_by_account: dict[UUID, TaxAccountMapping] = {
        m.account_id: m for m in existing
    }
    accounts_by_id: dict[UUID, ChartOfAccounts] = {a.id: a for a in accounts}

    result = auto_propose_mappings(
        form_code=form_code, accounts=accounts, lines=lines
    )

    proposed_ids: list[UUID] = []
    already: list[tuple[str, str, str]] = []
    for proposal in result.proposals:
        if proposal.account_id in existing_by_account:
            existing_m = existing_by_account[proposal.account_id]
            acct = accounts_by_id.get(proposal.account_id)
            already.append(
                (
                    (acct.code if acct else "") or "",
                    (acct.name if acct else "") or "",
                    existing_m.status.value,
                )
            )
            continue
        row = propose_mapping(
            sess,
            firm_id=firm_id, client_id=client_id, actor=actor, scope=scope,
            form_id=form.id, proposal=proposal,
        )
        proposed_ids.append(row.id)

    return AutoProposeSummary(
        form_code=form_code,
        proposed=tuple(proposed_ids),
        skipped=result.skipped,
        already_existed=tuple(already),
    )


def approve_all_drafts_for_form(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    form_code: TaxFormCode,
) -> tuple[UUID, ...]:
    """Bulk-approve every DRAFT mapping for (client, form). Returns the list
    of mapping_ids that were flipped to APPROVED."""
    if scope is not AccessScope.FIRM:
        raise TaxAccessForbiddenError("Only firm staff may approve tax mappings.")

    form = get_form_by_code(sess, form_code)
    drafts = sess.execute(
        select(TaxAccountMapping).where(
            TaxAccountMapping.client_id == client_id,
            TaxAccountMapping.form_id == form.id,
            TaxAccountMapping.status == TaxMappingStatus.DRAFT,
        )
    ).scalars().all()

    approved_ids: list[UUID] = []
    for m in drafts:
        approve_mapping(
            sess,
            firm_id=firm_id, client_id=client_id, actor=actor, scope=scope,
            mapping_id=m.id,
        )
        approved_ids.append(m.id)
    return tuple(approved_ids)


@dataclass(frozen=True, slots=True)
class AutoFillResult:
    auto_propose: AutoProposeSummary
    approved_mapping_ids: tuple[UUID, ...]
    worksheet: TaxWorksheet


def auto_fill_worksheet(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    period_id: UUID,
    form_code: TaxFormCode,
) -> AutoFillResult:
    """One-click: propose + approve all + generate.

    For demo / first-run UX. The reviewer can still re-review any individual
    mapping after the fact and re-generate the worksheet; the older worksheet
    remains as an audit record (worksheets are immutable).
    """
    if scope is not AccessScope.FIRM:
        raise TaxAccessForbiddenError("Only firm staff may auto-fill worksheets.")

    summary = auto_propose_for_form(
        sess, firm_id=firm_id, client_id=client_id, actor=actor, scope=scope,
        form_code=form_code,
    )
    approved = approve_all_drafts_for_form(
        sess, firm_id=firm_id, client_id=client_id, actor=actor, scope=scope,
        form_code=form_code,
    )
    ws = generate_worksheet(
        sess, firm_id=firm_id, client_id=client_id, actor=actor, scope=scope,
        period_id=period_id, form_code=form_code,
    )
    return AutoFillResult(
        auto_propose=summary,
        approved_mapping_ids=approved,
        worksheet=ws,
    )


# --------------------------------------------------------------------------- #
# Worksheet engine
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _AccountActivity:
    account_id: UUID
    code: str
    name: str
    account_type: AccountType
    debit: Decimal
    credit: Decimal

    @property
    def signed_balance(self) -> Decimal:
        return _signed_balance(self.account_type, self.debit, self.credit)


def _period_activity(
    sess: Session, *, firm_id: UUID, client_id: UUID, period: AccountingPeriod,
    account_types: Iterable[AccountType],
) -> list[_AccountActivity]:
    """Per-account activity for the period (POSTED only) for the given types."""
    type_set = tuple(account_types)
    stmt = (
        select(
            ChartOfAccounts.id,
            ChartOfAccounts.code,
            ChartOfAccounts.name,
            ChartOfAccounts.account_type,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .join(JournalLine, JournalLine.account_id == ChartOfAccounts.id, isouter=True)
        .join(
            JournalEntry,
            and_(
                JournalEntry.id == JournalLine.entry_id,
                JournalEntry.status == JournalEntryStatus.POSTED,
                JournalEntry.entry_date >= period.start_date,
                JournalEntry.entry_date <= period.end_date,
            ),
            isouter=True,
        )
        .where(
            ChartOfAccounts.firm_id == firm_id,
            ChartOfAccounts.client_id == client_id,
            ChartOfAccounts.account_type.in_(type_set),
        )
        .group_by(
            ChartOfAccounts.id,
            ChartOfAccounts.code,
            ChartOfAccounts.name,
            ChartOfAccounts.account_type,
        )
    )
    rows = sess.execute(stmt).all()
    return [
        _AccountActivity(
            account_id=r[0],
            code=r[1],
            name=r[2],
            account_type=r[3],
            debit=Decimal(str(r[4])),
            credit=Decimal(str(r[5])),
        )
        for r in rows
    ]


def _hash_lines(rows: list[tuple[str, Decimal]]) -> str:
    """Stable sha256 over (line_code, amount) pairs in sequence."""
    canonical = json.dumps(
        [(code, str(amount.quantize(Decimal("0.0001")))) for code, amount in rows],
        sort_keys=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _section_total(by_section: dict[TaxFormSection, Decimal],
                   s: TaxFormSection) -> Decimal:
    return by_section.get(s, ZERO)


def generate_worksheet(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    period_id: UUID,
    form_code: TaxFormCode,
) -> TaxWorksheet:
    """Compute and persist an immutable worksheet snapshot.

    Gates:
      * Firm scope only.
      * Period must exist in tenant.
      * No DraftClassification rows for the period+client still PENDING_REVIEW.
      * Every active P&L account (revenue/expense) for the period must have an
        APPROVED mapping for the chosen form. Cogs accounts (if modeled as
        expense type) ARE considered part of P&L for this gate.

    Side effect: regenerating for an existing (client, period, form) whose
    prior worksheet is APPROVED supersedes that prior row (status -> SUPERSEDED)
    so the catalog never carries two APPROVED snapshots for the same triple.
    """
    if scope is not AccessScope.FIRM:
        raise TaxAccessForbiddenError(
            "Only firm staff may generate tax worksheets."
        )

    period = sess.get(AccountingPeriod, period_id)
    if period is None or period.firm_id != firm_id or period.client_id != client_id:
        raise TaxWorksheetGenerationError("Accounting period not found in this tenant.")

    pending_drafts = sess.execute(
        select(func.count()).select_from(DraftClassification).where(
            DraftClassification.client_id == client_id,
            DraftClassification.status == DraftStatus.PENDING_REVIEW,
        )
    ).scalar_one()
    if pending_drafts:
        raise TaxWorksheetGenerationError(
            f"Refusing to generate worksheet: {pending_drafts} draft(s) for this "
            f"tenant are still pending review. Approve or reject them first."
        )

    form = get_form_by_code(sess, form_code)

    # Activity for income-statement accounts only (Phase 5 scope).
    activity = _period_activity(
        sess, firm_id=firm_id, client_id=client_id, period=period,
        account_types=(AccountType.REVENUE, AccountType.EXPENSE),
    )

    # Pull every APPROVED mapping for this client+form once.
    approved_rows = sess.execute(
        select(TaxAccountMapping).where(
            TaxAccountMapping.client_id == client_id,
            TaxAccountMapping.form_id == form.id,
            TaxAccountMapping.status == TaxMappingStatus.APPROVED,
        )
    ).scalars().all()
    approved_by_account: dict[UUID, TaxAccountMapping] = {
        m.account_id: m for m in approved_rows
    }

    # Gate: every account with non-zero activity must be mapped.
    unmapped: list[tuple[UUID, str, str]] = []
    for a in activity:
        if a.signed_balance == ZERO:
            continue
        if a.account_id not in approved_by_account:
            unmapped.append((a.account_id, a.code, a.name))
    if unmapped:
        raise UnmappedAccountsError(accounts=tuple(unmapped))

    # Build per-line aggregates.
    form_lines = sess.execute(
        select(TaxFormLine).where(TaxFormLine.form_id == form.id)
        .order_by(TaxFormLine.sequence)
    ).scalars().all()

    per_line_amount: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    per_line_contributors: dict[UUID, list[dict]] = defaultdict(list)

    activity_by_id = {a.account_id: a for a in activity}
    for account_id, mapping in approved_by_account.items():
        act = activity_by_id.get(account_id)
        if act is None or act.signed_balance == ZERO:
            continue
        contribution = act.signed_balance
        if mapping.sign is TaxLineSign.NEGATIVE:
            contribution = -contribution
        per_line_amount[mapping.line_id] += contribution
        per_line_contributors[mapping.line_id].append(
            {
                "account_id": str(act.account_id),
                "code": act.code,
                "name": act.name,
                "account_type": act.account_type.value,
                "debit_total": str(act.debit),
                "credit_total": str(act.credit),
                "signed_balance": str(act.signed_balance),
                "sign": mapping.sign.value,
                "contribution": str(contribution),
            }
        )

    # Build worksheet rows in form-sequence order.
    line_rows: list[tuple[TaxFormLine, Decimal]] = []
    for fl in form_lines:
        amount = per_line_amount.get(fl.id, ZERO)
        line_rows.append((fl, amount))

    # Section totals.
    by_section: dict[TaxFormSection, Decimal] = defaultdict(lambda: ZERO)
    for fl, amount in line_rows:
        by_section[fl.section] += amount

    total_income = _section_total(by_section, TaxFormSection.INCOME)
    total_cogs = _section_total(by_section, TaxFormSection.COGS)
    total_deductions = _section_total(by_section, TaxFormSection.DEDUCTIONS)
    taxable_income = total_income - total_cogs - total_deductions

    # Stable hash over the sequence of (line_code, amount) pairs.
    sha = _hash_lines([(fl.code, amount) for fl, amount in line_rows])

    # Phase 8b: regenerate auto-supersede. Any prior APPROVED worksheet
    # for the same (client, period, form) is flipped to SUPERSEDED so the
    # catalog never carries two APPROVED snapshots for the same triple.
    # COMPUTED priors are also superseded (they would otherwise be stale
    # review candidates competing with the freshly computed one).
    prior_active = sess.execute(
        select(TaxWorksheet).where(
            TaxWorksheet.client_id == client_id,
            TaxWorksheet.period_id == period.id,
            TaxWorksheet.form_id == form.id,
            TaxWorksheet.status.in_(
                (TaxWorksheetStatus.COMPUTED, TaxWorksheetStatus.APPROVED)
            ),
        )
    ).scalars().all()
    superseded_ids: list[UUID] = []
    for prior in prior_active:
        prior.status = TaxWorksheetStatus.SUPERSEDED
        superseded_ids.append(prior.id)
    if prior_active:
        sess.flush()
        write_audit(
            sess,
            firm_id=firm_id, client_id=client_id, actor=actor,
            action=AuditAction.TAX_WORKSHEET_SUPERSEDE,
            entity_type="tax_worksheet",
            entity_id=prior_active[0].id,
            details={
                "form_code": form_code.value,
                "period_id": str(period.id),
                "superseded_ids": [str(i) for i in superseded_ids],
                "reason": "regenerate",
            },
        )

    ws = TaxWorksheet(
        firm_id=firm_id,
        client_id=client_id,
        period_id=period.id,
        form_id=form.id,
        status=TaxWorksheetStatus.COMPUTED,
        catalog_version="db",  # marker; the catalog row already carries the version
        total_income=total_income,
        total_cogs=total_cogs,
        total_deductions=total_deductions,
        taxable_income=taxable_income,
        sha256=sha,
        generated_by=actor,
    )
    sess.add(ws)
    sess.flush()
    for fl, amount in line_rows:
        sess.add(
            TaxWorksheetLine(
                firm_id=firm_id,
                client_id=client_id,
                worksheet_id=ws.id,
                form_line_id=fl.id,
                line_code=fl.code,
                line_label=fl.label,
                section=fl.section,
                sequence=fl.sequence,
                amount=amount,
                contributing_accounts=per_line_contributors.get(fl.id, []),
            )
        )
    sess.flush()

    # Reload the catalog_version from the form row so the worksheet records
    # exactly which catalog version it was generated against.
    ws.catalog_version = form.catalog_version
    sess.flush()

    write_audit(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        action=AuditAction.TAX_WORKSHEET_GENERATE,
        entity_type="tax_worksheet",
        entity_id=ws.id,
        details={
            "form_code": form_code.value,
            "period_id": str(period.id),
            "sha256": sha,
            "total_income": str(total_income),
            "taxable_income": str(taxable_income),
        },
    )
    return ws


def approve_worksheet(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    worksheet_id: UUID,
) -> TaxWorksheet:
    if scope is not AccessScope.FIRM:
        raise TaxAccessForbiddenError("Only firm staff may approve tax worksheets.")
    ws = sess.get(TaxWorksheet, worksheet_id)
    if ws is None or ws.firm_id != firm_id or ws.client_id != client_id:
        raise TaxWorksheetGenerationError("Worksheet not found in this tenant.")
    if ws.status is not TaxWorksheetStatus.COMPUTED:
        raise TaxWorksheetGenerationError(
            f"Cannot approve worksheet in status {ws.status.value}; "
            "only COMPUTED is approvable."
        )
    ws.status = TaxWorksheetStatus.APPROVED
    ws.approved_by = actor
    ws.approved_at = datetime.now(tz=UTC)
    sess.flush()
    write_audit(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        action=AuditAction.TAX_WORKSHEET_APPROVE,
        entity_type="tax_worksheet",
        entity_id=ws.id,
        details={"sha256": ws.sha256},
    )
    return ws


def reject_worksheet(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    worksheet_id: UUID,
    reason: str | None = None,
) -> TaxWorksheet:
    """Reject a COMPUTED worksheet. Mirrors `reject_mapping`.

    Only COMPUTED worksheets may be rejected — APPROVED rows must be
    regenerated (which auto-supersedes the prior). SUPERSEDED rows are
    historical and cannot transition.
    """
    if scope is not AccessScope.FIRM:
        raise TaxAccessForbiddenError("Only firm staff may reject tax worksheets.")
    ws = sess.get(TaxWorksheet, worksheet_id)
    if ws is None or ws.firm_id != firm_id or ws.client_id != client_id:
        raise TaxWorksheetGenerationError("Worksheet not found in this tenant.")
    if ws.status is not TaxWorksheetStatus.COMPUTED:
        raise TaxWorksheetGenerationError(
            f"Cannot reject worksheet in status {ws.status.value}; "
            "only COMPUTED is rejectable."
        )
    ws.status = TaxWorksheetStatus.REJECTED
    ws.approved_by = actor       # repurpose the reviewer slot
    ws.approved_at = datetime.now(tz=UTC)
    sess.flush()
    write_audit(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        action=AuditAction.TAX_WORKSHEET_REJECT,
        entity_type="tax_worksheet",
        entity_id=ws.id,
        details={"sha256": ws.sha256, "reason": reason},
    )
    return ws


__all__ = [
    "AutoFillResult",
    "AutoProposeSummary",
    "MappingProposal",
    "TaxAccessForbiddenError",
    "TaxMappingError",
    "TaxWorksheetGenerationError",
    "UnmappedAccountsError",
    "approve_all_drafts_for_form",
    "approve_mapping",
    "approve_worksheet",
    "auto_fill_worksheet",
    "auto_propose_for_form",
    "generate_worksheet",
    "get_form_by_code",
    "propose_mapping",
    "reject_mapping",
    "reject_worksheet",
]
