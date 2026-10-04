#!/usr/bin/env bash
# Start the Alembic migration Container Apps Job and WAIT for it to finish.
#
# `az containerapp job start` returns as soon as the execution is queued, so
# calling it alone lets a failing migration sail through CD green — which is
# exactly how the dev database silently drifted 13 revisions behind the code.
# This script blocks until the execution reaches a terminal state and exits
# non-zero on anything other than success.
#
# Required env:
#   MIGRATION_JOB_NAME  Container Apps Job name (e.g. ca-ctaa-dev-cus-migrate)
#   RESOURCE_GROUP      Resource group holding the job
# Optional env:
#   MIGRATION_TIMEOUT_SECONDS  Give up after this long (default 1800)
set -euo pipefail

: "${MIGRATION_JOB_NAME:?MIGRATION_JOB_NAME must be set}"
: "${RESOURCE_GROUP:?RESOURCE_GROUP must be set}"
TIMEOUT="${MIGRATION_TIMEOUT_SECONDS:-1800}"

echo "Starting migration job '$MIGRATION_JOB_NAME' in '$RESOURCE_GROUP'..."
execution=$(az containerapp job start \
    --name "$MIGRATION_JOB_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query name -o tsv)

if [[ -z "$execution" ]]; then
    echo "ERROR: job start returned no execution name." >&2
    exit 1
fi
echo "Execution: $execution"

deadline=$(( SECONDS + TIMEOUT ))
while true; do
    state=$(az containerapp job execution show \
        --name "$MIGRATION_JOB_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --job-execution-name "$execution" \
        --query properties.status -o tsv 2>/dev/null || echo "Unknown")

    case "$state" in
        Succeeded)
            echo "Migration job succeeded."
            exit 0
            ;;
        Failed|Cancelled|Degraded)
            echo "ERROR: migration job ended with status '$state'." >&2
            echo "--- job logs ---" >&2
            az containerapp job logs show \
                --name "$MIGRATION_JOB_NAME" \
                --resource-group "$RESOURCE_GROUP" \
                --execution "$execution" \
                --tail 200 >&2 || echo "(could not fetch logs)" >&2
            exit 1
            ;;
        *)
            if (( SECONDS >= deadline )); then
                echo "ERROR: timed out after ${TIMEOUT}s waiting for migration job (last status: $state)." >&2
                exit 1
            fi
            echo "  status=$state — waiting..."
            sleep 10
            ;;
    esac
done
