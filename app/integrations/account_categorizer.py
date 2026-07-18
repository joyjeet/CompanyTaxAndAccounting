"""Vendor / transaction → Chart-of-Accounts code categorizer.

The bank-statement parser in `app.integrations.bank_statement` produces a
list of transactions with a *first-pass* `proposed_account_code`. For known
vendors that match `_VENDOR_TO_CODE`, the code is deterministic and good
enough. For everything else, the parser falls back to:

    * "4000" (Sales Revenue) for deposits, or
    * "9999" (Suspense) for payments.

That's the long-tail problem this module addresses: a real client's
statement has dozens of vendors the dictionary will never cover. This
module defines a pluggable `AccountCategorizer` that takes the rows the
dictionary couldn't map confidently and asks a smarter back-end (Azure
OpenAI today, possibly Document Intelligence layout features tomorrow) to
pick a better code from the client's actual chart of accounts.

Design:
  * Pure function shape — `recategorize(transactions, chart_of_accounts)`
    returns a NEW list with `proposed_account_code` updated and an
    optional `_categorizer_reason` field per row. Inputs are never mutated.
  * Deterministic dictionary path is the default (`DictionaryCategorizer`)
    — it leaves the parser's output unchanged, so behavior is identical to
    before this module existed. Useful as a no-op baseline.
  * `AzureOpenAICategorizer` is opt-in via settings. It only sends the
    transaction `description`, `direction`, and `amount` plus the COA
    summary — never the raw OCR text or any PII the description didn't
    already contain.
  * On ANY failure (network, JSON parse, validation), the categorizer
    falls back to the input row unchanged. Never raises.
"""
from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - dependency is present in runtime image
    yaml = None


