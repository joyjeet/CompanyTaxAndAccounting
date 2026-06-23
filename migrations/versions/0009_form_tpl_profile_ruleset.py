"""Phase 8b: form-template registry + client profile + entity-form ruleset.

Revision ID: 0009_form_template_profile_ruleset
Revises: 0008_coa_hierarchy_and_templates
Create Date: 2026-07-05

Adds the three Phase 8b infrastructure tables:

1. ``form_template`` — reference table (NO RLS, NOT tenant). One row per
   (form_code, tax_year, revision) of an official IRS PDF. Status moves
   DRAFT → ACTIVE → SUPERSEDED on CPA activation; a separate ``verified``
   flag tracks whether the CPA has mapped every AcroForm field in
   ``irs_form_fields.py``. Activation requires verified=True. App role:
   SELECT only. Seeded as DRAFT/unverified for F1120, F1120S, F1065,
   F1040SC, tax_year=2025.

2. ``client_profile`` — tenant table (RLS+FORCE) with the structured
   client profile (entity_type, industry, tax_year, home_state,
   additional_states, fiscal_year_end_month, entity_attributes jsonb).
   1:1 with ``client`` via UNIQUE(client_id). App role: full DML.

3. ``entity_form_ruleset`` — reference table (NO RLS, NOT tenant). One
   row per (entity_type, tax_year, version) carrying the JSON list of
   required tax forms for that entity type. Status moves DRAFT → ACTIVE
   → SUPERSEDED on CPA activation. App role: SELECT only. Seeded as
   DRAFT for every supported EntityType for tax_year=2025; the CPA must
   activate before clients of that entity type can generate worksheets.

Also extends ``audit_action`` with the new Phase 8b actions.

Downgrade: drops the new tables/enums. ``audit_action`` enum values are
not removed (Postgres can't drop enum values).
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0009_form_tpl_profile_ruleset"
down_revision: str | None = "0008_coa_hierarchy_and_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_APP_ROLE_CANDIDATES = ("app_user", "app_user_test")


# Forms shipped with PART B. Seed each as a DRAFT, unverified template
# row for tax_year=2025. CPA must locate the PDF, set the path + sha256,
# verify, then activate.
_SEED_FORMS: tuple[tuple[str, int, str], ...] = (
    # (form_code, tax_year, revision)
    ("F1120",   2025, "2024.01"),  # The IRS publishes ~mid-year for prior tax year.
    ("F1120S",  2025, "2024.01"),
    ("F1065",   2025, "2024.01"),
    ("F1040SC", 2025, "2024.01"),
)

# Each EntityType -> required forms. SCHEDULES are intentionally NOT
# fabricated here as separate codes — they're sub-forms within the parent
# return and the catalog will scaffold them in a CPA-supervised follow-up.
# This minimal seed makes the form-set engine *work* for v1; the CPA
# review doc lists every entity → form pair that requires verification.
_SEED_RULESETS: tuple[tuple[str, int, str, list[str]], ...] = (
    # (entity_type, tax_year, version, required_forms)
    ("c_corp",            2025, "v1", ["F1120"]),
    ("s_corp",            2025, "v1", ["F1120S"]),
    ("partnership",       2025, "v1", ["F1065"]),
    ("single_member_llc", 2025, "v1", ["F1040SC"]),
    ("sole_prop",         2025, "v1", ["F1040SC"]),
)


# --------------------------------------------------------------------------- #
# Upgrade
# --------------------------------------------------------------------------- #
def upgrade() -> None:
    bind = op.get_bind()

    # ----- New enums -------------------------------------------------------- #
    pg.ENUM("draft", "active", "superseded", name="form_template_status").create(
        bind, checkfirst=True
    )
    pg.ENUM(
        "draft", "active", "superseded", name="entity_form_ruleset_status",
    ).create(bind, checkfirst=True)

    # ----- Extend audit_action enum --------------------------------------- #
    for value in (
        "form_template_register",
        "form_template_verify",
        "form_template_activate",
        "client_profile_upsert",
        "entity_form_ruleset_activate",
        "tax_worksheet_reject",
        "tax_worksheet_supersede",
    ):
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")

    # ----- Extend tax_worksheet_status with 'rejected' --------------------- #
    # Reject flow mirrors the mapping-reject lifecycle (DRAFT -> REJECTED).
    op.execute(
        "ALTER TYPE tax_worksheet_status ADD VALUE IF NOT EXISTS 'rejected'"
    )

    # ----- form_template (reference) -------------------------------------- #
    op.create_table(
        "form_template",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "form_code",
            pg.ENUM(name="tax_form_code", create_type=False),
            nullable=False,
        ),
        sa.Column("tax_year", sa.Integer, nullable=False),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.Column(
            "status",
            pg.ENUM(name="form_template_status", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "verified",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("local_template_path", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", sa.String(255), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "form_code", "tax_year", "revision",
            name="uq_form_template_code_year_revision",
        ),
    )
    op.create_index(
        "ix_form_template_code_year_status",
        "form_template",
        ["form_code", "tax_year", "status"],
    )

    # ----- client_profile (tenant, RLS+FORCE) ----------------------------- #
    op.create_table(
        "client_profile",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("firm_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "client_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("client.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column(
            "industry", sa.String(64), nullable=False, server_default="generic"
        ),
        sa.Column("tax_year", sa.Integer, nullable=False),
        sa.Column("home_state", sa.String(2), nullable=True),
        sa.Column("additional_states", pg.JSONB, nullable=True),
        sa.Column(
            "fiscal_year_end_month",
            sa.Integer,
            nullable=False,
            server_default=sa.text("12"),
        ),
        sa.Column("entity_attributes", pg.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("client_id", name="uq_client_profile_client_id"),
    )

    # ----- entity_form_ruleset (reference) -------------------------------- #
    op.create_table(
        "entity_form_ruleset",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("tax_year", sa.Integer, nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column(
            "status",
            pg.ENUM(name="entity_form_ruleset_status", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("required_forms", pg.JSONB, nullable=False),
        sa.Column("notes", sa.String(2048), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "entity_type", "tax_year", "version",
            name="uq_efr_entity_year_version",
        ),
    )
    op.create_index(
        "ix_efr_entity_year_status",
        "entity_form_ruleset",
        ["entity_type", "tax_year", "status"],
    )

    # ----- Grants --------------------------------------------------------- #
    tenant_tables = ("client_profile",)
    reference_tables = ("form_template", "entity_form_ruleset")
    for role in _APP_ROLE_CANDIDATES:
        for t in tenant_tables:
            op.execute(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                        GRANT SELECT, INSERT, UPDATE, DELETE
                            ON TABLE {t} TO {role};
                    END IF;
                END
                $$;
                """
            )
        for t in reference_tables:
            op.execute(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                        GRANT SELECT ON TABLE {t} TO {role};
                    END IF;
                END
                $$;
                """
            )

    # ----- RLS on tenant tables ------------------------------------------ #
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
    for t in tenant_tables:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS p_isolation ON {t};")
        op.execute(
            f"""
            CREATE POLICY p_isolation ON {t}
                AS PERMISSIVE
                FOR ALL
                TO PUBLIC
                USING ({predicate})
                WITH CHECK ({predicate});
            """
        )

    # ----- Seed form_template (DRAFT/unverified) -------------------------- #
    _seed_form_templates(bind)

    # ----- Seed entity_form_ruleset (DRAFT) ------------------------------- #
    _seed_entity_form_rulesets(bind)


# --------------------------------------------------------------------------- #
# Seed helpers
# --------------------------------------------------------------------------- #
def _seed_form_templates(bind: sa.engine.Connection) -> None:  # type: ignore[name-defined]
    """Insert a DRAFT/unverified row per (form_code, tax_year, revision).

    Idempotent on the (form_code, tax_year, revision) uniqueness.
    sha256 reflects the bundled PDF bytes when present; if the file is
    not yet bundled (CPA hasn't sourced it), we register a placeholder
    sha of zeros so the row exists and the CPA can update it during the
    verify step.
    """
    # Lazy import — the irs_form_fields module is the source of truth
    # for where each form's bundled PDF lives.
    from app.domain import irs_form_fields as ff
    from app.models.enums import TaxFormCode

    form_template_tbl = sa.table(
        "form_template",
        sa.column("id", pg.UUID(as_uuid=True)),
        sa.column("form_code", pg.ENUM(name="tax_form_code", create_type=False)),
        sa.column("tax_year", sa.Integer),
        sa.column("revision", sa.String),
        sa.column("status", pg.ENUM(name="form_template_status", create_type=False)),
        sa.column("verified", sa.Boolean),
        sa.column("local_template_path", sa.String),
        sa.column("sha256", sa.String),
    )

    placeholder_sha = "0" * 64

    for form_code_str, tax_year, revision in _SEED_FORMS:
        existing = bind.execute(
            sa.text(
                "SELECT id FROM form_template "
                "WHERE form_code = :form_code "
                "AND tax_year = :tax_year "
                "AND revision = :revision"
            ),
            {
                "form_code": form_code_str,
                "tax_year": tax_year,
                "revision": revision,
            },
        ).first()
        if existing:
            continue
        form_code = TaxFormCode(form_code_str)
        path = ff.template_path(form_code)
        sha = placeholder_sha
        if path.exists():
            sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        bind.execute(
            form_template_tbl.insert().values(
                id=uuid4(),
                form_code=form_code_str,
                tax_year=tax_year,
                revision=revision,
                status="draft",
                verified=False,
                local_template_path=str(path),
                sha256=sha,
            )
        )


def _seed_entity_form_rulesets(bind: sa.engine.Connection) -> None:  # type: ignore[name-defined]
    """Insert a DRAFT row per (entity_type, tax_year, version)."""
    import json as _json

    ruleset_tbl = sa.table(
        "entity_form_ruleset",
        sa.column("id", pg.UUID(as_uuid=True)),
        sa.column("entity_type", sa.String),
        sa.column("tax_year", sa.Integer),
        sa.column("version", sa.String),
        sa.column(
            "status",
            pg.ENUM(name="entity_form_ruleset_status", create_type=False),
        ),
        sa.column("required_forms", pg.JSONB),
        sa.column("notes", sa.String),
    )

    for entity_type, tax_year, version, required_forms in _SEED_RULESETS:
        existing = bind.execute(
            sa.text(
                "SELECT id FROM entity_form_ruleset "
                "WHERE entity_type = :entity_type "
                "AND tax_year = :tax_year "
                "AND version = :version"
            ),
            {
                "entity_type": entity_type,
                "tax_year": tax_year,
                "version": version,
            },
        ).first()
        if existing:
            continue
        bind.execute(
            ruleset_tbl.insert().values(
                id=uuid4(),
                entity_type=entity_type,
                tax_year=tax_year,
                version=version,
                status="draft",
                # Pass the Python list directly; SQLAlchemy's JSONB type
                # serializes it to a real JSON array, not a JSON-string
                # scalar. (Wrapping in json.dumps stores '["F1120"]' as a
                # JSON *string*, which then iterates char-by-char on read.)
                required_forms=required_forms,
                notes=(
                    "Seeded DRAFT by migration 0009. CPA must verify the "
                    "required-forms list against current IRS guidance and "
                    "ACTIVATE before this ruleset gates worksheet generation."
                ),
            )
        )


# --------------------------------------------------------------------------- #
# Downgrade
# --------------------------------------------------------------------------- #
def downgrade() -> None:
    # entity_form_ruleset
    op.drop_index("ix_efr_entity_year_status", table_name="entity_form_ruleset")
    op.drop_table("entity_form_ruleset")

    # client_profile
    op.execute("DROP POLICY IF EXISTS p_isolation ON client_profile;")
    op.drop_table("client_profile")

    # form_template
    op.drop_index("ix_form_template_code_year_status", table_name="form_template")
    op.drop_table("form_template")

    op.execute("DROP TYPE IF EXISTS entity_form_ruleset_status")
    op.execute("DROP TYPE IF EXISTS form_template_status")
    # audit_action enum values stay (Postgres doesn't support drop).
