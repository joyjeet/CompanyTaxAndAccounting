// ----------------------------------------------------------------------------
// keyvault.bicep
// Azure Key Vault for per-firm KEKs and runtime secrets.
//   * RBAC authorization (no access policies).
//   * Purge protection ENABLED — cannot be disabled. This is mandatory for
//     crypto-shred integrity: a deleted key cannot be silently restored.
//   * Soft delete retention 90 days.
//   * Private endpoint only; public network access disabled.
//   * Diagnostic settings forward all audit + policy events to Log Analytics.
//   * The application UAMI is granted "Key Vault Crypto User" (wrap/unwrap)
//     and "Key Vault Secrets User" (read app secrets only).
// ----------------------------------------------------------------------------
param location string
param keyVaultName string
param tags object
param tenantId string = subscription().tenantId
param appPrincipalId string
param peSubnetId string
param privateDnsZoneId string
param workspaceId string

resource kv 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

// Role assignments — least privilege.
// "Key Vault Crypto User" GUID: 12338af0-0e69-4776-bea7-57ae8d297424
var roleCryptoUser = '12338af0-0e69-4776-bea7-57ae8d297424'
// "Key Vault Secrets User" GUID: 4633458b-17de-408a-b874-0445c86b69e6
var roleSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

resource raCrypto 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, appPrincipalId, roleCryptoUser)
  scope: kv
  properties: {
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleCryptoUser)
  }
}

resource raSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, appPrincipalId, roleSecretsUser)
  scope: kv
  properties: {
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleSecretsUser)
  }
}

resource pe 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${keyVaultName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: { id: peSubnetId }
    privateLinkServiceConnections: [
      {
        name: 'kvLink'
        properties: {
          privateLinkServiceId: kv.id
          groupIds: [ 'vault' ]
        }
      }
    ]
  }
}

resource peDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  name: 'default'
  parent: pe
  properties: {
    privateDnsZoneConfigs: [
      { name: 'kv', properties: { privateDnsZoneId: privateDnsZoneId } }
    ]
  }
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'audit-to-log'
  scope: kv
  properties: {
    workspaceId: workspaceId
    logs: [
      { categoryGroup: 'audit', enabled: true }
      { categoryGroup: 'allLogs', enabled: true }
    ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

output keyVaultId string = kv.id
output keyVaultUri string = kv.properties.vaultUri
