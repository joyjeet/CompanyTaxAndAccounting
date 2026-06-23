"""Phase 8c: client profile — contact/address fields + nullable tax fields.

Revision ID: 0010_client_profile_contact
Revises: 0009_form_tpl_profile_ruleset
Create Date: 2026-06-22

Two changes to ``client_profile``:

1. **Add contact / address columns** so a client (or their firm) can
   maintain the business's identity and reachability in one place:
     - business_legal_name, dba_name, ein
     - phone, email, website
     - address_line1, address_line2, city, address_state, postal_code,
       country (default "US")

2. **Relax ``entity_type`` and ``tax_year`` to nullable.** Until this
   migration, those two were required, which meant only firm staff could
   ever create a profile row. With this migration, a client portal user
   can save their contact info first — the firm fills in (or confirms)
   the tax-side fields later. The form-set engine already fails closed
   when ``entity_type`` is missing, so this change is backward-safe.

The unique-on-client_id constraint, RLS policy, FK to ``client``, and
all column types except the two nullability changes are untouched.

Downgrade: drops the new columns and restores NOT NULL on
``entity_type`` / ``tax_year`` (will fail if any row currently has
NULLs — operator must backfill first).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0010_client_profile_contact"
down_revision: str | None = "0009_form_tpl_profile_ruleset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ----- 1. Add contact / address columns ------------------------------- #
    op.add_column(
        "client_profile",
        sa.Column("business_legal_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "client_profile",
        sa.Column("dba_name", sa.String(255), nullable=True),
    )
    op.add_column(
        "client_profile",
        # EIN is "XX-XXXXXXX" — 10 chars including the hyphen. Allow 32 for
        # international tax IDs in the future.
        sa.Column("ein", sa.String(32), nullable=True),
    )
    op.add_column(
        "client_profile",
        sa.Column("phone", sa.String(64), nullable=True),
    )
    op.add_column(
        "client_profile",
        sa.Column("email", sa.String(255), nullable=True),
    )
    op.add_column(
        "client_profile",
        sa.Column("website", sa.String(512), nullable=True),
    )
    op.add_column(
        "client_profile",
        sa.Column("address_line1", sa.String(255), nullable=True),
    )
    op.add_column(
        "client_profile",
        sa.Column("address_line2", sa.String(255), nullable=True),
    )
    op.add_column(
        "client_profile",
        sa.Column("city", sa.String(128), nullable=True),
    )
    op.add_column(
        "client_profile",
        # Use a separate column from `home_state` so we can distinguish
        # mailing address vs tax home (sometimes different — e.g. a
        # multi-state firm with HQ in Delaware but operations in CA).
        sa.Column("address_state", sa.String(2), nullable=True),
    )
    op.add_column(
        "client_profile",
        sa.Column("postal_code", sa.String(16), nullable=True),
    )
    op.add_column(
        "client_profile",
        sa.Column(
            "country", sa.String(2), nullable=False, server_default="US"
        ),
    )

    # ----- 2. Relax NOT NULL on entity_type + tax_year -------------------- #
    op.alter_column("client_profile", "entity_type", nullable=True)
    op.alter_column("client_profile", "tax_year", nullable=True)


def downgrade() -> None:
    # Drop new columns first, then restore NOT NULL on the tax fields.
    for col in (
        "country",
        "postal_code",
        "address_state",
        "city",
        "address_line2",
        "address_line1",
        "website",
        "email",
        "phone",
        "ein",
        "dba_name",
        "business_legal_name",
    ):
        op.drop_column("client_profile", col)

    op.alter_column("client_profile", "tax_year", nullable=False)
    op.alter_column("client_profile", "entity_type", nullable=False)
