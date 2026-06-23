"""Unit tests for the AzureOpenAICategorizer confidence + alternatives signal.

Mocks the AzureOpenAI client so we can assert that:
  * confidence is parsed and clamped to [0.0, 1.0]
  * alternatives are kept only for codes that exist in the COA
  * confidence below CONFIDENCE_THRESHOLD sets `_categorizer_needs_review`
  * malformed responses fall back silently (row unchanged)
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.integrations.account_categorizer import (
    CONFIDENCE_THRESHOLD,
    AzureOpenAICategorizer,
    _coerce_alternatives,
    _coerce_confidence,
)


def _make_categorizer_with_decisions(decisions: list[dict]) -> AzureOpenAICategorizer:
    """Construct an AzureOpenAICategorizer whose client returns the given decisions."""
    cat = AzureOpenAICategorizer.__new__(AzureOpenAICategorizer)
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = json.dumps({"decisions": decisions})
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_resp
    cat._client = fake_client
    cat._deployment = "gpt-test"
    cat._max_batch = 50
    return cat


_COA = [
    {"code": "5520", "name": "Utilities Expense", "account_type": "expense"},
    {"code": "7520", "name": "Telephone Expense", "account_type": "expense"},
    {"code": "9999", "name": "Suspense", "account_type": "expense"},
]


# --------------------------------------------------------------------------- #
# _coerce_confidence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        (0.85, 0.85),
        ("0.85", 0.85),
        (85, 0.85),  # percentage form
        (1.5, 1.0),  # over-range clamped
        (-0.3, 0.0),  # under-range clamped
        (None, 0.0),  # missing → forces needs_review
        ("not-a-number", 0.0),
    ],
)
def test_coerce_confidence(raw: Any, expected: float) -> None:
    assert _coerce_confidence(raw) == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# _coerce_alternatives
# --------------------------------------------------------------------------- #
def test_coerce_alternatives_drops_invalid_codes() -> None:
    raw = [
        {"code": "7520", "reason": "could be phone"},
        {"code": "0001", "reason": "doesn't exist"},  # filtered out
    ]
    out = _coerce_alternatives(raw, {"5520", "7520"})
    assert len(out) == 1
    assert out[0]["code"] == "7520"


def test_coerce_alternatives_caps_at_two() -> None:
    raw = [
        {"code": "5520", "reason": "a"},
        {"code": "7520", "reason": "b"},
        {"code": "9999", "reason": "c"},
    ]
    out = _coerce_alternatives(raw, {"5520", "7520", "9999"})
    assert len(out) == 2


def test_coerce_alternatives_rejects_non_list() -> None:
    assert _coerce_alternatives("nope", {"5520"}) == []
    assert _coerce_alternatives(None, {"5520"}) == []


# --------------------------------------------------------------------------- #
# High-confidence path
# --------------------------------------------------------------------------- #
def test_recategorize_high_confidence_does_not_need_review() -> None:
    cat = _make_categorizer_with_decisions(
        [
            {
                "index": 0,
                "code": "5520",
                "confidence": 0.95,
                "reason": "utility company merchant",
                "alternatives": [
                    {"code": "7520", "reason": "could be phone"},
                ],
            }
        ]
    )
    txns = [
        {
            "proposed_account_code": "9999",  # weak → categorizer runs
            "direction": "payment",
            "amount": "120.50",
            "description": "PG&E ENERGY",
        }
    ]
    out = cat.recategorize(txns, _COA)
    assert out[0]["proposed_account_code"] == "5520"
    assert out[0]["_categorizer_confidence"] == pytest.approx(0.95)
    assert out[0]["_categorizer_needs_review"] is False
    assert out[0]["_categorizer_alternatives"] == [
        {"code": "7520", "reason": "could be phone"}
    ]


# --------------------------------------------------------------------------- #
# Low-confidence path
# --------------------------------------------------------------------------- #
def test_recategorize_low_confidence_flags_needs_review() -> None:
    low = CONFIDENCE_THRESHOLD - 0.1
    cat = _make_categorizer_with_decisions(
        [
            {
                "index": 0,
                "code": "5520",
                "confidence": low,
                "reason": "could be a few things",
                "alternatives": [
                    {"code": "7520", "reason": "phone-like merchant string"},
                ],
            }
        ]
    )
    txns = [
        {
            "proposed_account_code": "9999",
            "direction": "payment",
            "amount": "44.00",
            "description": "MERCH XYZ",
        }
    ]
    out = cat.recategorize(txns, _COA)
    # Code still set so reviewer sees the suggestion
    assert out[0]["proposed_account_code"] == "5520"
    # But the flag tells the promotion pipeline NOT to post automatically.
    assert out[0]["_categorizer_needs_review"] is True
    assert out[0]["_categorizer_confidence"] == pytest.approx(low)


# --------------------------------------------------------------------------- #
# Resilience
# --------------------------------------------------------------------------- #
def test_recategorize_returns_input_when_no_weak_rows() -> None:
    cat = _make_categorizer_with_decisions([])
    txns = [
        {
            "proposed_account_code": "5000",  # NOT weak
            "direction": "payment",
            "amount": "10",
            "description": "Office supplies",
        }
    ]
    out = cat.recategorize(txns, _COA)
    assert out == txns
    # The categorizer should never have called the LLM
    cat._client.chat.completions.create.assert_not_called()


def test_recategorize_missing_confidence_defaults_to_needs_review() -> None:
    cat = _make_categorizer_with_decisions(
        [
            {
                "index": 0,
                "code": "5520",
                "reason": "guess",
                # confidence intentionally omitted
            }
        ]
    )
    txns = [
        {
            "proposed_account_code": "9999",
            "direction": "payment",
            "amount": "10",
            "description": "vague",
        }
    ]
    out = cat.recategorize(txns, _COA)
    assert out[0]["_categorizer_confidence"] == pytest.approx(0.0)
    assert out[0]["_categorizer_needs_review"] is True
