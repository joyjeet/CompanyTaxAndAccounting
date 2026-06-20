// ----------------------------------------------------------------------------
// servicebus.bicep
// Service Bus namespace + extraction queue.
//   * Premium SKU in prod for VNet integration + zone redundancy; Standard
//     elsewhere for cost.
//   * Public network access disabled in prod (PE only).
//   * App UAMI gets "Azure Service Bus Data Sender" + "Receiver" on the
//     queue.
// ----------------------------------------------------------------------------
param location string
param serviceBusName string
param tags object
param appPrincipalId string
param peSubnetId string
param privateDnsZoneId string
param workspaceId string
@allowed([ 'Standard', 'Premium' ])
param sku string = 'Standard'
@description('Disable public network access. Required true for prod.')
param disablePublicNetworkAccess bool = false

resource sb 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: serviceBusName
  location: location
  tags: tags
  sku: {
    name: sku
    tier: sku
    capacity: sku == 'Premium' ? 1 : 0
  }
  properties: {
    minimumTlsVersion: '1.2'
    publicNetworkAccess: disablePublicNetworkAccess ? 'Disabled' : 'Enabled'
    zoneRedundant: sku == 'Premium'
  }
}

resource queueExtraction 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = {
  name: 'extraction-jobs'
  parent: sb
  properties: {
    maxDeliveryCount: 5
    deadLetteringOnMessageExpiration: true
    defaultMessageTimeToLive: 'P14D'
    lockDuration: 'PT5M'
  }
}

// Role assignments (scoped to namespace; we operate one queue per env).
// "Azure Service Bus Data Sender"   '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
// "Azure Service Bus Data Receiver" '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
var roleSender = '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
var roleReceiver = '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'

resource raSend 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sb.id, appPrincipalId, roleSender)
  scope: sb
  properties: {
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleSender)
  }
}

resource raRecv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sb.id, appPrincipalId, roleReceiver)
  scope: sb
  properties: {
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleReceiver)
  }
}

resource pe 'Microsoft.Network/privateEndpoints@2024-05-01' = if (sku == 'Premium') {
  name: '${serviceBusName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: { id: peSubnetId }
    privateLinkServiceConnections: [
      {
        name: 'sbLink'
        properties: {
          privateLinkServiceId: sb.id
          groupIds: [ 'namespace' ]
        }
      }
    ]
  }
}

resource peDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = if (sku == 'Premium') {
  name: 'default'
  parent: pe
  properties: {
    privateDnsZoneConfigs: [
      { name: 'sb', properties: { privateDnsZoneId: privateDnsZoneId } }
    ]
  }
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'sb-to-log'
  scope: sb
  properties: {
    workspaceId: workspaceId
    logs: [
      { categoryGroup: 'allLogs', enabled: true }
    ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

output serviceBusEndpoint string = 'https://${sb.name}.servicebus.windows.net/'
output extractionQueueName string = queueExtraction.name
output serviceBusId string = sb.id
