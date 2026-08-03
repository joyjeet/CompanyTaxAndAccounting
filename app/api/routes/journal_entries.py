"""Journal entries API: list (with lines) and manual posting.

The list endpoint filters by client_id (and optionally period_id or an
entry-date range) and pulls each entry's lines so the UI can render the full
T-account view. The post endpoint routes through `LedgerService.post()` which
enforces the books-balance invariant before any SQL is emitted.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.db.tenant import AccessScope
from app.domain.exceptions import (
    CrossTenantError,
    InvalidAccountError,
    PeriodLockedError,
    UnbalancedJournalEntryError,
)
from app.domain.ledger import LedgerService, LineInput
from app.models.accounting import Client, JournalEntry, JournalLine

router = APIRouter(prefix="/journal-entries", tags=["journal-entries"])


# --------------------------------------------------------------------------- #
# Pydantic
# --------------------------------------------------------------------------- #
class JournalLineOut(BaseModel):
    id: UUID
    line_no: int
    account_id: UUID
    debit: Decimal
    credit: Decimal
    description: str | None


class JournalEntryOut(BaseModel):
    id: UUID
    client_id: UUID
    period_id: UUID
    entry_date: date
    memo: str | None
    status: str
    source_document_id: UUID | None
    lines: list[JournalLineOut]


class JournalLineIn(BaseModel):
    account_id: UUID
    debit: Decimal = Field(default=Decimal("0"))
    credit: Decimal = Field(default=Decimal("0"))
    description: str | None = None


class JournalEntryCreateIn(BaseModel):
    client_id: UUID
    period_id: UUID
    entry_date: date
    memo: str | None = None
    lines: list[JournalLineIn] = Field(min_length=2)


# --------------------------------------------------------------------------- #
def _require_client_access(identity: AuthIdentity, client_id: UUID) -> None:
    if identity.scope is AccessScope.CLIENT and identity.client_id != client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cross-client access denied",
        )


def _entry_to_out(e: JournalEntry) -> JournalEntryOut:
    return JournalEntryOut(
        id=e.id,
        client_id=e.client_id,
        period_id=e.period_id,
        entry_date=e.entry_date,
        memo=e.memo,
        status=e.status.value,
        source_document_id=e.source_document_id,
        lines=[
            JournalLineOut(
                id=ln.id,
                line_no=ln.line_no,
                account_id=ln.account_id,
                debit=ln.debit,
                credit=ln.credit,
                description=ln.description,
            )
            for ln in e.lines
        ],
    )


# --------------------------------------------------------------------------- #
@router.get("", response_model=list[JournalEntryOut])
def list_journal_entries(
    client_id: UUID = Query(...),
    period_id: UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> list[JournalEntryOut]:
    _require_client_access(identity, client_id)
    # Verify the client exists / is visible — RLS would already prevent leaks,
    # but this gives a clean 404.
    if sess.get(Client, client_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client not found")
    if date_from is not None and date_to is not None and date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_to must be on or after date_from",
        )
    q = (
        select(JournalEntry)
        .where(JournalEntry.client_id == client_id)
        .options(selectinload(JournalEntry.lines))
        .order_by(JournalEntry.entry_date.desc(), JournalEntry.created_at.desc())
    )
    if period_id is not None:
        q = q.where(JournalEntry.period_id == period_id)
    if date_from is not None:
        q = q.where(JournalEntry.entry_date >= date_from)
    if date_to is not None:
        q = q.where(JournalEntry.entry_date <= date_to)
    rows = sess.execute(q).scalars().all()
    return [_entry_to_out(e) for e in rows]


@router.get("/{entry_id}", response_model=JournalEntryOut)
def get_journal_entry(
    entry_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> JournalEntryOut:
    e = sess.execute(
        select(JournalEntry)
        .where(JournalEntry.id == entry_id)
        .options(selectinload(JournalEntry.lines))
    ).scalar_one_or_none()
    if e is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="entry not found")
    _require_client_access(identity, e.client_id)
    return _entry_to_out(e)


@router.post(
    "",
    response_model=JournalEntryOut,
    status_code=status.HTTP_201_CREATED,
)
def post_journal_entry(
    body: JournalEntryCreateIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> JournalEntryOut:
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only firm-scope users can post journal entries",
        )
    _require_client_access(identity, body.client_id)
    svc = LedgerService(
        sess,
        firm_id=identity.firm_id,
        client_id=body.client_id,
        actor=identity.subject,
    )
    try:
        entry = svc.post(
            period_id=body.period_id,
            entry_date=body.entry_date,
            lines=[
                LineInput(
                    account_id=ln.account_id,
                    debit=ln.debit,
                    credit=ln.credit,
                    description=ln.description,
                )
                for ln in body.lines
            ],
            memo=body.memo,
        )
    except UnbalancedJournalEntryError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except PeriodLockedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except (CrossTenantError, InvalidAccountError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    sess.flush()
    # Reload with lines for the response.
    entry = sess.execute(
        select(JournalEntry)
        .where(JournalEntry.id == entry.id)
        .options(selectinload(JournalEntry.lines))
    ).scalar_one()
    return _entry_to_out(entry)
