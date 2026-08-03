from __future__ import annotations


class DomainError(Exception):
    """Base class for domain-layer errors."""


class UnbalancedJournalEntryError(DomainError):
    """Raised when SUM(debits) != SUM(credits) for a journal entry."""


class PeriodLockedError(DomainError):
    """Raised when attempting to post into a locked accounting period."""


class CrossTenantError(DomainError):
    """Raised when a domain operation references entities outside the caller's tenant."""


class InvalidAccountError(DomainError):
    """COA row is missing, inactive, or of the wrong type for this operation."""


class ClientArchivedError(DomainError):
    """Raised when attempting to write new books for an archived client."""
