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
