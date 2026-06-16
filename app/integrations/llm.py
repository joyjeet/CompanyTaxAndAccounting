"""LLM-based document classification — DRAFTS ONLY.

CRITICAL contract: this layer ONLY proposes labels / suggestions and produces
a `Classification` payload that is later written to `draft_classification`.
It must never compute totals, balance books, or directly mutate accounting
tables. The deterministic domain layer is the sole source of truth for math.

If the underlying LLM returns malformed JSON, we fall back to a low-confidence
"generic" classification so the pipeline never crashes — the draft will be
flagged `needs_review=True` and surfaced for human triage.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.integrations.ocr import ExtractionResult


# --------------------------------------------------------------------------- #
# Result shape
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Classification:
    kind: str  # bank_transaction | tax_form | invoice | receipt | generic
    confidence: Decimal  # 0..1
    payload: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    prompt_version: str = ""
    warnings: list[str] = field(default_factory=list)


def _validate_payload(kind: str, payload: dict[str, Any]) -> list[str]:
    """Lightweight per-kind structural validation. Returns errors (empty -> ok)."""
    errors: list[str] = []
    if kind == "bank_transaction":
        for required in ("date", "amount", "proposed_account_code", "memo"):
            if required not in payload:
                errors.append(f"missing field: {required}")
    elif kind == "tax_form":
        if "form_type" not in payload:
            errors.append("missing field: form_type")
        if not isinstance(payload.get("fields", []), list):
            errors.append("fields must be a list")
    elif kind in ("invoice", "receipt"):
        for required in ("vendor", "total", "date"):
            if required not in payload:
                errors.append(f"missing field: {required}")
    return errors


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #
class LLMClassifier(ABC):
    @abstractmethod
    def classify(
        self,
        *,
        kind_hint: str,
        extraction: ExtractionResult,
        chart_of_accounts: list[dict[str, Any]] | None = None,
    ) -> Classification:
        ...


# --------------------------------------------------------------------------- #
# Mock — deterministic, used by tests
# --------------------------------------------------------------------------- #
class MockLLMClassifier(LLMClassifier):
    """Deterministic classifier for tests/dev."""

    PROMPT_VERSION = "mock-v1"

    _MERCHANT_TO_CODE = {
        "ACME COFFEE": ("5000", 0.93),  # Office Expense
        "BETA SUPPLIES": ("5000", 0.90),
    }

    def classify(
        self,
        *,
        kind_hint: str,
        extraction: ExtractionResult,
        chart_of_accounts: list[dict[str, Any]] | None = None,
    ) -> Classification:
        if kind_hint == "bank_transaction":
            fields = {f["name"]: f for f in extraction.fields}
            merchant = (fields.get("merchant", {}).get("value") or "").upper()
            amount = fields.get("amount", {}).get("value") or "0"
            txn_date = fields.get("date", {}).get("value") or ""
            code, conf = self._MERCHANT_TO_CODE.get(merchant, ("9999", 0.40))
            return Classification(
                kind="bank_transaction",
                confidence=Decimal(str(conf)),
                payload={
                    "date": txn_date,
                    "amount": amount,
                    "proposed_account_code": code,
                    "memo": merchant.title() if merchant else "Unknown",
                    "merchant": merchant,
                },
                model="mock",
                prompt_version=self.PROMPT_VERSION,
            )

        if kind_hint.startswith("tax_form_"):
            form_type = {
                "tax_form_w2": "W-2",
                "tax_form_1099_nec": "1099-NEC",
                "tax_form_1099_int": "1099-INT",
                "tax_form_1098": "1098",
            }.get(kind_hint, "UNKNOWN")
            return Classification(
                kind="tax_form",
                confidence=Decimal("0.95") if form_type != "UNKNOWN" else Decimal("0.40"),
                payload={"form_type": form_type, "fields": extraction.fields},
                model="mock",
                prompt_version=self.PROMPT_VERSION,
            )

        if kind_hint == "invoice":
            f = {x["name"]: x for x in extraction.fields}
            return Classification(
                kind="invoice",
                confidence=Decimal("0.85"),
                payload={
                    "vendor": f.get("vendor", {}).get("value", ""),
                    "total": f.get("total", {}).get("value", ""),
                    "date": f.get("invoice_date", {}).get("value", ""),
                },
                model="mock",
                prompt_version=self.PROMPT_VERSION,
            )

        return Classification(
            kind="generic",
            confidence=Decimal("0.30"),
            payload={"text": extraction.text},
            model="mock",
            prompt_version=self.PROMPT_VERSION,
        )


# --------------------------------------------------------------------------- #
# Azure OpenAI
# --------------------------------------------------------------------------- #
_AZURE_DEFAULT_DEPLOYMENT = "gpt-4o-mini"
_AZURE_ESCALATION_DEPLOYMENT = "gpt-4o"
_DEFAULT_THRESHOLD_FOR_ESCALATION = Decimal("0.70")


class AzureOpenAIClassifier(LLMClassifier):
    """Azure OpenAI Chat Completions classifier with structured output.

    Strategy:
      1. Call default deployment (`gpt-4o-mini`) with JSON-object response_format.
      2. Validate JSON against the kind's schema.
      3. If invalid OR confidence < escalation threshold, retry with `gpt-4o`.
      4. If still invalid, return a deterministic low-confidence "generic"
         Classification with `warnings` populated. NEVER raise.
    """

    PROMPT_VERSION = "v1"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None = None,
        api_version: str = "2024-08-01-preview",
        deployment: str = _AZURE_DEFAULT_DEPLOYMENT,
        escalation_deployment: str = _AZURE_ESCALATION_DEPLOYMENT,
        escalation_threshold: Decimal = _DEFAULT_THRESHOLD_FOR_ESCALATION,
    ) -> None:
        from openai import AzureOpenAI  # type: ignore[import-not-found]

        self._client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_version=api_version,
            api_key=api_key or os.environ.get("AZURE_OPENAI_API_KEY"),
        )
        self._deployment = deployment
        self._escalation = escalation_deployment
        self._escalation_threshold = escalation_threshold

    def _build_prompt(
        self,
        kind_hint: str,
        extraction: ExtractionResult,
        chart_of_accounts: list[dict[str, Any]] | None,
    ) -> tuple[str, str]:
        system = (
            "You are an accounting assistant. Extract a structured "
            "classification from the document. Respond with ONLY JSON. "
            "Include a top-level field `confidence` between 0 and 1."
        )
        coa_str = ""
        if chart_of_accounts:
            coa_str = "\nAvailable accounts:\n" + "\n".join(
                f"  {a['code']}\t{a['name']}\t({a['account_type']})"
                for a in chart_of_accounts
            )
        user = (
            f"Document kind hint: {kind_hint}\n"
            f"OCR text:\n{(extraction.text or '')[:6000]}\n"
            f"OCR fields:\n{json.dumps(extraction.fields)[:6000]}"
            f"{coa_str}"
        )
        return system, user

    def _call(
        self, deployment: str, system: str, user: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        try:
            resp = self._client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            content = resp.choices[0].message.content or ""
            return json.loads(content), None
        except Exception as e:  # broad: API + JSON errors
            return None, f"{type(e).__name__}: {e}"

    def classify(
        self,
        *,
        kind_hint: str,
        extraction: ExtractionResult,
        chart_of_accounts: list[dict[str, Any]] | None = None,
    ) -> Classification:
        system, user = self._build_prompt(kind_hint, extraction, chart_of_accounts)
        warnings: list[str] = []

        for deployment in (self._deployment, self._escalation):
            payload, err = self._call(deployment, system, user)
            if err is not None:
                warnings.append(f"{deployment}: {err}")
                continue
            assert payload is not None
            kind = payload.get("kind", kind_hint if kind_hint != "generic" else "generic")
            try:
                conf = Decimal(str(payload.get("confidence", "0")))
            except Exception:
                conf = Decimal("0")
            errors = _validate_payload(kind, payload)
            if errors:
                warnings.extend([f"{deployment}: {e}" for e in errors])
                continue
            if conf < self._escalation_threshold and deployment == self._deployment:
                warnings.append(
                    f"{deployment}: low confidence {conf} < {self._escalation_threshold}, escalating"
                )
                continue
            return Classification(
                kind=kind,
                confidence=conf,
                payload=payload,
                model=deployment,
                prompt_version=self.PROMPT_VERSION,
                warnings=warnings,
            )

        # All paths failed — deterministic safe fallback.
        return Classification(
            kind="generic",
            confidence=Decimal("0"),
            payload={"text": extraction.text, "fields": extraction.fields},
            model=self._deployment,
            prompt_version=self.PROMPT_VERSION,
            warnings=warnings + ["fallback: no valid response"],
        )


__all__ = [
    "AzureOpenAIClassifier",
    "Classification",
    "LLMClassifier",
    "MockLLMClassifier",
]
