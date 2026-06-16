"""Job dispatcher.

This module decodes a queue payload and runs the right domain handler under a
**fresh** tenant_session built from the payload. The dispatcher is deliberately
decoupled from any transport (Redis Streams, in-memory queue, RQ, Celery): it
takes a `dict` payload and runs the work. The Redis consumer in `consumer.py`
imports `dispatch_payload` and feeds it.

Tenant isolation contract
-------------------------
Every payload carries `firm_id`, `client_id`, `scope`. The dispatcher opens a
NEW `tenant_session` against those values, so jobs from different tenants
running on the same worker process see strictly separate RLS contexts. The
`tenant_session` context manager scopes `SET LOCAL` to the transaction, so
nothing leaks across jobs.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.db.session import tenant_session
from app.db.tenant import AccessScope, TenantContext
from app.domain.classification import run_classification
from app.domain.extraction import run_extraction
from app.integrations.registry import get_classifier, get_extractor, get_queue, get_storage


class UnknownJobTypeError(Exception):
    pass


def _ctx_from_payload(payload: dict[str, Any]) -> TenantContext:
    return TenantContext(
        firm_id=UUID(payload["firm_id"]),
        client_id=UUID(payload["client_id"]),
        scope=AccessScope(payload["scope"]),
    )


def dispatch_payload(payload: dict[str, Any]) -> None:
    """Decode the payload and run the matching handler.

    Raises `UnknownJobTypeError` for an unrecognised `type`.
    """
    job_type = payload.get("type")
    ctx = _ctx_from_payload(payload)
    actor = str(payload.get("actor", "worker"))

    if job_type == "extract":
        with tenant_session(ctx) as sess:
            run_extraction(
                sess,
                firm_id=ctx.firm_id,
                client_id=UUID(payload["client_id"]),
                actor=actor,
                source_document_id=UUID(payload["source_document_id"]),
                kind_hint=str(payload.get("kind_hint", "generic")),
                storage=get_storage(),
                extractor=get_extractor(),
                queue=get_queue(),
            )
        return

    if job_type == "classify":
        with tenant_session(ctx) as sess:
            run_classification(
                sess,
                firm_id=ctx.firm_id,
                client_id=UUID(payload["client_id"]),
                actor=actor,
                source_document_id=UUID(payload["source_document_id"]),
                kind_hint=str(payload.get("kind_hint", "generic")),
                classifier=get_classifier(),
            )
        return

    raise UnknownJobTypeError(f"Unknown job type: {job_type!r}")


__all__ = ["UnknownJobTypeError", "dispatch_payload"]
