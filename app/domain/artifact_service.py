"""Orchestrator: presentation -> render -> encrypted store -> registry row.

Single public surface for the output layer. Everything downstream (API
handlers, audit-package builder, frontend renderers) calls into here so the
encryption / lifecycle / audit semantics are uniform.

Lifecycle
---------
* `generate_*` produces a DRAFT artifact. Reviewers can produce as many
  drafts as they want; portal users never see drafts.
* `finalize_artifact` flips DRAFT -> FINALIZED. It REFUSES if any
  `DraftClassification` for the client+period is still PENDING_REVIEW
  ("only finalized data exportable"). Finalizing also SUPERSEDES any prior
  FINALIZED artifact of the same (kind, format, period_id).
* `download_artifact` decrypts and returns the body. Portal users get 404
  on anything other than FINALIZED.

Encryption + integrity
----------------------
Bytes are encrypted via `EncryptedStorage`. The returned `StoredObject.sha256`
is the at-rest ciphertext hash. We ALSO record `plaintext_sha256` so audit
packages can prove the bytes a downstream reader extracts match what was
generated, without trusting the storage layer.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tenant import AccessScope
from app.domain.audit import write_audit
from app.domain.exceptions import DomainError
from app.domain.narrative import (
    NarrativeSafetyReport,
    NarrativeWriter,
    generate_narrative,
)
from app.domain.presentation import (
    PresentationRules,
    PresentedBalanceSheet,
    PresentedCashFlow,
    PresentedProfitAndLoss,
    present_balance_sheet,
    present_cash_flow,
    present_profit_and_loss,
)
from app.domain.renderers import (
    BrandingContext,
    PdfStatementRenderer,
    StatementRenderer,
    XlsxStatementRenderer,
)
from app.domain.statements import StatementsService
from app.integrations.keys import LocalKeyProvider
from app.integrations.registry import get_storage
from app.integrations.storage import StorageService
from app.models.accounting import (
    AccountingPeriod,
    Client,
    DraftClassification,
    GeneratedArtifact,
    TaxForm,
    TaxWorksheet,
    TaxWorksheetLine,
)
from app.models.enums import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactStatus,
    AuditAction,
    DraftStatus,
)
from app.security.encrypted_storage import EncryptedStorage


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class ArtifactAccessForbiddenError(DomainError):
    """Caller's scope does not permit this artifact action."""


class ArtifactNotFoundError(DomainError):
    """Artifact id is unknown or RLS-masked."""


class ArtifactStateError(DomainError):
    """Attempted a transition that the artifact's current state forbids."""


class ExportBlockedByPendingDraftsError(DomainError):
    """Finalize / package refused because PENDING_REVIEW drafts exist."""


# --------------------------------------------------------------------------- #
# Encrypted-storage helper
# --------------------------------------------------------------------------- #
_RENDERERS: dict[ArtifactFormat, StatementRenderer] = {
    ArtifactFormat.PDF: PdfStatementRenderer(),
    ArtifactFormat.XLSX: XlsxStatementRenderer(),
}


def _renderer_for(fmt: ArtifactFormat) -> StatementRenderer:
    try:
        return _RENDERERS[fmt]
    except KeyError as e:
        raise ArtifactStateError(
            f"No renderer registered for format {fmt.value}"
        ) from e


def _build_encrypted_storage(inner: StorageService) -> EncryptedStorage:
    """Wrap the configured StorageService with envelope encryption.

    KEK material is derived from settings.app_local_kek_master via HKDF; this
    keeps the test setup deterministic and survives across processes (so an
    artifact written by an API handler can be decrypted by the test that
    reads it back).
    """
    from app.core.config import get_settings

    s = get_settings()
    kp = LocalKeyProvider(master_secret=s.app_local_kek_master.encode())
    return EncryptedStorage(inner=inner, key_provider=kp)


