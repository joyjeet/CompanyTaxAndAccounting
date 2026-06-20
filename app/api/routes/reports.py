"""Output-layer HTTP API.

Endpoints (all require Authorization: Bearer <jwt>):

  POST /reports/statements/generate         — render a PL/BS/CF artifact         [firm]
  POST /reports/narratives/generate         — render the period narrative        [firm]
  POST /reports/tax-worksheets/{id}/render  — render a tax-worksheet artifact    [firm]
  POST /reports/audit-packages              — assemble the audit-ready zip       [firm]
  POST /reports/artifacts/{id}/finalize     — flip DRAFT->FINALIZED              [firm]
  GET  /reports/artifacts                   — list artifacts (portal sees FINAL)
  GET  /reports/artifacts/{id}/download     — stream decrypted bytes
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.db.tenant import AccessScope
from app.domain.artifact_service import (
    ArtifactAccessForbiddenError,
    ArtifactNotFoundError,
    ArtifactStateError,
    ExportBlockedByPendingDraftsError,
    GenerateNarrativeRequest,
    GenerateStatementRequest,
    download_artifact,
    finalize_artifact,
    generate_narrative_artifact,
    generate_statement_artifact,
    generate_tax_worksheet_artifact,
    list_artifacts,
)
from app.domain.audit_package import (
    AuditPackageMissingDependencyError,
    generate_audit_package,
)
from app.models.accounting import GeneratedArtifact
from app.models.enums import ArtifactFormat, ArtifactKind

router = APIRouter(prefix="/reports", tags=["reports"])


# --------------------------------------------------------------------------- #
# Pydantic
# --------------------------------------------------------------------------- #
class StatementGenerateIn(BaseModel):
    period_id: UUID
    kind: ArtifactKind
    format: ArtifactFormat
    cash_account_codes: list[str] | None = None
    prior_period_id: UUID | None = None


class NarrativeGenerateIn(BaseModel):
    period_id: UUID
    cash_account_codes: list[str] | None = None
    prior_period_id: UUID | None = None


class AuditPackageIn(BaseModel):
    period_id: UUID


class ArtifactOut(BaseModel):
    id: UUID
    firm_id: UUID
    client_id: UUID
    period_id: UUID | None
    tax_worksheet_id: UUID | None
    kind: str
    format: str
    status: str
    title: str
    plaintext_sha256: str
    size_bytes: int
    generated_by: str
    finalized_by: str | None
    parameters: dict


def _to_out(a: GeneratedArtifact) -> ArtifactOut:
    return ArtifactOut(
        id=a.id,
        firm_id=a.firm_id,
        client_id=a.client_id,
        period_id=a.period_id,
        tax_worksheet_id=a.tax_worksheet_id,
        kind=a.kind.value,
        format=a.format.value,
        status=a.status.value,
        title=a.title,
        plaintext_sha256=a.plaintext_sha256,
        size_bytes=a.size_bytes,
        generated_by=a.generated_by,
        finalized_by=a.finalized_by,
        parameters=a.parameters or {},
    )


# --------------------------------------------------------------------------- #
# Guards / error mapping
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


def _map_domain_error(e: Exception) -> HTTPException:
    if isinstance(e, ArtifactAccessForbiddenError):
        return HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ArtifactNotFoundError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ExportBlockedByPendingDraftsError):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, AuditPackageMissingDependencyError):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, ArtifactStateError):
        return HTTPException(status_code=409, detail=str(e))
    raise e


# --------------------------------------------------------------------------- #
# Generate
# --------------------------------------------------------------------------- #
@router.post("/statements/generate", response_model=ArtifactOut, status_code=201)
def generate_statement(
    body: StatementGenerateIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> ArtifactOut:
    _require_firm_with_client(identity)
    try:
        art = generate_statement_artifact(
            sess,
            firm_id=identity.firm_id,
            client_id=identity.client_id,  # type: ignore[arg-type]
            actor=identity.subject,
            scope=identity.scope,
            request=GenerateStatementRequest(
                period_id=body.period_id,
                kind=body.kind,
                format=body.format,
                cash_account_codes=body.cash_account_codes,
                prior_period_id=body.prior_period_id,
            ),
        )
    except Exception as e:  # noqa: BLE001 — mapped below
        raise _map_domain_error(e) from e
    return _to_out(art)


@router.post("/narratives/generate", response_model=ArtifactOut, status_code=201)
def generate_narrative(
    body: NarrativeGenerateIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> ArtifactOut:
    _require_firm_with_client(identity)
    try:
        result = generate_narrative_artifact(
            sess,
            firm_id=identity.firm_id,
            client_id=identity.client_id,  # type: ignore[arg-type]
            actor=identity.subject,
            scope=identity.scope,
            request=GenerateNarrativeRequest(
                period_id=body.period_id,
                cash_account_codes=body.cash_account_codes,
                prior_period_id=body.prior_period_id,
            ),
        )
    except Exception as e:  # noqa: BLE001
        raise _map_domain_error(e) from e
    return _to_out(result.artifact)


@router.post(
    "/tax-worksheets/{worksheet_id}/render",
    response_model=ArtifactOut,
    status_code=201,
)
def render_tax_worksheet(
    worksheet_id: UUID,
    format: ArtifactFormat,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> ArtifactOut:
    _require_firm_with_client(identity)
    try:
        art = generate_tax_worksheet_artifact(
            sess,
            firm_id=identity.firm_id,
            client_id=identity.client_id,  # type: ignore[arg-type]
            actor=identity.subject,
            scope=identity.scope,
            worksheet_id=worksheet_id,
            fmt=format,
        )
    except Exception as e:  # noqa: BLE001
        raise _map_domain_error(e) from e
    return _to_out(art)


@router.post(
    "/audit-packages", response_model=ArtifactOut, status_code=201,
)
def create_audit_package(
    body: AuditPackageIn,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> ArtifactOut:
    _require_firm_with_client(identity)
    try:
        result = generate_audit_package(
            sess,
            firm_id=identity.firm_id,
            client_id=identity.client_id,  # type: ignore[arg-type]
            actor=identity.subject,
            scope=identity.scope,
            period_id=body.period_id,
        )
    except Exception as e:  # noqa: BLE001
        raise _map_domain_error(e) from e
    return _to_out(result.artifact)


# --------------------------------------------------------------------------- #
# Finalize / list / download
# --------------------------------------------------------------------------- #
@router.post("/artifacts/{artifact_id}/finalize", response_model=ArtifactOut)
def finalize(
    artifact_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> ArtifactOut:
    _require_firm_with_client(identity)
    try:
        art = finalize_artifact(
            sess,
            firm_id=identity.firm_id,
            client_id=identity.client_id,  # type: ignore[arg-type]
            actor=identity.subject,
            scope=identity.scope,
            artifact_id=artifact_id,
        )
    except Exception as e:  # noqa: BLE001
        raise _map_domain_error(e) from e
    return _to_out(art)


@router.get("/artifacts", response_model=list[ArtifactOut])
def list_artifacts_endpoint(
    period_id: UUID | None = None,
    kind: ArtifactKind | None = None,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> list[ArtifactOut]:
    rows = list_artifacts(
        sess, scope=identity.scope, period_id=period_id, kind=kind,
    )
    return [_to_out(r) for r in rows]


@router.get("/artifacts/{artifact_id}/download")
def download(
    artifact_id: UUID,
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> StreamingResponse:
    if identity.client_id is None:
        raise HTTPException(
            status_code=400,
            detail="client_id must be present in identity for this action.",
        )
    try:
        result = download_artifact(
            sess,
            firm_id=identity.firm_id,
            client_id=identity.client_id,
            actor=identity.subject,
            scope=identity.scope,
            artifact_id=artifact_id,
        )
    except Exception as e:  # noqa: BLE001
        raise _map_domain_error(e) from e
    import io
    art = result.artifact
    filename = f"{art.kind.value}-{art.id}.{art.format.value}"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Artifact-Sha256": art.plaintext_sha256,
    }
    return StreamingResponse(
        io.BytesIO(result.body),
        media_type=result.content_type,
        headers=headers,
    )


__all__ = ["router"]
