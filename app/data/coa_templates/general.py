"""General business COA template — DRAFT v0.1 for CPA review.

This is the **base tree** every client inherits. Industry overlays
ATTACH additional leaves onto these branches; clients add their own
custom leaves on top.

Design choices flagged for the CPA:
  * 4-digit numeric codes in QuickBooks-style ranges (1xxx assets,
    2xxx liabilities, 3xxx equity, 4xxx revenue, 5xxx COGS, 6xxx-9xxx
    operating expenses).
  * Deliberately granular at the expense leaf — categorization is the
    main consumer and shallow leaves give the LLM nowhere to land.
  * Branch nodes (non-leaf) carry a `parent_code` so the materialized
    path renders cleanly; they participate in reporting roll-ups but
    are NOT directly postable to the journal (validated at JE post
    time in PART A.6 hardening, not yet wired).

CPA: VERIFY every line. Particularly the contra-revenue treatment,
the placement of "Merchant Fees" (operating expense vs. contra-rev),
and depreciation/amortization grouping.
"""
from __future__ import annotations

from app.domain.account_classification import infer_sub_type
from app.models.enums import AccountType, CoaTemplateKind

# Each node: (code, name, account_type, parent_code, sort_order)
_RAW: list[tuple[str, str, AccountType, str | None, int]] = [
    # ----- 1xxx ASSETS -----
    ("1000", "Current Assets", AccountType.ASSET, None, 100),
    ("1010", "Cash and Cash Equivalents", AccountType.ASSET, "1000", 110),
    ("1011", "Operating Checking", AccountType.ASSET, "1010", 111),
    ("1012", "Payroll Checking", AccountType.ASSET, "1010", 112),
    ("1013", "Savings", AccountType.ASSET, "1010", 113),
    ("1014", "Petty Cash", AccountType.ASSET, "1010", 114),
    ("1015", "Money Market", AccountType.ASSET, "1010", 115),
    ("1020", "Accounts Receivable", AccountType.ASSET, "1000", 120),
    ("1021", "Trade Accounts Receivable", AccountType.ASSET, "1020", 121),
    ("1029", "Allowance for Doubtful Accounts", AccountType.ASSET, "1020", 129),
    ("1030", "Other Receivables", AccountType.ASSET, "1000", 130),
    ("1031", "Employee Advances", AccountType.ASSET, "1030", 131),
    ("1032", "Notes Receivable — Current", AccountType.ASSET, "1030", 132),
    ("1040", "Inventory", AccountType.ASSET, "1000", 140),
    ("1041", "Raw Materials", AccountType.ASSET, "1040", 141),
    ("1042", "Work in Process", AccountType.ASSET, "1040", 142),
    ("1043", "Finished Goods", AccountType.ASSET, "1040", 143),
    ("1050", "Prepaid Expenses", AccountType.ASSET, "1000", 150),
    ("1051", "Prepaid Insurance", AccountType.ASSET, "1050", 151),
    ("1052", "Prepaid Rent", AccountType.ASSET, "1050", 152),
    ("1053", "Prepaid Subscriptions", AccountType.ASSET, "1050", 153),

    ("1500", "Fixed Assets", AccountType.ASSET, None, 200),
    ("1510", "Land", AccountType.ASSET, "1500", 210),
    ("1520", "Buildings", AccountType.ASSET, "1500", 220),
    ("1525", "Accumulated Depreciation — Buildings", AccountType.ASSET, "1500", 225),
    ("1530", "Machinery and Equipment", AccountType.ASSET, "1500", 230),
    ("1535", "Accumulated Depreciation — Machinery", AccountType.ASSET, "1500", 235),
    ("1540", "Vehicles", AccountType.ASSET, "1500", 240),
    ("1545", "Accumulated Depreciation — Vehicles", AccountType.ASSET, "1500", 245),
    ("1550", "Furniture and Fixtures", AccountType.ASSET, "1500", 250),
    ("1555", "Accumulated Depreciation — F&F", AccountType.ASSET, "1500", 255),
    ("1560", "Computer Hardware", AccountType.ASSET, "1500", 260),
    ("1565", "Accumulated Depreciation — Computers", AccountType.ASSET, "1500", 265),
    ("1570", "Leasehold Improvements", AccountType.ASSET, "1500", 270),
    ("1575", "Accumulated Amortization — Leasehold", AccountType.ASSET, "1500", 275),

    ("1700", "Intangible Assets", AccountType.ASSET, None, 300),
    ("1710", "Goodwill", AccountType.ASSET, "1700", 310),
    ("1720", "Trademarks and Trade Names", AccountType.ASSET, "1700", 320),
    ("1730", "Software (Capitalized)", AccountType.ASSET, "1700", 330),
    ("1735", "Accumulated Amortization — Software", AccountType.ASSET, "1700", 335),
    ("1740", "Patents", AccountType.ASSET, "1700", 340),
    ("1745", "Accumulated Amortization — Patents", AccountType.ASSET, "1700", 345),

    ("1900", "Other Assets", AccountType.ASSET, None, 400),
    ("1910", "Security Deposits", AccountType.ASSET, "1900", 410),
    ("1920", "Notes Receivable — Long Term", AccountType.ASSET, "1900", 420),

    # ----- 2xxx LIABILITIES -----
    ("2000", "Current Liabilities", AccountType.LIABILITY, None, 500),
    ("2010", "Accounts Payable", AccountType.LIABILITY, "2000", 510),
    ("2020", "Credit Cards Payable", AccountType.LIABILITY, "2000", 520),
    ("2021", "Visa", AccountType.LIABILITY, "2020", 521),
    ("2022", "Mastercard", AccountType.LIABILITY, "2020", 522),
    ("2023", "American Express", AccountType.LIABILITY, "2020", 523),
    ("2030", "Accrued Expenses", AccountType.LIABILITY, "2000", 530),
    ("2031", "Accrued Wages", AccountType.LIABILITY, "2030", 531),
    ("2032", "Accrued Interest", AccountType.LIABILITY, "2030", 532),
    ("2033", "Accrued Professional Fees", AccountType.LIABILITY, "2030", 533),
    ("2040", "Payroll Liabilities", AccountType.LIABILITY, "2000", 540),
    ("2041", "Federal Income Tax Withheld", AccountType.LIABILITY, "2040", 541),
    ("2042", "FICA Withheld", AccountType.LIABILITY, "2040", 542),
    ("2043", "Medicare Withheld", AccountType.LIABILITY, "2040", 543),
    ("2044", "State Income Tax Withheld", AccountType.LIABILITY, "2040", 544),
    ("2045", "FUTA Payable", AccountType.LIABILITY, "2040", 545),
    ("2046", "SUTA Payable", AccountType.LIABILITY, "2040", 546),
    ("2047", "401(k) Withheld", AccountType.LIABILITY, "2040", 547),
    ("2048", "Health Insurance Withheld", AccountType.LIABILITY, "2040", 548),
    ("2050", "Sales Tax Payable", AccountType.LIABILITY, "2000", 550),
    ("2060", "Customer Deposits", AccountType.LIABILITY, "2000", 560),
    ("2070", "Deferred Revenue — Current", AccountType.LIABILITY, "2000", 570),
    ("2080", "Income Tax Payable — Federal", AccountType.LIABILITY, "2000", 580),
    ("2081", "Income Tax Payable — State", AccountType.LIABILITY, "2000", 581),
    ("2090", "Short-Term Notes Payable", AccountType.LIABILITY, "2000", 590),
    ("2095", "Current Portion of Long-Term Debt", AccountType.LIABILITY, "2000", 595),

    ("2500", "Long-Term Liabilities", AccountType.LIABILITY, None, 600),
    ("2510", "Notes Payable — Long Term", AccountType.LIABILITY, "2500", 610),
    ("2520", "Mortgages Payable", AccountType.LIABILITY, "2500", 620),
    ("2530", "Loans from Shareholders / Members", AccountType.LIABILITY, "2500", 630),
    ("2540", "Deferred Revenue — Long Term", AccountType.LIABILITY, "2500", 640),
    ("2550", "Deferred Tax Liabilities", AccountType.LIABILITY, "2500", 650),

    # ----- 3xxx EQUITY -----
    ("3000", "Equity", AccountType.EQUITY, None, 700),
    ("3010", "Common Stock", AccountType.EQUITY, "3000", 710),
    ("3020", "Preferred Stock", AccountType.EQUITY, "3000", 720),
    ("3030", "Additional Paid-in Capital", AccountType.EQUITY, "3000", 730),
    ("3040", "Treasury Stock", AccountType.EQUITY, "3000", 740),
    ("3050", "Retained Earnings", AccountType.EQUITY, "3000", 750),
    ("3060", "Owner's / Member Capital Contributions", AccountType.EQUITY, "3000", 760),
    ("3070", "Owner's / Member Draws / Distributions", AccountType.EQUITY, "3000", 770),
    ("3080", "Accumulated Other Comprehensive Income", AccountType.EQUITY, "3000", 780),

    # ----- 4xxx REVENUE -----
    ("4000", "Revenue", AccountType.REVENUE, None, 800),
    ("4010", "Product Sales", AccountType.REVENUE, "4000", 810),
    ("4020", "Service Revenue", AccountType.REVENUE, "4000", 820),
    ("4030", "Subscription / Recurring Revenue", AccountType.REVENUE, "4000", 830),
    ("4040", "Shipping and Handling Income", AccountType.REVENUE, "4000", 840),
    ("4050", "Other Operating Revenue", AccountType.REVENUE, "4000", 850),
    ("4090", "Sales Returns and Allowances", AccountType.REVENUE, "4000", 890),
    ("4095", "Sales Discounts", AccountType.REVENUE, "4000", 895),

    ("4500", "Non-Operating Revenue", AccountType.REVENUE, None, 900),
    ("4510", "Interest Income", AccountType.REVENUE, "4500", 910),
    ("4520", "Dividend Income", AccountType.REVENUE, "4500", 920),
    ("4530", "Rental Income", AccountType.REVENUE, "4500", 930),
    ("4540", "Gain on Sale of Assets", AccountType.REVENUE, "4500", 940),
    ("4550", "Foreign Exchange Gain", AccountType.REVENUE, "4500", 950),
    ("4590", "Other Non-Operating Income", AccountType.REVENUE, "4500", 990),

    # ----- 5xxx COGS -----
    ("5000", "Cost of Goods Sold", AccountType.EXPENSE, None, 1000),
    ("5010", "Materials and Supplies (COGS)", AccountType.EXPENSE, "5000", 1010),
    ("5020", "Direct Labor", AccountType.EXPENSE, "5000", 1020),
    ("5030", "Subcontractor Costs", AccountType.EXPENSE, "5000", 1030),
    ("5040", "Inventory Adjustments", AccountType.EXPENSE, "5000", 1040),
    ("5050", "Freight In / Inbound Shipping", AccountType.EXPENSE, "5000", 1050),
    ("5060", "Manufacturing Overhead", AccountType.EXPENSE, "5000", 1060),
    ("5070", "Purchase Discounts (Contra)", AccountType.EXPENSE, "5000", 1070),

    # ----- 6xxx OPERATING EXPENSES — Personnel -----
    ("6000", "Personnel Expenses", AccountType.EXPENSE, None, 1200),
    ("6010", "Salaries and Wages — Officers", AccountType.EXPENSE, "6000", 1210),
    ("6020", "Salaries and Wages — Employees", AccountType.EXPENSE, "6000", 1220),
    ("6030", "Contract Labor / 1099", AccountType.EXPENSE, "6000", 1230),
    ("6040", "Payroll Taxes — Employer FICA", AccountType.EXPENSE, "6000", 1240),
    ("6041", "Payroll Taxes — Employer Medicare", AccountType.EXPENSE, "6000", 1241),
    ("6042", "Payroll Taxes — FUTA", AccountType.EXPENSE, "6000", 1242),
    ("6043", "Payroll Taxes — SUTA", AccountType.EXPENSE, "6000", 1243),
    ("6050", "Employee Benefits", AccountType.EXPENSE, "6000", 1250),
    ("6051", "Health Insurance (Employer Share)", AccountType.EXPENSE, "6050", 1251),
    ("6052", "Dental and Vision Insurance", AccountType.EXPENSE, "6050", 1252),
    ("6053", "Retirement / 401(k) Match", AccountType.EXPENSE, "6050", 1253),
    ("6054", "Workers' Compensation Insurance", AccountType.EXPENSE, "6050", 1254),
    ("6055", "Disability and Life Insurance", AccountType.EXPENSE, "6050", 1255),
    ("6060", "Payroll Processing Fees", AccountType.EXPENSE, "6000", 1260),
    ("6070", "Training and Development", AccountType.EXPENSE, "6000", 1270),
    ("6080", "Employee Meals (50% deductible)", AccountType.EXPENSE, "6000", 1280),
    ("6090", "Recruiting Fees", AccountType.EXPENSE, "6000", 1290),

    # ----- 7xxx OCCUPANCY -----
    ("7000", "Occupancy", AccountType.EXPENSE, None, 1300),
    ("7010", "Rent — Office", AccountType.EXPENSE, "7000", 1310),
    ("7020", "Rent — Warehouse / Storage", AccountType.EXPENSE, "7000", 1320),
    ("7030", "Utilities", AccountType.EXPENSE, "7000", 1330),
    ("7031", "Electricity", AccountType.EXPENSE, "7030", 1331),
    ("7032", "Gas / Heating", AccountType.EXPENSE, "7030", 1332),
    ("7033", "Water and Sewer", AccountType.EXPENSE, "7030", 1333),
    ("7034", "Trash and Recycling", AccountType.EXPENSE, "7030", 1334),
    ("7040", "Internet and Phone", AccountType.EXPENSE, "7000", 1340),
    ("7041", "Internet", AccountType.EXPENSE, "7040", 1341),
    ("7042", "Telephone — Landline", AccountType.EXPENSE, "7040", 1342),
    ("7043", "Telephone — Mobile", AccountType.EXPENSE, "7040", 1343),
    ("7050", "Repairs and Maintenance — Building", AccountType.EXPENSE, "7000", 1350),
    ("7060", "Cleaning and Janitorial", AccountType.EXPENSE, "7000", 1360),
    ("7070", "Property Insurance", AccountType.EXPENSE, "7000", 1370),
    ("7080", "Property Taxes", AccountType.EXPENSE, "7000", 1380),

    # ----- 7500 OFFICE -----
    ("7500", "Office and Administration", AccountType.EXPENSE, None, 1400),
    ("7510", "Office Supplies", AccountType.EXPENSE, "7500", 1410),
    ("7520", "Software — SaaS / Subscriptions", AccountType.EXPENSE, "7500", 1420),
    ("7530", "Computer Equipment (Expensed)", AccountType.EXPENSE, "7500", 1430),
    ("7540", "Printing and Reproduction", AccountType.EXPENSE, "7500", 1440),
    ("7550", "Postage and Shipping (Outbound)", AccountType.EXPENSE, "7500", 1450),
    ("7560", "Dues and Subscriptions", AccountType.EXPENSE, "7500", 1460),
    ("7570", "Bank Service Charges", AccountType.EXPENSE, "7500", 1470),
    ("7580", "Merchant Processing Fees", AccountType.EXPENSE, "7500", 1480),

    # ----- 8xxx SELLING / G&A -----
    ("8000", "Sales and Marketing", AccountType.EXPENSE, None, 1500),
    ("8010", "Advertising — Online", AccountType.EXPENSE, "8000", 1510),
    ("8020", "Advertising — Print and Other Media", AccountType.EXPENSE, "8000", 1520),
    ("8030", "Marketing — Content and SEO", AccountType.EXPENSE, "8000", 1530),
    ("8040", "Trade Shows and Conferences", AccountType.EXPENSE, "8000", 1540),
    ("8050", "Sales Commissions", AccountType.EXPENSE, "8000", 1550),
    ("8060", "Customer Entertainment (50%)", AccountType.EXPENSE, "8000", 1560),
    ("8070", "Promotional / Branded Merchandise", AccountType.EXPENSE, "8000", 1570),

    ("8500", "General and Administrative", AccountType.EXPENSE, None, 1600),
    ("8510", "Accounting and Bookkeeping Fees", AccountType.EXPENSE, "8500", 1610),
    ("8520", "Legal Fees", AccountType.EXPENSE, "8500", 1620),
    ("8530", "Other Professional Services", AccountType.EXPENSE, "8500", 1630),
    ("8540", "Business Licenses and Permits", AccountType.EXPENSE, "8500", 1640),
    ("8550", "Business Insurance — General Liability", AccountType.EXPENSE, "8500", 1650),
    ("8551", "Business Insurance — E&O / D&O", AccountType.EXPENSE, "8500", 1651),
    ("8552", "Business Insurance — Cyber", AccountType.EXPENSE, "8500", 1652),
    ("8560", "Travel — Airfare", AccountType.EXPENSE, "8500", 1660),
    ("8561", "Travel — Lodging", AccountType.EXPENSE, "8500", 1661),
    ("8562", "Travel — Ground Transportation", AccountType.EXPENSE, "8500", 1662),
    ("8563", "Travel — Meals (50%)", AccountType.EXPENSE, "8500", 1663),
    ("8570", "Vehicle Expense — Fuel", AccountType.EXPENSE, "8500", 1670),
    ("8571", "Vehicle Expense — Repairs and Maintenance", AccountType.EXPENSE, "8500", 1671),
    ("8572", "Vehicle Expense — Lease", AccountType.EXPENSE, "8500", 1672),
    ("8573", "Vehicle Expense — Mileage (Std Rate)", AccountType.EXPENSE, "8500", 1673),
    ("8580", "Charitable Contributions", AccountType.EXPENSE, "8500", 1680),
    ("8590", "Other Operating Expense", AccountType.EXPENSE, "8500", 1690),

    # ----- 9xxx DEPR / NON-OP / TAX -----
    ("9000", "Depreciation and Amortization", AccountType.EXPENSE, None, 1700),
    ("9010", "Depreciation Expense", AccountType.EXPENSE, "9000", 1710),
    ("9020", "Amortization Expense", AccountType.EXPENSE, "9000", 1720),

    ("9100", "Non-Operating Expense", AccountType.EXPENSE, None, 1800),
    ("9110", "Interest Expense", AccountType.EXPENSE, "9100", 1810),
    ("9120", "Loss on Sale of Assets", AccountType.EXPENSE, "9100", 1820),
    ("9130", "Foreign Exchange Loss", AccountType.EXPENSE, "9100", 1830),
    ("9140", "Bad Debt Expense", AccountType.EXPENSE, "9100", 1840),
    ("9190", "Other Non-Operating Expense", AccountType.EXPENSE, "9100", 1890),

    ("9500", "Income Tax Expense", AccountType.EXPENSE, None, 1900),
    ("9510", "Federal Income Tax Expense", AccountType.EXPENSE, "9500", 1910),
    ("9520", "State Income Tax Expense", AccountType.EXPENSE, "9500", 1920),
    ("9530", "Deferred Tax Expense", AccountType.EXPENSE, "9500", 1930),

    ("9900", "Suspense", AccountType.EXPENSE, None, 9999),
    ("9999", "Suspense / Uncategorized", AccountType.EXPENSE, "9900", 9999),
]


TEMPLATE = {
    "key": "general",
    "display_name": "General Business — Base COA",
    "kind": CoaTemplateKind.GENERAL,
    "industry": None,
    "version": "0.1-draft",
    "nodes": [
        {
            "code": code,
            "name": name,
            "account_type": acct_type,
            "sub_type": infer_sub_type(code, acct_type),
            "parent_code": parent,
            "sort_order": sort,
        }
        for (code, name, acct_type, parent, sort) in _RAW
    ],
}
