"""Professional Services industry overlay — DRAFT v0.1.

Targets law, accounting, consulting, agencies. Adds WIP/unbilled, trust
accounts, per-engagement revenue, and CLE/credentialing expenses.

CPA: VERIFY:
  * Trust accounts (1080/2065) are LIABILITY-side on purpose: client
    funds in trust are not the firm's revenue/asset until earned.
    Confirm jurisdiction-specific IOLTA placement.
  * Unbilled Revenue (1023) sits under AR for reporting roll-up;
    some firms prefer a separate top-level node.
"""
from __future__ import annotations

from app.models.enums import AccountType, CoaTemplateKind, Industry

_RAW: list[tuple[str, str, AccountType, str | None, int]] = [
    # Receivables / unbilled
    ("1022", "Trade A/R — Engagements Billed", AccountType.ASSET, "1020", 122),
    ("1023", "Unbilled Revenue / WIP", AccountType.ASSET, "1020", 123),
    ("1024", "Retainers / Advance Fees Held", AccountType.ASSET, "1020", 124),

    # Trust / IOLTA (asset cash + matching liability)
    ("1080", "Trust / IOLTA Bank Account", AccountType.ASSET, "1010", 116),
    ("2065", "Client Trust Funds Held", AccountType.LIABILITY, "2060", 565),

    # Revenue lines by engagement type
    ("4021", "Service Revenue — Hourly / T&M", AccountType.REVENUE, "4020", 821),
    ("4022", "Service Revenue — Fixed Fee", AccountType.REVENUE, "4020", 822),
    ("4023", "Service Revenue — Retainer", AccountType.REVENUE, "4020", 823),
    ("4024", "Service Revenue — Contingency", AccountType.REVENUE, "4020", 824),
    ("4025", "Reimbursable Expenses Billed", AccountType.REVENUE, "4020", 825),

    # COGS — direct delivery
    ("5150", "Direct Labor — Billable Staff", AccountType.EXPENSE, "5020", 1025),
    ("5151", "Direct Labor — Subcontract Consultants", AccountType.EXPENSE, "5030", 1035),
    ("5160", "Reimbursable Expense Costs (Pass-Through)", AccountType.EXPENSE, "5000", 1085),

    # Professional dev / licensing
    ("6075", "Continuing Education / CLE / CPE", AccountType.EXPENSE, "6070", 1271),
    ("6076", "Professional Licenses and Bar Dues", AccountType.EXPENSE, "6070", 1272),
    ("6077", "Professional Association Memberships", AccountType.EXPENSE, "6070", 1273),

    # Marketing / BD typical of pro services
    ("8045", "Business Development Meals (50%)", AccountType.EXPENSE, "8000", 1545),
    ("8055", "Referral Fees (Outbound)", AccountType.EXPENSE, "8000", 1555),
]


TEMPLATE = {
    "key": "industry:professional_services",
    "display_name": "Professional Services (WIP, Trust, Engagements)",
    "kind": CoaTemplateKind.INDUSTRY_OVERLAY,
    "industry": Industry.PROFESSIONAL_SERVICES,
    "version": "0.1-draft",
    "nodes": [
        {
            "code": code, "name": name, "account_type": acct_type,
            "parent_code": parent, "sort_order": sort,
        }
        for (code, name, acct_type, parent, sort) in _RAW
    ],
}
