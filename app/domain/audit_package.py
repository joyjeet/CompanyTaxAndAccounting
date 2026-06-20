"""Audit-ready package builder.

Assembles a single zip from the set of FINALIZED artifacts for a period,
plus the period's audit log, plus a manifest carrying SHA256s. The zip is
then encrypt-stored as an `AUDIT_PACKAGE` artifact in its own right so its
download is itself audited.

Contract
--------
* Period must have FINALIZED PL/BS/CF in BOTH PDF and XLSX formats.
* Period must have a FINALIZED NARRATIVE artifact.
* All FINALIZED tax-worksheet artifacts that reference the period are
  included (any format).
* Any PENDING_REVIEW draft classifications for the client block the
  package — this is the "only finalized data exportable" rule.
* The audit log included is filtered to events whose `at` falls within the
  period dates, scoped to the (firm_id, client_id) pair.
* The manifest records the sha256 of EACH zip member and the package
  generation context (actor, generated_at, period dates, dependency
  artifact ids).
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.tenant import AccessScope
from app.domain.artifact_service import (
    ArtifactAccessForbiddenError,
    ArtifactNotFoundError,
    ArtifactStateError,
    ExportBlockedByPendingDraftsError,
    _build_encrypted_storage,
    _dump_json_bytes,
    _pending_drafts_count,
    _store_and_register,
)
from app.domain.audit import write_audit
from app.integrations.registry import get_storage
from app.models.accounting import (
    AccountingPeriod,
    AuditEvent,
    GeneratedArtifact,
)
from app.models.enums import (
    ArtifactFormat,
    ArtifactKind,
    ArtifactStatus,
    AuditAction,
)

REQUIRED_STATEMENTS: tuple[tuple[ArtifactKind, ArtifactFormat], ...] = (
    (ArtifactKind.PROFIT_AND_LOSS, ArtifactFormat.PDF),
    (ArtifactKind.PROFIT_AND_LOSS, ArtifactFormat.XLSX),
    (ArtifactKind.BALANCE_SHEET, ArtifactFormat.PDF),
    (ArtifactKind.BALANCE_SHEET, ArtifactFormat.XLSX),
    (ArtifactKind.CASH_FLOW, ArtifactFormat.PDF),
    (ArtifactKind.CASH_FLOW, ArtifactFormat.XLSX),
)


class AuditPackageMissingDependencyError(ArtifactStateError):
    """One or more required FINALIZED artifacts are missing."""


@dataclass(frozen=True, slots=True)
class AuditPackageResult:
    artifact: GeneratedArtifact
    member_count: int
    dependency_ids: tuple[UUID, ...]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _latest_finalized(
    sess: Session,
    *,
    client_id: UUID,
    period_id: UUID,
    kind: ArtifactKind,
    fmt: ArtifactFormat,
) -> GeneratedArtifact | None:
    q = (
        select(GeneratedArtifact)
        .where(
            GeneratedArtifact.client_id == client_id,
            GeneratedArtifact.period_id == period_id,
            GeneratedArtifact.kind == kind,
            GeneratedArtifact.format == fmt,
            GeneratedArtifact.status == ArtifactStatus.FINALIZED,
        )
        .order_by(GeneratedArtifact.finalized_at.desc())
    )
    return sess.execute(q).scalars().first()


def _finalized_tax_worksheets(
    sess: Session, *, client_id: UUID, period_id: UUID,
) -> list[GeneratedArtifact]:
    q = (
        select(GeneratedArtifact)
        .where(
            GeneratedArtifact.client_id == client_id,
            GeneratedArtifact.period_id == period_id,
            GeneratedArtifact.kind == ArtifactKind.TAX_WORKSHEET,
            GeneratedArtifact.status == ArtifactStatus.FINALIZED,
        )
        .order_by(GeneratedArtifact.finalized_at.desc())
    )
    return list(sess.execute(q).scalars().all())


def _audit_events_for_period(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    period: AccountingPeriod,
) -> list[dict]:
    # Cast period date boundaries to datetime; audit_event.at is a TS.
    start_ts = datetime(
        period.start_date.year, period.start_date.month, period.start_date.day,
        tzinfo=UTC,
    )
    # End-of-day exclusive: extend to next-day midnight for the upper bound.
    from datetime import timedelta
    end_ts = datetime(
        period.end_date.year, period.end_date.month, period.end_date.day,
        tzinfo=UTC,
    ) + timedelta(days=1)
    q = (
        select(AuditEvent)
        .where(
            AuditEvent.firm_id == firm_id,
            AuditEvent.client_id == client_id,
            AuditEvent.at >= start_ts,
            AuditEvent.at < end_ts,
        )
        .order_by(AuditEvent.at.asc())
    )
    out: list[dict] = []
    for ev in sess.execute(q).scalars().all():
        out.append({
            "id": str(ev.id),
            "actor": ev.actor,
            "action": ev.action.value,
            "entity_type": ev.entity_type,
            "entity_id": str(ev.entity_id) if ev.entity_id else None,
            "at": ev.at.isoformat(),
            "details": ev.details or {},
        })
    return out


def _read_artifact_body(sess: Session, art: GeneratedArtifact) -> bytes:
    """Decrypt the artifact body and verify the plaintext sha256."""
    enc = _build_encrypted_storage(get_storage())
    body = enc.get(
        firm_id=art.firm_id, client_id=art.client_id,
        storage_uri=art.storage_uri,
    )
    actual = hashlib.sha256(body).hexdigest()
    if actual != art.plaintext_sha256:
        raise ArtifactStateError(
            f"Plaintext sha256 mismatch for artifact {art.id} during package "
            "assembly."
        )
    return body


def _path_for(art: GeneratedArtifact) -> str:
    """Zip-internal path for an artifact."""
    kind_dir = {
        ArtifactKind.PROFIT_AND_LOSS: "statements",
        ArtifactKind.BALANCE_SHEET: "statements",
        ArtifactKind.CASH_FLOW: "statements",
        ArtifactKind.TAX_WORKSHEET: "tax",
        ArtifactKind.NARRATIVE: ".",
    }.get(art.kind, "other")
    name = f"{art.kind.value}.{art.format.value}"
    if art.kind is ArtifactKind.TAX_WORKSHEET:
        worksheet_label = (
            art.parameters.get("form_code") if isinstance(art.parameters, dict) else None
        ) or str(art.tax_worksheet_id)
        name = f"{worksheet_label}.{art.format.value}"
    if art.kind is ArtifactKind.NARRATIVE:
        name = "narrative.md"
    if kind_dir == ".":
        return name
    return f"{kind_dir}/{name}"


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def generate_audit_package(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    scope: AccessScope,
    period_id: UUID,
) -> AuditPackageResult:
    """Build the audit-ready package for a period and persist as DRAFT.

    Raises:
        ArtifactAccessForbiddenError: scope is not FIRM.
        ArtifactNotFoundError: period missing in this tenant.
        AuditPackageMissingDependencyError: required FINALIZED artifacts absent.
        ExportBlockedByPendingDraftsError: PENDING_REVIEW drafts exist.
    """
    if scope is not AccessScope.FIRM:
        raise ArtifactAccessForbiddenError(
            "Only firm staff may generate audit packages."
        )
    period = sess.get(AccountingPeriod, period_id)
    if period is None or period.client_id != client_id:
        raise ArtifactNotFoundError("Period not found in this tenant.")

    pending = _pending_drafts_count(
        sess, client_id=client_id,
        period_start=period.start_date, period_end=period.end_date,
    )
    if pending > 0:
        raise ExportBlockedByPendingDraftsError(
            f"{pending} pending classification draft(s) must be resolved "
            "before generating an audit package."
        )

    # Gather required statements.
    members: list[GeneratedArtifact] = []
    missing: list[str] = []
    for kind, fmt in REQUIRED_STATEMENTS:
        art = _latest_finalized(
            sess, client_id=client_id, period_id=period_id,
            kind=kind, fmt=fmt,
        )
        if art is None:
            missing.append(f"{kind.value} ({fmt.value})")
        else:
            members.append(art)

    # Narrative is required.
    narrative = _latest_finalized(
        sess, client_id=client_id, period_id=period_id,
        kind=ArtifactKind.NARRATIVE, fmt=ArtifactFormat.MARKDOWN,
    )
    if narrative is None:
        missing.append("narrative (markdown)")
    else:
        members.append(narrative)

    if missing:
        raise AuditPackageMissingDependencyError(
            "Audit package requires FINALIZED artifacts that are missing: "
            + ", ".join(missing)
        )

    # Tax worksheets are optional; include all FINALIZED for the period.
    for ws_art in _finalized_tax_worksheets(
        sess, client_id=client_id, period_id=period_id,
    ):
        members.append(ws_art)

    # Build the zip in memory.
    audit_events = _audit_events_for_period(
        sess, firm_id=firm_id, client_id=client_id, period=period,
    )
    audit_events_bytes = _dump_json_bytes(audit_events)

    generated_at = datetime.now(tz=UTC)

    member_records: list[dict] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for art in members:
            body = _read_artifact_body(sess, art)
            path = _path_for(art)
            zf.writestr(path, body)
            member_records.append({
                "path": path,
                "artifact_id": str(art.id),
                "kind": art.kind.value,
                "format": art.format.value,
                "title": art.title,
                "plaintext_sha256": art.plaintext_sha256,
                "size_bytes": art.size_bytes,
                "finalized_by": art.finalized_by,
                "finalized_at": (
                    art.finalized_at.isoformat() if art.finalized_at else None
                ),
            })

        # Audit log
        zf.writestr("audit_events.json", audit_events_bytes)
        member_records.append({
            "path": "audit_events.json",
            "kind": "audit_log",
            "format": "json",
            "plaintext_sha256": hashlib.sha256(audit_events_bytes).hexdigest(),
            "size_bytes": len(audit_events_bytes),
            "event_count": len(audit_events),
        })

        # Manifest (must be added LAST so it can reflect every other member).
        manifest = {
            "package_version": "1",
            "client_id": str(client_id),
            "firm_id": str(firm_id),
            "period": {
                "id": str(period.id),
                "name": period.name,
                "start_date": period.start_date.isoformat(),
                "end_date": period.end_date.isoformat(),
            },
            "generated_at": generated_at.isoformat(),
            "generated_by": actor,
            "members": member_records,
        }
        manifest_bytes = _dump_json_bytes(manifest)
        zf.writestr("manifest.json", manifest_bytes)

    zip_bytes = buf.getvalue()

    # Persist as a single AUDIT_PACKAGE artifact.
    art = _store_and_register(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        kind=ArtifactKind.AUDIT_PACKAGE, fmt=ArtifactFormat.ZIP,
        title=f"Audit package — {period.name}",
        body=zip_bytes,
        parameters={
            "period_id": str(period_id),
            "member_count": len(member_records),
            "dependency_ids": [str(m.id) for m in members],
        },
        period_id=period_id,
    )

    write_audit(
        sess,
        firm_id=firm_id, client_id=client_id, actor=actor,
        action=AuditAction.AUDIT_PACKAGE_GENERATE,
        entity_type="generated_artifact",
        entity_id=art.id,
        details={
            "period_id": str(period_id),
            "member_count": len(member_records),
            "dependency_ids": [str(m.id) for m in members],
            "package_sha256": art.plaintext_sha256,
        },
    )

    return AuditPackageResult(
        artifact=art,
        member_count=len(member_records),
        dependency_ids=tuple(m.id for m in members),
    )


__all__ = [
    "AuditPackageMissingDependencyError",
    "AuditPackageResult",
    "REQUIRED_STATEMENTS",
    "generate_audit_package",
]
