"""Worker-level tenant isolation: jobs from different tenants run on the
same worker process and MUST NOT see each other's data."""
from __future__ import annotations

from sqlalchemy import select

from app.db.session import tenant_session
from app.domain.ingest import ingest_document
from app.models.accounting import DraftClassification, SourceDocument
from app.workers.jobs import dispatch_payload
from tests.conftest import SeededWorld, ctx_firm_for_client


def _enqueue_one(
    world: SeededWorld,
    fake_integrations,
    *,
    seeded,
    data: bytes,
    kind_hint: str,
):
    with tenant_session(ctx_firm_for_client(seeded.firm_id, seeded.client_id)) as sess:
        return ingest_document(
            sess,
            firm_id=seeded.firm_id,
            client_id=seeded.client_id,
            actor="staff",
            data=data,
            filename="f.pdf",
            content_type="application/pdf",
            kind_hint=kind_hint,
            storage=fake_integrations.storage,
            queue=fake_integrations.queue,
        )


def test_dispatcher_does_not_leak_across_tenants(
    world: SeededWorld, fake_integrations
) -> None:
    # Two distinct tenants.
    r1 = _enqueue_one(
        world, fake_integrations, seeded=world.a1,
        data=b"ACME COFFEE 03/15 $4.25", kind_hint="bank_transaction",
    )
    r2 = _enqueue_one(
        world, fake_integrations, seeded=world.b1,
        data=b"BETA SUPPLIES 01/05 $9.99", kind_hint="bank_transaction",
    )

    # Dispatch all extract + classify jobs in the same worker process.
    for payload in [p for _, p in fake_integrations.queue.drain("extract")]:
        dispatch_payload(payload)
    for payload in [p for _, p in fake_integrations.queue.drain("classify")]:
        dispatch_payload(payload)

    # Verify each tenant sees ONLY their own draft + source doc.
    with tenant_session(ctx_firm_for_client(world.a1.firm_id, world.a1.client_id)) as sess:
        docs = sess.execute(select(SourceDocument)).scalars().all()
        assert len(docs) == 1
        assert docs[0].id == r1.source_document_id
        drafts = sess.execute(select(DraftClassification)).scalars().all()
        assert len(drafts) == 1
        assert drafts[0].source_document_id == r1.source_document_id

    with tenant_session(ctx_firm_for_client(world.b1.firm_id, world.b1.client_id)) as sess:
        docs = sess.execute(select(SourceDocument)).scalars().all()
        assert len(docs) == 1
        assert docs[0].id == r2.source_document_id
        drafts = sess.execute(select(DraftClassification)).scalars().all()
        assert len(drafts) == 1
        assert drafts[0].source_document_id == r2.source_document_id