# --------------------------------------------------------------------------- #
# Tax worksheet serialization (used by tax-worksheet renderer)
# --------------------------------------------------------------------------- #
def _serialize_worksheet_for_render(
    sess: Session, ws: TaxWorksheet,
) -> dict[str, Any]:
    period = sess.get(AccountingPeriod, ws.period_id)
    form = sess.get(TaxForm, ws.form_id)
    lines = sess.execute(
        select(TaxWorksheetLine)
        .where(TaxWorksheetLine.worksheet_id == ws.id)
        .order_by(TaxWorksheetLine.sequence)
    ).scalars().all()
    return {
        "id": str(ws.id),
        "form_id": str(ws.form_id),
        "form_code": form.code.value if form else "",
        "status": ws.status.value,
        "catalog_version": ws.catalog_version,
        "sha256": ws.sha256,
        "period_id": str(ws.period_id),
        "period_start": period.start_date.isoformat() if period else "",
        "period_end": period.end_date.isoformat() if period else "",
        "total_income": str(ws.total_income),
        "total_cogs": str(ws.total_cogs),
        "total_deductions": str(ws.total_deductions),
        "taxable_income": str(ws.taxable_income),
        "lines": [
            {
                "line_code": ln.line_code,
                "line_label": ln.line_label,
                "section": ln.section.value,
                "sequence": ln.sequence,
                "amount": str(ln.amount),
                "contributing_accounts": ln.contributing_accounts or [],
            }
            for ln in lines
        ],
    }


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class GenerateStatementRequest:
    period_id: UUID
    kind: ArtifactKind
    format: ArtifactFormat
    cash_account_codes: list[str] | None = None  # required for CASH_FLOW
    prior_period_id: UUID | None = None


def _client_name(sess: Session, client_id: UUID) -> str:
    c = sess.get(Client, client_id)
    return c.name if c else str(client_id)


def _ensure_period(
    sess: Session, *, client_id: UUID, period_id: UUID,
) -> AccountingPeriod:
    p = sess.get(AccountingPeriod, period_id)
    if p is None or p.client_id != client_id:
        raise ArtifactNotFoundError("Period not found in this tenant.")
    return p


def _pending_drafts_count(
    sess: Session, *, client_id: UUID, period_start: date, period_end: date,
) -> int:
    # We count drafts globally on the client (drafts aren't period-scoped on
    # the schema). This is the same gate the tax worksheet uses; documented
    # constraint: "only finalized data exportable".
    _ = (period_start, period_end)
    n = sess.execute(
        select(func.count()).select_from(DraftClassification).where(
            DraftClassification.client_id == client_id,
            DraftClassification.status == DraftStatus.PENDING_REVIEW,
        )
    ).scalar_one()
    return int(n)


def _store_and_register(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    kind: ArtifactKind,
    fmt: ArtifactFormat,
    title: str,
    body: bytes,
    parameters: dict[str, Any],
    period_id: UUID | None = None,
    tax_worksheet_id: UUID | None = None,
) -> GeneratedArtifact:
    plaintext_sha = hashlib.sha256(body).hexdigest()
    enc = _build_encrypted_storage(get_storage())
    stored = enc.put(
        firm_id=firm_id, client_id=client_id,
        doc_type=f"artifact_{kind.value}_{fmt.value}",
        data=body,
        filename=f"{kind.value}.{fmt.value}",
        content_type=_content_type_for(fmt),
    )
    row = GeneratedArtifact(
        firm_id=firm_id, client_id=client_id,
        period_id=period_id, tax_worksheet_id=tax_worksheet_id,
        kind=kind, format=fmt, status=ArtifactStatus.DRAFT,
        storage_uri=stored.storage_uri,
        encrypted_sha256=stored.sha256,
        plaintext_sha256=plaintext_sha,
        size_bytes=len(body),
        title=title,
        parameters=parameters,
        generated_by=actor,
    )
    sess.add(row)
    sess.flush()
    write_audit(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        action=AuditAction.ARTIFACT_GENERATE,
        entity_type="generated_artifact",
        entity_id=row.id,
        details={
            "kind": kind.value, "format": fmt.value,
            "plaintext_sha256": plaintext_sha,
            "size_bytes": len(body),
            "period_id": str(period_id) if period_id else None,
        },
    )
    return row


def _content_type_for(fmt: ArtifactFormat) -> str:
    return {
        ArtifactFormat.PDF: "application/pdf",
        ArtifactFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ArtifactFormat.ZIP: "application/zip",
        ArtifactFormat.JSON: "application/json",
        ArtifactFormat.MARKDOWN: "text/markdown",
    }.get(fmt, "application/octet-stream")


