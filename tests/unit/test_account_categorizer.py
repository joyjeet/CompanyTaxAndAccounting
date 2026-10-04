"""Unit tests for the AccountCategorizer protocol + implementations.

The Azure backend is tested with a fake `chat.completions.create` that
returns canned JSON, so no network or `openai` SDK is required.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.integrations.account_categorizer import (
    AzureOpenAICategorizer,
    CategorizationRule,
    DictionaryCategorizer,
    RuleCondition,
    XeroRuleEngineCategorizer,
    _is_weak,
    load_rules_from_file,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def coa() -> list[dict[str, Any]]:
    return [
        {"code": "1000", "name": "Cash", "account_type": "asset"},
        {"code": "4000", "name": "Sales Revenue", "account_type": "revenue"},
        {"code": "5000", "name": "Office Expense", "account_type": "expense"},
        {"code": "5100", "name": "Bank Fees", "account_type": "expense"},
        {"code": "5200", "name": "Rent Expense", "account_type": "expense"},
        {"code": "5300", "name": "Professional Fees", "account_type": "expense"},
        {"code": "2400", "name": "Bank Loan Payable", "account_type": "liability"},
        {"code": "9999", "name": "Suspense", "account_type": "asset"},
    ]


@pytest.fixture
def sample_txns() -> list[dict[str, Any]]:
    return [
        # Already mapped — should be left alone by every categorizer.
        {
            "description": "SBB MDEPOSIT",
            "amount": "350.00",
            "direction": "deposit",
            "proposed_account_code": "4000",
        },
        # Dictionary defaulted to 9999 — categorizer should reclassify.
        {
            "description": "CCD PAYMENT PATEL CONSULTING SERVICES",
            "amount": "70.16",
            "direction": "payment",
            "proposed_account_code": "9999",
        },
        # Refund deposit landed on 4000 (Sales) but description signals
        # it is not really a sale; weak-detector should flag for retry.
        {
            "description": "REFUND CHASE TRAVEL",
            "amount": "50.00",
            "direction": "deposit",
            "proposed_account_code": "4000",
        },
        # Already mapped to a real expense — should be left alone.
        {
            "description": "DROPBOX SUBSCRIPTION",
            "amount": "119.88",
            "direction": "payment",
            "proposed_account_code": "5000",
        },
    ]


# --------------------------------------------------------------------------- #
# _is_weak helper
# --------------------------------------------------------------------------- #
def test_is_weak_flags_suspense_rows() -> None:
    assert _is_weak({"proposed_account_code": "9999", "direction": "payment"}) is True


def test_is_weak_leaves_known_mappings_alone() -> None:
    assert _is_weak({"proposed_account_code": "5000", "direction": "payment"}) is False
    assert _is_weak({
        "proposed_account_code": "4000",
        "direction": "deposit",
        "description": "SBB MDEPOSIT",
    }) is False


def test_is_weak_flags_misclassified_deposit_refund() -> None:
    assert _is_weak({
        "proposed_account_code": "4000",
        "direction": "deposit",
        "description": "Chase Travel REFUND",
    }) is True


# --------------------------------------------------------------------------- #
# DictionaryCategorizer — must be a true no-op.
# --------------------------------------------------------------------------- #
def test_dictionary_categorizer_returns_input_unchanged(
    sample_txns: list[dict[str, Any]],
    coa: list[dict[str, Any]],
) -> None:
    cat = DictionaryCategorizer()
    result = cat.recategorize(sample_txns, coa)
    assert result == sample_txns
    # And the result is a NEW list (not aliased) — callers may mutate.
    assert result is not sample_txns


def test_xero_rule_engine_maps_loan_description_to_2400(
    coa: list[dict[str, Any]],
) -> None:
    txns = [
        {
            "description": "ACH LOAN PAYMENT SBA",
            "amount": "250.00",
            "direction": "payment",
            "proposed_account_code": "9999",
        }
    ]
    cat = XeroRuleEngineCategorizer()
    result = cat.recategorize(txns, coa)
    assert result[0]["proposed_account_code"] == "2400"
    assert result[0]["_categorizer"] == "xero_rule_engine"


def test_xero_rule_engine_only_applies_when_rule_target_exists_in_coa() -> None:
    txns = [
        {
            "description": "ACH LOAN PAYMENT SBA",
            "amount": "250.00",
            "direction": "payment",
            "proposed_account_code": "9999",
        }
    ]
    coa_without_loan = [
        {"code": "1000", "name": "Cash", "account_type": "asset"},
        {"code": "9999", "name": "Suspense", "account_type": "asset"},
    ]
    cat = XeroRuleEngineCategorizer()
    result = cat.recategorize(txns, coa_without_loan)
    assert result[0]["proposed_account_code"] == "9999"


def test_xero_rule_engine_supports_custom_rules(
    coa: list[dict[str, Any]],
) -> None:
    txns = [
        {
            "description": "AMZN MKTPLACE ORDER",
            "amount": "42.00",
            "direction": "payment",
            "proposed_account_code": "9999",
        }
    ]
    custom = (
        CategorizationRule(
            name="Amazon office supplies",
            target_code="5000",
            conditions=(RuleCondition("description", "contains", "amzn"),),
        ),
    )
    cat = XeroRuleEngineCategorizer(rules=custom)
    result = cat.recategorize(txns, coa)
    assert result[0]["proposed_account_code"] == "5000"


def test_xero_rule_engine_maps_zelle_person_vs_company() -> None:
    txns = [
        {
            "description": "Zelle payment to John Doe",
            "amount": "85.00",
            "direction": "payment",
            "proposed_account_code": "9999",
        },
        {
            "description": "Zelle transfer ACME LLC",
            "amount": "130.00",
            "direction": "payment",
            "proposed_account_code": "9999",
        },
    ]
    coa = [
        {"code": "3070", "name": "Owner Draws", "account_type": "equity"},
        {"code": "7500", "name": "Office and Administration", "account_type": "expense"},
        {"code": "9999", "name": "Suspense", "account_type": "asset"},
    ]

    cat = XeroRuleEngineCategorizer()
    result = cat.recategorize(txns, coa)

    assert result[0]["proposed_account_code"] == "3070"
    assert result[1]["proposed_account_code"] == "7500"


def test_load_rules_from_yaml_file(tmp_path: Any) -> None:
    pytest.importorskip("yaml")
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(
        """
