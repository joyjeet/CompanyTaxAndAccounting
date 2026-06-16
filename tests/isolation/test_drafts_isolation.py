"""Cross-tenant isolation for the draft_classification table."""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError

from app.db.session import tenant_session, unscoped_session
from app.models.accounting import DraftClassification, SourceDocument
from app.models.enums import DraftKind, DraftStatus, OcrStatus
from tests.conftest import SeededWorld, ctx_client, ctx_firm, ctx_firm_for_client


def _seed_doc_and_draft(world: SeededWorld) -> dict:
    """Create one source_document + draft_classification per seeded client.
    Returns a dict mapping (firm_id, client_id) -> draft_id."""
    out: dict = {}
    for sc in (world.a1, world.a2, world.b1):
        with tenant_session(ctx_firm_for_client(sc.firm_id, sc.client_id)) as sess:
            sd_id = uuid4()
            sess.add(
                SourceDocument(
                    id=sd_id,
                    firm_id=sc.firm_id,
                    client_id=sc.client_id,
                    kind="generic",
                    storage_uri=f"firm-{sc.firm_id}/client-{sc.client_id}/2026/generic/{uuid4()}.pdf",
                    sha256="0" * 64,
                    ocr_status=OcrStatus.COMPLETE,
                    extracted={"text": "hi", "fields": [], "model": "mock"},
                )
            )
            sess.flush()
            d_id = uuid4()
            sess.add(
                DraftClassification(
                    id=d_id,
                    firm_id=sc.firm_id,
                    client_id=sc.client_id,
                    source_document_id=sd_id,
                    kind=DraftKind.GENERIC,
                    status=DraftStatus.PENDING_REVIEW,
                    needs_review=True,
                    high_confidence=False,
                    confidence=Decimal("0.5"),
                    model="mock",
                    prompt_version="1",
                    payload={"text": "hi"},
                )
            )
            sess.flush()
            out[(sc.firm_id, sc.client_id)] = d_id
    return out


def test_firm_scope_cannot_see_other_firms_drafts(world: SeededWorld) -> None:
    _seed_doc_and_draft(world)
    with tenant_session(ctx_firm(world.firm_a)) as sess:
        rows = sess.execute(select(DraftClassification)).scalars().all()
        seen = {(d.firm_id, d.client_id) for d in rows}
        assert seen == {(world.firm_a, world.a1.client_id), (world.firm_a, world.a2.client_id)}, seen


def test_client_scope_only_sees_own_drafts(world: SeededWorld) -> None:
    _seed_doc_and_draft(world)
    with tenant_session(ctx_client(world.firm_a, world.a1.client_id)) as sess:
        rows = sess.execute(select(DraftClassification)).scalars().all()
        for d in rows:
            assert d.client_id == world.a1.client_id


def test_no_context_sees_no_drafts(world: SeededWorld) -> None:
    _seed_doc_and_draft(world)
    with unscoped_session() as sess:
        rows = sess.execute(select(DraftClassification)).scalars().all()
        assert rows == []


def test_cannot_insert_draft_into_another_firm(world: SeededWorld) -> None:
    """Firm A staff tagging a draft with firm B's id must fail RLS WITH CHECK."""
    _seed_doc_and_draft(world)
    # Get a SourceDocument id from B (RLS-bypass via direct seed lookup).
    with tenant_session(ctx_firm(world.firm_b)) as sess:
        sd = sess.execute(select(SourceDocument)).scalars().first()
        assert sd is not None
        sd_id = sd.id
        target_firm = sd.firm_id
        target_client = sd.client_id

    with pytest.raises(ProgrammingError):
        with tenant_session(ctx_firm(world.firm_a)) as sess:
            sess.add(
                DraftClassification(
                    id=uuid4(),
                    firm_id=target_firm,  # B!
                    client_id=target_client,
                    source_document_id=sd_id,
                    kind=DraftKind.GENERIC,
                    status=DraftStatus.PENDING_REVIEW,
                    needs_review=True,
                    high_confidence=False,
                    confidence=Decimal("0.5"),
                    model="evil",
                    prompt_version="0",
                    payload={},
                )
            )
            sess.flush()
