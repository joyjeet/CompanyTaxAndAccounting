"""Document extraction (OCR).

Two implementations:
  * `MockDocumentExtractor`               — deterministic, used for tests/dev.
  * `AzureDocumentIntelligenceExtractor`  — Azure AI Document Intelligence.
    Uses the prebuilt-read model for general OCR; routes specific kinds
    (W-2, 1099-NEC/INT, 1098, invoice, receipt) to the matching prebuilt
    models when the kind is known.

Output schema is a normalised dict:
    {
      "text": <full text or None>,
      "fields": [
          {"name": str, "value": str, "confidence": float},  # per-field
          ...
      ],
      "model": str,
      "model_version": str | None,
      "page_count": int,
      "warnings": [str, ...],
    }
Per-field confidence is preserved when the underlying service supplies it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExtractionResult:
    text: str | None
    fields: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    model_version: str | None = None
    page_count: int = 0
    warnings: list[str] = field(default_factory=list)
    # Extra structured payload that survives extraction. The bank-statement
    # path uses this to ship a pre-parsed `transactions` list straight from
    # Document Intelligence to the classifier, bypassing the heuristic
    # text parser. Shape is backend-specific; consumers must treat it as
    # untrusted/opaque and feature-detect known keys.
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "fields": self.fields,
            "model": self.model,
            "model_version": self.model_version,
            "page_count": self.page_count,
            "warnings": self.warnings,
            "extra": self.extra,
        }


# Mapping from our internal kind to Azure DI model id. Kept here so callers
# only pass a domain-level kind.
_AZURE_MODEL_FOR_KIND: dict[str, str] = {
    "tax_form_w2": "prebuilt-tax.us.w2",
    "tax_form_1099_nec": "prebuilt-tax.us.1099NEC",
    "tax_form_1099_int": "prebuilt-tax.us.1099INT",
    "tax_form_1098": "prebuilt-tax.us.1098",
    "invoice": "prebuilt-invoice",
    "receipt": "prebuilt-receipt",
    # Bank statements use the prebuilt-bankStatement.us model for
    # high-fidelity transaction extraction (US only).
    "bank_transaction": "prebuilt-bankStatement.us",
    # default
    "generic": "prebuilt-read",
}


def azure_model_for(kind: str) -> str:
    return _AZURE_MODEL_FOR_KIND.get(kind, "prebuilt-read")


class DocumentExtractor(ABC):
    @abstractmethod
    def extract(
        self, *, data: bytes, mime_type: str | None, kind: str
    ) -> ExtractionResult:
        ...


# --------------------------------------------------------------------------- #
# Mock — deterministic fixtures used in tests and dev.
# --------------------------------------------------------------------------- #
class MockDocumentExtractor(DocumentExtractor):
    """Deterministic extractor for tests and the demo path.

    Behavior:
      * If the uploaded bytes are a real PDF (header `%PDF-`), use `pypdf`
        to extract actual text + a minimal field set. This makes the
        demo's mock pipeline genuinely useful when a customer uploads a
        real bank statement / invoice / W-2.
      * Otherwise (tests passing arbitrary bytes), fall back to the
        existing kind-keyed canned outputs.
    """

    def extract(
        self, *, data: bytes, mime_type: str | None, kind: str
    ) -> ExtractionResult:
        # 1) Real PDF — extract text + cheap structured fields.
        if self._is_pdf(data, mime_type):
            text, page_count, warnings = self._extract_pdf_text(data)
            fields = self._fields_from_pdf_text(text)
            return ExtractionResult(
                text=text,
                fields=fields,
                model="pypdf",
                model_version="local",
                page_count=page_count,
                warnings=warnings,
            )

        # 2) Canned fixtures keyed on kind hint (preserves test behavior).
        if kind == "bank_transaction":
            return ExtractionResult(
                text="ACME COFFEE 03/15 $4.25",
                fields=[
                    {"name": "merchant", "value": "ACME COFFEE", "confidence": 0.97},
                    {"name": "amount", "value": "4.25", "confidence": 0.99},
                    {"name": "date", "value": "2026-03-15", "confidence": 0.99},
                ],
                model="mock",
                model_version="1",
                page_count=1,
            )
        if kind == "tax_form_w2":
            return ExtractionResult(
                text="W-2 mock",
                fields=[
                    {"name": "employer_ein", "value": "12-3456789", "confidence": 0.99},
                    {"name": "wages_box1", "value": "82500.00", "confidence": 0.98},
                    {"name": "fed_wh_box2", "value": "12100.00", "confidence": 0.97},
                ],
                model="mock",
                model_version="1",
                page_count=1,
            )
        if kind == "invoice":
            return ExtractionResult(
                text="Invoice mock",
                fields=[
                    {"name": "vendor", "value": "Beta Supplies", "confidence": 0.95},
                    {"name": "total", "value": "1234.56", "confidence": 0.97},
                    {"name": "invoice_date", "value": "2026-02-10", "confidence": 0.96},
                ],
                model="mock",
                model_version="1",
                page_count=1,
            )
        return ExtractionResult(
            text=f"<mock extraction for {kind}>",
            fields=[],
            model="mock",
            model_version="1",
            page_count=1,
        )

    # --- PDF helpers -------------------------------------------------------
    @staticmethod
    def _is_pdf(data: bytes, mime_type: str | None) -> bool:
        if data[:5] == b"%PDF-":
            return True
        if mime_type and "pdf" in mime_type.lower():
            return True
        return False

    @staticmethod
    def _extract_pdf_text(data: bytes) -> tuple[str, int, list[str]]:
        """Return (text, page_count, warnings). Never raises."""
        warnings: list[str] = []
        try:
            from io import BytesIO

            from pypdf import PdfReader  # type: ignore[import-not-found]
        except ImportError:
            return ("", 0, ["pypdf not installed; PDF text not extracted"])

        try:
            reader = PdfReader(BytesIO(data))
            pages = reader.pages
            text = "\n".join((p.extract_text() or "") for p in pages)
            return (text, len(pages), warnings)
        except Exception as exc:  # noqa: BLE001 — best-effort extractor
            return ("", 0, [f"pypdf failed to read document: {exc}"])

    @staticmethod
    def _fields_from_pdf_text(text: str) -> list[dict[str, Any]]:
        """Best-effort structured fields from raw PDF text.

        If the PDF looks like a bank statement, surface the period and
        balance lines as fields so the UI's "OCR fields" table is useful
        even before the classifier runs. Returns an empty list otherwise.
        """
        from app.integrations.bank_statement import (
            looks_like_bank_statement,
            parse_statement,
        )

        if not looks_like_bank_statement(text):
            return []
        parsed = parse_statement(text)
        fields: list[dict[str, Any]] = []
        if parsed.get("account_holder"):
            fields.append(
                {
                    "name": "account_holder",
                    "value": parsed["account_holder"],
                    "confidence": 0.9,
                }
            )
        if parsed.get("statement_period"):
            fields.append(
                {
                    "name": "statement_period",
                    "value": parsed["statement_period"],
                    "confidence": 0.9,
                }
            )
        if parsed.get("beginning_balance"):
            fields.append(
                {
                    "name": "beginning_balance",
                    "value": parsed["beginning_balance"],
                    "confidence": 0.95,
                }
            )
        if parsed.get("ending_balance"):
            fields.append(
                {
                    "name": "ending_balance",
                    "value": parsed["ending_balance"],
                    "confidence": 0.95,
                }
            )
        fields.append(
            {
                "name": "transaction_count",
                "value": str(len(parsed.get("transactions", []))),
                "confidence": 0.85,
            }
        )
        return fields


# --------------------------------------------------------------------------- #
# Azure AI Document Intelligence (lazy import)
# --------------------------------------------------------------------------- #
class AzureDocumentIntelligenceExtractor(DocumentExtractor):
    """Calls Azure AI Document Intelligence. Lazy-imports the SDK.

    `credential` may be either an `AzureKeyCredential` or any
    `TokenCredential` (e.g. `DefaultAzureCredential`). The SDK accepts
    both; we don't constrain the type here.
    """

    def __init__(self, *, endpoint: str, credential: object) -> None:
        from azure.ai.documentintelligence import (
            DocumentIntelligenceClient,  # type: ignore[import-not-found]
        )

        self._client = DocumentIntelligenceClient(
            endpoint=endpoint, credential=credential
        )

    def extract(
        self, *, data: bytes, mime_type: str | None, kind: str
    ) -> ExtractionResult:
        model_id = azure_model_for(kind)
        poller = self._client.begin_analyze_document(model_id=model_id, body=data)
        result = poller.result()

        fields: list[dict[str, Any]] = []
        # `documents[0].fields` shape varies by model; we surface name,
        # content, and confidence in a uniform way.
        for doc in getattr(result, "documents", []) or []:
            for name, fld in (getattr(doc, "fields", {}) or {}).items():
                fields.append(
                    {
                        "name": name,
                        "value": getattr(fld, "content", None)
                        or str(getattr(fld, "value", "")),
                        "confidence": float(getattr(fld, "confidence", 0.0) or 0.0),
                    }
                )

        extra: dict[str, Any] = {}
        if kind == "bank_transaction":
            extra = self._postprocess_bank_statement(result)
            # Also surface the statement-level summary fields the UI shows
            # in the OCR fields table, on top of the raw DI fields above.
            for key in (
                "account_holder",
                "statement_period",
                "beginning_balance",
                "ending_balance",
            ):
                v = extra.get(key)
                if v is not None:
                    fields.append(
                        {"name": key, "value": str(v), "confidence": 0.95}
                    )
            txns = extra.get("transactions") or []
            if txns:
                fields.append(
                    {
                        "name": "transaction_count",
                        "value": str(len(txns)),
                        "confidence": 0.95,
                    }
                )

        return ExtractionResult(
            text=getattr(result, "content", None),
            fields=fields,
            model=model_id,
            model_version=getattr(result, "model_id", None),
            page_count=len(getattr(result, "pages", []) or []),
            extra=extra,
        )

    # ------------------------------------------------------------------ #
    # Bank-statement post-processing
    # ------------------------------------------------------------------ #
    @staticmethod
    def _postprocess_bank_statement(result: Any) -> dict[str, Any]:
        """Convert prebuilt-bankStatement.us output into our transaction shape.

        DI returns one document per account in the statement. Each
        document has fields:
          AccountHolderName, AccountNumber, BeginningBalance, EndingBalance,
          StatementStartDate, StatementEndDate,
          Transactions: list of items with fields:
              Date, Description, Amount (signed, deposit=+, withdrawal=-)

        We flatten across all accounts into a single transactions array
        matching `app.integrations.bank_statement.parse_statement()`:
            {date, description, amount, direction, section,
             proposed_account_code}
        plus account_holder / statement_period / beginning_balance /
        ending_balance for the first account (to surface in the UI).
        """
        from app.integrations.bank_statement import _propose_account_code

        out: dict[str, Any] = {"transactions": []}
        docs = getattr(result, "documents", None) or []
        if not docs:
            return out

        # Summary fields from the first account.
        first_fields = getattr(docs[0], "fields", {}) or {}

        def _f_value(f_name: str) -> Any:
            fld = first_fields.get(f_name)
            if fld is None:
                return None
            # Prefer typed `value`, fall back to `content` (raw text).
            return getattr(fld, "value", None) or getattr(fld, "content", None)

        holder = _f_value("AccountHolderName")
        if holder:
            out["account_holder"] = str(holder)

        start = _f_value("StatementStartDate")
        end = _f_value("StatementEndDate")
        if start and end:
            out["statement_period"] = f"{start} - {end}"
        elif start:
            out["statement_period"] = str(start)

        beg = _f_value("BeginningBalance")
        if beg is not None:
            out["beginning_balance"] = str(beg)
        endb = _f_value("EndingBalance")
        if endb is not None:
            out["ending_balance"] = str(endb)

        # Flatten transactions across all accounts.
        for doc in docs:
            fields = getattr(doc, "fields", {}) or {}
            txns_field = fields.get("Transactions")
            if txns_field is None:
                continue
            # Array-typed field: items live under `value` (list of objects).
            items = (
                getattr(txns_field, "value", None)
                or getattr(txns_field, "value_array", None)
                or []
            )
            for item in items:
                # Each item is itself an object whose `value` is a dict of
                # named DocumentField entries.
                obj = (
                    getattr(item, "value", None)
                    or getattr(item, "value_object", None)
                    or {}
                )
                if not obj:
                    continue
                date_v = AzureDocumentIntelligenceExtractor._field_str(
                    obj.get("Date")
                )
                desc_v = AzureDocumentIntelligenceExtractor._field_str(
                    obj.get("Description")
                ) or ""
                amt_raw = AzureDocumentIntelligenceExtractor._field_number(
                    obj.get("Amount")
                )
                if amt_raw is None or not desc_v:
                    continue
                direction = "deposit" if amt_raw >= 0 else "payment"
                amount = f"{abs(amt_raw):.2f}"
                out["transactions"].append(
                    {
                        "date": date_v,
                        "description": desc_v,
                        "amount": amount,
                        "direction": direction,
                        "section": (
                            "deposits" if direction == "deposit" else "payments"
                        ),
                        "proposed_account_code": _propose_account_code(
                            desc_v, direction
                        ),
                    }
                )
        return out

    @staticmethod
    def _field_str(fld: Any) -> str | None:
        if fld is None:
            return None
        v = getattr(fld, "value", None)
        if v is not None:
            return str(v)
        c = getattr(fld, "content", None)
        return str(c) if c is not None else None

    @staticmethod
    def _field_number(fld: Any) -> float | None:
        if fld is None:
            return None
        v = getattr(fld, "value", None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
        c = getattr(fld, "content", None)
        if c is None:
            return None
        # Strip currency symbols / commas / parentheses (for negatives).
        s = str(c).strip()
        neg = s.startswith("(") and s.endswith(")")
        s = s.strip("()$").replace(",", "").replace("$", "")
        try:
            n = float(s)
        except ValueError:
            return None
        return -n if neg else n


__all__ = [
    "AzureDocumentIntelligenceExtractor",
    "DocumentExtractor",
    "ExtractionResult",
    "MockDocumentExtractor",
    "azure_model_for",
]
