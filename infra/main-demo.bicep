// ----------------------------------------------------------------------------
// main-demo.bicep
// Minimal ephemeral deployment for 24h customer demos.
//
// Scope deliberately stripped vs `main.bicep`:
//   * No VNet, no private endpoints, no private DNS — Postgres uses public
//     access with the "Allow Azure services" firewall rule on, so the
//     Container Apps env can reach it without VNet integration.
//   * No Key Vault, no Service Bus, no Storage account, no Front Door,
//     no alerts, no encryption at the app layer (APP_KEK_PROVIDER=local).
//   * APP_AUTH_MODE=test — the customer uses the dev-token login form.
//   * Two container apps in one shared ACA env: `ctax-api` and `ctax-ui`,
//     both with external HTTPS ingress.
//   * Tagged `expiresAt=<ISO>` so the teardown sweeper can find this RG.
//
// NEVER deploy real client data into this stack.
// ----------------------------------------------------------------------------
targetScope = 'subscription'

@description('Short env name. Embedded in resource names.')
param env string = 'demo'

@description('Azure region.')
param location string = 'centralus'

@description('Short location code paired with `location`.')
param locationShort string = 'cus'

@description('3-6 char lowercase prefix used in every resource name.')
@minLength(3)
@maxLength(6)
param namePrefix string = 'ctax'

@description('Container image for the API, including tag.')
param apiImage string

@description('Container image for the UI, including tag.')
param uiImage string

@description('ACR login server (e.g. ctaxdemo.azurecr.io). UAMI is granted AcrPull on this registry.')
param acrLoginServer string

@description('ACR resource name (just the name, not the FQDN).')
param acrName string

@description('Resource group that holds the ACR. The ACR is shared across multiple demo deploys so it normally lives in a separate, longer-lived RG.')
param acrResourceGroup string

@secure()
@description('Postgres administrator password. Random per deploy, supplied by the deploy script.')
param postgresAdminPassword string

@secure()
@description('HS256 secret for the dev/test JWT mint endpoint. Random per deploy.')
param appTestJwtSecret string

@description('ISO-8601 timestamp at which the auto-teardown sweeper should delete this RG.')
param expiresAt string

var prefix = '${namePrefix}-${env}-${locationShort}'
var u = uniqueString(subscription().id, env, locationShort, namePrefix, expiresAt)

var commonTags = {
  app: namePrefix
  env: env
  ephemeral: 'true'
  expiresAt: expiresAt
  costCenter: 'demo'
  managedBy: 'bicep'
  owner: 'platform-team'
}

var names = {
  rg:           'rg-${prefix}'
  logAnalytics: 'log-${prefix}'
  appInsights:  'appi-${prefix}'
  postgres:     'psql-${prefix}-${u}'
  containerEnv: 'cae-${prefix}'
  apiApp:       'ca-${prefix}-api'
  uiApp:        'ca-${prefix}-ui'
  uami:         'id-${prefix}-app'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-11-01' = {
  name: names.rg
  location: location
  tags: commonTags
}

// Create the UAMI first — we need its principalId to author the AcrPull
// role assignment, and we want that assignment in place BEFORE the
// container apps try to pull. Otherwise ACA fails with "unable to pull
// image" due to the eventually-consistent role propagation.
module uamiMod 'modules/uami.bicep' = {
  scope: rg
  name: 'uamiMod'
  params: {
    name: names.uami
    location: location
    tags: commonTags
  }
}

// Grant the demo UAMI AcrPull on the (cross-RG) ACR.
resource acrRg 'Microsoft.Resources/resourceGroups@2024-11-01' existing = {
  name: acrResourceGroup
}

module acrRole 'modules/acr-role.bicep' = {
  scope: acrRg
  name: 'acrPull-${env}-${locationShort}'
  params: {
    acrName: acrName
    principalId: uamiMod.outputs.principalId
  }
}

module demo 'modules/demo-stack.bicep' = {
  scope: rg
  name: 'demoStack'
  params: {
    location: location
    tags: commonTags
    names: names
    apiImage: apiImage
    uiImage: uiImage
    acrLoginServer: acrLoginServer
    postgresAdminPassword: postgresAdminPassword
    appTestJwtSecret: appTestJwtSecret
    uamiId: uamiMod.outputs.id
  }
  // Explicit dependency — do not let the container apps inside this module
  // start provisioning until AcrPull is in place on the registry.
  dependsOn: [ acrRole ]
}

output resourceGroupName string = rg.name
output postgresFqdn string = demo.outputs.postgresFqdn
output apiFqdn string = demo.outputs.apiFqdn
output uiFqdn string = demo.outputs.uiFqdn
output apiContainerAppName string = names.apiApp
output uiContainerAppName string = names.uiApp
output uamiClientId string = uamiMod.outputs.clientId
