"""API tests for deleting an uploaded document — DELETE /documents/{id}.

Covers the mistaken-upload cleanup path:
  * pending drafts are cascade-removed with the document;
  * deletion is refused (409) once a journal entry was posted from it, so the
    trial balance can never change without a reversing entry;
  * the list response carries `uploaded_by` for tracking.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import tenant_session
from app.db.tenant import AccessScope
from app.domain.promotion import PromoteLineInput, promote_draft
from app.main import create_app
from app.models.accounting import DraftClassification, SourceDocument
from app.models.enums import DraftKind, DraftStatus, OcrStatus
from app.security.auth import mint_test_token
from tests.conftest import SeededWorld, ctx_firm_for_client


def _client() -> TestClient:
    return TestClient(create_app())


def _headers(world: SeededWorld) -> dict[str, str]:
    token = mint_test_token(
        sub="firm-a-staff",
        firm_id=world.firm_a,
        role="firm_staff",
        client_id=world.a1.client_id,
    )
    return {"Authorization": f"Bearer {token}"}


def _seed_doc_and_draft(a1) -> tuple[UUID, UUID]:  # type: ignore[no-untyped-def]
    doc_id, draft_id = uuid4(), uuid4()
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        sess.add(
            SourceDocument(
                id=doc_id,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                kind=DraftKind.BANK_TRANSACTION.value,
                original_filename="txn.pdf",
                mime_type="application/pdf",
                sha256="0" * 64,
                storage_uri="mock://test/txn.pdf",
                ocr_status=OcrStatus.COMPLETE,
                uploaded_by="tester",
            )
        )
        sess.flush()
        sess.add(
            DraftClassification(
                id=draft_id,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                source_document_id=doc_id,
                kind=DraftKind.BANK_TRANSACTION,
                status=DraftStatus.PENDING_REVIEW,
                needs_review=True,
                high_confidence=False,
                confidence=Decimal("0.70"),
                model="mock",
                prompt_version="mock-v1",
                payload={
                    "description": "ACH Payment ACME",
                    "amount": "4.25",
                    "direction": "payment",
                    "proposed_account_code": "4000",
                },
            )
        )
    return doc_id, draft_id


def test_delete_document_removes_pending_drafts(
    world: SeededWorld, fake_integrations
) -> None:
    a1 = world.a1
    doc_id, draft_id = _seed_doc_and_draft(a1)

    resp = _client().delete(f"/documents/{doc_id}", headers=_headers(world))
    assert resp.status_code == 204, resp.text

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        assert sess.get(SourceDocument, doc_id) is None
        remaining = sess.execute(
            select(DraftClassification).where(DraftClassification.id == draft_id)
        ).scalar_one_or_none()
        assert remaining is None


def test_delete_document_blocked_when_journal_entry_posted(
    world: SeededWorld, fake_integrations
) -> None:
    a1 = world.a1
    doc_id, draft_id = _seed_doc_and_draft(a1)

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        promote_draft(
            sess,
            firm_id=a1.firm_id,
            client_id=a1.client_id,
            actor="reviewer@acme",
            scope=AccessScope.FIRM,
            draft_id=draft_id,
            period_id=a1.period_id,
            entry_date=date(2026, 3, 15),
            lines=[
                PromoteLineInput(
                    account_id=a1.expense_account_id,
                    debit=Decimal("4.25"),
                    description="Coffee",
                ),
                PromoteLineInput(
                    account_id=a1.cash_account_id, credit=Decimal("4.25")
                ),
            ],
            memo="Coffee run",
        )

    resp = _client().delete(f"/documents/{doc_id}", headers=_headers(world))
    assert resp.status_code == 409, resp.text
    assert "posted" in resp.json()["detail"].lower()

    # The document (and its posted entry) survive.
    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        assert sess.get(SourceDocument, doc_id) is not None


def test_documents_list_includes_uploaded_by(
    world: SeededWorld, fake_integrations
) -> None:
    headers = _headers(world)
    client = _client()
    up = client.post(
        "/documents/upload",
        headers=headers,
        files={"file": ("d.pdf", b"raw bytes", "application/pdf")},
        data={"kind_hint": "generic"},
    )
    assert up.status_code == 201, up.text

    listed = client.get("/documents", headers=headers).json()
    assert listed
    assert listed[0]["uploaded_by"] == "firm-a-staff"


def test_delete_missing_document_is_404(
    world: SeededWorld, fake_integrations
) -> None:
    resp = _client().delete(f"/documents/{uuid4()}", headers=_headers(world))
    assert resp.status_code == 404
