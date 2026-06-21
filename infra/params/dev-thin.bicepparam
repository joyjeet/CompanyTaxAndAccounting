// Cost-minimised smoke-test profile.
// Differences vs dev.bicepparam:
//   * Front Door + WAF disabled (the ~$335/mo cost driver).
//   * Alert rules disabled (clean teardown).
//   * Container Apps env public (so the API is reachable without Front Door).
//   * Postgres on smallest Burstable SKU.
//   * Service Bus Standard, no geo-redundant pg backup.
//
// Intended for ephemeral validation deploys only. NOT for any real client
// data. Always pair with `az group delete` once the smoke test is done.
using '../main.bicep'

param env = 'dev'
param location = 'centralus'
param locationShort = 'cus'
param namePrefix = 'ctax'

// Filled in by the deploy script after the image is pushed to ACR.
param apiImage = ''
param workerImage = ''

// Filled in at deploy time from KV / generated.
param postgresAdminPassword = ''

param firmDatabases = [ 'ctax' ]
param corsOrigins = '*'
param actionGroupEmail = 'noreply@example.com'

param serviceBusSku = 'Standard'
param wafMode = 'Detection'

param postgresHa = 'Disabled'
param postgresSkuName = 'Standard_B1ms'
param postgresSkuTier = 'Burstable'
param postgresGeoRedundantBackup = 'Disabled'

param logRetentionDays = 30

param apiMinReplicas = 1
param apiMaxReplicas = 2
param workerMinReplicas = 0
param workerMaxReplicas = 1

// Cost-thin flags
param enableFrontDoor = false
param enableAlerts = false
param containerEnvInternalOnly = false

// DB has not been bootstrapped in this thin profile (no app_user role, no
// secret-injected DATABASE_URL). Use a no-DB readiness probe so the replica
// stays in rotation and we can curl /livez to validate the deploy path.
param apiReadinessPath = '/healthz'
