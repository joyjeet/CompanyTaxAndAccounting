// ----------------------------------------------------------------------------
// main.bicep
// Subscription-scoped top-level deployment for one environment (dev|staging|
// prod). Creates the resource group, validates location is US-only, then
// instantiates every module in dependency order.
//
// No secrets in this file. Postgres admin password MUST be supplied via a
// `@secure()` parameter (env var KV reference in the CI pipeline). All other
// secrets are read at runtime from Key Vault using Managed Identity.
//
// Requires-Process (cannot be automated here):
//   * Subscription creation, tenant + Defender Standard tier enablement.
//   * Entra ID App Registration for the firm's SSO provider.
//   * DNS CNAME at the firm's apex/subdomain pointing at the Front Door
//     endpoint, and a managed cert validation.
// ----------------------------------------------------------------------------
targetScope = 'subscription'

@allowed([ 'dev', 'staging', 'prod' ])
param env string

@description('Azure region. Must be US for client data residency.')
@allowed([
  'eastus'
  'eastus2'
  'centralus'
  'westus'
  'westus2'
  'westus3'
  'southcentralus'
  'northcentralus'
])
param location string = 'eastus2'

@description('Short location code paired with `location`.')
param locationShort string = 'eus'

@description('Container image for the API role (e.g. acrname.azurecr.io/ctaa-api:sha).')
param apiImage string

@description('Container image for the worker role.')
param workerImage string

@description('Container image for the UI role.')
param uiImage string

@secure()
@description('Postgres administrator password. Supplied from CI via KV reference; never committed.')
param postgresAdminPassword string

@description('Per-firm Postgres databases. Each firm gets its own database for stricter blast-radius isolation.')
param firmDatabases array = [ 'ctaa' ]

@description('Comma-separated CORS allow-list for the API.')
param corsOrigins string = ''

@description('Operations email address to receive alerts.')
param actionGroupEmail string

@description('Service Bus SKU. Premium recommended for prod (VNet integration + zone redundancy).')
@allowed([ 'Standard', 'Premium' ])
param serviceBusSku string = 'Standard'

@description('WAF mode. Prevention required for prod.')
@allowed([ 'Detection', 'Prevention' ])
param wafMode string = 'Prevention'

@allowed([ 'ZoneRedundant', 'SameZone', 'Disabled' ])
param postgresHa string = 'ZoneRedundant'

@allowed([
  'Standard_B1ms'
  'Standard_B2s'
  'Standard_D2ds_v5'
  'Standard_D4ds_v5'
  'Standard_D8ds_v5'
])
param postgresSkuName string = 'Standard_D2ds_v5'

@allowed([ 'Burstable', 'GeneralPurpose', 'MemoryOptimized' ])
param postgresSkuTier string = 'GeneralPurpose'

@allowed([ 'Disabled', 'Enabled' ])
param postgresGeoRedundantBackup string = 'Enabled'

param logRetentionDays int = 365

param apiMinReplicas int = 1
param apiMaxReplicas int = 10
param workerMinReplicas int = 1
param workerMaxReplicas int = 20
param uiMinReplicas int = 1
param uiMaxReplicas int = 3

@description('Provision Front Door + WAF in front of the ACA app. Set false to save cost on dev/smoke deploys.')
param enableFrontDoor bool = true

@description('Provision alert rules + action group. Set false on dev/smoke deploys to suppress noise.')
param enableAlerts bool = true

@description('Whether the ACA environment ingress is internal-only (VNet) or public. Set false on cost-thin deploys so the API has a public FQDN reachable without Front Door.')
param containerEnvInternalOnly bool = true

@description('3-6 char lowercase prefix used in every resource name. Default ctaa.')
@minLength(3)
@maxLength(6)
param namePrefix string = 'ctaa'

@description('Readiness probe path for the API container app. Defaults to /readyz (DB-aware). Set to /healthz in cost-thin deploys where the DB has not yet been bootstrapped — otherwise the replica stays out of rotation indefinitely.')
param apiReadinessPath string = '/readyz'

@description('ACR login server hostname used to pull images (e.g. ctaxsmoke.azurecr.io). When set, the UAMI must already have AcrPull on this registry. Empty = the container app pulls anonymously (public images only).')
param acrLoginServer string = ''

@description('ACR resource name. Required when `acrLoginServer` is set so we can create the AcrPull role assignment inside the same resource group.')
param acrName string = ''

@description('Resource group that contains the shared ACR used by the container apps.')
param acrResourceGroup string = 'rg-ctax-shared-cus'

var commonTags = {
  app: namePrefix
  env: env
  costCenter: 'accounting-platform'
  dataClass: 'client-confidential'
  owner: 'platform-team'
  managedBy: 'bicep'
  compliance: 'glba,irs-pub-4557,ftc-safeguards'
}

