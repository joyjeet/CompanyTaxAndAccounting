from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.session import tenant_session
from app.integrations.account_categorizer import load_rules_from_file
from app.main import create_app
from app.models.accounting import DraftClassification, SourceDocument
from app.models.enums import DraftKind, DraftStatus, OcrStatus
from app.security.auth import mint_test_token, reset_identity_provider
from tests.conftest import ctx_firm_for_client


@pytest.fixture(autouse=True)
def _reset_identity():
    reset_identity_provider()
    yield
    reset_identity_provider()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _seed_statement_draft(world) -> str:
    a1 = world.a1
    doc_id = uuid4()
    draft_id = uuid4()

    with tenant_session(ctx_firm_for_client(a1.firm_id, a1.client_id)) as sess:
        sess.add(
            SourceDocument(
                id=doc_id,
                firm_id=a1.firm_id,
                client_id=a1.client_id,
                kind=DraftKind.BANK_TRANSACTION.value,
                original_filename="statement.pdf",
                mime_type="application/pdf",
                sha256="0" * 64,
                storage_uri="mock://test/statement.pdf",
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
                confidence=Decimal("0.81"),
                model="mock",
                prompt_version="mock-v1",
                payload={
                    "is_statement": True,
                    "transactions": [
                        {
                            "date": "2026-07-05",
                            "raw_date": "07/05",
                            "description": "Facebook Ads 12345",
                            "amount": "125.00",
                            "direction": "payment",
                            "proposed_account_code": "4000",
                        }
                    ],
                },
            )
        )
    return str(draft_id)


def test_learn_rule_endpoint_learns_and_persists_rule(
    client: TestClient,
    world,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules_file = tmp_path / "categorization_rules.yaml"
    rules_file.write_text("rules: []\n", encoding="utf-8")

    class _Settings:
        app_categorizer_backend = "xero_rule_engine"
        app_categorizer_rules_file = str(rules_file)

    monkeypatch.setattr("app.domain.promotion.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.domain.promotion._reload_rules_runtime", lambda: None)

    draft_id = _seed_statement_draft(world)
    token = mint_test_token(
        sub="firm-staff",
        firm_id=world.firm_a,
        role="firm_staff",
        client_id=world.a1.client_id,
    )

    resp = client.post(
        f"/drafts/{draft_id}/learn-rule",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "transaction_index": 0,
            "target_account_code": "5000",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["learned_rule_count"] == 1

    learned = load_rules_from_file(rules_file)
    assert learned[0].target_code == "5000"
    assert any(c.field == "description" for c in learned[0].conditions)


def test_learn_rule_endpoint_rejects_out_of_range_index(
    client: TestClient,
    world,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules_file = tmp_path / "categorization_rules.yaml"
    rules_file.write_text("rules: []\n", encoding="utf-8")

    class _Settings:
        app_categorizer_backend = "xero_rule_engine"
        app_categorizer_rules_file = str(rules_file)

    monkeypatch.setattr("app.domain.promotion.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.domain.promotion._reload_rules_runtime", lambda: None)

    draft_id = _seed_statement_draft(world)
    token = mint_test_token(
        sub="firm-staff",
        firm_id=world.firm_a,
        role="firm_staff",
        client_id=world.a1.client_id,
    )

    resp = client.post(
        f"/drafts/{draft_id}/learn-rule",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "transaction_index": 5,
            "target_account_code": "5000",
        },
    )
    assert resp.status_code == 400
    assert "out of range" in resp.json()["detail"].lower()
