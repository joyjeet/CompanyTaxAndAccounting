#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# _azure_env.sh — resolves the Azure subscription for the deploy scripts.
#
# Source this, do not execute it:
#
#     source "$(dirname "${BASH_SOURCE[0]}")/_azure_env.sh"
#
# The subscription ID used to be hardcoded as a default in each script. This
# repository is public, so it now comes from an untracked local file instead.
# A subscription ID is not a credential, but it is useful reconnaissance and
# there is no reason to publish it.
#
# Resolution order:
#   1. $SUBSCRIPTION_ID already exported in the environment (CI, one-offs).
#   2. SUBSCRIPTION_ID in <repo root>/.azure.env  (untracked; see
#      .azure.env.example).
#   3. Fail with instructions. We deliberately do NOT fall back to whatever
#      `az account show` reports — the owner has several subscriptions and the
#      active one drifts, so guessing risks deploying into the wrong place.
# ---------------------------------------------------------------------------

_azure_env_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_azure_env_file="${AZURE_ENV_FILE:-$_azure_env_root/.azure.env}"

if [[ -z "${SUBSCRIPTION_ID:-}" && -f "$_azure_env_file" ]]; then
    # shellcheck disable=SC1090
    set -a && source "$_azure_env_file" && set +a
fi

if [[ -z "${SUBSCRIPTION_ID:-}" ]]; then
    cat >&2 <<EOF
ERROR: SUBSCRIPTION_ID is not set.

The Azure subscription is no longer hardcoded in this repository. Set it once:

    cp .azure.env.example .azure.env
    \$EDITOR .azure.env          # fill in SUBSCRIPTION_ID

.azure.env is gitignored. Alternatively, pass it for a single run:

    SUBSCRIPTION_ID=<id> $0
EOF
    exit 1
fi

unset _azure_env_root _azure_env_file
