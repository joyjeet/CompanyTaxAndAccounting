#!/usr/bin/env bash
# ============================================================================
# schedule_azure_teardown.sh
#
# Creates a one-shot Azure Logic App inside the target RG that fires at a
# target ISO timestamp and DELETEs that same resource group via ARM.
#
# The Logic App uses a System-Assigned Managed Identity. The script grants
# that MI Contributor on the target RG so the delete call succeeds.
#
# Args:
#   --resource-group   target RG to delete
#   --expires-at       ISO-8601 UTC timestamp
#   --subscription     subscription ID
#   --shared-rg        (unused but accepted for forward-compat)
#   --location         Azure region for the Logic App
#   --name-prefix      short name prefix
# ============================================================================
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:$PATH

TARGET_RG=""
EXPIRES_AT=""
SUBSCRIPTION_ID=""
SHARED_RG=""
LOCATION="eastus2"
NAME_PREFIX="ctax"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --resource-group) TARGET_RG="$2"; shift 2 ;;
        --expires-at)     EXPIRES_AT="$2"; shift 2 ;;
        --subscription)   SUBSCRIPTION_ID="$2"; shift 2 ;;
        --shared-rg)      SHARED_RG="$2"; shift 2 ;;
        --location)       LOCATION="$2"; shift 2 ;;
        --name-prefix)    NAME_PREFIX="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

[[ -n "$TARGET_RG" && -n "$EXPIRES_AT" && -n "$SUBSCRIPTION_ID" ]] || {
    echo "Missing required args" >&2; exit 2
}

LOCATION_SHORT="$(echo "$LOCATION" | tr -d ' ' | cut -c1-3 | tr '[:upper:]' '[:lower:]')"
TS_SHORT="$(date -u +%Y%m%d%H%M%S)"
LA_NAME="la-teardown-${TARGET_RG}-${TS_SHORT}"
# Logic App names are limited to 80 chars.
LA_NAME="$(echo "$LA_NAME" | cut -c1-80)"

echo "Teardown RG:  $TARGET_RG"
echo "Logic App:    $LA_NAME"
echo "Fires at:     $EXPIRES_AT"
echo "Will delete:  $TARGET_RG"

# Logic App workflow definition: a single Recurrence trigger that fires once,
# at the target time, then an HTTP action that DELETEs the target RG using
# the Logic App's Managed Identity.
WORKFLOW_JSON=$(cat <<EOF
{
  "definition": {
    "\$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {},
    "triggers": {
      "OnceAtExpiry": {
        "type": "Recurrence",
        "recurrence": {
          "frequency": "Day",
          "interval": 1,
          "startTime": "$EXPIRES_AT"
        }
      }
    },
    "actions": {
      "DeleteResourceGroup": {
        "type": "Http",
        "inputs": {
          "method": "DELETE",
          "uri": "https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$TARGET_RG?api-version=2024-11-01",
          "authentication": {
            "type": "ManagedServiceIdentity",
            "audience": "https://management.azure.com/"
          }
        },
        "runAfter": {}
      },
    },
    "outputs": {}
  },
  "parameters": {}
}
EOF
)

WF_TMP=$(mktemp)
echo "$WORKFLOW_JSON" > "$WF_TMP"

echo "Creating Logic App workflow..."
# `az logic workflow create` was previously in preview; fall back to az resource create.
az resource create \
  --resource-group "$TARGET_RG" \
    --name "$LA_NAME" \
    --resource-type "Microsoft.Logic/workflows" \
    --is-full-object \
    --properties "$(jq -c --arg loc "$LOCATION" --slurpfile body "$WF_TMP" '
        {
            location: $loc,
            identity: { type: "SystemAssigned" },
            tags: { purpose: "teardown", target: env.TARGET_RG, expiresAt: env.EXPIRES_AT },
            properties: { state: "Enabled", definition: $body[0].definition, parameters: $body[0].parameters }
        }' <<< '{}')" \
    -o none || {
        # If jq isn't installed, fall back to a simpler path.
        echo "jq missing or composition failed; using az logic workflow create..."
        az logic workflow create \
      --resource-group "$TARGET_RG" \
            --name "$LA_NAME" \
            --location "$LOCATION" \
            --definition "$WF_TMP" \
            -o none
        # Then patch to add MSI.
    az resource update --resource-group "$TARGET_RG" --name "$LA_NAME" \
            --resource-type "Microsoft.Logic/workflows" \
            --set identity.type=SystemAssigned -o none
    }

rm -f "$WF_TMP"

# Grab the MSI principalId and grant it Contributor on the target RG so it
# can DELETE the RG when the timer fires.
echo "Waiting for Managed Identity to propagate..."
PRINCIPAL_ID=""
for i in $(seq 1 10); do
  PRINCIPAL_ID=$(az resource show -g "$TARGET_RG" -n "$LA_NAME" --resource-type Microsoft.Logic/workflows --query identity.principalId -o tsv 2>/dev/null || true)
    [[ -n "$PRINCIPAL_ID" && "$PRINCIPAL_ID" != "null" ]] && break
    sleep 3
done

if [[ -z "$PRINCIPAL_ID" || "$PRINCIPAL_ID" == "null" ]]; then
    echo "WARN: could not read MSI principalId — auto-teardown WILL FAIL. Run teardown manually at $EXPIRES_AT."
    exit 1
fi

echo "MSI principalId: $PRINCIPAL_ID — granting Contributor on $TARGET_RG"
az role assignment create \
    --assignee-object-id "$PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Contributor" \
    --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$TARGET_RG" \
    -o none || echo "(role may already exist)"

echo "Auto-teardown scheduled. Logic App: $TARGET_RG/$LA_NAME — fires at $EXPIRES_AT (UTC)."
