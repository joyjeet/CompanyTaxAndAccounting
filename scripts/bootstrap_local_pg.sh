#!/usr/bin/env bash
# Bootstrap a LOCAL (non-Docker) Postgres instance for CTAA dev.
#
# Creates the `ctaa` database, the `ctaa_owner` role (used for migrations
# and DDL), and the `app_user` role (the runtime app role — NOSUPERUSER,
# NOBYPASSRLS, so RLS is enforced). Idempotent: re-running is safe.
#
# Expects an already-running local Postgres reachable via the current user
# over Unix socket / TCP, with that user holding CREATEROLE + CREATEDB
# privileges (typically the macOS Homebrew default).
#
# Usage:
#   PG_SUPERUSER=joyjeetm \
#   POSTGRES_DB=ctaa \
#   POSTGRES_OWNER_USER=ctaa_owner POSTGRES_OWNER_PASSWORD=owner_password \
#   POSTGRES_APP_USER=app_user     POSTGRES_APP_PASSWORD=app_password \
#   scripts/bootstrap_local_pg.sh
set -euo pipefail

PG_SUPERUSER="${PG_SUPERUSER:-$USER}"
POSTGRES_DB="${POSTGRES_DB:-ctaa}"
POSTGRES_OWNER_USER="${POSTGRES_OWNER_USER:-ctaa_owner}"
POSTGRES_OWNER_PASSWORD="${POSTGRES_OWNER_PASSWORD:-owner_password}"
POSTGRES_APP_USER="${POSTGRES_APP_USER:-app_user}"
POSTGRES_APP_PASSWORD="${POSTGRES_APP_PASSWORD:-app_password}"

echo "Bootstrapping local Postgres:"
echo "  superuser : $PG_SUPERUSER"
echo "  database  : $POSTGRES_DB"
echo "  owner role: $POSTGRES_OWNER_USER"
echo "  app role  : $POSTGRES_APP_USER"

psql -v ON_ERROR_STOP=1 -U "$PG_SUPERUSER" -d postgres <<EOSQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${POSTGRES_OWNER_USER}') THEN
        CREATE ROLE "${POSTGRES_OWNER_USER}"
            WITH LOGIN PASSWORD '${POSTGRES_OWNER_PASSWORD}' NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${POSTGRES_APP_USER}') THEN
        CREATE ROLE "${POSTGRES_APP_USER}"
            WITH LOGIN PASSWORD '${POSTGRES_APP_PASSWORD}' NOSUPERUSER NOBYPASSRLS;
    END IF;
END
\$\$;
EOSQL

# Create the database if missing, owned by ctaa_owner.
if ! psql -U "$PG_SUPERUSER" -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'" | grep -q 1; then
    psql -v ON_ERROR_STOP=1 -U "$PG_SUPERUSER" -d postgres \
        -c "CREATE DATABASE \"${POSTGRES_DB}\" OWNER \"${POSTGRES_OWNER_USER}\";"
fi

psql -v ON_ERROR_STOP=1 -U "$PG_SUPERUSER" -d postgres <<EOSQL
ALTER DATABASE "${POSTGRES_DB}" OWNER TO "${POSTGRES_OWNER_USER}";
GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO "${POSTGRES_OWNER_USER}";
GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO "${POSTGRES_APP_USER}";
EOSQL

psql -v ON_ERROR_STOP=1 -U "$PG_SUPERUSER" -d "$POSTGRES_DB" <<EOSQL
GRANT USAGE ON SCHEMA public TO "${POSTGRES_APP_USER}";
GRANT CREATE ON SCHEMA public TO "${POSTGRES_OWNER_USER}";

-- Future tables created by the owner are accessible to the app role.
ALTER DEFAULT PRIVILEGES FOR ROLE "${POSTGRES_OWNER_USER}" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "${POSTGRES_APP_USER}";
ALTER DEFAULT PRIVILEGES FOR ROLE "${POSTGRES_OWNER_USER}" IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO "${POSTGRES_APP_USER}";
EOSQL

echo "Local Postgres ready: database '${POSTGRES_DB}' owned by '${POSTGRES_OWNER_USER}', runtime role '${POSTGRES_APP_USER}'."
