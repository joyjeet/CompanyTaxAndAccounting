"""Membership-backed authorization.

Adds the pieces needed to stop trusting `firm_id` / `client_id` / `roles`
claims in the token and resolve them from our own tables instead:

1. `firm_membership.client_id` — a client-portal member belongs to exactly one
   client. Staff roles have no client_id. Enforced by a CHECK constraint.

2. A `p_self_read` RLS policy on `firm_membership`, keyed on a new
   `app.current_subject` GUC.

   Why this is needed: `firm_membership` is FORCE ROW LEVEL SECURITY with a
   policy keyed on `app.current_firm`. Resolving a login is a chicken-and-egg
   problem — we cannot set `app.current_firm` until we know which firm the
   user belongs to, and we cannot read the membership row to find out without
   it. FORCE means even the table owner is filtered, so there is no
   privileged-connection escape hatch either.

   The new policy is PERMISSIVE and SELECT-only, so it ORs with the existing
   isolation policy and widens read access by exactly one thing: you may see
   your own membership rows. Writes still require firm scope.

Revision ID: 0015_membership_authz
Revises: 0014_activate_coa_templates
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0015_membership_authz"
down_revision = "0014_activate_coa_templates"
branch_labels = None
depends_on = None

# NULLIF so that an unset GUC (empty string) never matches a real row.
_SUBJECT = "NULLIF(current_setting('app.current_subject', true), '')"

_SELF_READ = f"""
CREATE POLICY p_self_read ON firm_membership
    AS PERMISSIVE
    FOR SELECT
    TO PUBLIC
    USING (
        user_id IN (
            SELECT id FROM user_account
            WHERE subject = {_SUBJECT}
        )
    );
"""


def upgrade() -> None:
    op.add_column(
        "firm_membership",
        sa.Column("client_id", PGUUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_firm_membership_client_id", "firm_membership", ["client_id"]
    )

    # A client_portal membership without a client_id is unusable — it can never
    # resolve to a tenant context. None should exist (client_id did not exist
    # until now), but the team API does accept the full StaffRole enum, so
    # demote any stragglers rather than fail the migration or delete the row.
    op.execute(
        """
        UPDATE firm_membership
           SET role = 'read_only', status = 'disabled'
         WHERE role::text = 'client_portal' AND client_id IS NULL;
        """
    )

    op.create_check_constraint(
        "ck_firm_membership_client_scope",
        "firm_membership",
        "(role::text = 'client_portal') = (client_id IS NOT NULL)",
    )

    op.execute("DROP POLICY IF EXISTS p_self_read ON firm_membership;")
    op.execute(_SELF_READ)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS p_self_read ON firm_membership;")
    op.drop_constraint(
        "ck_firm_membership_client_scope", "firm_membership", type_="check"
    )
    op.drop_index("ix_firm_membership_client_id", table_name="firm_membership")
    op.drop_column("firm_membership", "client_id")
