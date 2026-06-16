"""Tenant encryption key registry (admin-plane).

Revision ID: 0004_tenant_encryption_keys
Revises: 0003_drafts_and_extraction
Create Date: 2026-06-20

Adds a single admin-only table tracking the lifecycle of per-tenant KEKs:

    tenant_encryption_key (
        firm_id        UUID PRIMARY KEY,
        kek_id         TEXT NOT NULL,         -- KMS-side identifier or 'destroyed'
        status         tenant_kek_status NOT NULL,
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
        destroyed_at   TIMESTAMPTZ NULL,
        destroyed_by   TEXT NULL              -- subject id of admin who destroyed
    )

The table is NOT under RLS — it's admin-plane and is only ever accessed
through the owner connection. Application sessions (under `app_user_test`)
should NOT have read access; we revoke explicitly.

Crypto-shred contract: a row with `status='destroyed'` means the KEK has
been deleted at the KMS. Subsequent unwrap attempts MUST be rejected by
`KeyProvider.unwrap_data_key`.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0004_tenant_encryption_keys"
down_revision: str | None = "0003_drafts_and_extraction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_APP_ROLE_CANDIDATES = ("app_user", "app_user_test")


def upgrade() -> None:
    bind = op.get_bind()

    pg.ENUM(
        "active", "destroyed",
        name="tenant_kek_status",
    ).create(bind, checkfirst=True)

    op.create_table(
        "tenant_encryption_key",
        sa.Column("firm_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("kek_id", sa.Text(), nullable=False),
        sa.Column(
            "status",
            pg.ENUM(
                "active", "destroyed",
                name="tenant_kek_status",
                create_type=False,
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("destroyed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("destroyed_by", sa.Text(), nullable=True),
    )

    # Admin-only: revoke from any app role that exists.
    for role in _APP_ROLE_CANDIDATES:
        op.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                        REVOKE ALL ON TABLE tenant_encryption_key FROM {role};
                    END IF;
                END
                $$;
                """
            )
        )


def downgrade() -> None:
    op.drop_table("tenant_encryption_key")
    bind = op.get_bind()
    pg.ENUM(name="tenant_kek_status").drop(bind, checkfirst=True)
