#!/usr/bin/env bash
# ============================================================================
# deploy_azure_customer.sh
#
# End-to-end deploy of an ephemeral, customer-testable CTAA stack on Azure.
# This is NOT production: APP_AUTH_MODE=test, public Postgres, no Front Door,
# all secrets baked as plain Container App secrets, auto-teardown at T+24h.
#
# Pre-reqs:
#   * az CLI signed in to subscription 0270f50b-... (verified at start).
#   * Docker NOT required locally — images are built with `az acr build`.
#   * Run from repo root: ./scripts/deploy_azure_customer.sh
#
# What it does, in order:
#   1. Computes RG name + a unique random suffix for the deploy.
#   2. Creates RG-scoped ACR (Basic SKU) if it does not already exist.
#   3. Builds & pushes the API image with `az acr build` from docker/Dockerfile.
#   4. Runs `az deployment sub create` against infra/main-demo.bicep
#      with random PG admin password + random test JWT secret.
#   5. Reads the API FQDN from the deployment output, then builds & pushes
#      the UI image with VITE_API_BASE baked in.
#   6. Patches the UI container app to use the freshly built UI image.
#   7. Adds the operator's public IP to the Postgres firewall, then runs
#      bootstrap (CREATE ROLE app_user + alembic upgrade + seed_demo) via
#      `az containerapp exec` into the API container.
#   8. Prints the customer-facing URLs and the seeded firm_id/client_id.
#   9. Schedules an auto-teardown at T+24h via a separate Logic App.
#
# Outputs a JSON receipt at results/azure-demo-<timestamp>/deploy.json.
# ============================================================================
set -euo pipefail

# Make sure we use system tooling on macOS, not whatever a user shell injected.
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:$PATH

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-0270f50b-f296-40a3-9f05-3f8ff04ba8bc}"
# centralus picked because eastus2 / eastus / westus2 are offer-restricted
# for Postgres Flexible Server on this Visual Studio Enterprise subscription.
# centralus + westus3 are the unrestricted US regions for this sub today.
LOCATION="${LOCATION:-centralus}"
LOCATION_SHORT="${LOCATION_SHORT:-cus}"
NAME_PREFIX="${NAME_PREFIX:-ctax}"
ENV_NAME="${ENV_NAME:-demo}"
TTL_HOURS="${TTL_HOURS:-24}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
RESULTS_DIR="results/azure-demo-${TS}"
mkdir -p "$RESULTS_DIR"
LOG_FILE="$RESULTS_DIR/deploy.log"
RECEIPT="$RESULTS_DIR/deploy.json"

