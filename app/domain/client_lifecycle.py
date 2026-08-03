"""Client lifecycle: archive, restore, and delete.

Clients could be created but never removed, so a client created by mistake
stayed in the list forever.

Deleting a real client is the wrong default. Record retention -- IRS guidance
on supporting records, plus state board rules on workpapers -- means a
departed client's books have to outlive the engagement. So:

* **Archive** is the normal action. Nothing is removed. The client drops out
  of lists and pickers and refuses new postings, and it can be restored.
* **Delete** is only for the mistake case: a client with no books at all.
  The auto-seeded chart of accounts, any empty periods, and the profile do
  not count as books -- a client created a minute ago has all three, and
  that is exactly the client you want to be able to remove.

Audit events are deliberately *not* deleted. They are the record that the
client existed and was removed, which is the one thing that must survive.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.domain.audit import write_audit
from app.domain.exceptions import DomainError
from app.models.accounting import (
    AccountingPeriod,
    Asset,
    BankTransaction,
    ChartOfAccounts,
    Client,
    DraftClassification,
    GeneratedArtifact,
    JournalEntry,
    Reconciliation,
    SourceDocument,
    TaxAccountMapping,
    TaxWorksheet,
)
from app.models.client_profile import ClientProfile
from app.models.enums import AuditAction


class ClientLifecycleError(DomainError):
    """Base for archive/restore/delete failures."""


class ClientNotFoundError(ClientLifecycleError):
    """No such client in this tenant."""


class ClientHasDataError(ClientLifecycleError):
    """The client has books and may only be archived, never deleted."""


# Anything here means the client has real history. Ordered so the message
# names the most meaningful evidence first.
_BLOCKING: tuple[tuple[type, str], ...] = (
    (JournalEntry, "journal entry"),
    (SourceDocument, "uploaded document"),
    (BankTransaction, "bank transaction"),
    (DraftClassification, "draft"),
    (GeneratedArtifact, "generated artifact"),
    (TaxWorksheet, "tax worksheet"),
    (Asset, "fixed asset"),
    (Reconciliation, "reconciliation"),
)

# Setup rows that exist purely because the client was created. These are
# removed along with the client.
_CASCADE: tuple[type, ...] = (
    ChartOfAccounts,
    AccountingPeriod,
    TaxAccountMapping,
    ClientProfile,
)


def _load(sess: Session, client_id: UUID) -> Client:
    client = sess.get(Client, client_id)
    if client is None:
        # Missing or hidden by RLS — same answer either way.
        raise ClientNotFoundError("Client not found.")
    return client


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def client_data_counts(sess: Session, *, client_id: UUID) -> dict[str, int]:
    """Non-zero counts of the records that block deletion, keyed by label."""
    counts: dict[str, int] = {}
    for model, label in _BLOCKING:
        n = sess.execute(
            select(func.count()).select_from(model).where(model.client_id == client_id)
        ).scalar_one()
        if n:
            counts[label] = n
    return counts


def archive_client(
    sess: Session, *, firm_id: UUID, client_id: UUID, actor: str
) -> Client:
    """Hide the client and stop new postings. Fully reversible."""
    client = _load(sess, client_id)
    if client.is_active:
        client.is_active = False
        client.archived_at = datetime.now(UTC)
        sess.flush()
        write_audit(
            sess,
            firm_id=firm_id,
            client_id=client_id,
            actor=actor,
            action=AuditAction.CLIENT_ARCHIVE,
            entity_type="client",
            entity_id=client_id,
            details={"name": client.name},
        )
    return client


def restore_client(
    sess: Session, *, firm_id: UUID, client_id: UUID, actor: str
) -> Client:
    """Bring an archived client back into active use."""
    client = _load(sess, client_id)
    if not client.is_active:
        client.is_active = True
        client.archived_at = None
        sess.flush()
        write_audit(
            sess,
            firm_id=firm_id,
            client_id=client_id,
            actor=actor,
            action=AuditAction.CLIENT_RESTORE,
            entity_type="client",
            entity_id=client_id,
            details={"name": client.name},
        )
    return client


def delete_client(
    sess: Session, *, firm_id: UUID, client_id: UUID, actor: str
) -> None:
    """Remove a client that has no books.

    Raises `ClientHasDataError` the moment any real history exists — those
    clients are archived instead, because deleting them would destroy records
    the firm is required to keep.
    """
    client = _load(sess, client_id)
    counts = client_data_counts(sess, client_id=client_id)
    if counts:
        found = ", ".join(_plural(n, label) for label, n in counts.items())
        raise ClientHasDataError(
            f"'{client.name}' has {found} and cannot be deleted. Archive it "
            "instead — it will disappear from your client list and stop "
            "accepting entries, but its books stay intact."
        )

    snapshot = {"name": client.name, "external_code": client.external_code}

    # Write the audit row before the delete so it is never lost if the
    # transaction is inspected mid-flight. It intentionally outlives the
    # client row.
    write_audit(
        sess,
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=AuditAction.CLIENT_DELETE,
        entity_type="client",
        entity_id=client_id,
        details=snapshot,
    )

    for model in _CASCADE:
        sess.execute(delete(model).where(model.client_id == client_id))
    sess.delete(client)
    sess.flush()


__all__ = [
    "ClientHasDataError",
    "ClientLifecycleError",
    "ClientNotFoundError",
    "archive_client",
    "client_data_counts",
    "delete_client",
    "restore_client",
]
