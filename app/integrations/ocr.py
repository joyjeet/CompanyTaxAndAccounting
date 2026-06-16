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

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "fields": self.fields,
            "model": self.model,
            "model_version": self.model_version,
            "page_count": self.page_count,
            "warnings": self.warnings,
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
    # default
    "generic": "prebuilt-read",
    "bank_transaction": "prebuilt-read",
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
    """Returns deterministic output keyed on `kind`. Used by tests so the
    extraction pipeline can be exercised without external services."""

    def extract(
        self, *, data: bytes, mime_type: str | None, kind: str
    ) -> ExtractionResult:
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


# --------------------------------------------------------------------------- #
# Azure AI Document Intelligence (lazy import)
# --------------------------------------------------------------------------- #
class AzureDocumentIntelligenceExtractor(DocumentExtractor):
    """Calls Azure AI Document Intelligence. Lazy-imports the SDK."""

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

        return ExtractionResult(
            text=getattr(result, "content", None),
            fields=fields,
            model=model_id,
            model_version=getattr(result, "model_id", None),
            page_count=len(getattr(result, "pages", []) or []),
        )


__all__ = [
    "AzureDocumentIntelligenceExtractor",
    "DocumentExtractor",
    "ExtractionResult",
    "MockDocumentExtractor",
    "azure_model_for",
]
