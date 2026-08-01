"""Phase 11: firm team membership + invites.

Revision ID: 0011_team_membership
Revises: 0010_client_profile_contact
Create Date: 2026-07-18
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0011_team_membership"
down_revision: str | None = "0010_client_profile_contact"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'staff_role') THEN
                CREATE TYPE staff_role AS ENUM (
                    'firm_owner', 'firm_admin', 'manager', 'staff', 'read_only', 'client_portal'
                );
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'membership_status') THEN
                CREATE TYPE membership_status AS ENUM ('active', 'disabled');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'invite_status') THEN
                CREATE TYPE invite_status AS ENUM ('pending', 'accepted', 'canceled', 'expired');
            END IF;
        END
        $$;
        """
    )

    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'user_invite_create'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'user_invite_cancel'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'user_invite_accept'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'user_role_update'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'user_status_update'")

    staff_role_col = postgresql.ENUM(
        "firm_owner",
        "firm_admin",
        "manager",
        "staff",
        "read_only",
        "client_portal",
        name="staff_role",
        create_type=False,
    )
    membership_status_col = postgresql.ENUM(
        "active",
        "disabled",
        name="membership_status",
        create_type=False,
    )
    invite_status_col = postgresql.ENUM(
        "pending",
        "accepted",
        "canceled",
        "expired",
        name="invite_status",
        create_type=False,
    )

    op.create_table(
        "user_account",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject", name="uq_user_account_subject"),
        sa.UniqueConstraint("email", name="uq_user_account_email"),
    )

    op.create_table(
        "firm_membership",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("firm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", staff_role_col, nullable=False),
        sa.Column("status", membership_status_col, server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["firm_id"], ["firm.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("firm_id", "user_id", name="uq_firm_membership_firm_user"),
    )
    op.create_index("ix_firm_membership_firm_id", "firm_membership", ["firm_id"])
    op.create_index("ix_firm_membership_user_id", "firm_membership", ["user_id"])
    op.create_index("ix_firm_membership_status", "firm_membership", ["status"])

    op.create_table(
        "firm_invite",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("firm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", staff_role_col, nullable=False),
        sa.Column("status", invite_status_col, server_default="pending", nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["firm_id"], ["firm.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["user_account.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_firm_invite_firm_id", "firm_invite", ["firm_id"])
    op.create_index("ix_firm_invite_status", "firm_invite", ["status"])
    op.create_index("ix_firm_invite_email", "firm_invite", ["email"])

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON user_account TO app_user;
                GRANT SELECT, INSERT, UPDATE, DELETE ON firm_membership TO app_user;
                GRANT SELECT, INSERT, UPDATE, DELETE ON firm_invite TO app_user;
            END IF;
        END
        $$;
        """
    )

    firm_uuid = "NULLIF(current_setting('app.current_firm', true), '')::uuid"

    for table in ("firm_membership", "firm_invite"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS p_isolation ON {table};")
        op.execute(
            f"""
            CREATE POLICY p_isolation ON {table}
                AS PERMISSIVE
                FOR ALL
                TO PUBLIC
                USING (firm_id = {firm_uuid})
                WITH CHECK (firm_id = {firm_uuid});
            """
        )


def downgrade() -> None:
    for table in ("firm_invite", "firm_membership"):
        op.execute(f"DROP POLICY IF EXISTS p_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_index("ix_firm_invite_email", table_name="firm_invite")
    op.drop_index("ix_firm_invite_status", table_name="firm_invite")
    op.drop_index("ix_firm_invite_firm_id", table_name="firm_invite")
    op.drop_table("firm_invite")

    op.drop_index("ix_firm_membership_status", table_name="firm_membership")
    op.drop_index("ix_firm_membership_user_id", table_name="firm_membership")
    op.drop_index("ix_firm_membership_firm_id", table_name="firm_membership")
    op.drop_table("firm_membership")

    op.drop_table("user_account")

    op.execute("DROP TYPE IF EXISTS invite_status")
    op.execute("DROP TYPE IF EXISTS membership_status")
    op.execute("DROP TYPE IF EXISTS staff_role")
