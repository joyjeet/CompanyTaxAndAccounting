"""Tax module: forms catalog, account mappings, generated worksheets.

Revision ID: 0005_tax_module
Revises: 0004_tenant_encryption_keys
Create Date: 2026-06-19

Reference (non-tenant) tables:
  * tax_form           — registry of supported forms (1120, 1120-S, 1065, 1040-SC)
  * tax_form_line      — line items per form

Tenant-scoped tables (RLS + FORCE):
  * tax_account_mapping  — reviewer-approved mapping: COA account -> tax line
  * tax_worksheet        — immutable computed snapshot per (client, period, form)
  * tax_worksheet_line   — per-line amounts within a worksheet

Seeding:
  Catalog rows are inserted from `app.domain.tax_catalog.CATALOG`. The same
  Python constant is used at runtime if a consumer needs the spec without a
  database round-trip; the migration keeps DB and code in lockstep.

Audit actions:
  Extends the `audit_action` enum with: tax_map_propose, tax_map_approve,
  tax_map_reject, tax_worksheet_generate, tax_worksheet_approve.
"""
from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.domain.tax_catalog import CATALOG, CATALOG_VERSION

revision: str = "0005_tax_module"
down_revision: str | None = "0004_tenant_encryption_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_APP_ROLE_CANDIDATES = ("app_user", "app_user_test")


