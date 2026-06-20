using '../main.bicep'

param env = 'prod'
param location = 'eastus2'
param locationShort = 'eus'

param apiImage = 'ctaaprodeus.azurecr.io/ctaa-api:prod'
param workerImage = 'ctaaprodeus.azurecr.io/ctaa-worker:prod'

param postgresAdminPassword = ''

// Each firm gets its own DB on the (initially) single Postgres server.
// Add firms here; module will create them.
param firmDatabases = [
  'ctaa_firm_acme'
]
param corsOrigins = 'https://app.ctaa.example.com'
param actionGroupEmail = 'ops-oncall@example.com'

param serviceBusSku = 'Premium'
param wafMode = 'Prevention'

param postgresHa = 'ZoneRedundant'
param postgresSkuName = 'Standard_D4ds_v5'
param postgresSkuTier = 'GeneralPurpose'
param postgresGeoRedundantBackup = 'Enabled'

param logRetentionDays = 365

param apiMinReplicas = 3
param apiMaxReplicas = 20
param workerMinReplicas = 2
param workerMaxReplicas = 30
