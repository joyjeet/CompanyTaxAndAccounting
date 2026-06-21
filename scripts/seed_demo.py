"""Seed a single demo firm + one client + a minimal chart of accounts and an
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

from app.db.session import tenant_session, unscoped_session
from app.db.tenant import AccessScope, TenantContext
from app.models.accounting import AccountingPeriod, ChartOfAccounts, Client, Firm
from app.models.enums import AccountType, NormalBalance


def _create_firm(name: str) -> UUID:
    firm_id = uuid4()
    with unscoped_session() as sess:
        sess.add(Firm(id=firm_id, name=name))
    return firm_id


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
                    id=uuid4(), firm_id=firm_id, client_id=client_id,
                    code="1000", name="Cash",
                    account_type=AccountType.ASSET, normal_balance=NormalBalance.DEBIT,
                ),
                ChartOfAccounts(
                    id=uuid4(), firm_id=firm_id, client_id=client_id,
                    code="1100", name="Accounts Receivable",
                    account_type=AccountType.ASSET, normal_balance=NormalBalance.DEBIT,
                ),
                ChartOfAccounts(
                    id=uuid4(), firm_id=firm_id, client_id=client_id,
                    code="2000", name="Accounts Payable",
                    account_type=AccountType.LIABILITY, normal_balance=NormalBalance.CREDIT,
                ),
                ChartOfAccounts(
                    id=uuid4(), firm_id=firm_id, client_id=client_id,
                    code="3000", name="Owner's Equity",
                    account_type=AccountType.EQUITY, normal_balance=NormalBalance.CREDIT,
                ),
                ChartOfAccounts(
                    id=uuid4(), firm_id=firm_id, client_id=client_id,
                    code="4000", name="Service Revenue",
                    account_type=AccountType.REVENUE, normal_balance=NormalBalance.CREDIT,
                ),
                ChartOfAccounts(
                    id=uuid4(), firm_id=firm_id, client_id=client_id,
                    code="5000", name="Office Expense",
                    account_type=AccountType.EXPENSE, normal_balance=NormalBalance.DEBIT,
                ),
                AccountingPeriod(
                    id=period_id, firm_id=firm_id, client_id=client_id,
                    name="2026",
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 12, 31),
                ),
            ]
        )
    return client_id, period_id


def main() -> None:
    firm_id = _create_firm("Demo CPA")
    client_id, period_id = _create_client_and_coa(firm_id, "Demo Client Inc.")
    print("Seeded demo data.")
    print(f"  firm_id   = {firm_id}")
    print(f"  client_id = {client_id}")
    print(f"  period_id = {period_id}")
    print()
    print("Use these in the frontend dev login form:")
    print(f"  Firm ID:   {firm_id}")
    print(f"  Client ID: {client_id}  (only required for role=client_portal)")


if __name__ == "__main__":
    main()
