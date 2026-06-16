"""Document extraction status + draft classification staging.

Revision ID: 0003_drafts_and_extraction
Revises: 0002_audit_append_only
Create Date: 2026-06-15

* Adds `ocr_status`, `ocr_completed_at`, `ocr_error` to `source_document`.
* Adds `idx_src_client_sha256` for ingest idempotency lookups.
* Creates `draft_classification` staging table for AI output. NOTHING in this
  table is ever written automatically to `journal_entry` / `journal_line`. A
  separate `promote_draft()` service uses the LedgerService to create a real
  balanced journal entry on human approval.
* RLS enabled + forced + isolation policy on the new table, identical pattern
  to all other tenant-scoped tables.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0003_drafts_and_extraction"
down_revision: str | None = "0002_audit_append_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_APP_ROLE_CANDIDATES = ("app_user", "app_user_test")


def upgrade() -> None:
    bind = op.get_bind()

    # ----- Enums ----------------------------------------------------------- #
    pg.ENUM(
        "pending", "in_progress", "complete", "failed",
        name="ocr_status",
    ).create(bind, checkfirst=True)
    pg.ENUM(
        "bank_transaction", "tax_form", "invoice", "receipt", "generic",
        name="draft_kind",
    ).create(bind, checkfirst=True)
    pg.ENUM(
        "pending_review", "promoted", "rejected",
        name="draft_status",
    ).create(bind, checkfirst=True)

    # ----- Extend audit_action with phase-2 actions ---------------------- #
    # PostgreSQL ALTER TYPE ... ADD VALUE must run outside a transaction
    # block. Alembic by default runs migrations transactionally, so we
    # execute these via op.execute() and rely on the migration containing
    # ONLY DDL that is OK to combine. ADD VALUE IF NOT EXISTS is idempotent.
    for value in ("ingest", "extract", "classify", "promote", "reject"):
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")

    # ----- source_document additions -------------------------------------- #
    op.add_column(
        "source_document",
        sa.Column(
            "ocr_status",
            pg.ENUM(
                "pending", "in_progress", "complete", "failed",
                name="ocr_status", create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "source_document",
        sa.Column("ocr_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "source_document",
        sa.Column("ocr_error", sa.Text, nullable=True),
    )
    # Used by ingest_document() for idempotency on re-upload of identical bytes.
    op.create_index(
        "ix_src_client_sha256",
        "source_document",
        ["client_id", "sha256"],
    )

    # ----- draft_classification ------------------------------------------- #
    op.create_table(
        "draft_classification",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "source_document_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("source_document.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            pg.ENUM(name="draft_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            pg.ENUM(name="draft_status", create_type=False),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("needs_review", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("high_confidence", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "confidence",
            sa.Numeric(5, 4),
            nullable=False,
        ),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("payload", pg.JSONB, nullable=False),
        sa.Column(
            "promoted_journal_entry_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("journal_entry.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_draft_confidence_range",
        ),
    )
    op.create_index("ix_draft_firm_id", "draft_classification", ["firm_id"])
    op.create_index("ix_draft_client_id", "draft_classification", ["client_id"])
    op.create_index("ix_draft_source_id", "draft_classification", ["source_document_id"])
    op.create_index("ix_draft_status", "draft_classification", ["status"])

    # Grant DML to app role(s) (default privs already cover this in dev, but be explicit).
    for role in _APP_ROLE_CANDIDATES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE
                        ON TABLE draft_classification TO {role};
                END IF;
            END
            $$;
            """
        )

    # ----- RLS on draft_classification ------------------------------------ #
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
    op.execute("ALTER TABLE draft_classification ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE draft_classification FORCE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS p_isolation ON draft_classification;")
    op.execute(
        f"""
        CREATE POLICY p_isolation ON draft_classification
            AS PERMISSIVE
            FOR ALL
            TO PUBLIC
            USING ({predicate})
            WITH CHECK ({predicate});
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS p_isolation ON draft_classification;")
    op.execute("ALTER TABLE draft_classification DISABLE ROW LEVEL SECURITY;")
    op.drop_index("ix_draft_status", table_name="draft_classification")
    op.drop_index("ix_draft_source_id", table_name="draft_classification")
    op.drop_index("ix_draft_client_id", table_name="draft_classification")
    op.drop_index("ix_draft_firm_id", table_name="draft_classification")
    op.drop_table("draft_classification")
    op.drop_index("ix_src_client_sha256", table_name="source_document")
    op.drop_column("source_document", "ocr_error")
    op.drop_column("source_document", "ocr_completed_at")
    op.drop_column("source_document", "ocr_status")
    op.execute("DROP TYPE IF EXISTS draft_status;")
    op.execute("DROP TYPE IF EXISTS draft_kind;")
    op.execute("DROP TYPE IF EXISTS ocr_status;")
