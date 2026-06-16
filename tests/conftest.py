"""Pytest fixtures.

Strategy:
  * `db_setup` (session-scoped) runs Alembic upgrade once against the dev DB.
  * `clean_db` (function-scoped) truncates all tenant tables between tests so
    isolation tests start from a known state. Truncation runs as the OWNER
    role and is the ONLY thing in the test suite that uses the owner role.
  * `seeded_world` (function-scoped) creates two firms, each with two clients,
    and a basic chart of accounts + accounting period for each client. All
    inserts go through the runtime app role with the appropriate tenant
    context, so they go through RLS just like real traffic.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.db.session import get_owner_engine, tenant_session, unscoped_session
from app.db.tenant import AccessScope, TenantContext
from app.models.accounting import (
    AccountingPeriod,
    ChartOfAccounts,
    Client,
    Firm,
)
from app.models.enums import AccountType, NormalBalance

# Tables that need TRUNCATE between tests (CASCADE handles ordering, but
# children-first is the conservative ordering).
_TENANT_TABLES = (
    "draft_classification",
    "audit_event",
    "reconciliation",
    "asset",
    "bank_transaction",
    "journal_line",
    "journal_entry",
    "source_document",
    "accounting_period",
    "chart_of_accounts",
    "client",
    "firm",
)


def _alembic_upgrade() -> None:
    """Run alembic upgrade head. Idempotent."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option(
        "script_location",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "migrations")),
    )
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def db_setup() -> Iterator[None]:
    _alembic_upgrade()
    yield


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    """Wipe tenant tables before each test using the owner connection.

    The owner is subject to FORCE RLS, but TRUNCATE is a DDL-ish operation that
    bypasses RLS predicates (RLS applies to row visibility on DML), so this is
    safe.
    """
    eng = get_owner_engine()
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_TENANT_TABLES) + " RESTART IDENTITY CASCADE"))
    yield


# --------------------------------------------------------------------------- #
# Domain seed helpers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SeededClient:
    firm_id: UUID
    client_id: UUID
    period_id: UUID
    cash_account_id: UUID
    revenue_account_id: UUID
    ar_account_id: UUID
    ap_account_id: UUID
    equity_account_id: UUID
    expense_account_id: UUID


@dataclass(frozen=True)
class SeededWorld:
    firm_a: UUID
    firm_b: UUID
    a1: SeededClient  # firm A, client 1
    a2: SeededClient  # firm A, client 2
    b1: SeededClient  # firm B, client 1


def _firm_admin_ctx(firm_id: UUID) -> TenantContext:
    """A firm admin context suitable for seeding data inside a firm."""
    return TenantContext(firm_id=firm_id, scope=AccessScope.FIRM)


def _create_firm(name: str) -> UUID:
    """Create a Firm row. `firm` is not RLS-protected, so we use a plain session
    via the runtime app role with no tenant context (empty context is fine for
    `firm` because that table has no policy).
    """
    firm_id = uuid4()
    with unscoped_session() as sess:
        sess.add(Firm(id=firm_id, name=name))
    return firm_id


