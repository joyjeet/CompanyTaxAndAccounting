#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# redeploy_ui.sh — fast UI-only redeploy for the live demo stack.
#
# Use this when you've only touched files under frontend/ and want a quick
# turnaround instead of running the full deploy_azure_customer.sh (which
# tears down + rebuilds the entire stack).
#
# Steps:
#   1. Pin to the project's subscription (see AGENTS.md).
#   2. Build a new UI image in ACR.
#   3. Patch the existing UI container app to that image.
#   4. Wait until the new revision is healthy and print the live URL.
#
# Reads:
#   SUBSCRIPTION_ID — defaults to the project pin (do NOT override casually).
#   ACR_NAME        — defaults to ctaxdemocusreg
#   ACR_RG          — defaults to rg-ctax-shared-cus
#   APP_NAME        — defaults to ca-ctax-demo-cus-ui
#   APP_RG          — defaults to rg-ctax-demo-cus
#   API_URL         — the existing API URL (auto-detected from container app).
# ---------------------------------------------------------------------------
set -euo pipefail

SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-0270f50b-f296-40a3-9f05-3f8ff04ba8bc}"
ACR_NAME="${ACR_NAME:-ctaxdemocusreg}"
ACR_RG="${ACR_RG:-rg-ctax-shared-cus}"
APP_NAME="${APP_NAME:-ca-ctax-demo-cus-ui}"
APP_RG="${APP_RG:-rg-ctax-demo-cus}"

echo "==> Pinning subscription to $SUBSCRIPTION_ID"
az account set --subscription "$SUBSCRIPTION_ID"

# Auto-detect API URL from the sibling container app if not provided.
if [[ -z "${API_URL:-}" ]]; then
  echo "==> Auto-detecting API URL from ca-ctax-demo-cus-api in $APP_RG"
  API_FQDN=$(az containerapp show -n ca-ctax-demo-cus-api -g "$APP_RG" \
    --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true)
  if [[ -z "$API_FQDN" ]]; then
    echo "ERROR: could not find API container app ca-ctax-demo-cus-api in $APP_RG." >&2
    echo "       Run scripts/deploy_azure_customer.sh first." >&2
    exit 1
  fi
  API_URL="https://$API_FQDN"
fi
echo "==> Using API URL: $API_URL"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
TAG="ui:$TS"
IMAGE="${ACR_NAME}.azurecr.io/${TAG}"

echo "==> Building $IMAGE via az acr build (this can take ~90s)"
az acr build \
  --registry "$ACR_NAME" \
  --resource-group "$ACR_RG" \
  --image "$TAG" \
  --file frontend/Dockerfile \
  --build-arg "VITE_API_BASE=${API_URL}" \
  --build-arg "VITE_AUTH_MODE=dev" \
  frontend

echo "==> Patching container app $APP_NAME -> $IMAGE"
az containerapp update \
  -n "$APP_NAME" \
  -g "$APP_RG" \
  --image "$IMAGE" \
  --output none

UI_FQDN=$(az containerapp show -n "$APP_NAME" -g "$APP_RG" \
  --query properties.configuration.ingress.fqdn -o tsv)
UI_URL="https://$UI_FQDN"

echo ""
echo "================================================================"
echo "  UI redeployed."
echo "  Image: $IMAGE"
echo "  URL:   $UI_URL"
echo "  API:   $API_URL"
echo "================================================================"

# Brief health probe so the operator sees the new revision is live.
for _ in 1 2 3 4 5 6; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$UI_URL/" || echo "000")
  if [[ "$code" == "200" ]]; then
    echo "==> UI healthy ($code)"
    exit 0
  fi
  echo "    waiting for new revision... ($code)"
  sleep 5
done
echo "WARN: UI did not return 200 within ~30s. Check 'az containerapp revision list'." >&2
exit 0
