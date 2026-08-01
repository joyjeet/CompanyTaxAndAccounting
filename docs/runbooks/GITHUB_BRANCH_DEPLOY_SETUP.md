# GitHub Setup: Branch-Based Automated Deployment

This runbook configures automated deployment by branch:

- Push to `dev` -> deploy Dev environment
- Push to `main` -> deploy Production environment

Workflow file in this repo:
- `.github/workflows/cd.yml`

## 1) Prerequisites

1. Azure subscription to use for this project:
   - `0270f50b-f296-40a3-9f05-3f8ff04ba8bc`
2. Azure region:
   - `centralus`
3. Existing infra templates:
   - `infra/main.bicep`
   - `infra/params/dev.bicepparam`
   - `infra/params/prod.bicepparam`

## 2) Create GitHub Environments

In GitHub repo settings:

1. Go to: Settings -> Environments
2. Create environment: `dev`
3. Create environment: `prod`

For `prod`, add protection:

1. Required reviewers (at least one approver)
2. Optionally restrict deployment branches to `main`

## 3) Configure Azure OIDC Authentication (recommended)

Use one Microsoft Entra app registration / service principal with federated credentials.

1. Create or select app registration for GitHub Actions deploy.
2. Add federated credential for `dev` environment:
   - Issuer: `https://token.actions.githubusercontent.com`
   - Subject: `repo:joyjeet/CompanyTaxAndAccounting:environment:dev`
   - Audience: `api://AzureADTokenExchange`
3. Add federated credential for `prod` environment:
   - Issuer: `https://token.actions.githubusercontent.com`
   - Subject: `repo:joyjeet/CompanyTaxAndAccounting:environment:prod`
   - Audience: `api://AzureADTokenExchange`
4. Grant service principal permissions needed for deploy (least privilege):
   - Subscription/Resource Group roles for deployment and resource updates
   - ACR push/pull permissions
   - Key Vault secret read permissions

## 4) Add GitHub Secrets

Add these as repository secrets (or environment secrets if you prefer split by env):

1. `AZURE_CLIENT_ID` = app registration (service principal) client id
2. `AZURE_TENANT_ID` = Entra tenant id
3. `AZURE_SUBSCRIPTION_ID` = `0270f50b-f296-40a3-9f05-3f8ff04ba8bc`

## 5) Add Environment Variables

Set the following GitHub Environment variables for each environment.

### Dev environment variables (`dev`)

1. `AZURE_LOCATION` = `centralus`
2. `ACR_NAME` = your dev ACR name (without `.azurecr.io`)
3. `BOOTSTRAP_KV` = Key Vault name that holds the Postgres admin secret
4. `PG_ADMIN_SECRET_NAME` = secret name for dev Postgres admin password
5. `RESOURCE_GROUP` = dev resource group name
6. `MIGRATION_JOB_NAME` = dev migration container app job name

### Prod environment variables (`prod`)

1. `AZURE_LOCATION` = `centralus`
2. `ACR_NAME` = your prod ACR name (without `.azurecr.io`)
3. `BOOTSTRAP_KV` = Key Vault name that holds the Postgres admin secret
4. `PG_ADMIN_SECRET_NAME` = secret name for prod Postgres admin password
5. `RESOURCE_GROUP` = prod resource group name
6. `MIGRATION_JOB_NAME` = prod migration container app job name

## 6) Protect Branches

In Settings -> Branches:

1. Protect `main`
   - Require pull request before merging
   - Require status checks to pass
   - Disable force pushes/deletions
2. Optional: Protect `dev`
   - Require status checks before merge

## 7) Deployment Behavior (after setup)

1. Push to `dev`:
   - Builds images
   - Runs `what-if`
   - Deploys Dev
2. Push to `main`:
   - Builds images
   - Runs production safety checks
   - Blocks deploy if `what-if` contains `Delete`
   - Deploys Production only when allowed by `prod` environment gate

## 8) Data-Safety Guardrails Already in Repo

1. `scripts/deploy_azure_customer.sh` is blocked for `prod`/`production` env names.
2. CD workflow runs production `what-if` and fails on destructive deletes.
3. Production job uses `infra/main.bicep` and `infra/params/prod.bicepparam` (not demo template).

## 9) First Validation

1. Push a small commit to `dev` and verify CD workflow deploys Dev.
2. Merge `dev` -> `main`, approve `prod` environment gate, verify Production deploy.
3. Confirm data remains intact on redeploy by checking existing customer records after a no-op redeploy.

## 10) Troubleshooting

1. Azure login fails in action:
   - Re-check OIDC federated credential subject and audience.
2. Key Vault secret read fails:
   - Grant the service principal `Key Vault Secrets User` (or equivalent read role).
3. Prod deployment blocked by delete safety check:
   - Review workflow log and `what-if` output.
   - Update IaC to avoid deletes, or run a controlled/manual migration plan.
