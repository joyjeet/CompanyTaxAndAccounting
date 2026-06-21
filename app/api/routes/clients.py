"""Tenant-scoped CRUD for clients, periods, and chart-of-accounts.

All endpoints respect RLS. Firm-scope identities can act across any client in
the firm. Portal (client-scope) identities are restricted to their own client
both by RLS and by an explicit guard.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.db.tenant import AccessScope
from app.models.accounting import AccountingPeriod, ChartOfAccounts, Client
from app.models.enums import AccountType, NormalBalance

router = APIRouter(prefix="/clients", tags=["clients"])


# --------------------------------------------------------------------------- #
# Pydantic
# --------------------------------------------------------------------------- #
class ClientOut(BaseModel):
    id: UUID
    firm_id: UUID
    name: str
    external_code: str | None


class ClientCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    external_code: str | None = Field(default=None, max_length=64)


class PeriodOut(BaseModel):
    id: UUID
    client_id: UUID
    name: str
    start_date: date
    end_date: date
    is_locked: bool


class PeriodCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    start_date: date
    end_date: date


class CoaOut(BaseModel):
    id: UUID
    client_id: UUID
    code: str
    name: str
    account_type: str
    normal_balance: str
    is_active: bool


class CoaCreateIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    account_type: AccountType
    normal_balance: NormalBalance


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #
def _require_firm_scope(identity: AuthIdentity) -> None:
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="firm-scope access required",
        )


def _require_client_access(identity: AuthIdentity, client_id: UUID) -> None:
    """Portal users can only touch their own client. Firm users can touch any
    client in the firm (RLS enforces the firm boundary)."""
    if identity.scope is AccessScope.CLIENT and identity.client_id != client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cross-client access denied",
        )


def _load_client_or_404(sess: Session, client_id: UUID) -> Client:
    c = sess.get(Client, client_id)
    if c is None:
        # Either missing or hidden by RLS — same response either way.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="client not found")
    return c


# --------------------------------------------------------------------------- #
# Clients
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[ClientOut])
def list_clients(sess: Session = Depends(db_session)) -> list[ClientOut]:
    rows = sess.execute(select(Client).order_by(Client.name)).scalars().all()
    return [
        ClientOut(id=c.id, firm_id=c.firm_id, name=c.name, external_code=c.external_code)
        for c in rows
    ]


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def create_client(
    body: ClientCreateIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> ClientOut:
    _require_firm_scope(identity)
    c = Client(
        id=uuid4(),
        firm_id=identity.firm_id,
        name=body.name,
        external_code=body.external_code,
    )
    sess.add(c)
    sess.flush()
    return ClientOut(id=c.id, firm_id=c.firm_id, name=c.name, external_code=c.external_code)


@router.get("/{client_id}", response_model=ClientOut)
def get_client(
    client_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> ClientOut:
    _require_client_access(identity, client_id)
    c = _load_client_or_404(sess, client_id)
    return ClientOut(id=c.id, firm_id=c.firm_id, name=c.name, external_code=c.external_code)


# --------------------------------------------------------------------------- #
# Periods
# --------------------------------------------------------------------------- #
@router.get("/{client_id}/periods", response_model=list[PeriodOut])
def list_periods(
    client_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> list[PeriodOut]:
    _require_client_access(identity, client_id)
    _load_client_or_404(sess, client_id)
    rows = (
        sess.execute(
            select(AccountingPeriod)
            .where(AccountingPeriod.client_id == client_id)
            .order_by(AccountingPeriod.start_date.desc())
        )
        .scalars()
        .all()
    )
    return [
        PeriodOut(
            id=p.id,
            client_id=p.client_id,
            name=p.name,
            start_date=p.start_date,
            end_date=p.end_date,
            is_locked=p.is_locked,
        )
        for p in rows
    ]


@router.post(
    "/{client_id}/periods",
    response_model=PeriodOut,
    status_code=status.HTTP_201_CREATED,
)
def create_period(
    client_id: UUID,
    body: PeriodCreateIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> PeriodOut:
    _require_firm_scope(identity)
    _load_client_or_404(sess, client_id)
    if body.start_date > body.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be <= end_date",
        )
    p = AccountingPeriod(
        id=uuid4(),
        firm_id=identity.firm_id,
        client_id=client_id,
        name=body.name,
        start_date=body.start_date,
        end_date=body.end_date,
    )
    sess.add(p)
    sess.flush()
    return PeriodOut(
        id=p.id,
        client_id=p.client_id,
        name=p.name,
        start_date=p.start_date,
        end_date=p.end_date,
        is_locked=p.is_locked,
    )


# --------------------------------------------------------------------------- #
# Chart of Accounts
# --------------------------------------------------------------------------- #
@router.get("/{client_id}/chart-of-accounts", response_model=list[CoaOut])
def list_chart_of_accounts(
    client_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> list[CoaOut]:
    _require_client_access(identity, client_id)
    _load_client_or_404(sess, client_id)
    rows = (
        sess.execute(
            select(ChartOfAccounts)
            .where(ChartOfAccounts.client_id == client_id)
            .order_by(ChartOfAccounts.code)
        )
        .scalars()
        .all()
    )
    return [
        CoaOut(
            id=a.id,
            client_id=a.client_id,
            code=a.code,
            name=a.name,
            account_type=a.account_type.value,
            normal_balance=a.normal_balance.value,
            is_active=a.is_active,
        )
        for a in rows
    ]


@router.post(
    "/{client_id}/chart-of-accounts",
    response_model=CoaOut,
    status_code=status.HTTP_201_CREATED,
)
def create_account(
    client_id: UUID,
    body: CoaCreateIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> CoaOut:
    _require_firm_scope(identity)
    _load_client_or_404(sess, client_id)
    a = ChartOfAccounts(
        id=uuid4(),
        firm_id=identity.firm_id,
        client_id=client_id,
        code=body.code,
        name=body.name,
        account_type=body.account_type,
        normal_balance=body.normal_balance,
        is_active=True,
    )
    sess.add(a)
    sess.flush()
    return CoaOut(
        id=a.id,
        client_id=a.client_id,
        code=a.code,
        name=a.name,
        account_type=a.account_type.value,
        normal_balance=a.normal_balance.value,
        is_active=a.is_active,
    )