// ---------------------------------------------------------------------------
// Naming — inlined (subscription-scoped deployment cannot call a module that
// runs at RG scope before the RG exists, so we compute names here directly).
// ---------------------------------------------------------------------------
var prefix = '${namePrefix}-${env}-${locationShort}'
var u = uniqueString(subscription().id, env, locationShort, namePrefix)
var runtimeAppEnv = env == 'dev' ? 'test' : (env == 'staging' ? 'staging' : 'prod')
var runtimeAppAuthMode = env == 'dev' ? 'test' : 'jwt'
var names = {
  rg:           'rg-${prefix}'
  vnet:         'vnet-${prefix}'
  logAnalytics: 'log-${prefix}'
  appInsights:  'appi-${prefix}'
  keyVault:     take(replace('kv-${prefix}-${u}', '-', ''), 24)
  storage:      take(toLower(replace('st${namePrefix}${env}${locationShort}${u}', '-', '')), 24)
  serviceBus:   'sb-${prefix}-${u}'
  postgres:     'psql-${prefix}-${u}'
  containerEnv: 'cae-${prefix}'
  apiApp:       'ca-${prefix}-api'
  workerApp:    'ca-${prefix}-worker'
  uiApp:        'ca-${prefix}-ui'
  migrationJob: 'ca-${prefix}-migrate'
  frontDoor:    'afd-${prefix}'
  wafPolicy:    take(replace('waf${namePrefix}${env}${locationShort}', '-', ''), 64)
  uami:         'id-${prefix}-app'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-11-01' = {
  name: names.rg
  location: location
  tags: commonTags
}

module monitoring 'modules/monitoring.bicep' = {
  scope: rg
  name: 'monitoring'
  params: {
    location: location
    workspaceName: names.logAnalytics
    appInsightsName: names.appInsights
    tags: commonTags
    retentionInDays: logRetentionDays
  }
}

module identity 'modules/identity.bicep' = {
  scope: rg
  name: 'identity'
  params: {
    location: location
    uamiName: names.uami
    tags: commonTags
  }
}

module acrPull 'modules/acrRoleAssignment.bicep' = if (!empty(acrName)) {
  scope: resourceGroup(acrResourceGroup)
  name: 'acrPull'
  params: {
    acrName: acrName
    principalId: identity.outputs.uamiPrincipalId
  }
}

module network 'modules/network.bicep' = {
  scope: rg
  name: 'network'
  params: {
    location: location
    vnetName: names.vnet
    tags: commonTags
  }
}

module keyvault 'modules/keyvault.bicep' = {
  scope: rg
  name: 'keyvault'
  params: {
    location: location
    keyVaultName: names.keyVault
    tags: commonTags
    appPrincipalId: identity.outputs.uamiPrincipalId
    peSubnetId: network.outputs.snetPeId
    privateDnsZoneId: network.outputs.dnsZoneKeyVaultId
    workspaceId: monitoring.outputs.workspaceId
  }
}

module storage 'modules/storage.bicep' = {
  scope: rg
  name: 'storage'
  params: {
    location: location
    storageName: names.storage
    tags: commonTags
    appPrincipalId: identity.outputs.uamiPrincipalId
    peSubnetId: network.outputs.snetPeId
    privateDnsZoneId: network.outputs.dnsZoneBlobId
    workspaceId: monitoring.outputs.workspaceId
  }
}

module servicebus 'modules/servicebus.bicep' = {
  scope: rg
  name: 'servicebus'
  params: {
    location: location
    serviceBusName: names.serviceBus
    tags: commonTags
    appPrincipalId: identity.outputs.uamiPrincipalId
    peSubnetId: network.outputs.snetPeId
    privateDnsZoneId: network.outputs.dnsZoneServiceBusId
    workspaceId: monitoring.outputs.workspaceId
    sku: serviceBusSku
    disablePublicNetworkAccess: env == 'prod'
  }
}

module postgres 'modules/postgres.bicep' = {
  scope: rg
  name: 'postgres'
  params: {
    location: location
    postgresName: names.postgres
    tags: commonTags
    subnetId: network.outputs.snetDataId
    privateDnsZoneId: network.outputs.dnsZonePostgresId
    workspaceId: monitoring.outputs.workspaceId
    administratorLoginPassword: postgresAdminPassword
    firmDatabases: firmDatabases
    highAvailabilityMode: postgresHa
    skuName: postgresSkuName
    skuTier: postgresSkuTier
    geoRedundantBackup: postgresGeoRedundantBackup
  }
}

// Workspace shared key for the Container Apps environment — resolved inside
// the module from the known workspace name (avoids passing the secret through
// any intermediate Bicep output or parameter file).
module containerEnv 'modules/containerenv.bicep' = {
  scope: rg
  name: 'containerenv'
  params: {
    location: location
    envName: names.containerEnv
    tags: commonTags
    subnetId: network.outputs.snetAcaId
    workspaceName: names.logAnalytics
    internalOnly: containerEnvInternalOnly
  }
  dependsOn: [ monitoring ]
}

