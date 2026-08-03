"""End-to-end test that the categorizer is applied to a bank statement
parsed by `MockLLMClassifier._maybe_classify_bank_statement`.

Uses a fake categorizer (not Azure OpenAI) to avoid any network dependency.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.integrations.account_categorizer import AccountCategorizer
from app.integrations.llm import MockLLMClassifier
from app.integrations.ocr import ExtractionResult

_STATEMENT = """\
M AND M FINANCIAL CONSULTANTS LLC
STATEMENT OF ACCOUNT

Statement Period: Jul 01 2025-Jul 31 2025

Beginning Balance              1000.00
Ending Balance                  900.00

Daily Account Activity

Deposits
07/05  SBB MDEPOSIT  150.00

Electronic Payments
07/10  CCD PAYMENT PATEL CONSULTING SERVICES  70.16
07/15  VENMO TRANSFER JOHN DOE  100.00
"""


class _StubCategorizer(AccountCategorizer):
    """Re-maps 9999 rows to fixed codes the test pins on."""

    NAME = "stub"

    def __init__(self) -> None:
        self.seen_coa: list[dict[str, Any]] | None = None
        self.seen_count: int | None = None

    def recategorize(
        self,
        transactions: list[dict[str, Any]],
        chart_of_accounts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.seen_coa = chart_of_accounts
        self.seen_count = sum(
            1 for t in transactions if t.get("proposed_account_code") == "9999"
        )
        out = []
        for t in transactions:
            new = dict(t)
            if new.get("proposed_account_code") == "9999":
                desc = (new.get("description") or "").lower()
                if "patel" in desc:
                    new["proposed_account_code"] = "5300"
                    new["_categorizer_reason"] = "Professional services"
                    new["_categorizer"] = self.NAME
                elif "venmo" in desc:
                    new["proposed_account_code"] = "5400"
                    new["_categorizer_reason"] = "Owner draw"
                    new["_categorizer"] = self.NAME
            out.append(new)
        return out


def _coa() -> list[dict[str, Any]]:
    return [
        {"code": "1000", "name": "Cash", "account_type": "asset"},
        {"code": "4000", "name": "Sales Revenue", "account_type": "revenue"},
        {"code": "5300", "name": "Professional Fees", "account_type": "expense"},
        {"code": "5400", "name": "Owner Draw", "account_type": "equity"},
        {"code": "9999", "name": "Suspense", "account_type": "asset"},
    ]


def test_classifier_applies_categorizer_when_coa_supplied() -> None:
    cat = _StubCategorizer()
    classifier = MockLLMClassifier(categorizer=cat)

    result = classifier.classify(
        kind_hint="generic",
        extraction=ExtractionResult(text=_STATEMENT, fields=[]),
        chart_of_accounts=_coa(),
    )

    assert result.kind == "bank_transaction"
    payload = result.payload
    assert payload["is_statement"] is True
    txns = payload["transactions"]
    by_desc = {t["description"]: t for t in txns}

    # Deposit row was strong (4000); categorizer should NOT touch it.
    deposit = next(t for t in txns if "MDEPOSIT" in t["description"])
    assert deposit["proposed_account_code"] == "4000"
    assert "_categorizer" not in deposit

    # Patel row was Suspense -> Professional Fees.
    patel = by_desc["CCD PAYMENT PATEL CONSULTING SERVICES"]
    assert patel["proposed_account_code"] == "5300"
    assert patel["_categorizer"] == "stub"
    assert patel["_categorizer_reason"] == "Professional services"

    # Venmo row was Suspense -> Owner Draw.
    venmo = next(t for t in txns if "VENMO" in t["description"])
    assert venmo["proposed_account_code"] == "5400"

    # Categorizer saw the COA we passed in and was told 2 weak rows.
    assert cat.seen_coa == _coa()
    assert cat.seen_count == 2

    # Reasons should mention the re-categorization.
    reasons = " ".join(payload["_reasons"])
    assert "re-categorized" in reasons
    assert "stub" in reasons


def test_classifier_skips_categorizer_when_no_coa() -> None:
    cat = _StubCategorizer()
    classifier = MockLLMClassifier(categorizer=cat)

    result = classifier.classify(
        kind_hint="generic",
        extraction=ExtractionResult(text=_STATEMENT, fields=[]),
        chart_of_accounts=None,
    )

    # Categorizer never invoked (gated on chart_of_accounts).
    assert cat.seen_coa is None
    # Both suspense rows remain in suspense.
    suspense = [
        t for t in result.payload["transactions"]
        if t["proposed_account_code"] == "9999"
    ]
    assert len(suspense) == 2


def test_classifier_default_categorizer_applies_rule_engine() -> None:
    # No categorizer supplied -> default deterministic rule engine.
    classifier = MockLLMClassifier()
    result = classifier.classify(
        kind_hint="generic",
        extraction=ExtractionResult(text=_STATEMENT, fields=[]),
        chart_of_accounts=_coa(),
    )
    suspense_count = sum(
        1 for t in result.payload["transactions"]
        if t["proposed_account_code"] == "9999"
    )
    # Patel row gets mapped by default rules; Venmo stays suspense.
    assert suspense_count == 1
    assert any(
        t["proposed_account_code"] == "5300"
        for t in result.payload["transactions"]
    )
    # Confidence remains at the canonical 0.80 floor.
    assert result.confidence == Decimal("0.80")


def test_classifier_uses_di_extra_transactions_when_present() -> None:
    """If `extraction.extra['transactions']` is populated (e.g. by
    `AzureDocumentIntelligenceExtractor.prebuilt-bankStatement.us`), the
    classifier should use them directly and skip the heuristic text parser.
    """
    di_txns = [
        {
            "date": "2026-04-02",
            "description": "ACH DEPOSIT ACME INC",
            "amount": "1250.00",
            "direction": "deposit",
            "section": "deposits",
            "proposed_account_code": "4000",
        },
        {
            "date": "2026-04-05",
            "description": "AMAZON PURCHASE",
            "amount": "42.50",
            "direction": "payment",
            "section": "payments",
            "proposed_account_code": "5000",
        },
    ]
    extraction = ExtractionResult(
        text=None,  # Critical: heuristic parser would have nothing to chew on.
        fields=[],
        extra={
            "transactions": di_txns,
            "account_holder": "JANE DOE",
            "statement_period": "2026-04-01 - 2026-04-30",
            "beginning_balance": "5000.00",
            "ending_balance": "6207.50",
        },
    )
    classifier = MockLLMClassifier()
    result = classifier.classify(
        kind_hint="bank_transaction",
        extraction=extraction,
        chart_of_accounts=None,
    )
    assert result.kind == "bank_transaction"
    txns = result.payload["transactions"]
    assert len(txns) == 2
    assert txns[0]["description"] == "ACH DEPOSIT ACME INC"
    assert txns[1]["proposed_account_code"] == "5000"
    # Statement summary fields from `extra` flowed through.
    assert result.payload["account_holder"] == "JANE DOE"
    assert result.payload["beginning_balance"] == "5000.00"
    assert result.payload["ending_balance"] == "6207.50"


def test_classifier_generic_fallback_detects_statement_fields() -> None:
    classifier = MockLLMClassifier()
    extraction = ExtractionResult(
        text="",
        fields=[
            {"name": "statement_period", "value": "2026-06-01 - 2026-06-30"},
            {"name": "beginning_balance", "value": "1023.45"},
            {"name": "ending_balance", "value": "992.11"},
            {"name": "transaction_count", "value": "18"},
        ],
    )

    result = classifier.classify(
        kind_hint="generic",
        extraction=extraction,
        chart_of_accounts=None,
    )

    assert result.kind == "bank_transaction"
    assert result.payload["is_statement"] is True
    assert result.payload["transaction_count"] == 18


def test_classifier_uses_named_suspense_account_code_when_not_9999() -> None:
    classifier = MockLLMClassifier()
    coa = [
        {"code": "1000", "name": "Cash", "account_type": "asset"},
        {"code": "4000", "name": "Service Revenue", "account_type": "revenue"},
        {"code": "9900", "name": "Suspense", "account_type": "expense"},
    ]
    result = classifier.classify(
        kind_hint="generic",
        extraction=ExtractionResult(text=_STATEMENT, fields=[]),
        chart_of_accounts=coa,
    )

    txns = result.payload["transactions"]
    assert any(t["proposed_account_code"] == "9900" for t in txns)
    assert not any(t["proposed_account_code"] == "9999" for t in txns)