def generate_statement_artifact(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    request: GenerateStatementRequest,
) -> GeneratedArtifact:
    """Render and store ONE financial-statement artifact."""
    if scope is not AccessScope.FIRM:
        raise ArtifactAccessForbiddenError("Only firm staff may generate artifacts.")
    if request.kind not in (
        ArtifactKind.PROFIT_AND_LOSS,
        ArtifactKind.BALANCE_SHEET,
        ArtifactKind.CASH_FLOW,
    ):
        raise ArtifactStateError(
            f"generate_statement_artifact does not support kind={request.kind.value}"
        )
    period = _ensure_period(sess, client_id=client_id, period_id=request.period_id)
    prior_period = None
    if request.prior_period_id is not None:
        prior_period = _ensure_period(
            sess, client_id=client_id, period_id=request.prior_period_id,
        )

    branding = BrandingContext.from_settings()
    renderer = _renderer_for(request.format)
    svc = StatementsService(sess, firm_id=firm_id, client_id=client_id)
    rules = PresentationRules()
    client_label = _client_name(sess, client_id)

    body: bytes
    title: str
    if request.kind is ArtifactKind.PROFIT_AND_LOSS:
        pl = svc.profit_and_loss(
            period_start=period.start_date, period_end=period.end_date,
        )
        prior = None
        if prior_period is not None:
            prior = svc.profit_and_loss(
                period_start=prior_period.start_date,
                period_end=prior_period.end_date,
            )
        presented = present_profit_and_loss(pl, rules=rules, prior=prior)
        body = renderer.render_profit_and_loss(
            presented, client_name=client_label, branding=branding,
        )
        title = f"Profit & Loss — {period.name}"
    elif request.kind is ArtifactKind.BALANCE_SHEET:
        bs = svc.balance_sheet(as_of=period.end_date)
        prior = None
        if prior_period is not None:
            prior = svc.balance_sheet(as_of=prior_period.end_date)
        presented = present_balance_sheet(bs, rules=rules, prior=prior)
        body = renderer.render_balance_sheet(
            presented, client_name=client_label, branding=branding,
        )
        title = f"Balance Sheet — {period.name}"
    else:  # CASH_FLOW
        if not request.cash_account_codes:
            raise ArtifactStateError(
                "cash_account_codes is required for cash-flow artifacts."
            )
        presented = present_cash_flow(
            sess,
            firm_id=firm_id, client_id=client_id,
            period_start=period.start_date,
            period_end=period.end_date,
            cash_account_codes=request.cash_account_codes,
            rules=rules,
        )
        body = renderer.render_cash_flow(
            presented, client_name=client_label, branding=branding,
        )
        title = f"Cash Flow — {period.name}"

    return _store_and_register(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        kind=request.kind, fmt=request.format,
        title=title, body=body,
        parameters={
            "period_id": str(request.period_id),
            "prior_period_id": (
                str(request.prior_period_id) if request.prior_period_id else None
            ),
            "cash_account_codes": request.cash_account_codes,
        },
        period_id=request.period_id,
    )


def generate_tax_worksheet_artifact(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    worksheet_id: UUID,
    fmt: ArtifactFormat,
) -> GeneratedArtifact:
    if scope is not AccessScope.FIRM:
        raise ArtifactAccessForbiddenError("Only firm staff may generate artifacts.")
    ws = sess.get(TaxWorksheet, worksheet_id)
    if ws is None or ws.client_id != client_id:
        raise ArtifactNotFoundError("Tax worksheet not found in this tenant.")
    branding = BrandingContext.from_settings()
    payload = _serialize_worksheet_for_render(sess, ws)
    client_label = _client_name(sess, client_id)

    # PDF tax-worksheet artifacts use the official IRS template (filled
    # AcroForm) instead of our generic ReportLab layout, so the output
    # is visually identical to the form taxpayers expect to see.
    if fmt is ArtifactFormat.PDF:
        body = _render_irs_pdf(sess, ws, payload, client_label)
    else:
        renderer = _renderer_for(fmt)
        body = renderer.render_tax_worksheet(
            payload, client_name=client_label, branding=branding,
        )
    return _store_and_register(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        kind=ArtifactKind.TAX_WORKSHEET, fmt=fmt,
        title=f"Tax Worksheet — {payload['form_code']}",
        body=body,
        parameters={
            "worksheet_id": str(worksheet_id),
            "form_code": payload["form_code"],
            "period_id": str(ws.period_id),
        },
        period_id=ws.period_id,
        tax_worksheet_id=ws.id,
    )


