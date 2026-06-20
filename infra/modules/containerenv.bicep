// ----------------------------------------------------------------------------
// containerenv.bicep
// Container Apps environment, VNet-injected, with workspace logging.
// We resolve the workspace shared key by referencing the existing workspace
// resource inside the same RG. This keeps the secret out of any param file.
// ----------------------------------------------------------------------------
param location string
param envName string
param tags object
param subnetId string
param workspaceName string
@description('Internal-only environment (no public ingress). The Front Door + WAF in front terminates TLS and routes to the env via a Private Endpoint / private link service.')
param internalOnly bool = true

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource env 'Microsoft.App/managedEnvironments@2024-10-02-preview' = {
  name: envName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: subnetId
      internal: internalOnly
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
    zoneRedundant: true
  }
}

output envId string = env.id
output defaultDomain string = env.properties.defaultDomain
output staticIp string = env.properties.staticIp
