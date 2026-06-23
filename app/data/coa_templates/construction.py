"""Construction industry overlay — DRAFT v0.1.

Layers job-costing, WIP, and retainage nodes onto the general base.

CPA: VERIFY these placements. In particular:
  * Retainage Receivable: parked under 1020 (AR) as a sibling sub-account.
    Some firms prefer a top-level "Retentions" branch.
  * WIP placement: 1042 already exists in general; we add a sub-node
    capturing under-/over-billing per ASC 606.
  * COGS sub-tree below "5000 Cost of Goods Sold" mirrors AICPA
    construction guide phases (labor, materials, equipment, subs).
"""
from __future__ import annotations

from app.models.enums import AccountType, CoaTemplateKind, Industry

_RAW: list[tuple[str, str, AccountType, str | None, int]] = [
    # Retainage — under AR / AP
    ("1025", "Retainage Receivable", AccountType.ASSET, "1020", 125),
    ("2015", "Retainage Payable", AccountType.LIABILITY, "2010", 515),

    # WIP / billings
    ("1044", "Costs and Estimated Earnings in Excess of Billings", AccountType.ASSET, "1040", 144),
    ("2075", "Billings in Excess of Costs and Estimated Earnings", AccountType.LIABILITY, "2070", 575),

    # Job-costed COGS sub-tree — attaches under 5000
    ("5100", "Job Costs — Direct Labor", AccountType.EXPENSE, "5000", 1080),
    ("5110", "Job Costs — Field Labor Wages", AccountType.EXPENSE, "5100", 1081),
    ("5111", "Job Costs — Field Labor Payroll Taxes", AccountType.EXPENSE, "5100", 1082),
    ("5112", "Job Costs — Field Labor Benefits", AccountType.EXPENSE, "5100", 1083),
    ("5200", "Job Costs — Materials", AccountType.EXPENSE, "5000", 1090),
    ("5210", "Job Costs — Lumber and Framing", AccountType.EXPENSE, "5200", 1091),
    ("5220", "Job Costs — Concrete and Masonry", AccountType.EXPENSE, "5200", 1092),
    ("5230", "Job Costs — Electrical Materials", AccountType.EXPENSE, "5200", 1093),
    ("5240", "Job Costs — Plumbing Materials", AccountType.EXPENSE, "5200", 1094),
    ("5250", "Job Costs — HVAC Materials", AccountType.EXPENSE, "5200", 1095),
    ("5290", "Job Costs — Other Materials", AccountType.EXPENSE, "5200", 1099),
    ("5300", "Job Costs — Subcontractors", AccountType.EXPENSE, "5000", 1100),
    ("5310", "Subs — Framing", AccountType.EXPENSE, "5300", 1101),
    ("5320", "Subs — Electrical", AccountType.EXPENSE, "5300", 1102),
    ("5330", "Subs — Plumbing", AccountType.EXPENSE, "5300", 1103),
    ("5340", "Subs — HVAC", AccountType.EXPENSE, "5300", 1104),
    ("5350", "Subs — Roofing", AccountType.EXPENSE, "5300", 1105),
    ("5360", "Subs — Concrete", AccountType.EXPENSE, "5300", 1106),
    ("5390", "Subs — Other Trades", AccountType.EXPENSE, "5300", 1109),
    ("5400", "Job Costs — Equipment", AccountType.EXPENSE, "5000", 1110),
    ("5410", "Equipment Rental (Job)", AccountType.EXPENSE, "5400", 1111),
    ("5420", "Small Tools and Consumables", AccountType.EXPENSE, "5400", 1112),
    ("5430", "Equipment Fuel and Maintenance (Job)", AccountType.EXPENSE, "5400", 1113),
    ("5500", "Job Costs — Other Direct", AccountType.EXPENSE, "5000", 1120),
    ("5510", "Permits and Inspection Fees (Job)", AccountType.EXPENSE, "5500", 1121),
    ("5520", "Bonding Costs (Job)", AccountType.EXPENSE, "5500", 1122),
    ("5530", "Job Site Cleanup", AccountType.EXPENSE, "5500", 1123),
    ("5540", "Job Site Insurance / Surety", AccountType.EXPENSE, "5500", 1124),

    # Revenue extensions
    ("4060", "Contract Revenue — Fixed Price", AccountType.REVENUE, "4000", 860),
    ("4061", "Contract Revenue — Time and Materials", AccountType.REVENUE, "4000", 861),
    ("4062", "Change Order Revenue", AccountType.REVENUE, "4000", 862),
]


TEMPLATE = {
    "key": "industry:construction",
    "display_name": "Construction (Job Costing, WIP, Retainage)",
    "kind": CoaTemplateKind.INDUSTRY_OVERLAY,
    "industry": Industry.CONSTRUCTION,
    "version": "0.1-draft",
    "nodes": [
        {
            "code": code, "name": name, "account_type": acct_type,
            "parent_code": parent, "sort_order": sort,
        }
        for (code, name, acct_type, parent, sort) in _RAW
    ],
}
