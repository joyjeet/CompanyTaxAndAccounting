using '../main.bicep'

param env = 'staging'
param location = 'eastus2'
param locationShort = 'eus'

param apiImage = 'ctaastagingeus.azurecr.io/ctaa-api:staging'
param workerImage = 'ctaastagingeus.azurecr.io/ctaa-worker:staging'

param postgresAdminPassword = ''

param firmDatabases = [ 'ctaa' ]
param corsOrigins = 'https://staging.ctaa.example.com'
param actionGroupEmail = 'ops-staging@example.com'

param serviceBusSku = 'Standard'
param wafMode = 'Prevention'

param postgresHa = 'SameZone'
param postgresSkuName = 'Standard_D2ds_v5'
param postgresSkuTier = 'GeneralPurpose'
param postgresGeoRedundantBackup = 'Enabled'

param logRetentionDays = 180

param apiMinReplicas = 1
param apiMaxReplicas = 5
param workerMinReplicas = 1
param workerMaxReplicas = 5
