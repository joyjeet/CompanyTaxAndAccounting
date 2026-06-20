"""Output layer: generated_artifact + extended audit_action enum.

Revision ID: 0006_generated_artifact
Revises: 0005_tax_module
Create Date: 2026-06-20

Adds the artifact registry that backs every polished output the platform
produces (PDF/XLSX statements, narratives, tax-worksheet renders, and the
zipped audit-ready package). Artifact bodies always live in the tenant blob
store via the encrypted-storage wrapper; this table only carries the metadata
plus a `plaintext_sha256` so a reader can verify the decrypted body matches.

The DRAFT -> FINALIZED -> SUPERSEDED lifecycle is enforced in
`app/domain/artifact_service.py`; FINALIZED artifacts are immutable and are
the only ones a portal user can see / download / be bundled into a package.

Also extends `audit_action` with the new actions emitted by the output layer:
  * artifact_generate
  * artifact_finalize
  * artifact_download
  * audit_package_generate
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0006_generated_artifact"
down_revision: str | None = "0005_tax_module"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_APP_ROLE_CANDIDATES = ("app_user", "app_user_test")


def upgrade() -> None:
    bind = op.get_bind()

    # ----- Enums ---------------------------------------------------------- #
    pg.ENUM(
        "profit_and_loss", "balance_sheet", "cash_flow",
        "tax_worksheet", "narrative", "audit_package",
        name="artifact_kind",
    ).create(bind, checkfirst=True)
    pg.ENUM(
        "pdf", "xlsx", "zip", "json", "markdown",
        name="artifact_format",
    ).create(bind, checkfirst=True)
    pg.ENUM(
        "draft", "finalized", "superseded",
        name="artifact_status",
    ).create(bind, checkfirst=True)

    # ----- Extend audit_action ------------------------------------------- #
    for value in (
        "artifact_generate",
        "artifact_finalize",
        "artifact_download",
        "audit_package_generate",
    ):
        op.execute(
            f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'"
        )

    # ----- generated_artifact (TENANT) ----------------------------------- #
    op.create_table(
        "generated_artifact",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "period_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("accounting_period.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "tax_worksheet_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tax_worksheet.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "kind",
            pg.ENUM(name="artifact_kind", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "format",
            pg.ENUM(name="artifact_format", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "status",
            pg.ENUM(name="artifact_status", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("storage_uri", sa.String(1024), nullable=False),
        sa.Column("encrypted_sha256", sa.String(64), nullable=False),
        sa.Column("plaintext_sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column(
            "parameters",
            pg.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("generated_by", sa.String(255), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finalized_by", sa.String(255), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "supersedes_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("generated_artifact.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_artifact_firm_id", "generated_artifact", ["firm_id"])
    op.create_index("ix_artifact_client_id", "generated_artifact", ["client_id"])
    op.create_index("ix_artifact_period_id", "generated_artifact", ["period_id"])
    op.create_index(
        "ix_artifact_kind_status", "generated_artifact", ["kind", "status"],
    )

    # ----- Grants --------------------------------------------------------- #
    for role in _APP_ROLE_CANDIDATES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE
                        ON TABLE generated_artifact TO {role};
                END IF;
            END
            $$;
            """
        )

    # ----- RLS ------------------------------------------------------------ #
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
    op.execute("ALTER TABLE generated_artifact ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE generated_artifact FORCE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS p_isolation ON generated_artifact;")
    op.execute(
        f"""
        CREATE POLICY p_isolation ON generated_artifact
            AS PERMISSIVE
            FOR ALL
            TO PUBLIC
            USING ({predicate})
            WITH CHECK ({predicate});
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS p_isolation ON generated_artifact;")
    op.execute("ALTER TABLE generated_artifact DISABLE ROW LEVEL SECURITY;")
    op.drop_index("ix_artifact_kind_status", table_name="generated_artifact")
    op.drop_index("ix_artifact_period_id", table_name="generated_artifact")
    op.drop_index("ix_artifact_client_id", table_name="generated_artifact")
    op.drop_index("ix_artifact_firm_id", table_name="generated_artifact")
    op.drop_table("generated_artifact")
    # Enums are retained — Postgres does not allow safe removal of enum values.
