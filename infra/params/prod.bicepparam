using '../main.bicep'

param env = 'prod'
param location = 'centralus'
param locationShort = 'cus'

param apiImage = 'ctaaprodcus.azurecr.io/ctaa-api:prod'
param workerImage = 'ctaaprodcus.azurecr.io/ctaa-worker:prod'
param uiImage = 'ctaaprodcus.azurecr.io/ctaa-ui:prod'
param acrLoginServer = 'ctaxdemocusreg.azurecr.io'
param acrName = 'ctaxdemocusreg'

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
param uiMinReplicas = 2
param uiMaxReplicas = 10
