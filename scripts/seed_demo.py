"""Seed a single demo firm + one client + a realistic chart of accounts and an
accounting period, then print the IDs.

Intended for use by testers / QA against the local dev stack:

    docker compose run --rm app python -m scripts.seed_demo

The script is idempotent on a clean DB but does NOT dedupe — running it twice
creates a second firm. Re-run `make down && make up && make migrate` to reset.

It uses the same RLS-respecting helpers the test suite uses, so all writes go
through `app_user` under FORCE RLS just like real traffic.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import tenant_session, unscoped_session
from app.db.tenant import AccessScope, TenantContext
from app.models.accounting import AccountingPeriod, ChartOfAccounts, Client, Firm
from app.models.client_profile import ClientProfile
from app.models.enums import (
    AccountType,
    EntityType,
    Industry,
    MembershipStatus,
    NormalBalance,
    StaffRole,
)
from app.models.identity import FirmMembership, UserAccount


def _create_firm(name: str) -> UUID:
    firm_id = uuid4()
    with unscoped_session() as sess:
        sess.add(Firm(id=firm_id, name=name))
    return firm_id


# Account name + numbering picked to match the keyword rules in
# ``app/domain/tax_automap.py`` so generated journal entries flow into the
# correct lines of Form 1120 / Schedule C without manual mapping.
#
# 1xxx Assets, 2xxx Liabilities, 3xxx Equity,
# 4xxx Revenue, 5xxx COGS, 6xxx Operating expenses,
# 7xxx Payroll / benefits, 8xxx Other expenses
DEMO_COA: list[tuple[str, str, AccountType, NormalBalance]] = [
    # ---- Assets ----
    ("1000", "Cash - Operating",              AccountType.ASSET,     NormalBalance.DEBIT),
    ("1010", "Cash - Payroll",                AccountType.ASSET,     NormalBalance.DEBIT),
    ("1020", "Cash - Savings",                AccountType.ASSET,     NormalBalance.DEBIT),
    ("1100", "Accounts Receivable",           AccountType.ASSET,     NormalBalance.DEBIT),
    ("1200", "Inventory",                     AccountType.ASSET,     NormalBalance.DEBIT),
    ("1300", "Prepaid Expenses",              AccountType.ASSET,     NormalBalance.DEBIT),
    ("1500", "Office Equipment",              AccountType.ASSET,     NormalBalance.DEBIT),
    ("1510", "Computers & Software",          AccountType.ASSET,     NormalBalance.DEBIT),
    ("1520", "Vehicles",                      AccountType.ASSET,     NormalBalance.DEBIT),
    ("1590", "Accumulated Depreciation",      AccountType.ASSET,     NormalBalance.CREDIT),
    # ---- Liabilities ----
    ("2000", "Accounts Payable",              AccountType.LIABILITY, NormalBalance.CREDIT),
    ("2100", "Credit Card Payable",           AccountType.LIABILITY, NormalBalance.CREDIT),
    ("2200", "Sales Tax Payable",             AccountType.LIABILITY, NormalBalance.CREDIT),
    ("2300", "Payroll Liabilities",           AccountType.LIABILITY, NormalBalance.CREDIT),
    ("2400", "Bank Loan Payable",             AccountType.LIABILITY, NormalBalance.CREDIT),
    # ---- Equity ----
    ("3000", "Owner's Equity",                AccountType.EQUITY,    NormalBalance.CREDIT),
    ("3100", "Owner's Draws",                 AccountType.EQUITY,    NormalBalance.DEBIT),
    ("3900", "Retained Earnings",             AccountType.EQUITY,    NormalBalance.CREDIT),
    # ---- Revenue ----
    ("4000", "Service Revenue",               AccountType.REVENUE,   NormalBalance.CREDIT),
    ("4100", "Product Sales",                 AccountType.REVENUE,   NormalBalance.CREDIT),
    ("4200", "Other Income",                  AccountType.REVENUE,   NormalBalance.CREDIT),
    ("4900", "Returns and Allowances",        AccountType.REVENUE,   NormalBalance.DEBIT),
    # ---- COGS (5xxx → maps to COGS / line 2 on 1120) ----
    ("5000", "Cost of Goods Sold",            AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("5100", "Materials & Supplies",          AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("5200", "Direct Labor",                  AccountType.EXPENSE,   NormalBalance.DEBIT),
    # ---- Operating expenses (6xxx) — names tuned for the automap keywords ----
    ("6000", "Officer Compensation",          AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6010", "Salaries & Wages",              AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6020", "Payroll Taxes",                 AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6100", "Office Rent",                   AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6110", "Utilities",                     AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6120", "Repairs and Maintenance",       AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6200", "Office Supplies",               AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6210", "Office Expense",                AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6300", "Advertising & Marketing",       AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6400", "Travel",                        AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6410", "Meals",                         AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6420", "Vehicle Expense",               AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6500", "Legal Services",                AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6510", "Professional Fees",             AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6600", "Bank Loan Interest Expense",    AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6700", "Depreciation Expense",          AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6800", "Charitable Donations",          AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("6900", "State Income Taxes",            AccountType.EXPENSE,   NormalBalance.DEBIT),
    # ---- Benefits (7xxx) ----
    ("7000", "Health Insurance",              AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("7100", "401k Match",                    AccountType.EXPENSE,   NormalBalance.DEBIT),
    # ---- Other (8xxx) ----
    ("8000", "Bad Debt Expense",              AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("8100", "Bank Fees",                     AccountType.EXPENSE,   NormalBalance.DEBIT),
    ("8200", "Insurance",                     AccountType.EXPENSE,   NormalBalance.DEBIT),
]


def _create_client_and_coa(firm_id: UUID, client_name: str) -> tuple[UUID, UUID]:
    ctx = TenantContext(firm_id=firm_id, scope=AccessScope.FIRM)
    client_id = uuid4()
    period_id = uuid4()
    with tenant_session(ctx) as sess:
        sess.add(Client(id=client_id, firm_id=firm_id, name=client_name))
        sess.flush()
        sess.add_all(
            [
                ChartOfAccounts(
                    id=uuid4(),
                    firm_id=firm_id,
                    client_id=client_id,
                    code=code,
                    name=name,
                    account_type=atype,
                    normal_balance=nbal,
                )
                for (code, name, atype, nbal) in DEMO_COA
            ]
            + [
                AccountingPeriod(
                    id=period_id,
                    firm_id=firm_id,
                    client_id=client_id,
                    name="2026",
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 12, 31),
                ),
                # Seed a starter profile so the dashboard isn't blank. The
                # firm or client can edit on the Profile tab / page.
                ClientProfile(
                    id=uuid4(),
                    firm_id=firm_id,
                    client_id=client_id,
                    entity_type=EntityType.S_CORP,
                    industry=Industry.PROFESSIONAL_SERVICES,
                    tax_year=2026,
                    home_state="CA",
                    additional_states=[],
                    fiscal_year_end_month=12,
                    business_legal_name=client_name,
                    country="US",
                ),
            ]
        )
    return client_id, period_id


DEMO_STAFF_SUBJECT = "dev-user@example.com"
DEMO_PORTAL_SUBJECT = "dev-client@example.com"


def _get_or_create_user(sess: Session, subject: str) -> UUID:
    """`user_account.subject` is unique, and the demo stack re-runs this script
    on every boot, so a plain INSERT would crash the container on restart."""
    existing = sess.execute(
        select(UserAccount.id).where(UserAccount.subject == subject)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    user_id = uuid4()
    sess.add(UserAccount(id=user_id, subject=subject, email=subject))
    return user_id


def _create_memberships(firm_id: UUID, client_id: UUID) -> None:
    """Give the two default dev-login subjects real membership rows.

    Without these, `APP_AUTHZ_SOURCE=membership` resolves no workspace and the
    UI parks you on "You're signed in, but not set up yet" even though the
    token is perfectly valid.

    `user_account` has no RLS, so it is written unscoped. `firm_membership`
    does, so it is written inside the firm's tenant context.
    """
    with unscoped_session() as sess:
        staff_user_id = _get_or_create_user(sess, DEMO_STAFF_SUBJECT)
        portal_user_id = _get_or_create_user(sess, DEMO_PORTAL_SUBJECT)

    with tenant_session(
        TenantContext(firm_id=firm_id, client_id=None, scope=AccessScope.FIRM)
    ) as sess:
        sess.add_all(
            [
                # Staff see the whole firm — client_id stays NULL.
                FirmMembership(
                    id=uuid4(),
                    firm_id=firm_id,
                    user_id=staff_user_id,
                    client_id=None,
                    role=StaffRole.FIRM_OWNER,
                    status=MembershipStatus.ACTIVE,
                ),
                # Portal users are pinned to exactly one client.
                FirmMembership(
                    id=uuid4(),
                    firm_id=firm_id,
                    user_id=portal_user_id,
                    client_id=client_id,
                    role=StaffRole.CLIENT_PORTAL,
                    status=MembershipStatus.ACTIVE,
                ),
            ]
        )


def main() -> None:
    firm_id = _create_firm("Demo CPA")
    client_id, period_id = _create_client_and_coa(firm_id, "Demo Client Inc.")
    _create_memberships(firm_id, client_id)
    print("Seeded demo data.")
    print(f"  firm_id   = {firm_id}")
    print(f"  client_id = {client_id}")
    print(f"  period_id = {period_id}")
    print()
    print("Use these in the frontend dev login form:")
    print(f"  Firm ID:   {firm_id}")
    print(f"  Client ID: {client_id}  (only required for role=client_portal)")
    print()
    print("Memberships (used when APP_AUTHZ_SOURCE=membership):")
    print(f"  {DEMO_STAFF_SUBJECT:<24} firm_owner    -> whole firm")
    print(f"  {DEMO_PORTAL_SUBJECT:<24} client_portal -> Demo Client Inc.")


if __name__ == "__main__":
    main()
