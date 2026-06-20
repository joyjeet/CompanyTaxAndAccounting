// ----------------------------------------------------------------------------
// network.bicep
// Virtual Network with subnet topology:
//   * snet-aca    : Container Apps environment (delegated)
//   * snet-pe     : Private endpoints (DB, KV, Storage, Service Bus)
//   * snet-data   : Postgres delegated subnet (Microsoft.DBforPostgreSQL)
// Private DNS zones for each PaaS service are linked to the VNet so the
// container apps can resolve internal endpoints without DNS leakage.
// ----------------------------------------------------------------------------
param location string
param vnetName string
param tags object

var addressSpace = '10.40.0.0/16'
var subnetAca = '10.40.0.0/23'   // /23 required for ACA workload profile envs
var subnetPe = '10.40.4.0/24'
var subnetData = '10.40.5.0/24'

resource nsgAca 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${vnetName}-nsg-aca'
  location: location
  tags: tags
  properties: { securityRules: [] }
}

resource nsgPe 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${vnetName}-nsg-pe'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'DenyInternetInbound'
        properties: {
          priority: 4000
          access: 'Deny'
          direction: 'Inbound'
          protocol: '*'
          sourceAddressPrefix: 'Internet'
          destinationAddressPrefix: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource nsgData 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${vnetName}-nsg-data'
  location: location
  tags: tags
  properties: { securityRules: [] }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [ addressSpace ] }
    subnets: [
      {
        name: 'snet-aca'
        properties: {
          addressPrefix: subnetAca
          networkSecurityGroup: { id: nsgAca.id }
          delegations: [
            { name: 'aca-delegation', properties: { serviceName: 'Microsoft.App/environments' } }
          ]
        }
      }
      {
        name: 'snet-pe'
        properties: {
          addressPrefix: subnetPe
          networkSecurityGroup: { id: nsgPe.id }
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'snet-data'
        properties: {
          addressPrefix: subnetData
          networkSecurityGroup: { id: nsgData.id }
          delegations: [
            { name: 'pg-delegation', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } }
          ]
        }
      }
    ]
  }
}

// Private DNS zones — one per PaaS resource type we put behind a PE.
var dnsZoneNames = [
  'privatelink.postgres.database.azure.com'
  'privatelink.vaultcore.azure.net'
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.servicebus.windows.net'
]

resource dnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for z in dnsZoneNames: {
  name: z
  location: 'global'
  tags: tags
}]

resource dnsLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (z, i) in dnsZoneNames: {
  name: '${vnetName}-link'
  parent: dnsZones[i]
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}]

output vnetId string = vnet.id
output snetAcaId string = '${vnet.id}/subnets/snet-aca'
output snetPeId string = '${vnet.id}/subnets/snet-pe'
output snetDataId string = '${vnet.id}/subnets/snet-data'
output dnsZonePostgresId string = dnsZones[0].id
output dnsZoneKeyVaultId string = dnsZones[1].id
output dnsZoneBlobId string = dnsZones[2].id
output dnsZoneServiceBusId string = dnsZones[3].id
