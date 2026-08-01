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

// Sourced at deploy time via:
//   --parameters postgresAdminPassword=$(az keyvault secret show --vault-name <bootstrap-kv> --name pg-admin-pwd --query value -o tsv)
param postgresAdminPassword = ''

param firmDatabases = [ 'ctaa' ]
param corsOrigins = 'https://dev.ctaa.example.com'
param actionGroupEmail = 'ops-dev@example.com'

param serviceBusSku = 'Standard'
param wafMode = 'Detection'

param postgresHa = 'Disabled'
param postgresSkuName = 'Standard_B2s'
param postgresSkuTier = 'Burstable'
param postgresGeoRedundantBackup = 'Disabled'

param logRetentionDays = 90

param apiMinReplicas = 1
param apiMaxReplicas = 3
param workerMinReplicas = 0
param workerMaxReplicas = 3
