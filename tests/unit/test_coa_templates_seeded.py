"""Static integrity checks for the bundled COA template seed data.

These tests do NOT touch the database — they inspect the in-memory tuple
exported by `app.data.coa_templates` and assert structural invariants
that the migration relies on (unique codes, resolvable parent_code,
no cycles, account_type ↔ normal_balance consistency).
"""
from __future__ import annotations

import pytest

from app.data.coa_templates import ALL_TEMPLATES
from app.models.enums import (
    NORMAL_BALANCE_FOR,
    AccountType,
    CoaTemplateKind,
    Industry,
)


def _general_codes() -> set[str]:
    for t in ALL_TEMPLATES:
        if t["key"] == "general":
            return {n["code"] for n in t["nodes"]}
    raise AssertionError("general template missing from ALL_TEMPLATES")


@pytest.mark.parametrize("tpl", ALL_TEMPLATES, ids=lambda t: t["key"])
def test_template_codes_unique_within_template(tpl: dict) -> None:
    codes = [n["code"] for n in tpl["nodes"]]
    assert len(codes) == len(set(codes)), (
        f"duplicate codes in template {tpl['key']}"
    )


@pytest.mark.parametrize("tpl", ALL_TEMPLATES, ids=lambda t: t["key"])
def test_template_parent_codes_resolve(tpl: dict) -> None:
    """Every non-null parent_code must point at a code that exists.

    For a GENERAL template that means inside the same template.
    For an INDUSTRY_OVERLAY, the parent may either be inside the overlay
    OR inside the general base.
    """
    own_codes = {n["code"] for n in tpl["nodes"]}
    general_codes = _general_codes() if tpl["key"] != "general" else set()
    for n in tpl["nodes"]:
        if n["parent_code"] is None:
            continue
        if tpl["kind"] is CoaTemplateKind.INDUSTRY_OVERLAY:
            allowed = own_codes | general_codes
        else:
            allowed = own_codes
        assert n["parent_code"] in allowed, (
            f"{tpl['key']} node {n['code']} references unknown "
            f"parent_code {n['parent_code']}"
        )


@pytest.mark.parametrize("tpl", ALL_TEMPLATES, ids=lambda t: t["key"])
def test_template_no_self_cycles(tpl: dict) -> None:
    """Walking parent_code from any node terminates within 20 steps."""
    by_code = {n["code"]: n for n in tpl["nodes"]}
    for n in tpl["nodes"]:
        seen: set[str] = set()
        cur = n["code"]
        for _ in range(20):
            if cur in seen:
                raise AssertionError(
                    f"{tpl['key']} cycle detected starting at {n['code']}"
                )
            seen.add(cur)
            parent = by_code.get(cur, {}).get("parent_code")
            if parent is None or parent not in by_code:
                break
            cur = parent


@pytest.mark.parametrize("tpl", ALL_TEMPLATES, ids=lambda t: t["key"])
def test_template_account_type_normal_balance_consistent(tpl: dict) -> None:
    """account_type values must be in the AccountType enum + map to NORMAL_BALANCE_FOR."""
    for n in tpl["nodes"]:
        assert isinstance(n["account_type"], AccountType), (
            f"{tpl['key']} {n['code']}: account_type must be AccountType enum"
        )
        assert n["account_type"] in NORMAL_BALANCE_FOR, (
            f"{tpl['key']} {n['code']}: account_type missing from NORMAL_BALANCE_FOR"
        )


def test_general_template_has_required_root_classes() -> None:
    """The general template must cover all 5 top-level GL classes."""
    general = next(t for t in ALL_TEMPLATES if t["key"] == "general")
    types = {n["account_type"] for n in general["nodes"]}
    required = {
        AccountType.ASSET,
        AccountType.LIABILITY,
        AccountType.EQUITY,
        AccountType.REVENUE,
        AccountType.EXPENSE,
    }
    missing = required - types
    assert not missing, f"general template missing account types: {missing}"


def test_industry_overlays_map_to_real_industry_values() -> None:
    """Every bundled overlay must name an Industry the app knows about.

    The reverse is deliberately NOT required: most industries ship no
    overlay and their clients simply get the general chart.
    """
    overlay_industries = {
        t["industry"]
        for t in ALL_TEMPLATES
        if t["kind"] is CoaTemplateKind.INDUSTRY_OVERLAY
    }
    unknown = overlay_industries - set(Industry)
    assert not unknown, f"overlays name unknown industries: {unknown}"


def test_all_template_versions_are_draft_strings() -> None:
    """All bundled versions still bear the '-draft' suffix."""
    for t in ALL_TEMPLATES:
        assert "-draft" in t["version"], (
            f"{t['key']} version '{t['version']}' is missing the -draft "
            "suffix; templates ship as DRAFT until CPA activation."
        )