rules:
  - name: Wire-in deposits
    target_code: "4000"
    match: all
    conditions:
      - field: direction
        operator: equals
        value: deposit
      - field: description
        operator: contains
        value: wire
""".strip(),
        encoding="utf-8",
    )
    rules = load_rules_from_file(rules_file)
    cat = XeroRuleEngineCategorizer(rules=rules)
    txns = [
        {
            "description": "WIRE TRANSFER RECEIVED",
            "amount": "1200.00",
            "direction": "deposit",
            "proposed_account_code": "9999",
        }
    ]
    coa = [
        {"code": "4000", "name": "Sales Revenue", "account_type": "revenue"},
        {"code": "9999", "name": "Suspense", "account_type": "asset"},
    ]
    result = cat.recategorize(txns, coa)
    assert result[0]["proposed_account_code"] == "4000"


def test_load_rules_from_json_file(tmp_path: Any) -> None:
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(
        """
{
  "rules": [
    {
      "name": "Wire-in deposits",
      "target_code": "4000",
      "match": "all",
      "conditions": [
        {"field": "direction", "operator": "equals", "value": "deposit"},
        {"field": "description", "operator": "contains", "value": "wire"}
      ]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    rules = load_rules_from_file(rules_file)
    cat = XeroRuleEngineCategorizer(rules=rules)
    txns = [
        {
            "description": "WIRE TRANSFER RECEIVED",
            "amount": "1200.00",
            "direction": "deposit",
            "proposed_account_code": "9999",
        }
    ]
    coa = [
        {"code": "4000", "name": "Sales Revenue", "account_type": "revenue"},
        {"code": "9999", "name": "Suspense", "account_type": "asset"},
    ]
    result = cat.recategorize(txns, coa)
    assert result[0]["proposed_account_code"] == "4000"


# --------------------------------------------------------------------------- #
# AzureOpenAICategorizer — patched client, no network.
# --------------------------------------------------------------------------- #
class _FakeChoices:
    def __init__(self, content: str) -> None:
        self.message = SimpleNamespace(content=content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoices(content)]


class _FakeChat:
    def __init__(self, content: str) -> None:
        self._content = content
        self.last_user: str | None = None
        self.calls = 0

    @property
    def completions(self):  # noqa: ANN201
        return self

    def create(self, **kwargs):  # noqa: ANN201, ANN003
        self.calls += 1
        # Stash the user prompt so the test can assert prompt contents.
        messages = kwargs.get("messages") or []
        for m in messages:
            if m.get("role") == "user":
                self.last_user = m.get("content")
        return _FakeResponse(self._content)


def _make_azure(fake_chat: _FakeChat) -> AzureOpenAICategorizer:
    # Construct without going through the openai import path — we patch
    # the private attribute directly. The default __init__ tries to import
    # `openai`, so we bypass it.
    cat = AzureOpenAICategorizer.__new__(AzureOpenAICategorizer)
    cat._client = SimpleNamespace(chat=fake_chat)  # type: ignore[attr-defined]
    cat._deployment = "gpt-4o-mini"
    cat._max_batch = 50
    return cat


def test_azure_categorizer_remaps_suspense_to_professional_fees(
    sample_txns: list[dict[str, Any]],
    coa: list[dict[str, Any]],
) -> None:
    # 2 weak rows in sample_txns: [1] (Patel/9999) and [2] (Refund/4000).
    fake = _FakeChat(
        '{"decisions":['
        '{"index":0,"code":"5300","reason":"Consulting/professional fees"},'
        '{"index":1,"code":"9999","reason":"Refund — needs reviewer decision"}'
        "]}"
    )
    cat = _make_azure(fake)

    result = cat.recategorize(sample_txns, coa)

    # Row 0 unchanged (already mapped to 4000 for SBB deposit).
    assert result[0]["proposed_account_code"] == "4000"
    assert "_categorizer_reason" not in result[0]
    # Row 1 (Patel) re-mapped to 5300 Professional Fees.
    assert result[1]["proposed_account_code"] == "5300"
    assert result[1]["_categorizer"] == "azure_openai"
    assert "Consulting" in result[1]["_categorizer_reason"]
    # Row 2 (Refund) re-mapped — model returned 9999, which is valid in COA.
    assert result[2]["proposed_account_code"] == "9999"
    # Row 3 unchanged (Dropbox already mapped to 5000).
    assert result[3]["proposed_account_code"] == "5000"
    assert "_categorizer_reason" not in result[3]

    # Single batched API call regardless of input length.
    assert fake.calls == 1
    # Prompt includes the COA and only the weak rows.
    assert fake.last_user is not None
    assert "5300  Professional Fees" in fake.last_user
    assert "PATEL CONSULTING" in fake.last_user
    assert "REFUND CHASE TRAVEL" in fake.last_user
    # Already-mapped rows are NOT sent to the model.
    assert "SBB MDEPOSIT" not in fake.last_user
    assert "DROPBOX" not in fake.last_user


def test_azure_categorizer_ignores_codes_not_in_coa(
    sample_txns: list[dict[str, Any]],
    coa: list[dict[str, Any]],
) -> None:
    # Model hallucinates account code 6000 which doesn't exist in COA.
    fake = _FakeChat(
        '{"decisions":['
        '{"index":0,"code":"6000","reason":"made-up code"},'
        '{"index":1,"code":"9999","reason":"keep in suspense"}'
        "]}"
    )
    cat = _make_azure(fake)
    result = cat.recategorize(sample_txns, coa)
    # Row 1 stays at 9999 because 6000 is not in COA.
    assert result[1]["proposed_account_code"] == "9999"
    assert "_categorizer" not in result[1]


def test_azure_categorizer_swallows_api_errors(
    sample_txns: list[dict[str, Any]],
    coa: list[dict[str, Any]],
) -> None:
    class _BoomChat(_FakeChat):
        def create(self, **kwargs):  # noqa: ANN201, ANN003
            raise RuntimeError("boom")

    cat = _make_azure(_BoomChat("ignored"))
    # Should fall back to input unchanged, never raise.
    result = cat.recategorize(sample_txns, coa)
    assert [r["proposed_account_code"] for r in result] == [
        t["proposed_account_code"] for t in sample_txns
    ]


def test_azure_categorizer_swallows_malformed_json(
    sample_txns: list[dict[str, Any]],
    coa: list[dict[str, Any]],
) -> None:
    fake = _FakeChat("not json at all")
    cat = _make_azure(fake)
    result = cat.recategorize(sample_txns, coa)
    assert result[1]["proposed_account_code"] == "9999"  # unchanged


def test_azure_categorizer_short_circuits_when_no_weak_rows(
    coa: list[dict[str, Any]],
) -> None:
    fake = _FakeChat('{"decisions":[]}')
    cat = _make_azure(fake)
    only_strong = [
        {
            "description": "SBB MDEPOSIT",
            "direction": "deposit",
            "amount": "350.00",
            "proposed_account_code": "4000",
        },
        {
            "description": "DROPBOX",
            "direction": "payment",
            "amount": "119.88",
            "proposed_account_code": "5000",
        },
    ]
    result = cat.recategorize(only_strong, coa)
    assert result == only_strong
    # No API call at all when nothing needs remapping.
    assert fake.calls == 0
