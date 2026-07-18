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

from app.integrations.account_categorizer import (
    AccountCategorizer,
    XeroRuleEngineCategorizer,
)
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
        # A multi-transaction statement uses a different shape — a list of
        # `transactions` instead of a single date/amount tuple.
        if payload.get("is_statement"):
            if not isinstance(payload.get("transactions"), list):
                errors.append("statement payload must include a transactions list")
            return errors
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

    def __init__(self, *, categorizer: AccountCategorizer | None = None) -> None:
        # Default to deterministic Xero-style rule engine categorizer.
        # Callers can still inject DictionaryCategorizer for strict no-op
        # behavior or AzureOpenAICategorizer for model-backed re-mapping.
        self._categorizer = categorizer or XeroRuleEngineCategorizer()

    def _maybe_classify_bank_statement(
        self, extraction: ExtractionResult,
        chart_of_accounts: list[dict[str, Any]] | None = None,
    ) -> Classification | None:
        """If `extraction` looks like a US bank statement, return a
        `bank_transaction` Classification whose payload contains a
        `transactions[]` array (one entry per posted line).

        Two paths:
          1. `extraction.extra["transactions"]` is non-empty
             (e.g. AzureDocumentIntelligenceExtractor running
             prebuilt-bankStatement.us has already returned structured
             data). Use it directly.
          2. Otherwise, run the heuristic text parser on
             `extraction.text` (Mock / pypdf path).

        Returns None when neither path yields a statement, letting the
        caller fall through to the existing single-document branches.
        """
        from app.integrations.bank_statement import (
            looks_like_bank_statement,
            parse_statement,
        )

        # Path 1: structured DI output.
        di_txns = (extraction.extra or {}).get("transactions") if hasattr(
            extraction, "extra"
        ) else None
        if di_txns:
            parsed: dict[str, Any] = {
                "account_holder": extraction.extra.get("account_holder"),
                "statement_period": extraction.extra.get("statement_period"),
                "beginning_balance": extraction.extra.get("beginning_balance"),
                "ending_balance": extraction.extra.get("ending_balance"),
                "transactions": di_txns,
            }
            txns = di_txns
        else:
            # Path 2: heuristic text parser.
            if not looks_like_bank_statement(extraction.text):
                return None
            parsed = parse_statement(extraction.text or "")
            txns = parsed.get("transactions") or []
            if not txns:
                # Looks like a statement but we couldn't pull any lines —
                # let the generic branch handle it so the reviewer sees
                # the text.
                return None

        # Second pass: ask the configured categorizer to re-map any rows
        # the dictionary couldn't confidently place. With the default
        # DictionaryCategorizer this is a no-op; with AzureOpenAICategorizer
        # this consults the LLM with the client's actual COA. Failures
        # silently degrade to the parser's first-pass output.
        recategorized_count = 0
        if chart_of_accounts:
            before = [
                t.get("proposed_account_code") for t in txns
            ]
            txns = self._categorizer.recategorize(txns, chart_of_accounts)
            recategorized_count = sum(
                1
                for old, t in zip(before, txns)
                if t.get("proposed_account_code") != old
            )

        deposits = sum(
            float(t["amount"]) for t in txns if t["direction"] == "deposit"
        )
        payments = sum(
            float(t["amount"]) for t in txns if t["direction"] == "payment"
        )
        reasons = [
            f"Detected a bank statement (period: "
            f"{parsed.get('statement_period') or 'unknown'}).",
            f"Parsed {len(txns)} transactions: "
            f"{sum(1 for t in txns if t['direction'] == 'deposit')} deposits "
            f"(${deposits:,.2f}), "
            f"{sum(1 for t in txns if t['direction'] == 'payment')} payments "
            f"(${payments:,.2f}).",
        ]
        if parsed.get("beginning_balance") and parsed.get("ending_balance"):
            reasons.append(
                f"Beginning balance ${parsed['beginning_balance']} -> "
                f"ending balance ${parsed['ending_balance']}."
            )
        unmapped = [
            t for t in txns if t.get("proposed_account_code") == "9999"
        ]
        if unmapped:
            reasons.append(
                f"{len(unmapped)} transaction(s) routed to Suspense (9999) "
                "because no merchant pattern matched — please reassign."
            )
        if recategorized_count:
            reasons.append(
                f"{recategorized_count} transaction(s) re-categorized by "
                f"the {self._categorizer.NAME} categorizer using the "
                "client's chart of accounts."
            )

        return Classification(
            kind="bank_transaction",
            # Keep confidence below the 0.85 auto-promote threshold so the
            # reviewer always sees a multi-transaction statement before
            # journal entries are posted.
            confidence=Decimal("0.80"),
            payload={
                "is_statement": True,
                "account_holder": parsed.get("account_holder"),
                "statement_period": parsed.get("statement_period"),
                "beginning_balance": parsed.get("beginning_balance"),
                "ending_balance": parsed.get("ending_balance"),
                "transactions": txns,
                "_reasons": reasons,
            },
            model="mock-bank-statement",
            prompt_version=self.PROMPT_VERSION,
        )

    def classify(
        self,
        *,
        kind_hint: str,
        extraction: ExtractionResult,
        chart_of_accounts: list[dict[str, Any]] | None = None,
    ) -> Classification:
        # --- Auto-detect bank statements from raw text, regardless of hint.
        # If a user uploads a multi-page PDF statement and labels it
        # "generic" (or even "bank_transaction" — singular), we still want
        # to parse out each transaction and surface them as a batch.
        stmt = self._maybe_classify_bank_statement(
            extraction, chart_of_accounts=chart_of_accounts,
        )
        if stmt is not None:
            return stmt

        if kind_hint == "bank_transaction":
            fields = {f["name"]: f for f in extraction.fields}
            merchant = (fields.get("merchant", {}).get("value") or "").upper()
            amount = fields.get("amount", {}).get("value") or "0"
            txn_date = fields.get("date", {}).get("value") or ""
            code, conf = self._MERCHANT_TO_CODE.get(merchant, ("9999", 0.40))
            reasons: list[str] = []
            if merchant and merchant in self._MERCHANT_TO_CODE:
                reasons.append(
                    f"Merchant '{merchant.title()}' matched a known vendor "
                    f"-> proposed account {code}."
                )
            elif merchant:
                reasons.append(
                    f"Merchant '{merchant.title()}' is not in the known-vendor "
                    f"map; falling back to suspense account 9999 (low confidence)."
                )
            else:
                reasons.append(
                    "OCR did not extract a merchant name; cannot match to a "
                    "known vendor."
                )
            if amount in ("", "0"):
                reasons.append("OCR did not extract a transaction amount.")
            return Classification(
                kind="bank_transaction",
                confidence=Decimal(str(conf)),
                payload={
                    "date": txn_date,
                    "amount": amount,
                    "proposed_account_code": code,
                    "memo": merchant.title() if merchant else "Unknown",
                    "merchant": merchant,
                    "_reasons": reasons,
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
            reasons = (
                [f"Kind hint '{kind_hint}' mapped to {form_type}; OCR fields kept verbatim."]
                if form_type != "UNKNOWN"
                else [f"Kind hint '{kind_hint}' is not a recognised tax-form variant."]
            )
            return Classification(
                kind="tax_form",
                confidence=Decimal("0.95") if form_type != "UNKNOWN" else Decimal("0.40"),
                payload={
                    "form_type": form_type,
                    "fields": extraction.fields,
                    "_reasons": reasons,
                },
                model="mock",
                prompt_version=self.PROMPT_VERSION,
            )

        if kind_hint == "invoice":
            f = {x["name"]: x for x in extraction.fields}
            vendor = f.get("vendor", {}).get("value", "")
            total = f.get("total", {}).get("value", "")
            reasons = []
            if vendor and total:
                reasons.append(
                    f"OCR extracted vendor='{vendor}' and total='{total}'."
                )
            else:
                reasons.append(
                    "OCR did not extract a vendor/total pair; review the raw "
                    "payload to fill in missing fields."
                )
            return Classification(
                kind="invoice",
                confidence=Decimal("0.85") if (vendor and total) else Decimal("0.55"),
                payload={
                    "vendor": vendor,
                    "total": total,
                    "date": f.get("invoice_date", {}).get("value", ""),
                    "_reasons": reasons,
                },
                model="mock",
                prompt_version=self.PROMPT_VERSION,
            )

        # --- Generic fallback: try to infer something useful from OCR fields
        # before giving up. This dramatically improves the demo UX when a user
        # uploads a document without picking a kind hint.
        f = {x["name"]: x for x in (extraction.fields or [])}
        merchant = (f.get("merchant", {}).get("value") or "").upper()
        amount = f.get("amount", {}).get("value") or ""
        vendor = f.get("vendor", {}).get("value") or ""
        total = f.get("total", {}).get("value") or ""

        if merchant and amount:
            code, conf = self._MERCHANT_TO_CODE.get(merchant, ("9999", 0.45))
            return Classification(
                kind="bank_transaction",
                confidence=Decimal(str(conf)),
                payload={
                    "date": f.get("date", {}).get("value") or "",
                    "amount": amount,
                    "proposed_account_code": code,
                    "memo": merchant.title(),
                    "merchant": merchant,
                    "_reasons": [
                        "Kind hint was 'generic' but OCR found a merchant + "
                        "amount, so this was re-classified as a bank transaction.",
                        f"Merchant '{merchant.title()}' "
                        + (
                            f"matched a known vendor -> account {code}."
                            if merchant in self._MERCHANT_TO_CODE
                            else "is not in the known-vendor map; using suspense account 9999."
                        ),
                    ],
                },
                model="mock",
                prompt_version=self.PROMPT_VERSION,
            )

        if vendor and total:
            return Classification(
                kind="invoice",
                confidence=Decimal("0.55"),
                payload={
                    "vendor": vendor,
                    "total": total,
                    "date": f.get("invoice_date", {}).get("value", ""),
                    "_reasons": [
                        "Kind hint was 'generic' but OCR found a vendor + total, "
                        "so this was re-classified as an invoice.",
                        "Confidence is moderate because no expense account was "
                        "inferred — please pick one.",
                    ],
                },
                model="mock",
                prompt_version=self.PROMPT_VERSION,
            )

        reasons = [
            "Kind hint was 'generic' (no document type specified at upload).",
        ]
        if not extraction.fields:
            reasons.append(
                "OCR returned no structured fields — only free-form text. "
                "Re-upload with a specific Kind hint "
                "(bank_transaction / invoice / receipt / tax_form_w2 / …) "
                "to get a structured proposal."
            )
        else:
            reasons.append(
                "OCR returned fields, but none of them matched a recognised "
                "pattern (merchant+amount or vendor+total)."
            )
        return Classification(
            kind="generic",
            confidence=Decimal("0.30"),
            payload={
                "text": extraction.text,
                "fields": extraction.fields,
                "_reasons": reasons,
            },
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
            # Surface the running warnings list inside the payload so the UI
            # can render an explanation of *why* the confidence is what it is.
            payload.setdefault("_reasons", list(warnings) or [
                f"Model {deployment} produced a valid structured response."
            ])
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
            payload={
                "text": extraction.text,
                "fields": extraction.fields,
                "_reasons": warnings + [
                    "All model calls failed validation; review manually."
                ],
            },
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
