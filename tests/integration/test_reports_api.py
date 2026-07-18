"""Integration tests for the PART C client-facing reports area.

Covers (all over the public HTTP API):

* General Ledger (`GET /statements/general-ledger`)
* AR/AP Aging (`GET /statements/{ar,ap}-aging`)
* Drill-down (`GET /statements/account-activity`)
* Account rollup tree (`GET /statements/account-rollup`)
* The portal "only finalized periods" gate on all five new endpoints.
* Cross-firm / cross-client isolation.
* Math invariants: TB debits == credits, BS balances, rollups equal
  sum of leaves, drill-down totals equal the figure they explain.

The fixtures (`world`, `_auth`) match the rest of the integration suite.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.security.auth import reset_identity_provider


@pytest.fixture(autouse=True)
def _reset_identity():
    reset_identity_provider()
    yield
    reset_identity_provider()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _auth(client: TestClient, role: str, firm_id, client_id=None) -> dict:
    body = {"sub": "tester", "role": role, "firm_id": str(firm_id)}
    if client_id is not None:
        body["client_id"] = str(client_id)
    resp = client.post("/auth/dev-token", json=body)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _post_entry(
    client: TestClient,
    headers: dict,
    *,
    client_id,
    period_id,
    entry_date: str,
    lines: list[dict],
) -> str:
    """POST a journal entry through the public API. Returns the entry id."""
    r = client.post(
        "/journal-entries",
        headers=headers,
        json={
            "client_id": str(client_id),
            "period_id": str(period_id),
            "entry_date": entry_date,
            "lines": lines,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _lock_period(client: TestClient, firm_h: dict, client_id, period_id) -> None:
    r = client.post(
        f"/clients/{client_id}/periods/{period_id}/lock",
        headers=firm_h,
    )
    assert r.status_code == 200, r.text


def _seed_three_entries(client: TestClient, h: dict, sc) -> None:
    """3 simple entries on different dates so we can age and drill into them.

    Day  1: Cash 5000 / Equity 5000           (owner investment)
    Day 60: AR  1500 / Revenue 1500           (invoice on account)
    Day 90: Expense 300 / Cash 300            (paid office expense)

    All in period 2026, so all dates < period_end 2026-12-31.
    """
    _post_entry(
        client, h,
        client_id=sc.client_id, period_id=sc.period_id,
        entry_date="2026-01-01",
        lines=[
            {"account_id": str(sc.cash_account_id), "debit": "5000", "credit": "0"},
            {"account_id": str(sc.equity_account_id), "debit": "0", "credit": "5000"},
        ],
    )
    _post_entry(
        client, h,
        client_id=sc.client_id, period_id=sc.period_id,
        entry_date="2026-03-01",
        lines=[
            {"account_id": str(sc.ar_account_id), "debit": "1500", "credit": "0"},
            {"account_id": str(sc.revenue_account_id), "debit": "0", "credit": "1500"},
        ],
    )
    _post_entry(
        client, h,
        client_id=sc.client_id, period_id=sc.period_id,
        entry_date="2026-04-01",
        lines=[
            {"account_id": str(sc.expense_account_id), "debit": "300", "credit": "0"},
            {"account_id": str(sc.cash_account_id), "debit": "0", "credit": "300"},
        ],
    )


# =========================================================================== #
# General Ledger
# =========================================================================== #
def test_general_ledger_running_balance_and_endpoints(
    client: TestClient, world,
) -> None:
    h = _auth(client, "firm_staff", world.firm_a)
    _seed_three_entries(client, h, world.a1)
    r = client.get(
        "/statements/general-ledger",
        headers=h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "account_id": str(world.a1.cash_account_id),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "general_ledger"
    assert body["account_code"] == "1000"
    assert body["account_type"] == "asset"
    assert Decimal(body["opening_balance"]) == Decimal("0")

    rows = body["rows"]
    assert len(rows) == 2  # the two cash legs
    # First (2026-01-01): +5000 → running 5000
    assert Decimal(rows[0]["debit"]) == Decimal("5000")
    assert Decimal(rows[0]["running_balance"]) == Decimal("5000")
    # Second (2026-04-01): -300 → running 4700
    assert Decimal(rows[1]["credit"]) == Decimal("300")
    assert Decimal(rows[1]["running_balance"]) == Decimal("4700")

    # Closing balance must equal the final running balance.
    assert Decimal(body["closing_balance"]) == Decimal("4700")


def test_general_ledger_404_on_foreign_account(client: TestClient, world) -> None:
    """Firm A staff asking for a Firm B account must 404 (RLS hides it)."""
    h = _auth(client, "firm_staff", world.firm_a)
    # b1.cash_account_id belongs to firm B; under firm A's RLS context it
    # simply doesn't exist.
    r = client.get(
        "/statements/general-ledger",
        headers=h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "account_id": str(world.b1.cash_account_id),
        },
    )
    assert r.status_code == 404


def test_general_ledger_portal_blocked_until_locked(
    client: TestClient, world,
) -> None:
    firm_h = _auth(client, "firm_staff", world.firm_a)
    _seed_three_entries(client, firm_h, world.a1)
    portal_h = _auth(
        client, "client_portal", world.firm_a, world.a1.client_id,
    )

    # Open period — portal blocked.
    r = client.get(
        "/statements/general-ledger",
        headers=portal_h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "account_id": str(world.a1.cash_account_id),
        },
    )
    assert r.status_code == 403

    # Firm locks the period.
    _lock_period(client, firm_h, world.a1.client_id, world.a1.period_id)

    # Now portal can read it.
    r = client.get(
        "/statements/general-ledger",
        headers=portal_h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "account_id": str(world.a1.cash_account_id),
        },
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["closing_balance"]) == Decimal("4700")


# =========================================================================== #
# AR / AP Aging
# =========================================================================== #
def test_ar_aging_buckets(client: TestClient, world) -> None:
    """Two invoices on different dates land in different buckets."""
    h = _auth(client, "firm_staff", world.firm_a)
    sc = world.a1

    # As-of period end = 2026-12-31.
    # Entry on 2026-12-01 (30 days old)  → 0-30 bucket  : $700
    # Entry on 2026-10-01 (91 days old) → 90+ bucket   : $400
    # Entry on 2026-11-15 (46 days old) → 31-60 bucket : $250
    cases = [("2026-12-01", "700"), ("2026-10-01", "400"), ("2026-11-15", "250")]
    for d, amt in cases:
        _post_entry(
            client, h, client_id=sc.client_id, period_id=sc.period_id,
            entry_date=d,
            lines=[
                {"account_id": str(sc.ar_account_id), "debit": amt, "credit": "0"},
                {"account_id": str(sc.revenue_account_id), "debit": "0", "credit": amt},
            ],
        )

    r = client.get(
        "/statements/ar-aging",
        headers=h,
        params={
            "client_id": str(sc.client_id),
            "period_id": str(sc.period_id),
            "account_codes": "1100",  # the seeded AR account
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "ar_aging"
    assert body["account_codes"] == ["1100"]

    by_label = {b["label"]: Decimal(b["amount"]) for b in body["totals_by_bucket"]}
    assert by_label["0-30"] == Decimal("700")
    assert by_label["31-60"] == Decimal("250")
    assert by_label["61-90"] == Decimal("0")
    assert by_label["90+"] == Decimal("400")
    assert Decimal(body["grand_total"]) == Decimal("1350")


def test_ar_aging_payment_cancels_invoice_in_same_bucket(
    client: TestClient, world,
) -> None:
    """Invoice debited + payment received credited net to 0 in their bucket."""
    h = _auth(client, "firm_staff", world.firm_a)
    sc = world.a1
    _post_entry(
        client, h, client_id=sc.client_id, period_id=sc.period_id,
        entry_date="2026-12-15",
        lines=[
            {"account_id": str(sc.ar_account_id), "debit": "500", "credit": "0"},
            {"account_id": str(sc.revenue_account_id), "debit": "0", "credit": "500"},
        ],
    )
    _post_entry(
        client, h, client_id=sc.client_id, period_id=sc.period_id,
        entry_date="2026-12-20",
        lines=[
            {"account_id": str(sc.cash_account_id), "debit": "500", "credit": "0"},
            {"account_id": str(sc.ar_account_id), "debit": "0", "credit": "500"},
        ],
    )

    r = client.get(
        "/statements/ar-aging",
        headers=h,
        params={
            "client_id": str(sc.client_id),
            "period_id": str(sc.period_id),
            "account_codes": "1100",
        },
    )
    assert r.status_code == 200
    body = r.json()
    # Both lines fall into 0-30; they net to 0 so the row is suppressed and
    # the grand total is 0.
    assert Decimal(body["grand_total"]) == Decimal("0")
    assert body["rows"] == []


def test_ap_aging_uses_liability_account(client: TestClient, world) -> None:
    h = _auth(client, "firm_staff", world.firm_a)
    sc = world.a1
    # Bill posted day 0 (2026-12-31 → 0-30 bucket): credit AP 800 / debit expense 800.
    _post_entry(
        client, h, client_id=sc.client_id, period_id=sc.period_id,
        entry_date="2026-12-31",
        lines=[
            {"account_id": str(sc.expense_account_id), "debit": "800", "credit": "0"},
            {"account_id": str(sc.ap_account_id), "debit": "0", "credit": "800"},
        ],
    )
    r = client.get(
        "/statements/ap-aging",
        headers=h,
        params={
            "client_id": str(sc.client_id),
            "period_id": str(sc.period_id),
            "account_codes": "2000",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "ap_aging"
    assert Decimal(body["grand_total"]) == Decimal("800")
    by_label = {b["label"]: Decimal(b["amount"]) for b in body["totals_by_bucket"]}
    assert by_label["0-30"] == Decimal("800")


def test_ar_aging_rejects_non_asset_account(client: TestClient, world) -> None:
    """Passing an AP account code to ar-aging must 422."""
    h = _auth(client, "firm_staff", world.firm_a)
    r = client.get(
        "/statements/ar-aging",
        headers=h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "account_codes": "2000",  # AP, not AR
        },
    )
    assert r.status_code == 422


def test_ap_aging_rejects_unknown_code(client: TestClient, world) -> None:
    h = _auth(client, "firm_staff", world.firm_a)
    r = client.get(
        "/statements/ap-aging",
        headers=h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "account_codes": "9999",  # doesn't exist
        },
    )
    assert r.status_code == 404


def test_aging_portal_blocked_until_locked(client: TestClient, world) -> None:
    firm_h = _auth(client, "firm_staff", world.firm_a)
    sc = world.a1
    _post_entry(
        client, firm_h, client_id=sc.client_id, period_id=sc.period_id,
        entry_date="2026-12-15",
        lines=[
            {"account_id": str(sc.ar_account_id), "debit": "500", "credit": "0"},
            {"account_id": str(sc.revenue_account_id), "debit": "0", "credit": "500"},
        ],
    )
    portal_h = _auth(client, "client_portal", world.firm_a, sc.client_id)
    r = client.get(
        "/statements/ar-aging",
        headers=portal_h,
        params={
            "client_id": str(sc.client_id),
            "period_id": str(sc.period_id),
            "account_codes": "1100",
        },
    )
    assert r.status_code == 403
    _lock_period(client, firm_h, sc.client_id, sc.period_id)
    r = client.get(
        "/statements/ar-aging",
        headers=portal_h,
        params={
            "client_id": str(sc.client_id),
            "period_id": str(sc.period_id),
            "account_codes": "1100",
        },
    )
    assert r.status_code == 200


# =========================================================================== #
# Drill-down (account-activity)
# =========================================================================== #
def test_drilldown_leaf_returns_underlying_lines(client: TestClient, world) -> None:
    """Drill into a leaf revenue account; signed_total must equal what P&L shows."""
    h = _auth(client, "firm_staff", world.firm_a)
    sc = world.a1
    _seed_three_entries(client, h, world.a1)

    # P&L revenue total = 1500 from the AR/revenue entry.
    r = client.get(
        "/statements/account-activity",
        headers=h,
        params={
            "client_id": str(sc.client_id),
            "period_id": str(sc.period_id),
            "account_id": str(sc.revenue_account_id),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_rollup"] is False
    assert body["leaf_account_ids"] == [str(sc.revenue_account_id)]
    assert len(body["lines"]) == 1
    assert Decimal(body["lines"][0]["credit"]) == Decimal("1500")
    # Revenue is credit-normal; signed = credit - debit = 1500.
    assert Decimal(body["signed_total"]) == Decimal("1500")


def test_drilldown_404_on_foreign_account(client: TestClient, world) -> None:
    h = _auth(client, "firm_staff", world.firm_a)
    r = client.get(
        "/statements/account-activity",
        headers=h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "account_id": str(uuid4()),
        },
    )
    assert r.status_code == 404


def test_drilldown_portal_blocked_until_locked(client: TestClient, world) -> None:
    firm_h = _auth(client, "firm_staff", world.firm_a)
    _seed_three_entries(client, firm_h, world.a1)
    portal_h = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    r = client.get(
        "/statements/account-activity",
        headers=portal_h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "account_id": str(world.a1.revenue_account_id),
        },
    )
    assert r.status_code == 403

    _lock_period(client, firm_h, world.a1.client_id, world.a1.period_id)
    r = client.get(
        "/statements/account-activity",
        headers=portal_h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "account_id": str(world.a1.revenue_account_id),
        },
    )
    assert r.status_code == 200


# =========================================================================== #
# Account rollup tree
# =========================================================================== #
def test_rollup_trial_balance_debits_equal_credits(
    client: TestClient, world,
) -> None:
    """For a trial-balance rollup, sum of all leaf debits equals sum of leaf credits."""
    h = _auth(client, "firm_staff", world.firm_a)
    _seed_three_entries(client, h, world.a1)

    r = client.get(
        "/statements/account-rollup",
        headers=h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "scope": "trial_balance",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope"] == "trial_balance"

    # Walk all leaves and sum debits / credits.
    def walk(nodes: list[dict]) -> tuple[Decimal, Decimal]:
        td = Decimal("0")
        tc = Decimal("0")
        for n in nodes:
            if n["is_leaf"]:
                td += Decimal(n["debit_total"])
                tc += Decimal(n["credit_total"])
            else:
                d, c = walk(n["children"])
                td += d
                tc += c
        return td, tc

    total_d, total_c = walk(body["roots"])
    assert total_d == total_c, (
        f"TB rollup must balance: debits={total_d} credits={total_c}"
    )


def test_rollup_balance_sheet_equation_holds(client: TestClient, world) -> None:
    """Sum leaf assets == sum leaf liabilities + sum leaf equity + net income."""
    h = _auth(client, "firm_staff", world.firm_a)
    _seed_three_entries(client, h, world.a1)
    r = client.get(
        "/statements/account-rollup",
        headers=h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "scope": "balance_sheet",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    sums = {"asset": Decimal("0"), "liability": Decimal("0"), "equity": Decimal("0")}

    def walk(nodes: list[dict]) -> None:
        for n in nodes:
            if n["is_leaf"]:
                sums[n["account_type"]] += Decimal(n["signed_balance"])
            walk(n["children"])

    walk(body["roots"])

    # Verify with the canonical BS endpoint that we agree on the totals.
    bs = client.get(
        "/statements/balance-sheet",
        headers=h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
        },
    ).json()
    assert sums["asset"] == Decimal(bs["total_assets"])
    assert sums["liability"] == Decimal(bs["total_liabilities"])
    # Equity in the rollup tree is just the equity accounts (no retained
    # earnings synthetic line). Equation: A = L + (Equity_posted + RE).
    assert sums["asset"] == sums["liability"] + sums["equity"] + Decimal(
        bs["retained_earnings_to_date"]
    )


def test_rollup_parent_equals_sum_of_leaf_descendants(
    client: TestClient, world,
) -> None:
    """For every parent node, signed_balance == sum of leaf-descendant signed_balance.

    This is the core invariant: parent subtotals are derived from leaves,
    never from direct postings (which leaf-only enforcement now blocks).
    """
    h = _auth(client, "firm_staff", world.firm_a)
    _seed_three_entries(client, h, world.a1)
    r = client.get(
        "/statements/account-rollup",
        headers=h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
            "scope": "trial_balance",
        },
    )
    assert r.status_code == 200
    roots = r.json()["roots"]

    def leaf_sum(node: dict) -> Decimal:
        if node["is_leaf"]:
            return Decimal(node["signed_balance"])
        return sum(
            (leaf_sum(c) for c in node["children"]),
            start=Decimal("0"),
        )

    def assert_invariant(node: dict) -> None:
        if not node["is_leaf"]:
            expected = leaf_sum(node)
            assert Decimal(node["signed_balance"]) == expected, (
                f"parent {node['code']} signed_balance="
                f"{node['signed_balance']} but leaves sum to {expected}"
            )
        for c in node["children"]:
            assert_invariant(c)

    for r_ in roots:
        assert_invariant(r_)


def test_rollup_hides_zero_only_heads(client: TestClient, world) -> None:
    h = _auth(client, "firm_staff", world.firm_a)
    _seed_three_entries(client, h, world.a1)

    for scope in ("trial_balance", "balance_sheet", "profit_and_loss"):
        r = client.get(
            "/statements/account-rollup",
            headers=h,
            params={
                "client_id": str(world.a1.client_id),
                "period_id": str(world.a1.period_id),
                "scope": scope,
            },
        )
        assert r.status_code == 200, r.text
        roots = r.json()["roots"]

        def assert_nonzero(nodes: list[dict]) -> None:
            for n in nodes:
                all_zero = (
                    Decimal(n["debit_total"]) == Decimal("0")
                    and Decimal(n["credit_total"]) == Decimal("0")
                    and Decimal(n["signed_balance"]) == Decimal("0")
                )
                assert not all_zero, f"zero-only node leaked in scope={scope}: {n['code']}"
                assert_nonzero(n["children"])

        assert_nonzero(roots)


def test_rollup_portal_blocked_until_locked(client: TestClient, world) -> None:
    firm_h = _auth(client, "firm_staff", world.firm_a)
    _seed_three_entries(client, firm_h, world.a1)
    portal_h = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    r = client.get(
        "/statements/account-rollup",
        headers=portal_h,
        params={
            "client_id": str(world.a1.client_id),
            "period_id": str(world.a1.period_id),
        },
    )
    assert r.status_code == 403


# =========================================================================== #
# Cross-tenant / cross-client isolation across ALL new endpoints
# =========================================================================== #
@pytest.mark.parametrize("path", [
    "/statements/general-ledger",
    "/statements/ar-aging",
    "/statements/ap-aging",
    "/statements/account-activity",
    "/statements/account-rollup",
])
def test_portal_cross_client_blocked(client: TestClient, world, path: str) -> None:
    """Portal scoped to a1 cannot peek at a2's reports — must 403 before any data leaks."""
    firm_h = _auth(client, "firm_staff", world.firm_a)
    # Lock a2's period so the lock-gate would PASS — we want to prove
    # cross-client is rejected for a reason independent of lock state.
    _lock_period(client, firm_h, world.a2.client_id, world.a2.period_id)

    portal_h = _auth(client, "client_portal", world.firm_a, world.a1.client_id)
    params = {
        "client_id": str(world.a2.client_id),
        "period_id": str(world.a2.period_id),
    }
    if path == "/statements/general-ledger":
        params["account_id"] = str(world.a2.cash_account_id)
    if path == "/statements/account-activity":
        params["account_id"] = str(world.a2.cash_account_id)
    if path == "/statements/ar-aging":
        params["account_codes"] = "1100"
    if path == "/statements/ap-aging":
        params["account_codes"] = "2000"

    r = client.get(path, headers=portal_h, params=params)
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("path", [
    "/statements/general-ledger",
    "/statements/ar-aging",
    "/statements/ap-aging",
    "/statements/account-activity",
    "/statements/account-rollup",
])
def test_firm_cross_firm_404(client: TestClient, world, path: str) -> None:
    """Firm A staff asking for Firm B's data must 404 (RLS hides it)."""
    h = _auth(client, "firm_staff", world.firm_a)
    params = {
        "client_id": str(world.b1.client_id),
        "period_id": str(world.b1.period_id),
    }
    if path == "/statements/general-ledger":
        params["account_id"] = str(world.b1.cash_account_id)
    if path == "/statements/account-activity":
        params["account_id"] = str(world.b1.cash_account_id)
    if path == "/statements/ar-aging":
        params["account_codes"] = "1100"
    if path == "/statements/ap-aging":
        params["account_codes"] = "2000"

    r = client.get(path, headers=h, params=params)
    # The period itself is missing from firm A's RLS view → 404.
    assert r.status_code == 404