def upgrade() -> None:
    bind = op.get_bind()

    # ----- Enums ---------------------------------------------------------- #
    pg.ENUM(
        "F1120", "F1120S", "F1065", "F1040SC",
        name="tax_form_code",
    ).create(bind, checkfirst=True)
    pg.ENUM(
        "income", "cogs", "deductions", "other",
        name="tax_form_section",
    ).create(bind, checkfirst=True)
    pg.ENUM(
        "positive", "negative",
        name="tax_line_sign",
    ).create(bind, checkfirst=True)
    pg.ENUM(
        "draft", "approved", "rejected", "superseded",
        name="tax_mapping_status",
    ).create(bind, checkfirst=True)
    pg.ENUM(
        "computed", "approved", "superseded",
        name="tax_worksheet_status",
    ).create(bind, checkfirst=True)

    # ----- Extend audit_action ------------------------------------------- #
    for value in (
        "tax_map_propose",
        "tax_map_approve",
        "tax_map_reject",
        "tax_worksheet_generate",
        "tax_worksheet_approve",
    ):
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")

    # ----- tax_form ------------------------------------------------------- #
    op.create_table(
        "tax_form",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "code",
            pg.ENUM(name="tax_form_code", create_type=False),
            nullable=False,
        ),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("jurisdiction", sa.String(64), nullable=False),
        sa.Column("catalog_version", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("code", name="uq_tax_form_code"),
    )

    # ----- tax_form_line -------------------------------------------------- #
    op.create_table(
        "tax_form_line",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "form_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tax_form.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column(
            "section",
            pg.ENUM(name="tax_form_section", create_type=False),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.UniqueConstraint("form_id", "code", name="uq_tax_form_line_code"),
    )
    op.create_index("ix_tax_form_line_form_id", "tax_form_line", ["form_id"])

    # ----- tax_account_mapping (TENANT) ---------------------------------- #
    op.create_table(
        "tax_account_mapping",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "form_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tax_form.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "line_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tax_form_line.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "sign",
            pg.ENUM(name="tax_line_sign", create_type=False),
            nullable=False,
            server_default="positive",
        ),
        sa.Column(
            "status",
            pg.ENUM(name="tax_mapping_status", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("proposed_by", sa.String(255), nullable=False),
        sa.Column(
            "proposed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "client_id", "form_id", "account_id", "status",
            name="uq_tax_map_client_form_acct_status",
        ),
    )
    op.create_index("ix_tax_map_firm_id", "tax_account_mapping", ["firm_id"])
    op.create_index("ix_tax_map_client_id", "tax_account_mapping", ["client_id"])
    op.create_index("ix_tax_map_form_id", "tax_account_mapping", ["form_id"])
    op.create_index("ix_tax_map_account_id", "tax_account_mapping", ["account_id"])
    op.create_index("ix_tax_map_status", "tax_account_mapping", ["status"])

    # ----- tax_worksheet (TENANT) ---------------------------------------- #
    op.create_table(
        "tax_worksheet",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "period_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("accounting_period.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "form_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tax_form.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            pg.ENUM(name="tax_worksheet_status", create_type=False),
            nullable=False,
            server_default="computed",
        ),
        sa.Column("catalog_version", sa.String(32), nullable=False),
        sa.Column("total_income", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("total_cogs", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("total_deductions", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("taxable_income", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("generated_by", sa.String(255), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("approved_by", sa.String(255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tax_ws_firm_id", "tax_worksheet", ["firm_id"])
    op.create_index("ix_tax_ws_client_id", "tax_worksheet", ["client_id"])
    op.create_index("ix_tax_ws_period_id", "tax_worksheet", ["period_id"])
    op.create_index("ix_tax_ws_form_id", "tax_worksheet", ["form_id"])
    op.create_index("ix_tax_ws_status", "tax_worksheet", ["status"])

    # ----- tax_worksheet_line (TENANT) ----------------------------------- #
    op.create_table(
        "tax_worksheet_line",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "worksheet_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tax_worksheet.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "form_line_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tax_form_line.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("line_code", sa.String(16), nullable=False),
        sa.Column("line_label", sa.String(255), nullable=False),
        sa.Column(
            "section",
            pg.ENUM(name="tax_form_section", create_type=False),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column(
            "contributing_accounts",
            pg.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index("ix_tax_ws_line_worksheet_id", "tax_worksheet_line", ["worksheet_id"])

    # ----- Grants ---------------------------------------------------------- #
    tenant_tables = ("tax_account_mapping", "tax_worksheet", "tax_worksheet_line")
    reference_tables = ("tax_form", "tax_form_line")
    for role in _APP_ROLE_CANDIDATES:
        for t in tenant_tables:
            op.execute(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                        GRANT SELECT, INSERT, UPDATE, DELETE
                            ON TABLE {t} TO {role};
                    END IF;
                END
                $$;
                """
            )
        for t in reference_tables:
            # Reference data: app role only needs SELECT.
            op.execute(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                        GRANT SELECT ON TABLE {t} TO {role};
                    END IF;
                END
                $$;
                """
            )

    # ----- RLS on tenant tables ------------------------------------------ #
    firm_uuid = "NULLIF(current_setting('app.current_firm', true), '')::uuid"
    client_uuid = "NULLIF(current_setting('app.current_client', true), '')::uuid"
    scope = "current_setting('app.access_scope', true)"
    predicate = f"""
        firm_id = {firm_uuid}
        AND (
            ({scope} = 'firm'
                AND ({client_uuid} IS NULL OR client_id = {client_uuid}))
            OR
            ({scope} = 'client' AND client_id = {client_uuid})
        )
    """
    for t in tenant_tables:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS p_isolation ON {t};")
        op.execute(
            f"""
            CREATE POLICY p_isolation ON {t}
                AS PERMISSIVE
                FOR ALL
                TO PUBLIC
                USING ({predicate})
                WITH CHECK ({predicate});
            """
        )

    # ----- Seed catalog --------------------------------------------------- #
    tax_form_tbl = sa.table(
        "tax_form",
        sa.column("id", pg.UUID(as_uuid=True)),
        sa.column("code", pg.ENUM(name="tax_form_code", create_type=False)),
        sa.column("label", sa.String),
        sa.column("jurisdiction", sa.String),
        sa.column("catalog_version", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    tax_form_line_tbl = sa.table(
        "tax_form_line",
        sa.column("id", pg.UUID(as_uuid=True)),
        sa.column("form_id", pg.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("label", sa.String),
        sa.column("section", pg.ENUM(name="tax_form_section", create_type=False)),
        sa.column("sequence", sa.Integer),
        sa.column("description", sa.Text),
    )

    for form in CATALOG:
        form_id = uuid4()
        op.bulk_insert(
            tax_form_tbl,
            [
                {
                    "id": form_id,
                    "code": form.code.value,
                    "label": form.label,
                    "jurisdiction": form.jurisdiction,
                    "catalog_version": CATALOG_VERSION,
                    "is_active": True,
                }
            ],
        )
        op.bulk_insert(
            tax_form_line_tbl,
            [
                {
                    "id": uuid4(),
                    "form_id": form_id,
                    "code": ln.code,
                    "label": ln.label,
                    "section": ln.section.value,
                    "sequence": ln.sequence,
                    "description": ln.description,
                }
                for ln in form.lines
            ],
        )


def downgrade() -> None:
    for t in ("tax_worksheet_line", "tax_worksheet", "tax_account_mapping"):
        op.execute(f"DROP POLICY IF EXISTS p_isolation ON {t};")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY;")

    op.drop_index("ix_tax_ws_line_worksheet_id", table_name="tax_worksheet_line")
    op.drop_table("tax_worksheet_line")

    op.drop_index("ix_tax_ws_status", table_name="tax_worksheet")
    op.drop_index("ix_tax_ws_form_id", table_name="tax_worksheet")
    op.drop_index("ix_tax_ws_period_id", table_name="tax_worksheet")
    op.drop_index("ix_tax_ws_client_id", table_name="tax_worksheet")
    op.drop_index("ix_tax_ws_firm_id", table_name="tax_worksheet")
    op.drop_table("tax_worksheet")

    op.drop_index("ix_tax_map_status", table_name="tax_account_mapping")
    op.drop_index("ix_tax_map_account_id", table_name="tax_account_mapping")
    op.drop_index("ix_tax_map_form_id", table_name="tax_account_mapping")
    op.drop_index("ix_tax_map_client_id", table_name="tax_account_mapping")
    op.drop_index("ix_tax_map_firm_id", table_name="tax_account_mapping")
    op.drop_table("tax_account_mapping")

    op.drop_index("ix_tax_form_line_form_id", table_name="tax_form_line")
    op.drop_table("tax_form_line")
    op.drop_table("tax_form")

    op.execute("DROP TYPE IF EXISTS tax_worksheet_status;")
    op.execute("DROP TYPE IF EXISTS tax_mapping_status;")
    op.execute("DROP TYPE IF EXISTS tax_line_sign;")
    op.execute("DROP TYPE IF EXISTS tax_form_section;")
    op.execute("DROP TYPE IF EXISTS tax_form_code;")
