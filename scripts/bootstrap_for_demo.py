"""Bootstrap script for the ephemeral demo container.

Designed to be run as the API container's startup command in the
`infra/main-demo.bicep` deployment. It is idempotent so it is safe to
run on every container restart and on multi-replica scale-up.

Steps:
  1. Connect to Postgres as ctaa_owner (DATABASE_OWNER_URL).
  2. Create the `app_user` runtime role (or update its password) and grant
     the standard schema privileges so RLS-respecting migrations work.
  3. Run `alembic upgrade head`.
  4. If the `firm` table is empty, seed the demo firm + client.
  5. Print the seeded IDs on lines prefixed with ::SEED_FIRM::, etc.,
     so the deploy script can scrape them from `az containerapp logs show`.

Environment:
  DATABASE_URL        SQLAlchemy URL for the runtime app_user role
  DATABASE_OWNER_URL  SQLAlchemy URL for the admin/owner (ctaa_owner)

Exits 0 on success even if the seed was skipped (idempotent), non-zero
only on hard errors.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from urllib.parse import urlparse, unquote


def _to_psycopg_url(sa_url: str) -> str:
    """Convert a SQLAlchemy psycopg URL to a plain libpq URL."""
    return sa_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _extract_password(database_url: str) -> str:
    """Pull the password out of DATABASE_URL so we can sync it to app_user."""
    parsed = urlparse(_to_psycopg_url(database_url))
    if parsed.password is None:
        raise RuntimeError("DATABASE_URL has no password component")
    return unquote(parsed.password)


def _bootstrap_role(owner_url: str, app_password: str) -> None:
    import psycopg  # local import — only present in the runtime image
    from psycopg import sql

    print("[bootstrap] connecting to PG as owner", flush=True)
    with psycopg.connect(_to_psycopg_url(owner_url), autocommit=True) as cn:
        with cn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", ("app_user",))
            exists = cur.fetchone() is not None
            # CREATE/ALTER ROLE does not allow parameter substitution for the
            # password literal — psycopg.sql.Literal renders a properly-escaped
            # PG string literal in-line.
            pwd_literal = sql.Literal(app_password)
            if exists:
                print("[bootstrap] app_user already exists; syncing password", flush=True)
                # Only the password is altered here. Touching role attributes
                # (NOSUPERUSER, NOBYPASSRLS, …) would require the connecting
                # role to itself be SUPERUSER, which `ctaa_owner` is not on
                # Azure PG Flex. Attributes are set at CREATE time on first
                # boot and are immutable thereafter.
                cur.execute(
                    sql.SQL("ALTER ROLE app_user WITH LOGIN PASSWORD {pwd}").format(pwd=pwd_literal)
                )
            else:
                print("[bootstrap] CREATE ROLE app_user", flush=True)
                cur.execute(
                    sql.SQL(
                        "CREATE ROLE app_user WITH LOGIN PASSWORD {pwd} "
                        "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
                    ).format(pwd=pwd_literal)
                )
            cur.execute("GRANT CONNECT ON DATABASE ctaa TO app_user")
            cur.execute("GRANT USAGE ON SCHEMA public TO app_user")
            # Privileges on tables that already exist (idempotent).
            cur.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user"
            )
            cur.execute(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user"
            )
            # And on tables the migrations will create after this point.
            cur.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user"
            )
            cur.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO app_user"
            )


def _alembic_upgrade() -> None:
    print("[bootstrap] alembic upgrade head", flush=True)
    subprocess.run(["alembic", "upgrade", "head"], check=True, cwd="/app")


def _firm_table_empty(owner_url: str) -> bool:
    import psycopg

    with psycopg.connect(_to_psycopg_url(owner_url), autocommit=True) as cn:
        with cn.cursor() as cur:
            try:
                cur.execute("SELECT count(*) FROM firm")
                row = cur.fetchone()
                return bool(row) and row[0] == 0
            except psycopg.errors.UndefinedTable:
                # Migrations didn't actually create the table — bail loud.
                return False


def _seed_and_print() -> None:
    print("[bootstrap] seeding demo data", flush=True)
    res = subprocess.run(
        [sys.executable, "-m", "scripts.seed_demo"],
        check=True,
        capture_output=True,
        text=True,
        cwd="/app",
    )
    sys.stdout.write(res.stdout)
    sys.stdout.flush()

    firm_m = re.search(r"firm_id\s*=\s*([0-9a-fA-F-]{36})", res.stdout)
    client_m = re.search(r"client_id\s*=\s*([0-9a-fA-F-]{36})", res.stdout)
    period_m = re.search(r"period_id\s*=\s*([0-9a-fA-F-]{36})", res.stdout)

    print(f"::SEED_FIRM::{firm_m.group(1) if firm_m else ''}", flush=True)
    print(f"::SEED_CLIENT::{client_m.group(1) if client_m else ''}", flush=True)
    print(f"::SEED_PERIOD::{period_m.group(1) if period_m else ''}", flush=True)


def _print_existing_firm(owner_url: str) -> None:
    """When the firm already exists, re-emit the IDs so the deploy script
    can still pick them up from a redeploy / restart."""
    import psycopg

    with psycopg.connect(_to_psycopg_url(owner_url), autocommit=True) as cn:
        with cn.cursor() as cur:
            cur.execute(
                "SELECT firm.id AS firm_id, client.id AS client_id "
                "FROM firm LEFT JOIN client ON client.firm_id = firm.id "
                "ORDER BY firm.created_at NULLS LAST LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                firm_id, client_id = row
                print(f"::SEED_FIRM::{firm_id}", flush=True)
                print(f"::SEED_CLIENT::{client_id or ''}", flush=True)
                cur.execute(
                    "SELECT id FROM accounting_period WHERE firm_id = %s LIMIT 1",
                    (firm_id,),
                )
                p = cur.fetchone()
                print(f"::SEED_PERIOD::{p[0] if p else ''}", flush=True)


def main() -> None:
    owner_url = os.environ["DATABASE_OWNER_URL"]
    app_url = os.environ["DATABASE_URL"]
    app_pwd = _extract_password(app_url)

    _bootstrap_role(owner_url, app_pwd)
    _alembic_upgrade()
    if _firm_table_empty(owner_url):
        _seed_and_print()
    else:
        print("[bootstrap] firm table non-empty; skipping seed", flush=True)
        _print_existing_firm(owner_url)

    print("[bootstrap] done", flush=True)


if __name__ == "__main__":
    main()
