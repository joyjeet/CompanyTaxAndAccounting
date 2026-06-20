"""Phase 7: extend audit_action with administrative + compliance actions.

Revision ID: 0007_audit_admin_actions
Revises: 0006_generated_artifact
Create Date: 2026-09-01

Adds:
  * tenant_keys_destroy  — emitted by the crypto-shred admin endpoint.
  * audit_export          — emitted by the audit-export endpoint each time
    a firm-admin pulls their tenant-scoped audit log.

Postgres' ALTER TYPE … ADD VALUE cannot run inside a transaction block, so
this revision uses `op.execute()` directly with `IF NOT EXISTS` for
idempotency. There is no schema-level downgrade for enum-value removal in
Postgres; the downgrade is intentionally a no-op.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_audit_admin_actions"
down_revision: str | None = "0006_generated_artifact"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for value in ("tenant_keys_destroy", "audit_export"):
        op.execute(
            f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    # Postgres does not support removing enum values. Intentional no-op.
    pass