def _create_client_and_coa(firm_id: UUID, client_name: str) -> SeededClient:
    """Create a client + minimal COA + period under firm-admin RLS context."""
    client_id = uuid4()
    period_id = uuid4()
    cash_id = uuid4()
    rev_id = uuid4()
    ar_id = uuid4()
    ap_id = uuid4()
    eq_id = uuid4()
    exp_id = uuid4()

    with tenant_session(_firm_admin_ctx(firm_id)) as sess:
        sess.add(Client(id=client_id, firm_id=firm_id, name=client_name))
        sess.flush()
        sess.add_all(
            [
                ChartOfAccounts(
                    id=cash_id, firm_id=firm_id, client_id=client_id,
                    code="1000", name="Cash",
                    account_type=AccountType.ASSET, normal_balance=NormalBalance.DEBIT,
                ),
                ChartOfAccounts(
                    id=ar_id, firm_id=firm_id, client_id=client_id,
                    code="1100", name="Accounts Receivable",
                    account_type=AccountType.ASSET, normal_balance=NormalBalance.DEBIT,
                ),
                ChartOfAccounts(
                    id=ap_id, firm_id=firm_id, client_id=client_id,
                    code="2000", name="Accounts Payable",
                    account_type=AccountType.LIABILITY, normal_balance=NormalBalance.CREDIT,
                ),
                ChartOfAccounts(
                    id=eq_id, firm_id=firm_id, client_id=client_id,
                    code="3000", name="Owner's Equity",
                    account_type=AccountType.EQUITY, normal_balance=NormalBalance.CREDIT,
                ),
                ChartOfAccounts(
                    id=rev_id, firm_id=firm_id, client_id=client_id,
                    code="4000", name="Service Revenue",
                    account_type=AccountType.REVENUE, normal_balance=NormalBalance.CREDIT,
                ),
                ChartOfAccounts(
                    id=exp_id, firm_id=firm_id, client_id=client_id,
                    code="5000", name="Office Expense",
                    account_type=AccountType.EXPENSE, normal_balance=NormalBalance.DEBIT,
                ),
                AccountingPeriod(
                    id=period_id, firm_id=firm_id, client_id=client_id,
                    name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
                ),
            ]
        )

    return SeededClient(
        firm_id=firm_id,
        client_id=client_id,
        period_id=period_id,
        cash_account_id=cash_id,
        revenue_account_id=rev_id,
        ar_account_id=ar_id,
        ap_account_id=ap_id,
        equity_account_id=eq_id,
        expense_account_id=exp_id,
    )


@pytest.fixture
def world() -> SeededWorld:
    firm_a = _create_firm("Acme CPA")
    firm_b = _create_firm("Beta CPA")
    a1 = _create_client_and_coa(firm_a, "ClientA1")
    a2 = _create_client_and_coa(firm_a, "ClientA2")
    b1 = _create_client_and_coa(firm_b, "ClientB1")
    return SeededWorld(firm_a=firm_a, firm_b=firm_b, a1=a1, a2=a2, b1=b1)


# Convenience helpers re-exported for tests
def ctx_firm(firm_id: UUID) -> TenantContext:
    return TenantContext(firm_id=firm_id, scope=AccessScope.FIRM)


def ctx_firm_for_client(firm_id: UUID, client_id: UUID) -> TenantContext:
    return TenantContext(firm_id=firm_id, client_id=client_id, scope=AccessScope.FIRM)


def ctx_client(firm_id: UUID, client_id: UUID) -> TenantContext:
    return TenantContext(firm_id=firm_id, client_id=client_id, scope=AccessScope.CLIENT)


# --------------------------------------------------------------------------- #
# Phase 2 fixtures: pluggable integrations
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_integrations(tmp_path):  # type: ignore[no-untyped-def]
    """Wire a fresh LocalFilesystemStorage + in-memory queue + mocks into the
    process registry. Each test gets its own tmp dir; teardown resets the
    registry so subsequent tests are isolated.
    """
    from app.integrations import registry
    from app.integrations.llm import MockLLMClassifier
    from app.integrations.ocr import MockDocumentExtractor
    from app.integrations.storage import LocalFilesystemStorage
    from app.workers.queue import InMemoryJobQueue

    storage = LocalFilesystemStorage(root=tmp_path / "blob")
    extractor = MockDocumentExtractor()
    classifier = MockLLMClassifier()
    queue = InMemoryJobQueue()

    registry.set_storage(storage)
    registry.set_extractor(extractor)
    registry.set_classifier(classifier)
    registry.set_queue(queue)

    @dataclass(frozen=True)
    class Wired:
        storage: object
        extractor: object
        classifier: object
        queue: object

    yield Wired(storage=storage, extractor=extractor, classifier=classifier, queue=queue)

    registry.reset()


__all__ = [
    "SeededClient",
    "SeededWorld",
    "ctx_client",
    "ctx_firm",
    "ctx_firm_for_client",
]