module apiApp 'modules/containerapp.bicep' = {
  scope: rg
  name: 'apiApp'
  params: {
    location: location
    name: names.apiApp
    tags: commonTags
    environmentId: containerEnv.outputs.envId
    uamiId: identity.outputs.uamiId
    uamiClientId: identity.outputs.uamiClientId
    image: apiImage
    role: 'api'
    appEnv: runtimeAppEnv
    appAuthMode: runtimeAppAuthMode
    minReplicas: apiMinReplicas
    maxReplicas: apiMaxReplicas
    keyVaultUri: keyvault.outputs.keyVaultUri
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    postgresFqdn: postgres.outputs.serverFqdn
    postgresDatabase: firmDatabases[0]
    postgresAdminPassword: postgresAdminPassword
    storageAccountName: storage.outputs.storageName
    serviceBusFqdn: replace(replace(servicebus.outputs.serviceBusEndpoint, 'https://', ''), '/', '')
    corsOrigins: corsOrigins
    acrLoginServer: acrLoginServer
    readinessPath: apiReadinessPath
  }
  dependsOn: [ acrPull ]
}

module workerApp 'modules/containerapp.bicep' = {
  scope: rg
  name: 'workerApp'
  params: {
    location: location
    name: names.workerApp
    tags: commonTags
    environmentId: containerEnv.outputs.envId
    uamiId: identity.outputs.uamiId
    uamiClientId: identity.outputs.uamiClientId
    image: workerImage
    role: 'worker'
    appEnv: runtimeAppEnv
    appAuthMode: runtimeAppAuthMode
    minReplicas: workerMinReplicas
    maxReplicas: workerMaxReplicas
    keyVaultUri: keyvault.outputs.keyVaultUri
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    postgresFqdn: postgres.outputs.serverFqdn
    postgresDatabase: firmDatabases[0]
    postgresAdminPassword: postgresAdminPassword
    storageAccountName: storage.outputs.storageName
    serviceBusFqdn: replace(replace(servicebus.outputs.serviceBusEndpoint, 'https://', ''), '/', '')
    acrLoginServer: acrLoginServer
  }
  dependsOn: [ acrPull ]
}

module uiApp 'modules/containerapp.bicep' = {
  scope: rg
  name: 'uiApp'
  params: {
    location: location
    name: names.uiApp
    tags: commonTags
    environmentId: containerEnv.outputs.envId
    uamiId: identity.outputs.uamiId
    uamiClientId: identity.outputs.uamiClientId
    image: uiImage
    role: 'ui'
    appEnv: runtimeAppEnv
    appAuthMode: runtimeAppAuthMode
    minReplicas: uiMinReplicas
    maxReplicas: uiMaxReplicas
    keyVaultUri: keyvault.outputs.keyVaultUri
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    postgresFqdn: postgres.outputs.serverFqdn
    postgresDatabase: firmDatabases[0]
    postgresAdminPassword: postgresAdminPassword
    storageAccountName: storage.outputs.storageName
    serviceBusFqdn: replace(replace(servicebus.outputs.serviceBusEndpoint, 'https://', ''), '/', '')
    acrLoginServer: acrLoginServer
  }
  dependsOn: [ acrPull ]
}

module migrationJob 'modules/migrationjob.bicep' = {
  scope: rg
  name: 'migrationJob'
  params: {
    location: location
    name: names.migrationJob
    tags: commonTags
    environmentId: containerEnv.outputs.envId
    uamiId: identity.outputs.uamiId
    uamiClientId: identity.outputs.uamiClientId
    image: apiImage
    keyVaultUri: keyvault.outputs.keyVaultUri
    postgresFqdn: postgres.outputs.serverFqdn
    postgresDatabase: firmDatabases[0]
    postgresAdminPassword: postgresAdminPassword
    acrLoginServer: acrLoginServer
  }
  dependsOn: [ acrPull ]
}

module frontdoor 'modules/frontdoor.bicep' = if (enableFrontDoor) {
  scope: rg
  name: 'frontdoor'
  params: {
    afdName: names.frontDoor
    wafPolicyName: names.wafPolicy
    tags: commonTags
    webOriginHostName: uiApp.outputs.fqdn
    apiOriginHostName: apiApp.outputs.fqdn
    originPrivateLinkResourceId: containerEnv.outputs.envId
    wafMode: wafMode
  }
}

module alerts 'modules/alerts.bicep' = if (enableAlerts) {
  scope: rg
  name: 'alerts'
  params: {
    location: location
    tags: commonTags
    workspaceId: monitoring.outputs.workspaceId
    appInsightsId: monitoring.outputs.appInsightsId
    serviceBusId: servicebus.outputs.serviceBusId
    actionGroupEmail: actionGroupEmail
  }
}

output rgName string = rg.name
output apiFqdn string = apiApp.outputs.fqdn
output migrationJobName string = migrationJob.outputs.jobName
output frontDoorEndpoint string = enableFrontDoor ? frontdoor!.outputs.endpointHostName : ''
output keyVaultUri string = keyvault.outputs.keyVaultUri
output postgresFqdn string = postgres.outputs.serverFqdn
