# Postgres Restore Drill Runbook

**Purpose:** Verify, on a recurring schedule, that the production Postgres
backups are recoverable, that the schema/migration head matches what the
running app expects, and that tenant isolation is intact after restore.

**Cadence:** Quarterly, plus on any major Postgres SKU/version change.

**Owner:** Platform on-call (rotation).

---

## Prereqs

* `az` CLI authenticated to the subscription containing the prod Postgres
  Flexible Server.
* RBAC: `Reader` on the prod server, `Contributor` on the drill resource
  group (`rg-ctaa-drill-eus`).
* A drill resource group exists in the same region as prod, with a VNet
  that has a delegated subnet for Postgres Flex.

## Procedure

### 1. Pick a restore point

The drill uses a point-in-time restore (PITR) at "now minus 1 hour".

```bash
RESTORE_TIME=$(date -u -v-1H '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null \
  || date -u -d '-1 hour' '+%Y-%m-%dT%H:%M:%SZ')
echo "Restoring to $RESTORE_TIME"
```

### 2. Trigger the restore

```bash
SOURCE_SERVER="psql-ctaa-prod-eus-<uniq>"     # from Bicep deploy output
DRILL_SERVER="psql-ctaa-drill-$(date +%Y%m%d)"
az postgres flexible-server restore \
  --resource-group rg-ctaa-drill-eus \
  --name "$DRILL_SERVER" \
  --source-server "$SOURCE_SERVER" \
  --restore-time "$RESTORE_TIME" \
  --no-wait
```

Wait for the server to reach `Ready` state:

```bash
az postgres flexible-server wait \
  --resource-group rg-ctaa-drill-eus \
  --name "$DRILL_SERVER" \
  --created --timeout 3600
```

### 3. Verify connectivity + schema

Run the drill script (see `scripts/restore_drill.py`):

```bash
DRILL_DATABASE_URL="postgresql+psycopg://ctaa_owner:<pwd>@$DRILL_SERVER.postgres.database.azure.com:5432/ctaa?sslmode=require" \
  .venv/bin/python scripts/restore_drill.py
```

The script:

1. Connects with `sslmode=require` (proves TLS is enforced).
2. Reads `alembic_version.version_num` and compares it to `alembic heads`
   in the local repo. If they differ, **fail** — the prod migration is
   behind/ahead of the codebase the drill expected.
3. Runs a minimal RLS-isolation probe: connects as `app_user`, sets the
   GUC to a random firm UUID, expects zero rows from `journal_entry`,
   `source_document`, etc. (the restored data set has no rows for that
   random firm, proving RLS is intact).
4. Prints the count of rows per major table for an at-a-glance sanity
   check.

A non-zero exit code from the drill script means the restore failed
verification.

### 4. Tear down

```bash
az postgres flexible-server delete \
  --resource-group rg-ctaa-drill-eus \
  --name "$DRILL_SERVER" \
  --yes
```

### 5. Record evidence

Capture in the quarterly drill log:

* timestamp of the drill
* restore-point chosen
* observed alembic head (must match repo)
* RLS probe result (must be zero rows)
* drill server deletion timestamp

This evidence is part of the SOC 2 backup-restore control package.

## Failure modes

| Symptom | Likely cause | Action |
|---|---|---|
| `RESTORE_FAILED` | PITR window expired (>35 days) or restore-time outside backup window | Pick a more recent restore time within the configured `backupRetentionDays` |
| `Could not connect` | drill resource group has no path to the new server's PE | Verify VNet + private DNS link exist in `rg-ctaa-drill-eus` |
| `alembic head mismatch` | prod migrated past CI's main, or rolled back | Investigate before next deploy; do NOT auto-run `alembic upgrade` against drill |
| `RLS probe returned >0 rows` | RLS policies missing or `app_user` got `BYPASSRLS` | STOP — production may have an isolation regression. Page security on-call. |