class AccountCategorizer(ABC):
    """Re-categorize transactions whose first-pass code is weak.

    A "weak" first-pass is currently defined as:
      * `proposed_account_code == "9999"` (Suspense), OR
      * `proposed_account_code == "4000"` for a deposit whose description
        doesn't obviously look like a sale (the parser's default).

    Implementations are free to refine that heuristic but MUST never
    re-map a transaction whose code is already explicitly mapped by the
    dictionary (those carry intent).
    """

    @abstractmethod
    def recategorize(
        self,
        transactions: list[dict[str, Any]],
        chart_of_accounts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ...


# --------------------------------------------------------------------------- #
# No-op / dictionary categorizer (default)
# --------------------------------------------------------------------------- #
class DictionaryCategorizer(AccountCategorizer):
    """Identity categorizer — preserves the parser's output verbatim.

    This is the default backend so deployments without Azure OpenAI keys
    behave exactly as before this module landed.
    """

    NAME = "dictionary"

    def recategorize(
        self,
        transactions: list[dict[str, Any]],
        chart_of_accounts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        _ = chart_of_accounts
        return list(transactions)


# --------------------------------------------------------------------------- #
# Deterministic rule engine (Xero-style bank rules)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RuleCondition:
    """Single condition in a categorization rule.

    Supported fields/operators:
      * field="description" with contains|starts_with|equals|regex
      * field="direction" with equals
      * field="amount" with gt|gte|lt|lte|equals
    """

    field: str
    operator: str
    value: str


@dataclass(frozen=True)
class CategorizationRule:
    """Rule that maps a matching transaction to a target COA code."""

    name: str
    target_code: str
    conditions: tuple[RuleCondition, ...]
    match: str = "all"  # all | any


_XERO_STYLE_RULES: tuple[CategorizationRule, ...] = (
    # High-signal liability mapping first.
    CategorizationRule(
        name="Loan transactions",
        target_code="2400",
        conditions=(RuleCondition("description", "contains", "loan"),),
    ),
    CategorizationRule(
        name="SBA loan transactions",
        target_code="2400",
        conditions=(RuleCondition("description", "contains", "sba"),),
    ),
    # Xero-style text rules for common operating spend buckets.
    CategorizationRule(
        name="Rent",
        target_code="5200",
        conditions=(RuleCondition("description", "contains", "rent"),),
    ),
    CategorizationRule(
        name="Bank fees",
        target_code="5100",
        conditions=(
            RuleCondition("description", "contains", "service charge"),
            RuleCondition("description", "contains", "monthly fee"),
            RuleCondition("description", "contains", "nsf"),
            RuleCondition("description", "contains", "overdraft"),
        ),
        match="any",
    ),
    CategorizationRule(
        name="Sales revenue from card/mobile deposits",
        target_code="4000",
        conditions=(
            RuleCondition("direction", "equals", "deposit"),
            RuleCondition("description", "contains", "square"),
        ),
    ),
    CategorizationRule(
        name="Professional fees",
        target_code="5300",
        conditions=(
            RuleCondition("direction", "equals", "payment"),
            RuleCondition("description", "contains", "consult"),
        ),
    ),
    # Zelle handling: company payees -> office expense, person payees -> draw.
    CategorizationRule(
        name="Zelle payment to company -> Office expense",
        target_code="7500",
        conditions=(
            RuleCondition("direction", "equals", "payment"),
            RuleCondition("description", "contains", "zelle"),
            RuleCondition(
                "description",
                "regex",
                r"\b(llc|inc|corp|co\.?|company|ltd)\b",
            ),
        ),
    ),
    CategorizationRule(
        name="Zelle payment to person -> Personal expense (owner draw)",
        target_code="3070",
        conditions=(
            RuleCondition("direction", "equals", "payment"),
            RuleCondition("description", "contains", "zelle"),
            RuleCondition(
                "description",
                "regex",
                r"\b(mr|mrs|ms|dr)\.?\s+[A-Za-z]+|\b[A-Z][a-z]+\s+[A-Z][a-z]+\b",
            ),
        ),
    ),
)

DEFAULT_RULES_FILE = Path(__file__).resolve().parents[2] / "data" / "categorization_rules.yaml"


def _parse_rules_obj(obj: Any, *, strict: bool) -> tuple[CategorizationRule, ...]:
    rules_raw = obj.get("rules") if isinstance(obj, dict) else None
    if not isinstance(rules_raw, list):
        if strict:
            raise ValueError("rules document must contain a top-level 'rules' list")
        return _XERO_STYLE_RULES

    parsed: list[CategorizationRule] = []
    for i, item in enumerate(rules_raw):
        if not isinstance(item, dict):
            if strict:
                raise ValueError(f"rule at index {i} must be an object")
            continue

        name = str(item.get("name") or "").strip()
        target_code = str(item.get("target_code") or "").strip()
        match = str(item.get("match") or "all").strip().lower()
        conds_raw = item.get("conditions")

        if not name:
            if strict:
                raise ValueError(f"rule at index {i} is missing name")
            continue
        if not target_code:
            if strict:
                raise ValueError(f"rule '{name}' is missing target_code")
            continue
        if match not in {"all", "any"}:
            if strict:
                raise ValueError(f"rule '{name}' has invalid match '{match}'")
            continue
        if not isinstance(conds_raw, list) or not conds_raw:
            if strict:
                raise ValueError(f"rule '{name}' must define at least one condition")
            continue

        conds: list[RuleCondition] = []
        for j, c in enumerate(conds_raw):
            if not isinstance(c, dict):
                if strict:
                    raise ValueError(f"rule '{name}' condition #{j} must be an object")
                continue

            field = str(c.get("field") or "").strip().lower()
            operator = str(c.get("operator") or "").strip().lower()
            value = str(c.get("value") or "").strip()
            if field not in {"description", "direction", "amount"}:
                if strict:
                    raise ValueError(f"rule '{name}' condition #{j} has invalid field '{field}'")
                continue
            if not operator:
                if strict:
                    raise ValueError(f"rule '{name}' condition #{j} is missing operator")
                continue
            conds.append(RuleCondition(field=field, operator=operator, value=value))

        if conds:
            parsed.append(
                CategorizationRule(
                    name=name,
                    target_code=target_code,
                    conditions=tuple(conds),
                    match=match,
                )
            )

    if not parsed:
        if strict:
            raise ValueError("no valid rules found in document")
        return _XERO_STYLE_RULES
    return tuple(parsed)


def parse_rules_content(content: str, *, format_hint: str) -> tuple[CategorizationRule, ...]:
    """Parse JSON/YAML rules content and raise ValueError on invalid input."""
    fmt = format_hint.strip().lower()
    if fmt not in {"json", "yaml", "yml"}:
        raise ValueError("format_hint must be one of: json, yaml, yml")

    try:
        if fmt in {"yaml", "yml"}:
            if yaml is None:
                raise ValueError("PyYAML is not installed; cannot parse YAML")
            obj = yaml.safe_load(content)
        else:
            obj = json.loads(content)
    except ValueError:
        raise
    except Exception as e:  # pragma: no cover - parser-specific exceptions
        raise ValueError(f"invalid {fmt} document: {e}") from e

    return _parse_rules_obj(obj, strict=True)


def load_rules_from_file(path: str | Path) -> tuple[CategorizationRule, ...]:
    """Load categorization rules from JSON or YAML.

    Expected shape:
      {
        "rules": [
          {
            "name": "Loan transactions",
            "target_code": "2400",
            "match": "all",
            "conditions": [
              {"field": "description", "operator": "contains", "value": "loan"}
            ]
          }
        ]
      }

    Invalid files fall back to built-in defaults to keep classification
    available even when operators edit rules incorrectly.
    """
    p = Path(path)
    if not p.exists():
        return _XERO_STYLE_RULES

    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return _XERO_STYLE_RULES

    fmt = "yaml" if p.suffix.lower() in {".yaml", ".yml"} else "json"
    try:
        return parse_rules_content(raw, format_hint=fmt)
    except ValueError:
        return _XERO_STYLE_RULES


class XeroRuleEngineCategorizer(AccountCategorizer):
    """Deterministic categorizer inspired by Xero bank-rule behavior.

    Behavior:
      * Evaluate ordered rules against each transaction.
      * First matching rule wins.
      * Only apply target codes that exist in the client's chart of accounts.
      * Preserve strong explicit mappings unless the row is weak (`_is_weak`).
    """

    NAME = "xero_rule_engine"

    def __init__(
        self,
        rules: tuple[CategorizationRule, ...] | None = None,
        rules_file: str | Path | None = None,
    ) -> None:
        if rules is not None:
            self._rules = rules
            return
        self._rules = load_rules_from_file(rules_file or DEFAULT_RULES_FILE)

    def recategorize(
        self,
        transactions: list[dict[str, Any]],
        chart_of_accounts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not transactions or not chart_of_accounts:
            return list(transactions)

        valid_codes = {str(a.get("code")) for a in chart_of_accounts if a.get("code")}
        out = [dict(t) for t in transactions]

        for idx, txn in enumerate(out):
            if not _is_weak(txn):
                continue

            decision = self._match_rule(txn, valid_codes)
            if decision is None:
                continue
            code, reason = decision
            txn["proposed_account_code"] = code
            txn["_categorizer"] = self.NAME
            txn["_categorizer_reason"] = reason
            # Deterministic rules are considered high confidence.
            txn["_categorizer_confidence"] = 0.95
            txn["_categorizer_needs_review"] = False
            out[idx] = txn

        return out

    def _match_rule(
        self,
        txn: dict[str, Any],
        valid_codes: set[str],
    ) -> tuple[str, str] | None:
        for rule in self._rules:
            if rule.target_code not in valid_codes:
                continue

            checks = [self._condition_matches(txn, c) for c in rule.conditions]
            matched = all(checks) if rule.match == "all" else any(checks)
            if matched:
                return (rule.target_code, f"Rule matched: {rule.name}")
        return None

    @staticmethod
    def _condition_matches(txn: dict[str, Any], cond: RuleCondition) -> bool:
        if cond.field == "description":
            desc = str(txn.get("description") or "")
            desc_l = desc.lower()
            val = cond.value.lower()
            if cond.operator == "contains":
                return val in desc_l
            if cond.operator == "starts_with":
                return desc_l.startswith(val)
            if cond.operator == "equals":
                return desc_l == val
            if cond.operator == "regex":
                try:
                    return re.search(cond.value, desc, flags=re.IGNORECASE) is not None
                except re.error:
                    return False
            return False

        if cond.field == "direction":
            direction = str(txn.get("direction") or "").lower()
            if cond.operator == "equals":
                return direction == cond.value.lower()
            return False

        if cond.field == "amount":
            try:
                amt = float(txn.get("amount") or 0.0)
                target = float(cond.value)
            except (TypeError, ValueError):
                return False
            if cond.operator == "gt":
                return amt > target
            if cond.operator == "gte":
                return amt >= target
            if cond.operator == "lt":
                return amt < target
            if cond.operator == "lte":
                return amt <= target
            if cond.operator == "equals":
                return amt == target
            return False

        return False


# --------------------------------------------------------------------------- #
# Azure OpenAI categorizer
# --------------------------------------------------------------------------- #
_SYSTEM_PROMPT = (
    "You are a senior bookkeeper. Given a list of bank transactions and the "
    "client's chart of accounts, propose the most appropriate account code "
    "for each transaction. Use ONLY codes that appear in the provided chart "
    "of accounts. If you genuinely cannot tell, return the code '9999' "
    "(Suspense). For each decision, also output a confidence score in "
    "[0.0, 1.0] reflecting how certain you are, and up to TWO alternative "
    "codes the reviewer should consider if the primary is wrong. "
    "Respond with JSON only — no prose."
)

# Decisions below this confidence threshold are not auto-applied. Rows are
# still re-coded (so the reviewer sees the suggestion) but flagged
# `_categorizer_needs_review = True` so the promotion pipeline knows to
# create a DraftClassification with needs_review=True instead of posting.
CONFIDENCE_THRESHOLD = 0.65


class AzureOpenAICategorizer(AccountCategorizer):
    """COA-aware categorizer backed by Azure OpenAI Chat Completions.

    Only re-categorizes rows that the dictionary marked weak. Sends ONE
    batched request per `recategorize()` call so latency stays bounded
    regardless of transaction count.
    """

    NAME = "azure_openai"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None = None,
        api_version: str = "2024-08-01-preview",
        deployment: str = "gpt-4o-mini",
        max_batch: int = 50,
    ) -> None:
        # Lazy import keeps `openai` out of the import path for tests /
        # deployments that don't enable the Azure backend.
        from openai import AzureOpenAI  # type: ignore[import-not-found]

        self._client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_version=api_version,
            api_key=api_key or os.environ.get("AZURE_OPENAI_API_KEY"),
        )
        self._deployment = deployment
        self._max_batch = max_batch

    # ----- public API ---------------------------------------------------- #
    def recategorize(
        self,
        transactions: list[dict[str, Any]],
        chart_of_accounts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not transactions or not chart_of_accounts:
            return list(transactions)

        valid_codes = {str(a.get("code")) for a in chart_of_accounts if a.get("code")}
        weak_indices = [
            i for i, t in enumerate(transactions) if _is_weak(t)
        ]
        if not weak_indices:
            return list(transactions)

        out = [dict(t) for t in transactions]
        # Process in batches so a 200-line statement still fits one prompt.
        for batch_start in range(0, len(weak_indices), self._max_batch):
            batch = weak_indices[batch_start : batch_start + self._max_batch]
            decisions = self._classify_batch(
                [transactions[i] for i in batch], chart_of_accounts,
            )
            if not decisions:
                continue  # silent fallback — leave rows untouched
            for local_idx, decision in enumerate(decisions):
                if local_idx >= len(batch):
                    break
                txn_idx = batch[local_idx]
                code = str(decision.get("code") or "").strip()
                reason = str(decision.get("reason") or "").strip()
                confidence = _coerce_confidence(decision.get("confidence"))
                alternatives = _coerce_alternatives(
                    decision.get("alternatives"), valid_codes
                )
                if code and code in valid_codes:
                    out[txn_idx]["proposed_account_code"] = code
                    if reason:
                        out[txn_idx]["_categorizer_reason"] = reason
                    out[txn_idx]["_categorizer"] = self.NAME
                    out[txn_idx]["_categorizer_confidence"] = confidence
                    out[txn_idx]["_categorizer_alternatives"] = alternatives
                    out[txn_idx]["_categorizer_needs_review"] = (
                        confidence < CONFIDENCE_THRESHOLD
                    )
        return out

    # ----- internals ----------------------------------------------------- #
    def _classify_batch(
        self,
        rows: list[dict[str, Any]],
        chart_of_accounts: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        coa_str = "\n".join(
            f"  {a['code']}  {a['name']}  ({a['account_type']})"
            for a in chart_of_accounts
        )
        rows_str = "\n".join(
            f"  [{i}] {r.get('direction', '?'):7s} "
            f"${r.get('amount', '?'):>10}  "
            f"{(r.get('description') or '')[:120]}"
            for i, r in enumerate(rows)
        )
        user = (
            f"Chart of accounts:\n{coa_str}\n\n"
            f"Transactions to categorize:\n{rows_str}\n\n"
            "Return a JSON object of the form "
            '{"decisions":[{"index":0,"code":"5000","confidence":0.85,'
            '"reason":"why","alternatives":[{"code":"6000","reason":"why"}]}]} '
            "with one decision per transaction, in the same order. "
            "The reason should be a short phrase (≤80 chars) explaining "
            "the choice. confidence MUST be a number in [0.0, 1.0]. "
            "alternatives may be omitted or empty; include at most TWO."
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._deployment,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            content = resp.choices[0].message.content or ""
            obj = json.loads(content)
        except Exception:
            return None
        decisions = obj.get("decisions")
        if not isinstance(decisions, list):
            return None
        return decisions


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _is_weak(txn: dict[str, Any]) -> bool:
    """Return True if the parser's first pass for this txn deserves a retry.

    Definition:
      * code is "9999" (Suspense), OR
      * code is "4000" (Sales Revenue default for unknown deposits) AND
        the description doesn't contain an obvious sales/payment keyword.
    """
    code = str(txn.get("proposed_account_code") or "")
    if code == "9999":
        return True
    direction = txn.get("direction")
    desc = (txn.get("description") or "").lower()
    if direction == "deposit" and code == "4000":
        # Heuristic: if the parser landed on 4000 (Sales Revenue) for an
        # unknown deposit, see if the description suggests it's actually
        # something else (refund, transfer in, loan proceeds, etc.).
        non_sale_keywords = (
            "refund",
            "reversal",
            "credit",
            "transfer from",
            "loan",
            "interest",
            "dividend",
        )
        if any(k in desc for k in non_sale_keywords):
            return True
    return False


def _coerce_confidence(raw: Any) -> float:
    """Map a model-supplied confidence to a clamped float in [0.0, 1.0].

    Tolerates strings, ints, and the common "percentage scale" mistake
    where the model returns 0-100 instead of 0-1. Any value >= 5 is
    interpreted as a percentage and divided by 100 first (since legitimate
    confidences cluster near 0-1). Out-of-range results are clamped.
    Unparseable input defaults to 0.0 (forces needs_review).
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if value >= 5.0:
        value = value / 100.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _coerce_alternatives(
    raw: Any, valid_codes: set[str]
) -> list[dict[str, str]]:
    """Normalize the model's alternatives field to a list of code+reason dicts.

    Drops alternatives whose code isn't in the valid set; caps at 2 entries.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if code and code in valid_codes:
            out.append({"code": code, "reason": reason})
        if len(out) >= 2:
            break
    return out


__all__ = [
    "AccountCategorizer",
    "AzureOpenAICategorizer",
    "CategorizationRule",
    "CONFIDENCE_THRESHOLD",
    "DEFAULT_RULES_FILE",
    "DictionaryCategorizer",
    "parse_rules_content",
    "RuleCondition",
    "XeroRuleEngineCategorizer",
    "load_rules_from_file",
]
