"""Initial schema + Row-Level Security.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-15

This migration:
  1. Creates all tables for the double-entry accounting core.
  2. Creates an `app_user` group / grants (idempotent against the bootstrap script).
  3. ENABLES and FORCES Row-Level Security on every tenant-scoped table.
  4. Installs one isolation policy per table with both USING and WITH CHECK,
     keyed on `app.current_firm`, `app.current_client`, `app.access_scope`
     read via current_setting(..., true) so that a missing setting -> NULL
     -> policy false -> zero rows. Fail closed.
  5. Grants table privileges to `app_user` so it can read/write subject to RLS.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tables that carry firm_id + client_id and need RLS.
TENANT_TABLES = (
    "client",  # firm_id only -> special policy below
    "chart_of_accounts",
    "accounting_period",
    "journal_entry",
    "journal_line",
    "bank_transaction",
    "asset",
    "reconciliation",
    "source_document",
    "audit_event",
)


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
ACCOUNT_TYPE = pg.ENUM(
    "asset", "liability", "equity", "revenue", "expense",
    name="account_type", create_type=False,
)
NORMAL_BALANCE = pg.ENUM("debit", "credit", name="normal_balance", create_type=False)
JE_STATUS = pg.ENUM(
    "draft", "posted", "reversed", name="journal_entry_status", create_type=False
)
RECON_STATUS = pg.ENUM(
    "open", "complete", "discrepancy", name="reconciliation_status", create_type=False
)
ASSET_STATUS = pg.ENUM("active", "disposed", name="asset_status", create_type=False)
AUDIT_ACTION = pg.ENUM(
    "create", "update", "delete", "post", "reverse",
    "lock_period", "unlock_period", "reconcile",
    name="audit_action", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    # ----- Enums ----------------------------------------------------------- #
    pg.ENUM(
        "asset", "liability", "equity", "revenue", "expense", name="account_type"
    ).create(bind, checkfirst=True)
    pg.ENUM("debit", "credit", name="normal_balance").create(bind, checkfirst=True)
    pg.ENUM(
        "draft", "posted", "reversed", name="journal_entry_status"
    ).create(bind, checkfirst=True)
    pg.ENUM(
        "open", "complete", "discrepancy", name="reconciliation_status"
    ).create(bind, checkfirst=True)
    pg.ENUM("active", "disposed", name="asset_status").create(bind, checkfirst=True)
    pg.ENUM(
        "create", "update", "delete", "post", "reverse",
        "lock_period", "unlock_period", "reconcile",
        name="audit_action",
    ).create(bind, checkfirst=True)

    # ----- firm ------------------------------------------------------------ #
    op.create_table(
        "firm",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ----- client ---------------------------------------------------------- #
    op.create_table(
        "client",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "firm_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("firm.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("external_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("firm_id", "external_code", name="uq_client_firm_external_code"),
    )
    op.create_index("ix_client_firm_id", "client", ["firm_id"])

    # ----- chart_of_accounts ---------------------------------------------- #
    op.create_table(
        "chart_of_accounts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("account_type", ACCOUNT_TYPE, nullable=False),
        sa.Column("normal_balance", NORMAL_BALANCE, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("client_id", "code", name="uq_coa_client_code"),
    )
    op.create_index("ix_coa_firm_id", "chart_of_accounts", ["firm_id"])
    op.create_index("ix_coa_client_id", "chart_of_accounts", ["client_id"])

    # ----- accounting_period ---------------------------------------------- #
    op.create_table(
        "accounting_period",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("is_locked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "client_id", "start_date", "end_date", name="uq_period_client_dates"
        ),
    )
    op.create_index("ix_period_firm_id", "accounting_period", ["firm_id"])
    op.create_index("ix_period_client_id", "accounting_period", ["client_id"])

    # ----- source_document (created before journal_entry for FK) ---------- #
    op.create_table(
        "source_document",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("storage_uri", sa.String(1024), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("original_filename", sa.String(512), nullable=True),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("extracted", pg.JSONB, nullable=True),
        sa.Column("uploaded_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_src_firm_id", "source_document", ["firm_id"])
    op.create_index("ix_src_client_id", "source_document", ["client_id"])

    # ----- journal_entry --------------------------------------------------- #
    op.create_table(
        "journal_entry",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "period_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("accounting_period.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entry_date", sa.Date, nullable=False),
        sa.Column("memo", sa.Text, nullable=True),
        sa.Column("status", JE_STATUS, nullable=False, server_default="draft"),
        sa.Column(
            "source_document_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("source_document.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_je_firm_id", "journal_entry", ["firm_id"])
    op.create_index("ix_je_client_id", "journal_entry", ["client_id"])
    op.create_index("ix_je_period_id", "journal_entry", ["period_id"])
    op.create_index("ix_je_entry_date", "journal_entry", ["entry_date"])

    # ----- journal_line ---------------------------------------------------- #
    op.create_table(
        "journal_line",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "entry_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("journal_entry.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column(
            "account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("debit", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("debit >= 0", name="ck_jl_debit_nonneg"),
        sa.CheckConstraint("credit >= 0", name="ck_jl_credit_nonneg"),
        sa.CheckConstraint(
            "(debit = 0) <> (credit = 0)",
            name="ck_jl_exactly_one_side",
        ),
    )
    op.create_index("ix_jl_firm_id", "journal_line", ["firm_id"])
    op.create_index("ix_jl_client_id", "journal_line", ["client_id"])
    op.create_index("ix_jl_entry_id", "journal_line", ["entry_id"])
    op.create_index("ix_jl_account_id", "journal_line", ["account_id"])

    # ----- bank_transaction ------------------------------------------------ #
    op.create_table(
        "bank_transaction",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("txn_date", sa.Date, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column(
            "matched_journal_line_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("journal_line.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_bt_firm_id", "bank_transaction", ["firm_id"])
    op.create_index("ix_bt_client_id", "bank_transaction", ["client_id"])
    op.create_index("ix_bt_account_id", "bank_transaction", ["account_id"])
    op.create_index("ix_bt_txn_date", "bank_transaction", ["txn_date"])

    # ----- asset ----------------------------------------------------------- #
    op.create_table(
        "asset",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("acquisition_date", sa.Date, nullable=False),
        sa.Column("acquisition_cost", sa.Numeric(20, 4), nullable=False),
        sa.Column("useful_life_months", sa.Integer, nullable=True),
        sa.Column("salvage_value", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("status", ASSET_STATUS, nullable=False, server_default="active"),
        sa.Column(
            "asset_account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "accum_depr_account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "depr_expense_account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_asset_firm_id", "asset", ["firm_id"])
    op.create_index("ix_asset_client_id", "asset", ["client_id"])

    # ----- reconciliation -------------------------------------------------- #
    op.create_table(
        "reconciliation",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("statement_balance", sa.Numeric(20, 4), nullable=False),
        sa.Column("ledger_balance", sa.Numeric(20, 4), nullable=False),
        sa.Column("difference", sa.Numeric(20, 4), nullable=False),
        sa.Column("status", RECON_STATUS, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_recon_firm_id", "reconciliation", ["firm_id"])
    op.create_index("ix_recon_client_id", "reconciliation", ["client_id"])
    op.create_index("ix_recon_account_id", "reconciliation", ["account_id"])

    # ----- audit_event ----------------------------------------------------- #
    op.create_table(
        "audit_event",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", AUDIT_ACTION, nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("details", pg.JSONB, nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_firm_id", "audit_event", ["firm_id"])
    op.create_index("ix_audit_client_id", "audit_event", ["client_id"])
    op.create_index("ix_audit_entity", "audit_event", ["entity_type", "entity_id"])
    op.create_index("ix_audit_at", "audit_event", ["at"])

    # ------------------------------------------------------------------ #
    # Grants. The bootstrap script has already granted defaults; we make
    # them explicit here so a fresh DB without the bootstrap (e.g. azure
    # managed Postgres) still gets correct privileges.
    # ------------------------------------------------------------------ #
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
                GRANT USAGE ON SCHEMA public TO app_user;
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON ALL TABLES IN SCHEMA public TO app_user;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------ #
    # Row-Level Security
    # ------------------------------------------------------------------ #
    # Build a single isolation policy per table.
    #
    # The predicate is identical for USING and WITH CHECK so that:
    #   * SELECT/UPDATE/DELETE only see permitted rows
    #   * INSERT/UPDATE cannot create or move rows out of the caller's tenant
    #
    # firm scope:    row.firm_id = current_firm
    #                AND (current_client IS NULL OR row.client_id = current_client)
    # client scope:  row.firm_id = current_firm AND row.client_id = current_client
    #
    # current_setting(..., true) -> NULL when unset; NULL = anything is FALSE,
    # so missing context returns/permits zero rows. Fail closed.

    # Predicate fragments. We refer to columns unprefixed; Postgres resolves
    # them against the row being checked.
    firm_uuid = "NULLIF(current_setting('app.current_firm', true), '')::uuid"
    client_uuid = "NULLIF(current_setting('app.current_client', true), '')::uuid"
    scope = "current_setting('app.access_scope', true)"

    def install_policy(table: str, has_client_id: bool = True) -> None:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS p_isolation ON {table};")

        if has_client_id:
            predicate = f"""
                firm_id = {firm_uuid}
                AND (
                    ({scope} = 'firm'
                        AND ({client_uuid} IS NULL OR client_id = {client_uuid}))
                    OR
                    ({scope} = 'client' AND client_id = {client_uuid})
                )
            """
        else:
            # `client` table itself: no client_id column, partition only by firm.
            # Portal users (scope='client') still need to see their own client row,
            # so additionally allow id = current_client.
            predicate = f"""
                firm_id = {firm_uuid}
                AND (
                    {scope} = 'firm'
                    OR ({scope} = 'client' AND id = {client_uuid})
                )
            """

        op.execute(
            f"""
            CREATE POLICY p_isolation ON {table}
                AS PERMISSIVE
                FOR ALL
                TO PUBLIC
                USING ({predicate})
                WITH CHECK ({predicate});
            """
        )

    # Tables WITH client_id
    for t in (
        "chart_of_accounts",
        "accounting_period",
        "journal_entry",
        "journal_line",
        "bank_transaction",
        "asset",
        "reconciliation",
        "source_document",
        "audit_event",
    ):
        install_policy(t, has_client_id=True)

    # `client` is special — no client_id column on itself; partition by firm.
    install_policy("client", has_client_id=False)


def downgrade() -> None:
    for t in (
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
    ):
        op.execute(f"DROP POLICY IF EXISTS p_isolation ON {t};")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("audit_event")
    op.drop_table("reconciliation")
    op.drop_table("asset")
    op.drop_table("bank_transaction")
    op.drop_table("journal_line")
    op.drop_table("journal_entry")
    op.drop_table("source_document")
    op.drop_table("accounting_period")
    op.drop_table("chart_of_accounts")
    op.drop_table("client")
    op.drop_table("firm")

    for enum_name in (
        "audit_action",
        "asset_status",
        "reconciliation_status",
        "journal_entry_status",
        "normal_balance",
        "account_type",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name};")
