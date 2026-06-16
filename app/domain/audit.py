"""Audit logging helper. ALL state changes route through here so the audit
trail is uniform and append-only at the application layer.

Note (assumption flagged): I have not yet REVOKE'd UPDATE/DELETE on
audit_event from app_user — that hardening is a follow-up. For now, append-only
is enforced by convention: nothing in the codebase mutates audit rows.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.accounting import AuditEvent
from app.models.enums import AuditAction


def write_audit(
    sess: Session,
    *,
    firm_id: UUID,
    client_id: UUID,
    actor: str,
    action: AuditAction,
    entity_type: str,
    entity_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    evt = AuditEvent(
        firm_id=firm_id,
        client_id=client_id,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    sess.add(evt)
    sess.flush()
    return evt
