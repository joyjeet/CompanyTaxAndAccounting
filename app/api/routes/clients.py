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
from app.domain.audit import write_audit
from app.domain.coa_templates import (
    CoaTemplateError,
    CoaTemplateForbiddenError,
    instantiate_for_client,
)
from app.models.accounting import AccountingPeriod, ChartOfAccounts, Client
from app.models.coa_template import CoaTemplate
from app.models.enums import (
    AccountType,
    AuditAction,
    CoaTemplateStatus,
    Industry,
    NormalBalance,
)

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


# --------------------------------------------------------------------------- #
# COA template listing (registered BEFORE /{client_id} so the literal path
# "coa-templates" is not misinterpreted as a client UUID parameter)
# --------------------------------------------------------------------------- #
class CoaTemplateOut(BaseModel):
    id: UUID
    key: str
    display_name: str
    kind: str
    industry: str | None
    version: str
    status: str
    node_count: int


@router.get("/coa-templates", response_model=list[CoaTemplateOut])
def list_coa_templates(
    status_filter: str | None = None,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> list[CoaTemplateOut]:
    """List all COA templates (general + industry overlays) registered.

    Firm-scope only — clients shouldn't see the template catalog directly.
    Use `?status_filter=draft|active|superseded` to filter.
    """
    _require_firm_scope(identity)
    stmt = select(CoaTemplate).order_by(
        CoaTemplate.kind, CoaTemplate.industry, CoaTemplate.version
    )
    if status_filter:
        try:
            wanted = CoaTemplateStatus(status_filter)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"invalid status_filter '{status_filter}'",
            ) from exc
        stmt = stmt.where(CoaTemplate.status == wanted)
    rows = sess.execute(stmt).scalars().all()
    out: list[CoaTemplateOut] = []
    for t in rows:
        node_count = len(t.nodes)
        out.append(
            CoaTemplateOut(
                id=t.id,
                key=t.key,
                display_name=t.display_name,
                kind=t.kind.value,
                industry=t.industry,
                version=t.version,
                status=t.status.value,
                node_count=node_count,
            )
        )
    return out


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
# Lock / unlock a period (firm-only)
# --------------------------------------------------------------------------- #
def _load_period_for_client(
    sess: Session, client_id: UUID, period_id: UUID,
) -> AccountingPeriod:
    p = sess.get(AccountingPeriod, period_id)
    if p is None or p.client_id != client_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="period not found for this client",
        )
    return p


