"""Seed data for granular Chart-of-Accounts templates.

Each module in this package exports a `TEMPLATE` dict shaped like::

    TEMPLATE = {
        "key": "general" | "industry:<industry_value>",
        "display_name": "Human-readable name",
        "kind": CoaTemplateKind.GENERAL | INDUSTRY_OVERLAY,
        "industry": Industry.<member> | None,   # None for the general base
        "version": "<semantic-ish version string>",
        "nodes": [
            {
                "code": "1000",
                "name": "Cash and Cash Equivalents",
                "account_type": AccountType.ASSET,
                "parent_code": None,        # None = top-level
                "sort_order": 10,
            },
            ...
        ],
    }

The data is intentionally Python (not YAML/JSON) so type-checkers catch
typos in enum names at import time, and so seed-file diffs are reviewed
the same way any code change is reviewed.

NOTHING in this package is wired in until a CPA explicitly ACTIVATEs the
template version via `app.domain.coa_templates.activate_template`. The
migration only INSERTs rows with status=DRAFT.

Path / depth / is_leaf are computed at seed time from `parent_code`
linkage; seed files only need the code/name/type/parent_code tuple.

For industry overlays, `parent_code` may reference EITHER a node defined
within the overlay file itself OR a code present in the general base
("Construction → COGS > Direct Labor > Field Labor" attaches under the
general's '5000 Cost of Goods Sold' branch). At instantiation, overlay
nodes are merged into the client's tree under their resolved parent.
"""
from __future__ import annotations

from app.data.coa_templates import (
    construction,
    general,
    generic,
    professional_services,
    retail_ecommerce,
)

ALL_TEMPLATES = (
    general.TEMPLATE,
    generic.TEMPLATE,
    construction.TEMPLATE,
    retail_ecommerce.TEMPLATE,
    professional_services.TEMPLATE,
)

__all__ = ["ALL_TEMPLATES"]
