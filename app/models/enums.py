from __future__ import annotations

import enum


class AccountType(enum.StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class NormalBalance(enum.StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


# Canonical mapping. Used by the engine to validate COA rows on insert.
NORMAL_BALANCE_FOR: dict[AccountType, NormalBalance] = {
    AccountType.ASSET: NormalBalance.DEBIT,
    AccountType.EXPENSE: NormalBalance.DEBIT,
    AccountType.LIABILITY: NormalBalance.CREDIT,
    AccountType.EQUITY: NormalBalance.CREDIT,
    AccountType.REVENUE: NormalBalance.CREDIT,
}


class JournalEntryStatus(enum.StrEnum):
    DRAFT = "draft"
    POSTED = "posted"
    REVERSED = "reversed"


class ReconciliationStatus(enum.StrEnum):
    OPEN = "open"
    COMPLETE = "complete"
    DISCREPANCY = "discrepancy"


class AssetStatus(enum.StrEnum):
    ACTIVE = "active"
    DISPOSED = "disposed"


class AuditAction(enum.StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    POST = "post"
    REVERSE = "reverse"
    LOCK_PERIOD = "lock_period"
    UNLOCK_PERIOD = "unlock_period"
    RECONCILE = "reconcile"
    INGEST = "ingest"
    EXTRACT = "extract"
    CLASSIFY = "classify"
    PROMOTE = "promote"
    REJECT = "reject"
    TAX_MAP_PROPOSE = "tax_map_propose"
    TAX_MAP_APPROVE = "tax_map_approve"
    TAX_MAP_REJECT = "tax_map_reject"
    TAX_WORKSHEET_GENERATE = "tax_worksheet_generate"
    TAX_WORKSHEET_APPROVE = "tax_worksheet_approve"


class OcrStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"


class DraftKind(enum.StrEnum):
    BANK_TRANSACTION = "bank_transaction"
    TAX_FORM = "tax_form"
    INVOICE = "invoice"
    RECEIPT = "receipt"
    GENERIC = "generic"


class DraftStatus(enum.StrEnum):
    PENDING_REVIEW = "pending_review"
    PROMOTED = "promoted"
    REJECTED = "rejected"


# --------------------------------------------------------------------------- #
# Tax module (Phase 5)
# --------------------------------------------------------------------------- #
class TaxFormCode(enum.StrEnum):
    """Supported US federal income-tax forms.

    v1 supports the major business return types. Each form is modeled with
    its income-statement-relevant lines (Sched L / M-1 / M-2 deferred).
    """

    F1120 = "F1120"       # US C-Corporation Income Tax Return
    F1120S = "F1120S"     # US S-Corporation Income Tax Return
    F1065 = "F1065"       # US Return of Partnership Income
    F1040SC = "F1040SC"   # US Sole Proprietor (Form 1040, Schedule C)


class TaxFormSection(enum.StrEnum):
    """Coarse sections we expose on every form. Maps to a worksheet block."""

    INCOME = "income"
    COGS = "cogs"
    DEDUCTIONS = "deductions"
    OTHER = "other"


class TaxLineSign(enum.StrEnum):
    """How an account's signed ledger balance contributes to a tax line.

    Tax lines are reported as positive numbers regardless of the ledger
    debit/credit posture. The signed_balance of an account (already at its
    natural normal balance — see app/domain/statements.py) is passed through
    one of these:

      * POSITIVE: signed_balance contributes as-is (revenue accounts on an
        income line; expense accounts on a deduction line — both yield a
        positive line amount).
      * NEGATIVE: signed_balance is negated (returns/allowances, contra
        revenue, etc.).
    """

    POSITIVE = "positive"
    NEGATIVE = "negative"


class TaxMappingStatus(enum.StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class TaxWorksheetStatus(enum.StrEnum):
    COMPUTED = "computed"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
