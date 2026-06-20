# Infrastructure as Code (Phase 7)

Bicep modules to provision the full Azure stack for **CTAA** (CompanyTaxAndAccounting)
in US data-residency regions.

## Layout

```
infra/
  main.bicep                  # Top-level: composes the modules below; inlines naming
  modules/
    network.bicep             # VNet, subnets, NSGs, private DNS zones
    monitoring.bicep          # Log Analytics + App Insights
    identity.bicep            # User-assigned managed identity
    keyvault.bicep            # Key Vault for per-firm KEKs + app secrets
    storage.bicep             # Blob with versioning + immutable WORM container
    servicebus.bicep          # Service Bus namespace + queue (extraction jobs)
    postgres.bicep            # Postgres Flexible Server (HA, PE, TLS-enforced)
    containerenv.bicep        # Container Apps environment (VNet-injected)
    containerapp.bicep        # API + worker container apps (KEDA scaling)
    frontdoor.bicep           # Front Door Premium + WAF policy
    alerts.bicep              # Action group + production alert rules
  params/
    dev.bicepparam            # Dev parameter file
    staging.bicepparam        # Staging parameter file
    prod.bicepparam           # Prod parameter file
```

## Principles

* **US data residency** — all resources deploy to a US region (default
  `eastus`). The `location` parameter validates against an allowed-list of US
  regions in `main.bicep`.
* **No secrets in IaC** — every credential is either generated at deploy time
  (random database admin password handed straight to Key Vault) or referenced
  from Key Vault via `keyVaultReference`. Managed Identity is the auth path
  for every service-to-service connection.
* **Least privilege** — the runtime container app gets only the role
  assignments it strictly needs (KV Crypto User, Storage Blob Data
  Contributor on the writable container, SB Data Receiver/Sender).
* **Private data plane** — Postgres, Storage, Key Vault, Service Bus, and the
  Container Apps environment live inside the VNet with private endpoints; the
  edge is exclusively Front Door + WAF.
* **DB-per-firm shardable** — `postgres.bicep` accepts a `firms` array; each
  firm's database lives on the same Flex Server initially but the module
  takes a `serverNameSuffix` so a second server can be carved off without
  refactoring (just a new module instance per firm-shard).
* **Reproducible per environment** — every environment difference is in the
  three `*.bicepparam` files; `main.bicep` is environment-agnostic.

## Deploying

Prerequisites: Azure subscription, `az` CLI logged in, contributor on a
target resource group, an existing user-assigned managed identity OR
permissions to create one.

```bash
# Validate
az bicep build --file infra/main.bicep
az deployment sub validate \
  --location eastus \
  --template-file infra/main.bicep \
  --parameters infra/params/dev.bicepparam

# What-if
az deployment sub what-if \
  --location eastus \
  --template-file infra/main.bicep \
  --parameters infra/params/dev.bicepparam

# Deploy (subscription-scoped because we create the resource group)
az deployment sub create \
  --location eastus \
  --name ctaa-dev-$(date +%s) \
  --template-file infra/main.bicep \
  --parameters infra/params/dev.bicepparam
```

## Tagging

Every resource is tagged with the following keys (enforced via the
`commonTags` variable at the top of `main.bicep`):

| key            | value                                         |
| -------------- | --------------------------------------------- |
| `app`          | `ctaa`                                        |
| `env`          | `dev` / `staging` / `prod`                    |
| `costCenter`   | `accounting-platform`                         |
| `dataClass`    | `client-confidential` (or `internal` for ops) |
| `owner`        | (firm operator email — set per env)           |
| `managedBy`    | `bicep`                                       |
| `compliance`   | `glba,irs-pub-4557,ftc-safeguards`            |

## What this module does NOT do (Requires-Process)

* Does not create the Azure subscription or assign global owners.
* Does not run the firm's KYC / signup for Microsoft Defender for Cloud
  Standard tier (must be enabled by a subscription owner).
* Does not register the app in Entra ID — the App Registration must be
  created by directory admins. The IaC accepts the resulting
  `oidc_issuer` / `oidc_audience` / `oidc_jwks_url` values as parameters.
* Does not handle DNS for the public domain — Front Door receives a CNAME
  target that must be set in the registrar after deploy.