log() { printf '\n=== %s ===\n' "$*" | tee -a "$LOG_FILE"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# Tee all subsequent output into the log too.
exec > >(tee -a "$LOG_FILE") 2>&1

log "Subscription / signin check"
az account set --subscription "$SUBSCRIPTION_ID"
SUB_NAME=$(az account show --query name -o tsv)
echo "Active subscription: $SUB_NAME ($SUBSCRIPTION_ID)"

# ----------------------------------------------------------------------------
# 1. Names + RG
# ----------------------------------------------------------------------------
PREFIX="${NAME_PREFIX}-${ENV_NAME}-${LOCATION_SHORT}"
RG_NAME="rg-${PREFIX}"
# Lowercase, alnum only, max 50 chars — ACR rules. We need a stable name
# (re-uses the registry across redeploys of the same RG) so we don't bake
# a timestamp into it.
ACR_NAME="$(echo "${NAME_PREFIX}${ENV_NAME}${LOCATION_SHORT}reg" | tr -cd '[:alnum:]' | tr 'A-Z' 'a-z' | cut -c1-50)"
ACR_LOGIN="${ACR_NAME}.azurecr.io"

EXPIRES_AT="$(date -u -v+${TTL_HOURS}H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "+${TTL_HOURS} hours" +%Y-%m-%dT%H:%M:%SZ)"
echo "Deploy expires at: $EXPIRES_AT (TTL=${TTL_HOURS}h)"
echo "Resource group:    $RG_NAME"
echo "ACR:               $ACR_LOGIN"

# Random secrets — alnum only so Postgres password rules are satisfied and
# they survive bash escaping in az calls.
PG_ADMIN_PASSWORD="$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-28)Aa1"
JWT_SECRET="$(openssl rand -hex 32)"

# ----------------------------------------------------------------------------
# 2. ACR — create if missing. Lives in its own RG so we can reuse it
#    across multiple demo deploys without rebuilding from scratch.
# ----------------------------------------------------------------------------
ACR_RG="rg-${NAME_PREFIX}-shared-${LOCATION_SHORT}"
log "ACR ($ACR_RG / $ACR_NAME)"
az group create -n "$ACR_RG" -l "$LOCATION" \
    --tags app="$NAME_PREFIX" purpose=shared-acr -o none
if ! az acr show -n "$ACR_NAME" -g "$ACR_RG" -o none 2>/dev/null; then
    echo "Creating ACR..."
    az acr create -n "$ACR_NAME" -g "$ACR_RG" --sku Basic --admin-enabled false -o none
fi

# ----------------------------------------------------------------------------
# 3. Build & push the API image (cloud build — no Docker on the laptop)
# ----------------------------------------------------------------------------
API_IMAGE_TAG="api:${TS}"
API_IMAGE="${ACR_LOGIN}/${API_IMAGE_TAG}"
log "Building API image -> $API_IMAGE"
az acr build \
    --registry "$ACR_NAME" \
    --resource-group "$ACR_RG" \
    --image "$API_IMAGE_TAG" \
    --file docker/Dockerfile \
    .

# ----------------------------------------------------------------------------
# 4. Bicep deploy. UI image is set to the API image as a temporary placeholder
#    so the container app resource can exist before we know the API FQDN
#    (we'll patch the UI app to the real UI image at step 6).
# ----------------------------------------------------------------------------
log "Bicep deploy (initial — UI uses placeholder image)"
DEPLOY_NAME="ctaa-demo-${TS}"
az deployment sub create \
    --name "$DEPLOY_NAME" \
    --location "$LOCATION" \
    --template-file infra/main-demo.bicep \
    --parameters \
        env="$ENV_NAME" \
        location="$LOCATION" \
        locationShort="$LOCATION_SHORT" \
        namePrefix="$NAME_PREFIX" \
        apiImage="$API_IMAGE" \
        uiImage="$API_IMAGE" \
        acrLoginServer="$ACR_LOGIN" \
        acrName="$ACR_NAME" \
        acrResourceGroup="$ACR_RG" \
        postgresAdminPassword="$PG_ADMIN_PASSWORD" \
        appTestJwtSecret="$JWT_SECRET" \
        expiresAt="$EXPIRES_AT" \
    -o none

OUTPUTS_JSON=$(az deployment sub show --name "$DEPLOY_NAME" --query properties.outputs -o json)
API_FQDN=$(echo "$OUTPUTS_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['apiFqdn']['value'])")
UI_FQDN=$(echo "$OUTPUTS_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['uiFqdn']['value'])")
PG_FQDN=$(echo "$OUTPUTS_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['postgresFqdn']['value'])")
API_APP=$(echo "$OUTPUTS_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['apiContainerAppName']['value'])")
UI_APP=$(echo "$OUTPUTS_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['uiContainerAppName']['value'])")
echo "API: https://$API_FQDN"
echo "UI:  https://$UI_FQDN"
echo "PG:  $PG_FQDN"

# ----------------------------------------------------------------------------
# 5. Build & push the UI image with the freshly-discovered API URL.
# ----------------------------------------------------------------------------
UI_IMAGE_TAG="ui:${TS}"
UI_IMAGE="${ACR_LOGIN}/${UI_IMAGE_TAG}"
log "Building UI image -> $UI_IMAGE (VITE_API_BASE=https://$API_FQDN)"
az acr build \
    --registry "$ACR_NAME" \
    --resource-group "$ACR_RG" \
    --image "$UI_IMAGE_TAG" \
    --file frontend/Dockerfile \
    --build-arg VITE_API_BASE="https://$API_FQDN" \
    --build-arg VITE_AUTH_MODE=dev \
    frontend

# ----------------------------------------------------------------------------
# 6. Patch the UI container app to use the new UI image.
# ----------------------------------------------------------------------------
log "Patching UI container app to real UI image"
az containerapp update \
    --name "$UI_APP" \
    --resource-group "$RG_NAME" \
    --image "$UI_IMAGE" \
    -o none

# ----------------------------------------------------------------------------
# 7. Wait for the API container to bootstrap & seed itself, then scrape the
#    seeded IDs from its console logs. The container's startup command runs
#    scripts/bootstrap_for_demo.py BEFORE uvicorn, and emits lines like
#    ::SEED_FIRM::<uuid> on stdout, which become container console logs.
# ----------------------------------------------------------------------------
log "Waiting for API container to bootstrap & report seed IDs"
SEED_FIRM=""
SEED_CLIENT=""
SEED_PERIOD=""
BOOTSTRAP_OUT="$RESULTS_DIR/bootstrap.log"
for i in $(seq 1 60); do
    # Fetch the last ~200 lines of logs across all replicas. `--tail` is the
    # number of lines, `--type console` selects stdout/stderr from the
    # container itself (vs the platform system events).
    az containerapp logs show \
        --name "$API_APP" \
        --resource-group "$RG_NAME" \
        --container api \
        --type console \
        --tail 200 \
        --format text 2>/dev/null > "$BOOTSTRAP_OUT.tmp" || true

    if [[ -s "$BOOTSTRAP_OUT.tmp" ]]; then
        cp "$BOOTSTRAP_OUT.tmp" "$BOOTSTRAP_OUT"
        SEED_FIRM=$(grep -o '::SEED_FIRM::[0-9a-fA-F-]*'   "$BOOTSTRAP_OUT" | tail -n1 | sed 's/::SEED_FIRM:://'   || true)
        SEED_CLIENT=$(grep -o '::SEED_CLIENT::[0-9a-fA-F-]*' "$BOOTSTRAP_OUT" | tail -n1 | sed 's/::SEED_CLIENT:://' || true)
        SEED_PERIOD=$(grep -o '::SEED_PERIOD::[0-9a-fA-F-]*' "$BOOTSTRAP_OUT" | tail -n1 | sed 's/::SEED_PERIOD:://' || true)
    fi

    if [[ -n "$SEED_FIRM" ]]; then
        echo "  bootstrap complete — firm_id=$SEED_FIRM"
        break
    fi
    echo "  attempt $i: bootstrap not done yet — sleeping 15s"
    sleep 15
done
rm -f "$BOOTSTRAP_OUT.tmp"

if [[ -z "$SEED_FIRM" ]]; then
    echo "WARNING: Could not scrape seed IDs from logs within 15 minutes."
    echo "  The deploy is otherwise complete. Check Log Analytics in the portal,"
    echo "  or re-run:  az containerapp logs show -n $API_APP -g $RG_NAME --container api --type console --tail 200"
fi

# ----------------------------------------------------------------------------
# 8. Update API readiness path to /readyz now that the DB is wired.
# ----------------------------------------------------------------------------
# Keeping /healthz is fine for an ephemeral demo — skip this to avoid an
# extra revision cycle.

# ----------------------------------------------------------------------------
# 9. Schedule auto-teardown.
# ----------------------------------------------------------------------------
log "Scheduling auto-teardown at $EXPIRES_AT"
./scripts/schedule_azure_teardown.sh \
    --resource-group "$RG_NAME" \
    --expires-at "$EXPIRES_AT" \
    --subscription "$SUBSCRIPTION_ID" \
    --shared-rg "$ACR_RG" \
    --location "$LOCATION" \
    --name-prefix "$NAME_PREFIX" \
  || echo "WARNING: schedule_azure_teardown.sh failed — you must run scripts/teardown_azure_customer.sh manually."

# ----------------------------------------------------------------------------
# 10. Receipt + handoff
# ----------------------------------------------------------------------------
cat > "$RECEIPT" <<EOF
{
  "timestamp":         "$TS",
  "expiresAt":         "$EXPIRES_AT",
  "ttlHours":          $TTL_HOURS,
  "subscriptionId":    "$SUBSCRIPTION_ID",
  "resourceGroup":     "$RG_NAME",
  "sharedAcrGroup":    "$ACR_RG",
  "acrLoginServer":    "$ACR_LOGIN",
  "apiUrl":            "https://$API_FQDN",
  "uiUrl":             "https://$UI_FQDN",
  "postgresFqdn":      "$PG_FQDN",
  "apiContainerApp":   "$API_APP",
  "uiContainerApp":    "$UI_APP",
  "demoFirmId":        "$SEED_FIRM",
  "demoClientId":      "$SEED_CLIENT",
  "demoPeriodId":      "$SEED_PERIOD",
  "appAuthMode":       "test",
  "note":              "Ephemeral demo. APP_AUTH_MODE=test. Do NOT load real client data."
}
EOF

cat <<EOF


============================================================================
  CTAA customer demo deployed
============================================================================
  Customer URL :  https://$UI_FQDN
  API URL      :  https://$API_FQDN
  Resource group: $RG_NAME    (expires $EXPIRES_AT)

  Login instructions for the customer:
    1. Open https://$UI_FQDN/login
    2. Role:      firm_staff
    3. Firm ID:   $SEED_FIRM
    4. Client ID: (leave blank — firm_staff sees all clients)
    5. Press "Sign in"

  Seeded data:
    firm_id   = $SEED_FIRM
    client_id = $SEED_CLIENT
    period_id = $SEED_PERIOD

  Receipt:  $RECEIPT
  Logs:     $LOG_FILE

  Manual teardown:
    ./scripts/teardown_azure_customer.sh --resource-group $RG_NAME
============================================================================
EOF
