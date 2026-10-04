"""Retail / eCommerce industry overlay — DRAFT v0.1.

Adds inventory granularity, merchant fees broken out per-processor,
returns/chargebacks, and channel-specific revenue.

CPA: VERIFY:
  * Merchant fees here are MOVED out of general's 7580 into a dedicated
    sub-tree (we still keep 7580 as a roll-up bucket — overlay nodes
    attach under it). Confirm this matches your firm's preference.
  * Sales Channel Revenue rows are siblings of 4010 Product Sales, not
    replacements — gives ECOM clients per-channel P&L without losing
    the general line item.
"""
from __future__ import annotations

from app.domain.account_classification import infer_sub_type
from app.models.enums import AccountType, CoaTemplateKind, Industry

_RAW: list[tuple[str, str, AccountType, str | None, int]] = [
    # Inventory expansion
    ("1045", "Inventory — In Transit", AccountType.ASSET, "1040", 145),
    ("1046", "Inventory — Returns and Damaged", AccountType.ASSET, "1040", 146),
    ("1047", "Inventory Reserve (Obsolescence)", AccountType.ASSET, "1040", 147),

    # Revenue channels
    ("4011", "Sales — Direct / Storefront", AccountType.REVENUE, "4010", 811),
    ("4012", "Sales — Online / Website", AccountType.REVENUE, "4010", 812),
    ("4013", "Sales — Amazon", AccountType.REVENUE, "4010", 813),
    ("4014", "Sales — Shopify / Other Platform", AccountType.REVENUE, "4010", 814),
    ("4015", "Sales — Wholesale / B2B", AccountType.REVENUE, "4010", 815),
    ("4016", "Sales — Marketplace (eBay, Etsy)", AccountType.REVENUE, "4010", 816),
    ("4091", "Sales Returns — Retail", AccountType.REVENUE, "4090", 891),
    ("4092", "Sales Returns — Online", AccountType.REVENUE, "4090", 892),
    ("4096", "Promotional Discounts and Coupons", AccountType.REVENUE, "4095", 896),
    ("4097", "Loyalty / Rewards Redemptions", AccountType.REVENUE, "4095", 897),

    # COGS — retail flavor
    ("5080", "Freight Out / Outbound Shipping", AccountType.EXPENSE, "5000", 1075),
    ("5081", "Fulfillment / 3PL Fees", AccountType.EXPENSE, "5000", 1076),
    ("5082", "Packaging Materials", AccountType.EXPENSE, "5000", 1077),
    ("5083", "Inventory Shrinkage", AccountType.EXPENSE, "5000", 1078),

    # Merchant fees — break out under 7580
    ("7581", "Merchant Fees — Stripe", AccountType.EXPENSE, "7580", 1481),
    ("7582", "Merchant Fees — Square", AccountType.EXPENSE, "7580", 1482),
    ("7583", "Merchant Fees — PayPal", AccountType.EXPENSE, "7580", 1483),
    ("7584", "Merchant Fees — Amazon Referral", AccountType.EXPENSE, "7580", 1484),
    ("7585", "Merchant Fees — Shopify Payments", AccountType.EXPENSE, "7580", 1485),
    ("7586", "Chargebacks and Disputes", AccountType.EXPENSE, "7580", 1486),

    # Marketing — eCom flavor
    ("8011", "Advertising — Google Ads", AccountType.EXPENSE, "8010", 1511),
    ("8012", "Advertising — Meta / Facebook", AccountType.EXPENSE, "8010", 1512),
    ("8013", "Advertising — TikTok", AccountType.EXPENSE, "8010", 1513),
    ("8014", "Advertising — Amazon PPC", AccountType.EXPENSE, "8010", 1514),
    ("8015", "Influencer / Affiliate Payments", AccountType.EXPENSE, "8010", 1515),
    ("8016", "Email / SMS Marketing Tools", AccountType.EXPENSE, "8010", 1516),
]


TEMPLATE = {
    "key": "industry:retail_ecommerce",
    "display_name": "Retail / eCommerce (Inventory, Channels, Merchant Fees)",
    "kind": CoaTemplateKind.INDUSTRY_OVERLAY,
    "industry": Industry.RETAIL_ECOMMERCE,
    "version": "0.1-draft",
    "nodes": [
        {
            "code": code, "name": name, "account_type": acct_type,
            "sub_type": infer_sub_type(code, acct_type),
            "parent_code": parent, "sort_order": sort,
        }
        for (code, name, acct_type, parent, sort) in _RAW
    ],
}
