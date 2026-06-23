"""Phase 8a: hierarchical COA + versioned COA templates (general + overlays).

Revision ID: 0008_coa_hierarchy_and_templates
Revises: 0007_audit_admin_actions
Create Date: 2026-06-22

This revision does three things:

1. Extends `chart_of_accounts` with the hierarchy + template-lineage
   columns: `parent_account_id`, `path`, `depth`, `is_leaf`,
   `template_node_id`, `origin`. Back-fills existing flat rows so they
   become roots with `path = code`.

2. Creates two reference-only (NON-tenant, NO RLS) tables:
     * `coa_template`       — versioned template registry
     * `coa_template_node`  — nodes within one template version
   App role gets SELECT only on these; activation flips status via the
   migration-owner connection through the domain service (no direct
   DML via the app role).

3. Seeds the bundled COA template data from `app/data/coa_templates/`
   as `status=draft`. **CPA must explicitly ACTIVATE** before a client
   can be onboarded with that template version. The seed is idempotent
   on (key, version).

4. Extends `audit_action` enum with the new Phase-8 actions
   (coa_template_activate, coa_template_instantiate,
   coa_account_rename, coa_account_deactivate).

Downgrade: drops the new tables/columns; the audit_action enum values
are NOT removed (Postgres can't drop enum values).
"""
from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0008_coa_hierarchy_and_templates"
down_revision: str | None = "0007_audit_admin_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_APP_ROLE_CANDIDATES = ("app_user", "app_user_test")


