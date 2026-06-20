"""Tenant-scoped audit log export with a tamper-evident hash chain.

Each exported row carries:

* the row's intrinsic data;
* a ``row_hash`` = SHA-256 over a canonical JSON encoding of that row;
* a ``prev_hash`` = the previous row's ``row_hash`` (or 64 zeros for the
  first row).

Exporting through this endpoint produces evidence the row order/content has
not been altered: any insertion/edit/deletion within the export will break
the chain.

The DB itself enforces audit-log immutability (REVOKE UPDATE/DELETE in
migration 0002). The chain emitted here is a *cross-system* attestation:
once it's been signed and stored externally (auditor share, write-once
storage), even an owner-level SQL injection cannot rewrite it.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import AuthIdentity, get_identity
from app.api.deps import db_session
from app.db.tenant import AccessScope
from app.domain.audit import write_audit
from app.models.accounting import AuditEvent
from app.models.enums import AuditAction

router = APIRouter(prefix="/audit", tags=["audit"])

_NULL_HASH = "0" * 64


def _canonicalize(row: dict[str, Any]) -> bytes:
    """Stable JSON encoding for hashing. Sorted keys + ISO timestamps."""
    return json.dumps(
        row,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


@router.get("/export")
def export_audit(
    period_start: datetime = Query(
        ..., description="Inclusive lower bound (UTC, ISO-8601)"
    ),
    period_end: datetime = Query(
        ..., description="Inclusive upper bound (UTC, ISO-8601)"
    ),
    identity: AuthIdentity = Depends(get_identity),
    sess: Session = Depends(db_session),
) -> dict[str, Any]:
    """Export the firm's audit log over a closed time window, with hash chain.

    Firm-scope only. RLS already filters rows to the caller's firm; this
    endpoint additionally refuses portal (CLIENT) tokens because the audit
    log is firm-administrative evidence.
    """
    if identity.scope is not AccessScope.FIRM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="audit export requires firm-scope identity",
        )
    if period_end < period_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_end must be >= period_start",
        )

    stmt = (
        select(AuditEvent)
        .where(AuditEvent.at >= period_start)
        .where(AuditEvent.at <= period_end)
        .order_by(AuditEvent.at, AuditEvent.id)
    )
    events = sess.execute(stmt).scalars().all()

    chain: list[dict[str, Any]] = []
    prev = _NULL_HASH
    for evt in events:
        body = {
            "id": str(evt.id),
            "firm_id": str(evt.firm_id),
            "client_id": str(evt.client_id),
            "actor": evt.actor,
            "action": evt.action.value,
            "entity_type": evt.entity_type,
            "entity_id": str(evt.entity_id) if evt.entity_id else None,
            "details": evt.details,
            "at": evt.at.isoformat(),
            "prev_hash": prev,
        }
        h = hashlib.sha256(_canonicalize(body)).hexdigest()
        body["row_hash"] = h
        chain.append(body)
        prev = h

    # The export itself is auditable.
    write_audit(
        sess,
        firm_id=identity.firm_id,
        client_id=identity.firm_id,
        actor=identity.subject,
        action=AuditAction.AUDIT_EXPORT,
        entity_type="audit_log",
        details={
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "row_count": len(chain),
            "tip_hash": prev,
        },
    )

    return {
        "firm_id": str(identity.firm_id),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "count": len(chain),
        "tip_hash": prev,
        "events": chain,
    }