def _render_irs_pdf(
    sess: Session,
    ws: TaxWorksheet,
    payload: dict[str, Any],
    client_label: str,
) -> bytes:
    """Render a tax worksheet by filling the official IRS PDF template."""
    # Imported lazily so missing pypdf or template files don't break other
    # artifact paths.
    from app.domain.irs_form_filler import IrsFormFiller, TaxFillerContext
    from app.models.enums import TaxFormCode

    form_code = TaxFormCode(payload["form_code"])
    period = sess.get(AccountingPeriod, ws.period_id)
    ctx = TaxFillerContext(
        client_name=client_label,
        period_start=period.start_date if period else None,
        period_end=period.end_date if period else None,
        # EIN / address are not yet stored on Client — leave blank rather
        # than make up values. The IRS form will simply have those header
        # boxes empty, exactly how a partially-completed return looks.
    )
    return IrsFormFiller().render(
        form_code=form_code, worksheet=payload, ctx=ctx,
    )


# --------------------------------------------------------------------------- #
# Finalize / supersession
# --------------------------------------------------------------------------- #
def finalize_artifact(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    artifact_id: UUID,
) -> GeneratedArtifact:
    """Promote a DRAFT artifact to FINALIZED.

    Refuses if any PENDING_REVIEW DraftClassification rows still exist for
    the client+period — the canonical "only finalized data exportable" gate.
    Supersedes any prior FINALIZED artifact of the same (kind, format,
    period_id) by flipping its status to SUPERSEDED.
    """
    if scope is not AccessScope.FIRM:
        raise ArtifactAccessForbiddenError("Only firm staff may finalize artifacts.")
    art = sess.get(GeneratedArtifact, artifact_id)
    if art is None or art.client_id != client_id:
        raise ArtifactNotFoundError("Artifact not found in this tenant.")
    if art.status is not ArtifactStatus.DRAFT:
        raise ArtifactStateError(
            f"Artifact is in status {art.status.value}; only DRAFT can be finalized."
        )
    # Pending-drafts gate.
    if art.period_id is not None:
        period = sess.get(AccountingPeriod, art.period_id)
        if period is not None:
            pending = _pending_drafts_count(
                sess, client_id=client_id,
                period_start=period.start_date, period_end=period.end_date,
            )
            if pending > 0:
                raise ExportBlockedByPendingDraftsError(
                    f"{pending} pending classification draft(s) must be resolved "
                    "before finalizing this artifact."
                )

    # Phase 8b: FormTemplate gate. A TAX_WORKSHEET PDF may only be
    # FINALIZED when an ACTIVE+verified form_template row exists for the
    # (form_code, tax_year). Non-PDF tax worksheets (XLSX/JSON/MD) are
    # internal review formats and not subject to this gate; non-tax
    # artifacts are unaffected entirely.
    if (
        art.kind is ArtifactKind.TAX_WORKSHEET
        and art.format is ArtifactFormat.PDF
        and art.tax_worksheet_id is not None
    ):
        from app.domain.form_template import (
            FormTemplateNotActiveError,
            get_active_verified,
        )

        ws = sess.get(TaxWorksheet, art.tax_worksheet_id)
        if ws is not None:
            form = sess.get(TaxForm, ws.form_id)
            period = sess.get(AccountingPeriod, ws.period_id)
            if form is not None and period is not None:
                try:
                    get_active_verified(
                        sess,
                        form_code=form.code,
                        tax_year=period.end_date.year,
                    )
                except FormTemplateNotActiveError as e:
                    raise ArtifactStateError(str(e)) from e

    # Supersede prior FINALIZED of same (kind, format, period_id).
    superseded_ids: list[str] = []
    prior_q = select(GeneratedArtifact).where(
        GeneratedArtifact.client_id == client_id,
        GeneratedArtifact.kind == art.kind,
        GeneratedArtifact.format == art.format,
        GeneratedArtifact.status == ArtifactStatus.FINALIZED,
    )
    if art.period_id is not None:
        prior_q = prior_q.where(GeneratedArtifact.period_id == art.period_id)
    if art.tax_worksheet_id is not None:
        prior_q = prior_q.where(GeneratedArtifact.tax_worksheet_id == art.tax_worksheet_id)
    for prior_art in sess.execute(prior_q).scalars().all():
        prior_art.status = ArtifactStatus.SUPERSEDED
        superseded_ids.append(str(prior_art.id))

    art.status = ArtifactStatus.FINALIZED
    art.finalized_by = actor
    art.finalized_at = datetime.now(tz=UTC)
    if superseded_ids:
        # Link the SUPERSEDED predecessor(s). We only carry one link slot;
        # for the common case of one prior, this is sufficient. The audit
        # trail carries the full list.
        first_prior = superseded_ids[0]
        art.supersedes_id = UUID(first_prior)
    sess.flush()
    write_audit(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        action=AuditAction.ARTIFACT_FINALIZE,
        entity_type="generated_artifact",
        entity_id=art.id,
        details={
            "kind": art.kind.value,
            "format": art.format.value,
            "superseded_ids": superseded_ids,
        },
    )
    return art


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ArtifactBody:
    artifact: GeneratedArtifact
    body: bytes
    content_type: str


