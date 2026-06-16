"""Deterministic accounting engine.

ALL numerical accounting work happens here. The AI layer (later) may *propose*
classifications and journal entry drafts but cannot post them: every figure on
every statement must trace back to journal_line rows by code in this package.
"""
from app.domain.audit import write_audit
from app.domain.exceptions import (
    DomainError,
    PeriodLockedError,
    UnbalancedJournalEntryError,
)
from app.domain.ledger import LedgerService, LineInput, post_journal_entry
from app.domain.reconciliation import ReconciliationResult, reconcile_account
from app.domain.statements import (
    BalanceSheet,
    CashFlowStatement,
    ProfitAndLoss,
    StatementsService,
)

__all__ = [
    "BalanceSheet",
    "CashFlowStatement",
    "DomainError",
    "LedgerService",
    "LineInput",
    "PeriodLockedError",
    "ProfitAndLoss",
    "ReconciliationResult",
    "StatementsService",
    "UnbalancedJournalEntryError",
    "post_journal_entry",
    "reconcile_account",
    "write_audit",
]
