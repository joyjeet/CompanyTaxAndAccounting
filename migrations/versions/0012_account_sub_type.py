"""Explicit reporting sub-type on COA rows and template nodes.

Statement layout used to be inferred from numeric code ranges in
`app/domain/presentation.py`. Those ranges disagreed with the shipped
general template, which pushed every operating expense (6xxx-9xxx) below
the operating-income line and left the Operating Expenses section empty.

This adds `sub_type` as explicit data on both `chart_of_accounts` and
`coa_template_node`, and backfills existing rows using the code ranges of
the shipped chart so no client's reports change shape unexpectedly.

Revision ID: 0012_account_sub_type
Revises: 0011_team_membership
Create Date: 2026-08-02
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_account_sub_type"
down_revision: str | None = "0011_team_membership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Backfill expression shared by both tables. Only applies to codes that are
# purely numeric; anything else falls back to the account_type default.
_BACKFILL = """
    UPDATE {table} SET sub_type = CASE
        WHEN account_type = 'equity' THEN 'equity'
        WHEN account_type = 'asset' THEN CASE
            WHEN code ~ '^[0-9]+$' AND code::int BETWEEN 1500 AND 1699 THEN 'fixed_asset'
            WHEN code ~ '^[0-9]+$' AND code::int BETWEEN 1700 AND 1899 THEN 'intangible_asset'
            WHEN code ~ '^[0-9]+$' AND code::int >= 1900 THEN 'other_asset'
            ELSE 'current_asset'
        END
        WHEN account_type = 'liability' THEN CASE
            WHEN code ~ '^[0-9]+$' AND code::int >= 2500 THEN 'long_term_liability'
            ELSE 'current_liability'
        END
        WHEN account_type = 'revenue' THEN CASE
            WHEN code ~ '^[0-9]+$' AND code::int BETWEEN 4500 AND 4999 THEN 'other_income'
            ELSE 'operating_revenue'
        END
        WHEN account_type = 'expense' THEN CASE
            WHEN code ~ '^[0-9]+$' AND code::int BETWEEN 5000 AND 5999 THEN 'cogs'
            WHEN code ~ '^[0-9]+$' AND code::int BETWEEN 9100 AND 9499 THEN 'other_expense'
            WHEN code ~ '^[0-9]+$' AND code::int BETWEEN 9500 AND 9899 THEN 'income_tax'
            ELSE 'operating_expense'
        END
    END
    WHERE sub_type IS NULL
"""


def upgrade() -> None:
    for table in ("chart_of_accounts", "coa_template_node"):
        op.add_column(table, sa.Column("sub_type", sa.String(32), nullable=True))
        op.execute(_BACKFILL.format(table=table))

    op.create_index(
        "ix_coa_client_sub_type",
        "chart_of_accounts",
        ["client_id", "sub_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_coa_client_sub_type", table_name="chart_of_accounts")
    for table in ("chart_of_accounts", "coa_template_node"):
        op.drop_column(table, "sub_type")
