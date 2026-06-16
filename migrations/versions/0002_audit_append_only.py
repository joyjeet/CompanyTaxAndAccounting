"""Audit append-only at the database layer.

Revision ID: 0002_audit_append_only
Revises: 0001_initial
Create Date: 2026-06-15

REVOKE UPDATE, DELETE on `audit_event` from `app_user` so no application-level
mutation can alter or remove an audit row. INSERT and SELECT remain. The
migration is idempotent against environments that don't have the role
(e.g. a fresh dev DB without the bootstrap script).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_audit_append_only"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# We accept any role name in the conventional set so the same migration works
# in dev (`app_user_test`) and in production (`app_user`). The owner identifies
# itself via the env var POSTGRES_APP_USER but at migration time we don't have
# that, so we apply to all candidates that exist.
_APP_ROLE_CANDIDATES = ("app_user", "app_user_test")


def upgrade() -> None:
    for role in _APP_ROLE_CANDIDATES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                    REVOKE UPDATE, DELETE ON TABLE audit_event FROM {role};
                END IF;
            END
            $$;
            """
        )

    # Default privileges: any future re-grants from the owner must NOT include
    # UPDATE / DELETE on audit_event. Future tables in general still get all
    # DML rights (the rule in 0001_initial); we only constrain audit_event.
    # We can't easily target "future ALTER on audit_event" so we rely on the
    # explicit REVOKE above plus convention; future-proofing would require an
    # event trigger.


def downgrade() -> None:
    for role in _APP_ROLE_CANDIDATES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                    GRANT UPDATE, DELETE ON TABLE audit_event TO {role};
                END IF;
            END
            $$;
            """
        )