# --------------------------------------------------------------------------- #
# Upgrade
# --------------------------------------------------------------------------- #
def upgrade() -> None:
    bind = op.get_bind()

    # ----- New enums -------------------------------------------------------- #
    pg.ENUM("general", "industry_overlay", name="coa_template_kind").create(
        bind, checkfirst=True
    )
    pg.ENUM("draft", "active", "superseded", name="coa_template_status").create(
        bind, checkfirst=True
    )
    pg.ENUM("general", "industry_overlay", "custom", name="coa_node_origin").create(
        bind, checkfirst=True
    )

    # ----- Extend audit_action enum (must run outside DDL txn block) ------ #
    for value in (
        "coa_template_activate",
        "coa_template_instantiate",
        "coa_account_rename",
        "coa_account_deactivate",
    ):
        op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")

    # ----- chart_of_accounts hierarchy columns ---------------------------- #
    op.add_column(
        "chart_of_accounts",
        sa.Column(
            "parent_account_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "chart_of_accounts",
        sa.Column("path", sa.String(1024), nullable=False, server_default=""),
    )
    op.add_column(
        "chart_of_accounts",
        sa.Column(
            "depth", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "chart_of_accounts",
        sa.Column(
            "is_leaf", sa.Boolean, nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "chart_of_accounts",
        sa.Column("template_node_id", pg.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "chart_of_accounts",
        sa.Column(
            "origin",
            pg.ENUM(name="coa_node_origin", create_type=False),
            nullable=False,
            server_default="custom",
        ),
    )
    op.create_index(
        "ix_coa_parent_account_id", "chart_of_accounts", ["parent_account_id"]
    )

    # Back-fill: every pre-existing flat account becomes a root whose path
    # is its own code (so subtree-prefix queries still work).
    op.execute(
        "UPDATE chart_of_accounts SET path = code WHERE path = '' OR path IS NULL"
    )

    # ----- coa_template (reference) --------------------------------------- #
    op.create_table(
        "coa_template",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column(
            "kind",
            pg.ENUM(name="coa_template_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("industry", sa.String(64), nullable=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column(
            "status",
            pg.ENUM(name="coa_template_status", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("key", "version", name="uq_coa_template_key_version"),
    )
    op.create_index("ix_coa_template_key", "coa_template", ["key"])
    op.create_index("ix_coa_template_status", "coa_template", ["status"])

    # ----- coa_template_node (reference) ---------------------------------- #
    op.create_table(
        "coa_template_node",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "template_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("coa_template.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "account_type",
            pg.ENUM(name="account_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "normal_balance",
            pg.ENUM(name="normal_balance", create_type=False),
            nullable=False,
        ),
        sa.Column("parent_code", sa.String(32), nullable=True),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("depth", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "is_leaf", sa.Boolean, nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "sort_order", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("template_id", "code", name="uq_coa_node_template_code"),
    )
    op.create_index("ix_coa_node_template_id", "coa_template_node", ["template_id"])
    op.create_index(
        "ix_coa_node_parent_code", "coa_template_node", ["template_id", "parent_code"]
    )

    # ----- FK from chart_of_accounts.template_node_id (after node table) -- #
    op.create_foreign_key(
        "fk_coa_template_node_id",
        "chart_of_accounts",
        "coa_template_node",
        ["template_node_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ----- Grants --------------------------------------------------------- #
    reference_tables = ("coa_template", "coa_template_node")
    for role in _APP_ROLE_CANDIDATES:
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

    # ----- Seed COA templates as DRAFT ------------------------------------ #
    # Done in a deferred Python function so we can build the materialized
    # paths from the parent_code linkage at seed time.
    _seed_templates(bind)


# --------------------------------------------------------------------------- #
# Seed helper
# --------------------------------------------------------------------------- #
def _seed_templates(bind: sa.engine.Connection) -> None:  # type: ignore[name-defined]
    """Insert (or skip) each bundled template + nodes as DRAFT.

    Idempotent on the `(key, version)` uniqueness. Existing rows are left
    untouched — re-running the migration cannot demote an already-ACTIVE
    template back to DRAFT.
    """
    # Lazy import so migration is importable in environments where the app
    # isn't fully installed (e.g. fresh alembic upgrade in CI).
    from app.data.coa_templates import ALL_TEMPLATES

    template_tbl = sa.table(
        "coa_template",
        sa.column("id", pg.UUID(as_uuid=True)),
        sa.column("key", sa.String),
        sa.column("display_name", sa.String),
        sa.column("kind", pg.ENUM(name="coa_template_kind", create_type=False)),
        sa.column("industry", sa.String),
        sa.column("version", sa.String),
        sa.column("status", pg.ENUM(name="coa_template_status", create_type=False)),
    )
    node_tbl = sa.table(
        "coa_template_node",
        sa.column("id", pg.UUID(as_uuid=True)),
        sa.column("template_id", pg.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("account_type", pg.ENUM(name="account_type", create_type=False)),
        sa.column(
            "normal_balance", pg.ENUM(name="normal_balance", create_type=False)
        ),
        sa.column("parent_code", sa.String),
        sa.column("path", sa.String),
        sa.column("depth", sa.Integer),
        sa.column("is_leaf", sa.Boolean),
        sa.column("sort_order", sa.Integer),
    )

    for tpl in ALL_TEMPLATES:
        existing = bind.execute(
            sa.text(
                "SELECT id FROM coa_template "
                "WHERE key = :key AND version = :version"
            ),
            {"key": tpl["key"], "version": tpl["version"]},
        ).first()
        if existing:
            continue
        tpl_id = uuid4()
        bind.execute(
            template_tbl.insert().values(
                id=tpl_id,
                key=tpl["key"],
                display_name=tpl["display_name"],
                kind=tpl["kind"].value,
                industry=tpl["industry"].value if tpl["industry"] else None,
                version=tpl["version"],
                status="draft",
            )
        )

        # Build (path, depth, is_leaf) from parent_code linkage. For an
        # overlay, an unknown parent_code is assumed to point at a general
        # node and is stored as-is (depth=1, path=parent_code>code) so the
        # node still surfaces meaningfully even before merge at
        # instantiation time. The instantiation service does the real
        # parent resolution against the client's COA tree.
        by_code: dict[str, dict] = {n["code"]: n for n in tpl["nodes"]}
        has_child: set[str] = set()
        for n in tpl["nodes"]:
            if n["parent_code"]:
                has_child.add(n["parent_code"])

        def _path_for(code: str) -> tuple[str, int]:
            steps: list[str] = []
            cur = code
            # Guard against accidental cycles.
            for _ in range(20):
                steps.append(cur)
                parent = by_code.get(cur, {}).get("parent_code")
                if not parent or parent not in by_code:
                    if parent:
                        # External parent (overlay attaches to general)
                        steps.append(parent)
                    break
                cur = parent
            steps.reverse()
            return ">".join(steps), len(steps) - 1

        from app.models.enums import NORMAL_BALANCE_FOR

        for n in tpl["nodes"]:
            path, depth = _path_for(n["code"])
            bind.execute(
                node_tbl.insert().values(
                    id=uuid4(),
                    template_id=tpl_id,
                    code=n["code"],
                    name=n["name"],
                    account_type=n["account_type"].value,
                    normal_balance=NORMAL_BALANCE_FOR[n["account_type"]].value,
                    parent_code=n["parent_code"],
                    path=path,
                    depth=depth,
                    is_leaf=(n["code"] not in has_child),
                    sort_order=n["sort_order"],
                )
            )


# --------------------------------------------------------------------------- #
# Downgrade
# --------------------------------------------------------------------------- #
def downgrade() -> None:
    op.drop_constraint(
        "fk_coa_template_node_id", "chart_of_accounts", type_="foreignkey"
    )
    op.drop_index("ix_coa_node_parent_code", table_name="coa_template_node")
    op.drop_index("ix_coa_node_template_id", table_name="coa_template_node")
    op.drop_table("coa_template_node")
    op.drop_index("ix_coa_template_status", table_name="coa_template")
    op.drop_index("ix_coa_template_key", table_name="coa_template")
    op.drop_table("coa_template")

    op.drop_index("ix_coa_parent_account_id", table_name="chart_of_accounts")
    op.drop_column("chart_of_accounts", "origin")
    op.drop_column("chart_of_accounts", "template_node_id")
    op.drop_column("chart_of_accounts", "is_leaf")
    op.drop_column("chart_of_accounts", "depth")
    op.drop_column("chart_of_accounts", "path")
    op.drop_column("chart_of_accounts", "parent_account_id")

    # Best-effort enum cleanup — only safe if no other objects reference it.
    op.execute("DROP TYPE IF EXISTS coa_node_origin")
    op.execute("DROP TYPE IF EXISTS coa_template_status")
    op.execute("DROP TYPE IF EXISTS coa_template_kind")
    # audit_action enum values stay (Postgres doesn't support drop).
