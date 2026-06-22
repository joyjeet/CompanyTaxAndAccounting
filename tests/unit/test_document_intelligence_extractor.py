"""Unit tests for `AzureDocumentIntelligenceExtractor`.

Constructs the extractor with `__new__` to skip the real SDK client and
patches `_client.begin_analyze_document` to return synthetic results
mirroring the prebuilt-bankStatement.us / prebuilt-invoice / prebuilt-read
shapes. No network, no Azure SDK install required.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.integrations.ocr import (
    AzureDocumentIntelligenceExtractor,
    ExtractionResult,
    azure_model_for,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _field(value: Any, content: str | None = None, confidence: float = 0.99):
    return SimpleNamespace(value=value, content=content, confidence=confidence)


def _array_field(items: list[Any]):
    return SimpleNamespace(value=items, content=None, confidence=0.95)


def _object_item(obj: dict[str, Any]):
    return SimpleNamespace(value=obj, content=None)


class _FakePoller:
    def __init__(self, result: Any) -> None:
        self._result = result

    def result(self) -> Any:
        return self._result


class _FakeClient:
    def __init__(self, result: Any) -> None:
        self._result = result
        self.calls: list[tuple[str, bytes]] = []

    def begin_analyze_document(self, *, model_id: str, body: bytes):
        self.calls.append((model_id, body))
        return _FakePoller(self._result)


def _make_extractor(result: Any) -> tuple[AzureDocumentIntelligenceExtractor, _FakeClient]:
    ext = AzureDocumentIntelligenceExtractor.__new__(AzureDocumentIntelligenceExtractor)
    client = _FakeClient(result)
    ext._client = client  # type: ignore[attr-defined]
    return ext, client


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
def test_azure_model_for_routes_bank_statement_to_prebuilt_bankstatement():
    assert azure_model_for("bank_transaction") == "prebuilt-bankStatement.us"


def test_azure_model_for_routes_w2_to_prebuilt_w2():
    assert azure_model_for("tax_form_w2") == "prebuilt-tax.us.w2"


def test_azure_model_for_routes_1099_nec():
    assert azure_model_for("tax_form_1099_nec") == "prebuilt-tax.us.1099NEC"


def test_azure_model_for_routes_invoice():
    assert azure_model_for("invoice") == "prebuilt-invoice"


def test_azure_model_for_unknown_defaults_to_prebuilt_read():
    assert azure_model_for("totally-unknown-kind") == "prebuilt-read"


# --------------------------------------------------------------------------- #
# Bank statement post-processing
# --------------------------------------------------------------------------- #
def _bank_statement_result() -> Any:
    """Build a fake DI result for prebuilt-bankStatement.us.

    Two transactions across one account:
      - 2026-04-02  ACH DEPOSIT ACME INC            +1250.00
      - 2026-04-05  AMAZON PURCHASE                  -42.50
    """
    txns_items = [
        _object_item(
            {
                "Date": _field("2026-04-02"),
                "Description": _field("ACH DEPOSIT ACME INC"),
                "Amount": _field(1250.00),
            }
        ),
        _object_item(
            {
                "Date": _field("2026-04-05"),
                "Description": _field("AMAZON PURCHASE"),
                "Amount": _field(-42.50),
            }
        ),
    ]

    doc_fields = {
        "AccountHolderName": _field("JANE DOE", confidence=0.99),
        "StatementStartDate": _field("2026-04-01"),
        "StatementEndDate": _field("2026-04-30"),
        "BeginningBalance": _field(5000.00),
        "EndingBalance": _field(6245.75),
        "Transactions": _array_field(txns_items),
    }
    doc = SimpleNamespace(fields=doc_fields)
    return SimpleNamespace(
        documents=[doc],
        content="raw OCR text from DI",
        model_id="prebuilt-bankStatement.us",
        pages=[SimpleNamespace()],
    )


def test_extractor_routes_bank_statement_kind_to_correct_model():
    ext, client = _make_extractor(_bank_statement_result())
    ext.extract(data=b"%PDF-fake", mime_type="application/pdf", kind="bank_transaction")
    assert client.calls[0][0] == "prebuilt-bankStatement.us"


def test_extractor_postprocesses_bank_transactions():
    ext, _ = _make_extractor(_bank_statement_result())
    r: ExtractionResult = ext.extract(
        data=b"%PDF-fake", mime_type="application/pdf", kind="bank_transaction"
    )

    txns = r.extra["transactions"]
    assert len(txns) == 2

    # Deposit
    assert txns[0]["date"] == "2026-04-02"
    assert txns[0]["description"] == "ACH DEPOSIT ACME INC"
    assert txns[0]["direction"] == "deposit"
    assert txns[0]["amount"] == "1250.00"
    assert txns[0]["section"] == "deposits"

    # Payment (negative amount -> withdrawal)
    assert txns[1]["date"] == "2026-04-05"
    assert txns[1]["description"] == "AMAZON PURCHASE"
    assert txns[1]["direction"] == "payment"
    assert txns[1]["amount"] == "42.50"
    assert txns[1]["section"] == "payments"

    # Statement summary fields are also surfaced.
    assert r.extra["account_holder"] == "JANE DOE"
    assert "2026-04-01" in r.extra["statement_period"]
    assert "2026-04-30" in r.extra["statement_period"]
    assert r.extra["beginning_balance"] == "5000.0"
    assert r.extra["ending_balance"] == "6245.75"

    # Fields table for the UI gets enriched too.
    names = {f["name"] for f in r.fields}
    assert "account_holder" in names
    assert "transaction_count" in names


def test_extractor_handles_empty_bank_statement_gracefully():
    empty_result = SimpleNamespace(
        documents=[],
        content=None,
        model_id="prebuilt-bankStatement.us",
        pages=[],
    )
    ext, _ = _make_extractor(empty_result)
    r = ext.extract(data=b"%PDF-x", mime_type=None, kind="bank_transaction")
    assert r.extra == {"transactions": []}
    # Nothing to surface, but the call itself must not raise.


# --------------------------------------------------------------------------- #
# Vendor pre-codes flow through the post-processor
# --------------------------------------------------------------------------- #
def test_postprocessed_transactions_get_vendor_precodes():
    """A description matching a known vendor keyword ("amazon") should get a
    real proposed_account_code via `_propose_account_code`, not Suspense."""
    ext, _ = _make_extractor(_bank_statement_result())
    r = ext.extract(
        data=b"%PDF-x", mime_type="application/pdf", kind="bank_transaction"
    )
    amazon = r.extra["transactions"][1]
    # `_VENDOR_TO_CODE` maps "amazon" → "5000" (Office Expense).
    assert amazon["proposed_account_code"] == "5000"

    # Deposit also gets a real code ("mdeposit" doesn't match here, but the
    # default-deposit fallback is 4000, NOT 9999).
    deposit = r.extra["transactions"][0]
    assert deposit["proposed_account_code"] == "4000"


# --------------------------------------------------------------------------- #
# Non-bank kinds: invoice still uses the legacy fields-only path
# --------------------------------------------------------------------------- #
def test_extractor_invoice_path_no_extra_transactions():
    invoice_doc = SimpleNamespace(
        fields={
            "VendorName": _field("Beta Supplies"),
            "InvoiceTotal": _field(1234.56),
        }
    )
    result = SimpleNamespace(
        documents=[invoice_doc],
        content="invoice text",
        model_id="prebuilt-invoice",
        pages=[SimpleNamespace()],
    )
    ext, client = _make_extractor(result)
    r = ext.extract(data=b"x", mime_type=None, kind="invoice")
    assert client.calls[0][0] == "prebuilt-invoice"
    # No bank-statement post-processing.
    assert "transactions" not in r.extra
    names = {f["name"] for f in r.fields}
    assert "VendorName" in names
    assert "InvoiceTotal" in names


def test_extractor_w2_kind_routes_and_surfaces_fields():
    w2_doc = SimpleNamespace(
        fields={
            "Employer": _field("ACME CORP"),
            "WagesTipsAndOtherCompensation": _field(82500.00),
            "FederalIncomeTaxWithheld": _field(12100.00),
        }
    )
    result = SimpleNamespace(
        documents=[w2_doc],
        content="w-2 text",
        model_id="prebuilt-tax.us.w2",
        pages=[SimpleNamespace()],
    )
    ext, client = _make_extractor(result)
    r = ext.extract(data=b"x", mime_type=None, kind="tax_form_w2")
    assert client.calls[0][0] == "prebuilt-tax.us.w2"
    assert "transactions" not in r.extra
    names = {f["name"] for f in r.fields}
    assert "Employer" in names
    assert "WagesTipsAndOtherCompensation" in names


def test_extractor_1099_nec_kind_routes_and_surfaces_fields():
    nec_doc = SimpleNamespace(
        fields={
            "Payer": _field("PAYER LLC"),
            "Recipient": _field("JANE DOE"),
            "NonemployeeCompensation": _field(15000.00),
        }
    )
    result = SimpleNamespace(
        documents=[nec_doc],
        content="1099-NEC text",
        model_id="prebuilt-tax.us.1099NEC",
        pages=[SimpleNamespace()],
    )
    ext, client = _make_extractor(result)
    r = ext.extract(data=b"x", mime_type=None, kind="tax_form_1099_nec")
    assert client.calls[0][0] == "prebuilt-tax.us.1099NEC"
    names = {f["name"] for f in r.fields}
    assert "NonemployeeCompensation" in names
    assert "Payer" in names