def download_artifact(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    artifact_id: UUID,
) -> ArtifactBody:
    """Fetch the decrypted body of an artifact.

    Portal users (`AccessScope.CLIENT`) get `ArtifactNotFoundError` for any
    artifact that is not FINALIZED. Verifies plaintext sha256 on read; tamper
    raises `ArtifactStateError`.
    """
    art = sess.get(GeneratedArtifact, artifact_id)
    if art is None:
        raise ArtifactNotFoundError("Artifact not found.")
    if scope is AccessScope.CLIENT and art.status is not ArtifactStatus.FINALIZED:
        raise ArtifactNotFoundError("Artifact not found.")
    enc = _build_encrypted_storage(get_storage())
    body = enc.get(
        firm_id=firm_id, client_id=client_id, storage_uri=art.storage_uri,
    )
    actual = hashlib.sha256(body).hexdigest()
    if actual != art.plaintext_sha256:
        raise ArtifactStateError(
            "Plaintext sha256 mismatch on download — body may have been tampered."
        )
    write_audit(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        action=AuditAction.ARTIFACT_DOWNLOAD,
        entity_type="generated_artifact",
        entity_id=art.id,
        details={
            "kind": art.kind.value,
            "format": art.format.value,
            "size_bytes": art.size_bytes,
        },
    )
    return ArtifactBody(
        artifact=art, body=body, content_type=_content_type_for(art.format),
    )


# --------------------------------------------------------------------------- #
# Narrative artifact
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class GenerateNarrativeRequest:
    period_id: UUID
    cash_account_codes: list[str] | None = None
    prior_period_id: UUID | None = None
    writer: NarrativeWriter | None = None  # default = deterministic template


@dataclass(frozen=True, slots=True)
class NarrativeArtifactResult:
    artifact: GeneratedArtifact
    safety_report: NarrativeSafetyReport
    used_fallback: bool


def _build_period_presentations(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    period: AccountingPeriod,
    prior_period: AccountingPeriod | None,
    cash_account_codes: list[str] | None,
    rules: PresentationRules,
) -> tuple[
    PresentedProfitAndLoss,
    PresentedBalanceSheet,
    PresentedCashFlow | None,
]:
    svc = StatementsService(sess, firm_id=firm_id, client_id=client_id)
    pl_raw = svc.profit_and_loss(
        period_start=period.start_date, period_end=period.end_date,
    )
    pl_prior = None
    bs_prior = None
    if prior_period is not None:
        pl_prior = svc.profit_and_loss(
            period_start=prior_period.start_date,
            period_end=prior_period.end_date,
        )
        bs_prior = svc.balance_sheet(as_of=prior_period.end_date)
    pl = present_profit_and_loss(pl_raw, rules=rules, prior=pl_prior)
    bs = present_balance_sheet(
        svc.balance_sheet(as_of=period.end_date), rules=rules, prior=bs_prior,
    )
    cf: PresentedCashFlow | None = None
    if cash_account_codes:
        cf = present_cash_flow(
            sess,
            firm_id=firm_id, client_id=client_id,
            period_start=period.start_date,
            period_end=period.end_date,
            cash_account_codes=cash_account_codes,
            rules=rules,
        )
    return pl, bs, cf


