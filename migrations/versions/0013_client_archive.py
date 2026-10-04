"""Client archive state.

Clients could be created but never removed, so a mis-typed client stayed in
the list forever. Deleting outright is wrong for a real engagement: record
retention (IRS guidance plus state board rules on workpapers) means a
departed client's books have to survive the end of the engagement.

So archiving is the primary action -- it hides the client and blocks new
postings while keeping every row. Hard delete is handled in the domain layer
and only permitted for a client with no books at all.

Revision ID: 0013_client_archive
Revises: 0012_account_sub_type
Create Date: 2026-08-02
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_client_archive"
down_revision: str | None = "0012_account_sub_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "client",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "client",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The default exists only to backfill existing rows; the application
    # always supplies the value.
    op.alter_column("client", "is_active", server_default=None)

    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'client_archive'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'client_restore'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'client_delete'")


def downgrade() -> None:
    # Enum values are intentionally left in place: Postgres cannot drop a
    # value from an enum type, and audit rows may already reference them.
    op.drop_column("client", "archived_at")
    op.drop_column("client", "is_active")
