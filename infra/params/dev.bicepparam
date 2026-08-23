// Dev environment parameters for CTAA.
// Postgres password and any actual secrets must come from KV references in
// the CI pipeline, NEVER hard-coded here.
using '../main.bicep'

param env = 'dev'
param location = 'centralus'
param locationShort = 'cus'

// CI fills these in (built per commit).
param apiImage = 'ctaadevcus.azurecr.io/ctaa-api:dev'
param workerImage = 'ctaadevcus.azurecr.io/ctaa-worker:dev'
param uiImage = 'ctaadevcus.azurecr.io/ctaa-ui:dev'
param acrLoginServer = 'ctaxdemocusreg.azurecr.io'
param acrName = 'ctaxdemocusreg'

// Sourced at deploy time via:
//   --parameters postgresAdminPassword=$(az keyvault secret show --vault-name <bootstrap-kv> --name pg-admin-pwd --query value -o tsv)
param postgresAdminPassword = ''

param firmDatabases = [ 'ctaa' ]
param corsOrigins = 'https://dev.ctaa.example.com'
param actionGroupEmail = 'ops-dev@example.com'

param serviceBusSku = 'Standard'
param wafMode = 'Detection'

// Cost: no Front Door on dev (Premium was ~$330/mo, the biggest line item).
// The UI app is the only public ingress and reverse-proxies /api to the API,
// which stays internal to the Container Apps environment. Public URL becomes
// the UI Container App FQDN.
param enableFrontDoor = false
param containerEnvInternalOnly = false

param postgresHa = 'Disabled'
param postgresSkuName = 'Standard_B2s'
param postgresSkuTier = 'Burstable'
param postgresGeoRedundantBackup = 'Disabled'

param logRetentionDays = 90

// Disable alert resources in dev to avoid noisy costs and schema/API drift issues.
param enableAlerts = false

param apiMinReplicas = 1
param apiMaxReplicas = 3
param workerMinReplicas = 0
param workerMaxReplicas = 3
param uiMinReplicas = 1
param uiMaxReplicas = 2

// Keep dev API healthy even when downstream dependencies are unstable.
param apiReadinessPath = '/healthz'