def generate_narrative_artifact(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    request: GenerateNarrativeRequest,
) -> NarrativeArtifactResult:
    """Compose the period narrative and persist it as a DRAFT artifact.

    Safety: prose is checked against `build_allowed_numbers(pl, bs, cf)`. If
    the configured writer (e.g. LLM) produces prose with a foreign number,
    `generate_narrative` silently falls back to the deterministic template;
    we record both the report and a `used_fallback` flag in the artifact's
    `parameters` and audit details so reviewers can investigate.
    """
    if scope is not AccessScope.FIRM:
        raise ArtifactAccessForbiddenError("Only firm staff may generate artifacts.")
    period = _ensure_period(sess, client_id=client_id, period_id=request.period_id)
    prior_period = None
    if request.prior_period_id is not None:
        prior_period = _ensure_period(
            sess, client_id=client_id, period_id=request.prior_period_id,
        )
    rules = PresentationRules()
    pl, bs, cf = _build_period_presentations(
        sess,
        firm_id=firm_id, client_id=client_id,
        period=period, prior_period=prior_period,
        cash_account_codes=request.cash_account_codes,
        rules=rules,
    )
    client_label = _client_name(sess, client_id)
    prose, report = generate_narrative(
        client_name=client_label,
        pl=pl, bs=bs, cf=cf,
        currency="USD",
        writer=request.writer,
    )
    used_fallback = not report.ok
    body = prose.encode("utf-8")
    art = _store_and_register(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        kind=ArtifactKind.NARRATIVE,
        fmt=ArtifactFormat.MARKDOWN,
        title=f"Narrative — {period.name}",
        body=body,
        parameters={
            "period_id": str(request.period_id),
            "prior_period_id": (
                str(request.prior_period_id) if request.prior_period_id else None
            ),
            "cash_account_codes": request.cash_account_codes,
            "used_fallback": used_fallback,
            "foreign_numbers": [
                {"kind": k, "value": str(v)} for k, v in report.foreign_numbers
            ],
        },
        period_id=request.period_id,
    )
    return NarrativeArtifactResult(
        artifact=art, safety_report=report, used_fallback=used_fallback,
    )


# --------------------------------------------------------------------------- #
# Query helpers
# --------------------------------------------------------------------------- #
def list_artifacts(
    sess: Session,
    *,
    scope: AccessScope,
    period_id: UUID | None = None,
    kind: ArtifactKind | None = None,
) -> list[GeneratedArtifact]:
    q = select(GeneratedArtifact)
    if period_id is not None:
        q = q.where(GeneratedArtifact.period_id == period_id)
    if kind is not None:
        q = q.where(GeneratedArtifact.kind == kind)
    if scope is AccessScope.CLIENT:
        # Portal users see in-progress (DRAFT) AND finalized work so they
        # know their firm is preparing reports. SUPERSEDED is hidden (it's
        # an old finalized doc that has been replaced). Download is still
        # blocked for non-FINALIZED artifacts in `download_artifact`.
        q = q.where(
            GeneratedArtifact.status.in_(
                [ArtifactStatus.DRAFT, ArtifactStatus.FINALIZED]
            )
        )
    q = q.order_by(GeneratedArtifact.generated_at.desc())
    return list(sess.execute(q).scalars().all())


def _decimal_set_from_obj(obj: Any) -> set[Decimal]:
    """Collect every Decimal-coercible number in a JSON-like structure."""
    out: set[Decimal] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= _decimal_set_from_obj(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= _decimal_set_from_obj(v)
    elif isinstance(obj, Decimal):
        out.add(obj)
    elif isinstance(obj, (int, float)):
        out.add(Decimal(str(obj)))
    elif isinstance(obj, str):
        # Don't try to parse arbitrary strings — too noisy. Numbers we care
        # about always arrive as Decimal/int/float from the engine.
        pass
    return out


def _dump_json_bytes(obj: Any) -> bytes:
    """Stable JSON dump for sha256 / inclusion in audit packages."""
    def default(o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, UUID):
            return str(o)
        raise TypeError(f"Not JSON-serialisable: {type(o)}")

    return json.dumps(obj, sort_keys=True, default=default, indent=2).encode()


def _iterable_artifacts(
    sess: Session, ids: Iterable[UUID],
) -> list[GeneratedArtifact]:
    """Fetch artifacts by id list, preserving the iteration order."""
    out: list[GeneratedArtifact] = []
    for aid in ids:
        art = sess.get(GeneratedArtifact, aid)
        if art is not None:
            out.append(art)
    return out


__all__ = [
    "ArtifactAccessForbiddenError",
    "ArtifactBody",
    "ArtifactNotFoundError",
    "ArtifactStateError",
    "ExportBlockedByPendingDraftsError",
    "GenerateNarrativeRequest",
    "GenerateStatementRequest",
    "NarrativeArtifactResult",
    "download_artifact",
    "finalize_artifact",
    "generate_narrative_artifact",
    "generate_statement_artifact",
    "generate_tax_worksheet_artifact",
    "list_artifacts",
    "_build_encrypted_storage",
    "_dump_json_bytes",
    "_iterable_artifacts",
    "_decimal_set_from_obj",
]
