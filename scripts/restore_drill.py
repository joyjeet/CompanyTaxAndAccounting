"""Restore-drill verification script.

Runs against a freshly-restored Postgres server (see
`docs/runbooks/restore_drill.md`). Exits non-zero on any failure.

Verifies:
  1. TLS-enforced connection (sslmode=require) works.
  2. The restored database's alembic head matches the repo's head.
  3. RLS is intact: as the app role with a random firm GUC, every
     tenant-scoped table returns zero rows.

This script is intentionally read-only against the restored DB except for
the SET LOCAL GUC statements (which are transaction-scoped and roll back).
"""
from __future__ import annotations

import os
import sys
from uuid import uuid4

from sqlalchemy import create_engine, text

TENANT_TABLES = (
    "journal_entry",
    "journal_line",
    "source_document",
    "draft_classification",
    "tax_form",
    "tax_worksheet",
    "generated_artifact",
)


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    url = os.environ.get("DRILL_DATABASE_URL")
    if not url:
        _fail("DRILL_DATABASE_URL not set")
    if "sslmode=require" not in url:  # type: ignore[operator]
        _fail("DRILL_DATABASE_URL must contain sslmode=require")

    app_url = os.environ.get("DRILL_APP_DATABASE_URL", url)

    repo_head_path = os.path.join("migrations", "versions")
    if not os.path.isdir(repo_head_path):
        _fail(f"expected {repo_head_path} to exist; run from repo root")

    # Determine the repo's alembic head by reading the latest revision file.
    # We avoid calling alembic CLI to keep this script side-effect free.
    revs = []
    for fn in os.listdir(repo_head_path):
        if fn.endswith(".py") and not fn.startswith("_"):
            revs.append(fn.split("_", 1)[0])
    revs.sort()
    if not revs:
        _fail("no migration revisions found in repo")
    repo_head = revs[-1]
    print(f"Repo alembic head: {repo_head}")

    # 1) Connect with TLS
    engine = create_engine(url, future=True)  # type: ignore[arg-type]
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
        if row is None:
            _fail("alembic_version table is empty in the restored DB")
        db_head = row[0]
        print(f"Restored DB alembic head: {db_head}")
        if not db_head.startswith(repo_head):
            _fail(f"alembic head mismatch: db={db_head} repo={repo_head}")

    # 2) Row counts as quick sanity (read-only, no GUC).
    print("\nRow counts (owner role, no RLS):")
    with engine.connect() as conn:
        for tbl in TENANT_TABLES:
            try:
                n = conn.execute(text(f"SELECT count(*) FROM {tbl}")).scalar()
                print(f"  {tbl:30s} {n}")
            except Exception as e:
                print(f"  {tbl:30s} ERROR {type(e).__name__}: {e}")

    # 3) RLS probe as app role with a random firm GUC — must see 0 rows.
    app_engine = create_engine(app_url, future=True)  # type: ignore[arg-type]
    random_firm = str(uuid4())
    print(f"\nRLS probe: app role + random firm_id={random_firm}")
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_firm', :v, true)"), {"v": random_firm})
        conn.execute(text("SELECT set_config('app.access_scope', 'firm', true)"))
        bad: list[str] = []
        for tbl in TENANT_TABLES:
            n = conn.execute(text(f"SELECT count(*) FROM {tbl}")).scalar()
            if n != 0:
                bad.append(f"{tbl}={n}")
        if bad:
            _fail(
                "RLS probe returned rows for a random firm — RLS may be broken: "
                + ", ".join(bad)
            )
    print("\nRESTORE DRILL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
