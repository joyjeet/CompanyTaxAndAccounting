#!/usr/bin/env bash
# ============================================================================
# teardown_azure_customer.sh
#
# Deletes a CTAA customer-demo resource group and its scheduled auto-teardown
# Logic App. Idempotent: missing resources are skipped, not an error.
#
# Usage:
#   ./scripts/teardown_azure_customer.sh --resource-group rg-ctax-demo-eus
#   ./scripts/teardown_azure_customer.sh   # uses default RG
# ============================================================================
set -euo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:$PATH

SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-0270f50b-f296-40a3-9f05-3f8ff04ba8bc}"
NAME_PREFIX="${NAME_PREFIX:-ctax}"
LOCATION_SHORT="${LOCATION_SHORT:-cus}"
ENV_NAME="${ENV_NAME:-demo}"
RG_NAME="rg-${NAME_PREFIX}-${ENV_NAME}-${LOCATION_SHORT}"
TEARDOWN_RG="rg-${NAME_PREFIX}-teardown-${LOCATION_SHORT}"
LOGIC_APP_NAME=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --resource-group|-g) RG_NAME="$2"; shift 2 ;;
        --subscription)      SUBSCRIPTION_ID="$2"; shift 2 ;;
        --teardown-rg)       TEARDOWN_RG="$2"; shift 2 ;;
        --logic-app)         LOGIC_APP_NAME="$2"; shift 2 ;;
        --yes|-y)            ASSUME_YES=1; shift ;;
        -h|--help)
            grep '^#' "$0" | head -20
            exit 0
            ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

az account set --subscription "$SUBSCRIPTION_ID" -o none
echo "Tearing down $RG_NAME in subscription $SUBSCRIPTION_ID"

if [[ "${ASSUME_YES:-0}" != "1" ]]; then
    read -r -p "Delete resource group '$RG_NAME'? Type the name to confirm: " ack
    if [[ "$ack" != "$RG_NAME" ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# Cancel the scheduled Logic App first so it doesn't double-fire.
if [[ -n "$LOGIC_APP_NAME" ]]; then
    if az resource show -g "$TEARDOWN_RG" -n "$LOGIC_APP_NAME" --resource-type Microsoft.Logic/workflows -o none 2>/dev/null; then
        echo "Deleting scheduled Logic App $LOGIC_APP_NAME..."
        az resource delete -g "$TEARDOWN_RG" -n "$LOGIC_APP_NAME" --resource-type Microsoft.Logic/workflows -o none || true
    fi
else
    # Best-effort: delete any Logic App tagged for this RG.
    for la in $(az resource list -g "$TEARDOWN_RG" --resource-type Microsoft.Logic/workflows --query "[?tags.target=='$RG_NAME'].name" -o tsv 2>/dev/null || true); do
        echo "Deleting matching Logic App $la..."
        az resource delete -g "$TEARDOWN_RG" -n "$la" --resource-type Microsoft.Logic/workflows -o none || true
    done
fi

if az group show -n "$RG_NAME" -o none 2>/dev/null; then
    echo "Issuing delete (async, --no-wait)..."
    az group delete -n "$RG_NAME" --yes --no-wait
    echo "Delete queued. Track with: az group show -n $RG_NAME"
else
    echo "Resource group $RG_NAME already gone."
fi
