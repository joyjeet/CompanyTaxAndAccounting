"""Tax module HTTP API.

Endpoints (all require Authorization: Bearer <jwt>):

  GET    /tax/forms                          — list active forms
  GET    /tax/forms/{form_code}/lines        — line schema for a form
  GET    /tax/mappings                       — current mappings (tenant)
  POST   /tax/mappings                       — propose a DRAFT mapping       [firm]
  POST   /tax/mappings/{id}/approve          — flip DRAFT->APPROVED          [firm]
  POST   /tax/mappings/{id}/reject           — flip DRAFT->REJECTED          [firm]
  POST   /tax/worksheets                     — generate immutable snapshot   [firm]
  GET    /tax/worksheets                     — list worksheets
  GET    /tax/worksheets/{id}                — detail (with lines)
  POST   /tax/worksheets/{id}/approve        — mark snapshot APPROVED        [firm]

Portal users (`AccessScope.CLIENT`) get read-only access to forms, lines,
and APPROVED worksheets for their own client. They cannot propose/approve
anything and cannot read DRAFT/REJECTED/SUPERSEDED rows.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.db.tenant import AccessScope
from app.domain.tax_service import (
    AutoFillResult,
    AutoProposeSummary,
    MappingProposal,
    TaxAccessForbiddenError,
    TaxMappingError,
    TaxWorksheetGenerationError,
    UnmappedAccountsError,
    approve_all_drafts_for_form,
    approve_mapping,
    approve_worksheet,
    auto_fill_worksheet,
    auto_propose_for_form,
    generate_worksheet,
    propose_mapping,
    reject_mapping,
)
from app.models.accounting import (
    TaxAccountMapping,
    TaxForm,
    TaxFormLine,
    TaxWorksheet,
    TaxWorksheetLine,
)
from app.models.enums import (
    TaxFormCode,
    TaxLineSign,
    TaxMappingStatus,
    TaxWorksheetStatus,
)

router = APIRouter(prefix="/tax", tags=["tax"])


# --------------------------------------------------------------------------- #
# Pydantic shapes
# --------------------------------------------------------------------------- #
class TaxFormOut(BaseModel):
    id: UUID
    code: str
    label: str
    jurisdiction: str
    catalog_version: str
    is_active: bool


class TaxFormLineOut(BaseModel):
    id: UUID
    code: str
    label: str
    section: str
    sequence: int
    description: str | None = None


class TaxFormDetailOut(TaxFormOut):
    lines: list[TaxFormLineOut]


class MappingOut(BaseModel):
    id: UUID
    form_id: UUID
    account_id: UUID
    line_id: UUID
    sign: str
    status: str
    notes: str | None = None
    proposed_by: str
    reviewed_by: str | None = None


class MappingProposeIn(BaseModel):
    form_id: UUID
    account_id: UUID
    line_id: UUID
    sign: TaxLineSign = TaxLineSign.POSITIVE
    notes: str | None = Field(default=None, max_length=1000)


class MappingRejectIn(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class WorksheetLineOut(BaseModel):
    line_code: str
    line_label: str
    section: str
    sequence: int
    amount: Decimal
    contributing_accounts: list[dict]


class WorksheetOut(BaseModel):
    id: UUID
    period_id: UUID
    form_id: UUID
    status: str
    catalog_version: str
    total_income: Decimal
    total_cogs: Decimal
    total_deductions: Decimal
    taxable_income: Decimal
    sha256: str
    generated_by: str
    approved_by: str | None = None


class WorksheetDetailOut(WorksheetOut):
    lines: list[WorksheetLineOut]


class WorksheetGenerateIn(BaseModel):
    period_id: UUID
    form_code: TaxFormCode


# --------------------------------------------------------------------------- #
# Forms (reference data — no RLS, but viewer must be authenticated)
# --------------------------------------------------------------------------- #
@router.get("/forms", response_model=list[TaxFormOut])
def list_forms(
    _identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> list[TaxFormOut]:
    rows = sess.execute(
        select(TaxForm).where(TaxForm.is_active.is_(True))
    ).scalars().all()
    return [
        TaxFormOut(
            id=r.id, code=r.code.value, label=r.label,
            jurisdiction=r.jurisdiction,
            catalog_version=r.catalog_version,
            is_active=r.is_active,
        )
        for r in rows
    ]


@router.get("/forms/{form_code}", response_model=TaxFormDetailOut)
def get_form(
    form_code: TaxFormCode,
    _identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> TaxFormDetailOut:
    form = sess.execute(
        select(TaxForm).where(TaxForm.code == form_code)
    ).scalar_one_or_none()
    if form is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tax form {form_code.value} not found.",
        )
    lines = sess.execute(
        select(TaxFormLine).where(TaxFormLine.form_id == form.id)
        .order_by(TaxFormLine.sequence)
    ).scalars().all()
    return TaxFormDetailOut(
        id=form.id, code=form.code.value, label=form.label,
        jurisdiction=form.jurisdiction, catalog_version=form.catalog_version,
        is_active=form.is_active,
        lines=[
            TaxFormLineOut(
                id=ln.id, code=ln.code, label=ln.label,
                section=ln.section.value, sequence=ln.sequence,
                description=ln.description,
            )
            for ln in lines
        ],
    )


# --------------------------------------------------------------------------- #
# Mappings (tenant)
# --------------------------------------------------------------------------- #
def _require_firm_with_client(identity: AuthIdentity) -> None:
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires firm-scope access.",
        )
    if identity.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id must be present in identity for this action.",
        )


@router.get("/mappings", response_model=list[MappingOut])
def list_mappings(
    form_code: TaxFormCode | None = None,
    status_filter: TaxMappingStatus | None = None,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> list[MappingOut]:
    q = select(TaxAccountMapping)
    if form_code is not None:
        form = sess.execute(
            select(TaxForm).where(TaxForm.code == form_code)
        ).scalar_one_or_none()
        if form is None:
            return []
        q = q.where(TaxAccountMapping.form_id == form.id)
    if status_filter is not None:
        q = q.where(TaxAccountMapping.status == status_filter)
    # Portal users see only APPROVED rows for their own client (RLS already
    # constrains client_id, but we additionally hide drafts).
    if identity.scope is AccessScope.CLIENT:
        q = q.where(TaxAccountMapping.status == TaxMappingStatus.APPROVED)
    rows = sess.execute(q).scalars().all()
    return [
        MappingOut(
            id=r.id, form_id=r.form_id, account_id=r.account_id,
            line_id=r.line_id, sign=r.sign.value, status=r.status.value,
            notes=r.notes, proposed_by=r.proposed_by, reviewed_by=r.reviewed_by,
        )
        for r in rows
    ]


@router.post("/mappings", response_model=MappingOut, status_code=201)
def propose(
    body: MappingProposeIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> MappingOut:
    _require_firm_with_client(identity)
    assert identity.client_id is not None  # guarded above
    try:
        row = propose_mapping(
            sess,
            firm_id=identity.firm_id,
            client_id=identity.client_id,
            actor=identity.subject,
            scope=identity.scope,
            form_id=body.form_id,
            proposal=MappingProposal(
                account_id=body.account_id,
                line_id=body.line_id,
                sign=body.sign,
                notes=body.notes,
            ),
        )
    except TaxAccessForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except TaxMappingError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return MappingOut(
        id=row.id, form_id=row.form_id, account_id=row.account_id,
        line_id=row.line_id, sign=row.sign.value, status=row.status.value,
        notes=row.notes, proposed_by=row.proposed_by, reviewed_by=row.reviewed_by,
    )


@router.post("/mappings/{mapping_id}/approve", response_model=MappingOut)
def approve(
    mapping_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> MappingOut:
    _require_firm_with_client(identity)
    assert identity.client_id is not None
    try:
        row = approve_mapping(
            sess,
            firm_id=identity.firm_id, client_id=identity.client_id,
            actor=identity.subject, scope=identity.scope,
            mapping_id=mapping_id,
        )
    except TaxAccessForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except TaxMappingError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return MappingOut(
        id=row.id, form_id=row.form_id, account_id=row.account_id,
        line_id=row.line_id, sign=row.sign.value, status=row.status.value,
        notes=row.notes, proposed_by=row.proposed_by, reviewed_by=row.reviewed_by,
    )


@router.post("/mappings/{mapping_id}/reject", response_model=MappingOut)
def reject(
    mapping_id: UUID,
    body: MappingRejectIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> MappingOut:
    _require_firm_with_client(identity)
    assert identity.client_id is not None
    try:
        row = reject_mapping(
            sess,
            firm_id=identity.firm_id, client_id=identity.client_id,
            actor=identity.subject, scope=identity.scope,
            mapping_id=mapping_id,
            reason=body.reason,
        )
    except TaxAccessForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except TaxMappingError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return MappingOut(
        id=row.id, form_id=row.form_id, account_id=row.account_id,
        line_id=row.line_id, sign=row.sign.value, status=row.status.value,
        notes=row.notes, proposed_by=row.proposed_by, reviewed_by=row.reviewed_by,
    )


# --------------------------------------------------------------------------- #
# Auto-mapping (heuristic) — one-button onboarding
# --------------------------------------------------------------------------- #
class AutoProposeIn(BaseModel):
    form_code: TaxFormCode


class AutoProposeOut(BaseModel):
    form_code: str
    proposed_mapping_ids: list[UUID]
    skipped: list[dict]
    already_existed: list[dict]


class AutoFillIn(BaseModel):
    period_id: UUID
    form_code: TaxFormCode


class AutoFillOut(BaseModel):
    proposed_mapping_ids: list[UUID]
    approved_mapping_ids: list[UUID]
    skipped: list[dict]
    already_existed: list[dict]
    worksheet: WorksheetDetailOut


def _serialize_auto_propose(s: AutoProposeSummary) -> AutoProposeOut:
    return AutoProposeOut(
        form_code=s.form_code.value,
        proposed_mapping_ids=list(s.proposed),
        skipped=[
            {"code": code, "name": name, "reason": reason}
            for code, name, reason in s.skipped
        ],
        already_existed=[
            {"code": code, "name": name, "status": st}
            for code, name, st in s.already_existed
        ],
    )


@router.post(
    "/mappings/auto-propose",
    response_model=AutoProposeOut,
    status_code=status.HTTP_201_CREATED,
)
def auto_propose(
    body: AutoProposeIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> AutoProposeOut:
    """Walk the client's COA and write DRAFT mappings using a heuristic
    (account-name keyword + code-range fallback). Idempotent — rows that
    already have a DRAFT/APPROVED mapping on this form are skipped."""
    _require_firm_with_client(identity)
    assert identity.client_id is not None
    try:
        summary = auto_propose_for_form(
            sess,
            firm_id=identity.firm_id, client_id=identity.client_id,
            actor=identity.subject, scope=identity.scope,
            form_code=body.form_code,
        )
    except TaxAccessForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except TaxMappingError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return _serialize_auto_propose(summary)


@router.post(
    "/mappings/approve-all",
    response_model=list[UUID],
)
def approve_all(
    body: AutoProposeIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> list[UUID]:
    """Flip every DRAFT mapping for (client, form) to APPROVED in one call."""
    _require_firm_with_client(identity)
    assert identity.client_id is not None
    try:
        ids = approve_all_drafts_for_form(
            sess,
            firm_id=identity.firm_id, client_id=identity.client_id,
            actor=identity.subject, scope=identity.scope,
            form_code=body.form_code,
        )
    except TaxAccessForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except TaxMappingError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return list(ids)


# --------------------------------------------------------------------------- #
# Worksheets (tenant)
# --------------------------------------------------------------------------- #
@router.post("/worksheets", response_model=WorksheetDetailOut, status_code=201)
def generate(
    body: WorksheetGenerateIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> WorksheetDetailOut:
    _require_firm_with_client(identity)
    assert identity.client_id is not None
    try:
        ws = generate_worksheet(
            sess,
            firm_id=identity.firm_id, client_id=identity.client_id,
            actor=identity.subject, scope=identity.scope,
            period_id=body.period_id, form_code=body.form_code,
        )
    except TaxAccessForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except UnmappedAccountsError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": str(e),
                "unmapped_accounts": [
                    {"id": str(aid), "code": code, "name": name}
                    for aid, code, name in e.accounts
                ],
            },
        ) from e
    except TaxWorksheetGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    return _serialize_worksheet(sess, ws)


@router.get("/worksheets", response_model=list[WorksheetOut])
def list_worksheets(
    period_id: UUID | None = None,
    form_code: TaxFormCode | None = None,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> list[WorksheetOut]:
    q = select(TaxWorksheet)
    if period_id is not None:
        q = q.where(TaxWorksheet.period_id == period_id)
    if form_code is not None:
        form = sess.execute(
            select(TaxForm).where(TaxForm.code == form_code)
        ).scalar_one_or_none()
        if form is None:
            return []
        q = q.where(TaxWorksheet.form_id == form.id)
    if identity.scope is AccessScope.CLIENT:
        # Portal: only APPROVED worksheets are visible.
        q = q.where(TaxWorksheet.status == TaxWorksheetStatus.APPROVED)
    rows = sess.execute(q.order_by(TaxWorksheet.generated_at.desc())).scalars().all()
    return [_worksheet_summary(r) for r in rows]


@router.get("/worksheets/{worksheet_id}", response_model=WorksheetDetailOut)
def get_worksheet(
    worksheet_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> WorksheetDetailOut:
    ws = sess.get(TaxWorksheet, worksheet_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Worksheet not found.")
    if identity.scope is AccessScope.CLIENT and ws.status is not TaxWorksheetStatus.APPROVED:
        raise HTTPException(status_code=404, detail="Worksheet not found.")
    return _serialize_worksheet(sess, ws)


@router.post("/worksheets/{worksheet_id}/approve", response_model=WorksheetDetailOut)
def approve_ws(
    worksheet_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> WorksheetDetailOut:
    _require_firm_with_client(identity)
    assert identity.client_id is not None
    try:
        ws = approve_worksheet(
            sess,
            firm_id=identity.firm_id, client_id=identity.client_id,
            actor=identity.subject, scope=identity.scope,
            worksheet_id=worksheet_id,
        )
    except TaxAccessForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except TaxWorksheetGenerationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return _serialize_worksheet(sess, ws)


# --------------------------------------------------------------------------- #
# Serialization helpers
# --------------------------------------------------------------------------- #
def _worksheet_summary(ws: TaxWorksheet) -> WorksheetOut:
    return WorksheetOut(
        id=ws.id, period_id=ws.period_id, form_id=ws.form_id,
        status=ws.status.value, catalog_version=ws.catalog_version,
        total_income=ws.total_income, total_cogs=ws.total_cogs,
        total_deductions=ws.total_deductions, taxable_income=ws.taxable_income,
        sha256=ws.sha256, generated_by=ws.generated_by,
        approved_by=ws.approved_by,
    )


def _serialize_worksheet(sess: Session, ws: TaxWorksheet) -> WorksheetDetailOut:
    lines = sess.execute(
        select(TaxWorksheetLine).where(TaxWorksheetLine.worksheet_id == ws.id)
        .order_by(TaxWorksheetLine.sequence)
    ).scalars().all()
    summary = _worksheet_summary(ws)
    return WorksheetDetailOut(
        **summary.model_dump(),
        lines=[
            WorksheetLineOut(
                line_code=ln.line_code, line_label=ln.line_label,
                section=ln.section.value, sequence=ln.sequence,
                amount=ln.amount,
                contributing_accounts=ln.contributing_accounts or [],
            )
            for ln in lines
        ],
    )


# --------------------------------------------------------------------------- #
# One-click "auto-fill": propose -> approve-all -> generate (in one txn).
# --------------------------------------------------------------------------- #
@router.post(
    "/auto-fill",
    response_model=AutoFillOut,
    status_code=status.HTTP_201_CREATED,
)
def auto_fill(
    body: AutoFillIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> AutoFillOut:
    """First-run convenience: heuristic-propose mappings, approve them all,
    then generate the worksheet for `period_id` + `form_code`. Returns the
    worksheet so the UI can render it immediately."""
    _require_firm_with_client(identity)
    assert identity.client_id is not None
    try:
        result: AutoFillResult = auto_fill_worksheet(
            sess,
            firm_id=identity.firm_id, client_id=identity.client_id,
            actor=identity.subject, scope=identity.scope,
            period_id=body.period_id, form_code=body.form_code,
        )
    except TaxAccessForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except UnmappedAccountsError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": str(e),
                "unmapped_accounts": [
                    {"id": str(aid), "code": code, "name": name}
                    for aid, code, name in e.accounts
                ],
            },
        ) from e
    except TaxMappingError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except TaxWorksheetGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    ws_detail = _serialize_worksheet(sess, result.worksheet)
    summary = result.auto_propose
    return AutoFillOut(
        proposed_mapping_ids=list(summary.proposed),
        approved_mapping_ids=list(result.approved_mapping_ids),
        skipped=[
            {"code": code, "name": name, "reason": reason}
            for code, name, reason in summary.skipped
        ],
        already_existed=[
            {"code": code, "name": name, "status": st}
            for code, name, st in summary.already_existed
        ],
        worksheet=ws_detail,
    )