@router.post("/{client_id}/periods/{period_id}/lock", response_model=PeriodOut)
def lock_period(
    client_id: UUID,
    period_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> PeriodOut:
    """Mark a period as finalized/closed (firm-only).

    Once locked: no new journal entries may post into the period (enforced by
    `LedgerService.post`), and the period's reports become visible to the
    portal (per the 'only finalized data is exportable' rule).
    """
    _require_firm_scope(identity)
    _load_client_or_404(sess, client_id)
    p = _load_period_for_client(sess, client_id, period_id)
    if not p.is_locked:
        p.is_locked = True
        sess.flush()
        write_audit(
            sess,
            firm_id=identity.firm_id,
            client_id=client_id,
            actor=identity.subject,
            action=AuditAction.LOCK_PERIOD,
            entity_type="accounting_period",
            entity_id=p.id,
            details={"name": p.name},
        )
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
# --------------------------------------------------------------------------- #@router.post("/{client_id}/periods/{period_id}/unlock", response_model=PeriodOut)
def unlock_period(
    client_id: UUID,
    period_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> PeriodOut:
    """Re-open a locked period (firm-only).

    Reverses `lock_period`. While unlocked, reports for this period are again
    hidden from the portal until re-locked.
    """
    _require_firm_scope(identity)
    _load_client_or_404(sess, client_id)
    p = _load_period_for_client(sess, client_id, period_id)
    if p.is_locked:
        p.is_locked = False
        sess.flush()
        write_audit(
            sess,
            firm_id=identity.firm_id,
            client_id=client_id,
            actor=identity.subject,
            action=AuditAction.UNLOCK_PERIOD,
            entity_type="accounting_period",
            entity_id=p.id,
            details={"name": p.name},
        )
    return PeriodOut(
        id=p.id,
        client_id=p.client_id,
        name=p.name,
        start_date=p.start_date,
        end_date=p.end_date,
        is_locked=p.is_locked,
    )
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


# --------------------------------------------------------------------------- #
# COA template onboarding (Phase 8a) — instantiate endpoint
# (The list endpoint is registered higher up to avoid the /{client_id}
# collision.)
# --------------------------------------------------------------------------- #
class CoaInstantiateIn(BaseModel):
    industry: Industry = Field(
        description=(
            "The industry overlay to layer on top of the ACTIVE general "
            "template. Use 'generic' for clients that don't need an overlay."
        )
    )


class CoaInstantiateOut(BaseModel):
    client_id: UUID
    industry: str
    created_count: int
    general_template_id: UUID
    overlay_template_id: UUID | None


@router.post(
    "/{client_id}/coa/instantiate",
    response_model=CoaInstantiateOut,
    status_code=status.HTTP_201_CREATED,
)
def instantiate_coa(
    client_id: UUID,
    body: CoaInstantiateIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> CoaInstantiateOut:
    """Instantiate the ACTIVE general COA + industry overlay for this client.

    Firm-scope only. Fails with 409 if the client already has any
    template-derived rows, or 412 if no template has been activated yet.
    """
    _require_firm_scope(identity)
    _load_client_or_404(sess, client_id)
    try:
        result = instantiate_for_client(
            sess,
            firm_id=identity.firm_id,
            client_id=client_id,
            industry=body.industry,
            actor=identity.subject,
            scope=identity.scope,
        )
    except CoaTemplateForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except CoaTemplateError as exc:
        msg = str(exc)
        if "No ACTIVE" in msg:
            code_ = status.HTTP_412_PRECONDITION_FAILED
        elif "already has" in msg:
            code_ = status.HTTP_409_CONFLICT
        else:
            code_ = status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code_, detail=msg) from exc

    return CoaInstantiateOut(
        client_id=client_id,
        industry=result.industry.value,
        created_count=result.created_count,
        general_template_id=result.general_template_id,
        overlay_template_id=result.overlay_template_id,
    )


# --------------------------------------------------------------------------- #
# Client profile (Phase 8b)
# --------------------------------------------------------------------------- #
class ClientProfileOut(BaseModel):
    client_id: UUID
    entity_type: str
    industry: str
    tax_year: int
    home_state: str | None
    additional_states: list[str]
    fiscal_year_end_month: int | None
    entity_attributes: dict
    created_at: str
    updated_at: str


class ClientProfileUpsertIn(BaseModel):
    entity_type: str = Field(min_length=1, max_length=32)
    tax_year: int = Field(ge=1900, le=2200)
    industry: str | None = Field(default=None, max_length=64)
    home_state: str | None = Field(default=None, max_length=2)
    additional_states: list[str] | None = None
    fiscal_year_end_month: int | None = Field(default=None, ge=1, le=12)
    entity_attributes: dict | None = None


def _serialize_profile(row) -> ClientProfileOut:
    return ClientProfileOut(
        client_id=row.client_id,
        entity_type=row.entity_type,
        industry=row.industry,
        tax_year=row.tax_year,
        home_state=row.home_state,
        additional_states=list(row.additional_states or []),
        fiscal_year_end_month=row.fiscal_year_end_month,
        entity_attributes=dict(row.entity_attributes or {}),
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.get("/{client_id}/profile", response_model=ClientProfileOut)
def get_client_profile_endpoint(
    client_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> ClientProfileOut:
    """Return the client's tax/entity profile. Both firm and portal scopes
    may read (RLS limits portal to their own client)."""
    from app.domain.client_profile import get_profile_for_client

    _require_client_access(identity, client_id)
    _load_client_or_404(sess, client_id)
    row = get_profile_for_client(sess, client_id=client_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="client profile not set",
        )
    return _serialize_profile(row)


@router.put("/{client_id}/profile", response_model=ClientProfileOut)
def upsert_client_profile_endpoint(
    client_id: UUID,
    body: ClientProfileUpsertIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> ClientProfileOut:
    """Create or update a client's profile. Firm staff only."""
    from app.domain.client_profile import (
        ClientProfileForbiddenError,
        ClientProfileValidationError,
        upsert_profile,
    )

    _require_firm_scope(identity)
    _load_client_or_404(sess, client_id)
    # Drop None-valued optional kwargs so the domain defaults apply.
    kwargs = {
        "entity_type": body.entity_type,
        "tax_year": body.tax_year,
    }
    if body.industry is not None:
        kwargs["industry"] = body.industry
    if body.home_state is not None:
        kwargs["home_state"] = body.home_state
    if body.additional_states is not None:
        kwargs["additional_states"] = body.additional_states
    if body.fiscal_year_end_month is not None:
        kwargs["fiscal_year_end_month"] = body.fiscal_year_end_month
    if body.entity_attributes is not None:
        kwargs["entity_attributes"] = body.entity_attributes
    try:
        row = upsert_profile(
            sess,
            firm_id=identity.firm_id,
            client_id=client_id,
            actor=identity.subject,
            scope=identity.scope,
            **kwargs,
        )
    except ClientProfileForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except ClientProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _serialize_profile(row)
