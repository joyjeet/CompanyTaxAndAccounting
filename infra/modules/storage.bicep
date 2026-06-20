// ----------------------------------------------------------------------------
// storage.bicep
// Azure Storage account for source documents + generated artifacts.
//   * Blob versioning ENABLED.
//   * "source-documents" container has immutability (WORM) policy attached
//     so reviewers cannot tamper with original client uploads.
//   * Public network access disabled; access via private endpoint only.
//   * The application UAMI receives "Storage Blob Data Contributor".
//   * Diagnostic settings forward StorageRead/Write/Delete to Log Analytics.
// ----------------------------------------------------------------------------
param location string
param storageName string
param tags object
param appPrincipalId string
param peSubnetId string
param privateDnsZoneId string
param workspaceId string
@description('Immutability period in days for the source-documents container. 2555 ~= 7 years.')
param immutabilityDays int = 2555

resource sa 'Microsoft.Storage/storageAccounts@2024-01-01' = {
  name: storageName
  location: location
  tags: tags
  sku: { name: 'Standard_GRS' }   // GRS gives us US paired-region redundancy
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false       // RBAC + identity only
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
    }
    encryption: {
      services: {
        blob: { enabled: true }
        file: { enabled: true }
      }
      keySource: 'Microsoft.Storage'
    }
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2024-01-01' = {
  name: 'default'
  parent: sa
  properties: {
    isVersioningEnabled: true
    deleteRetentionPolicy: { enabled: true, days: 30 }
    containerDeleteRetentionPolicy: { enabled: true, days: 30 }
    changeFeed: { enabled: true }
  }
}

resource cSource 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  name: 'source-documents'
  parent: blob
  properties: { publicAccess: 'None' }
}

resource cArtifacts 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  name: 'artifacts'
  parent: blob
  properties: { publicAccess: 'None' }
}

// WORM immutability policy on the source-documents container.
// Unlock not specified => policy created in unlocked state (admin must lock
// it from the portal/CLI before going prod). This is intentional: the IaC
// should not be able to one-way-lock a non-prod environment by mistake.
resource immutability 'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies@2024-01-01' = {
  name: 'default'
  parent: cSource
  properties: {
    immutabilityPeriodSinceCreationInDays: immutabilityDays
    allowProtectedAppendWrites: true
  }
}

// "Storage Blob Data Contributor" 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var roleBlobContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
resource raBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(sa.id, appPrincipalId, roleBlobContributor)
  scope: sa
  properties: {
    principalId: appPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBlobContributor)
  }
}

resource pe 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${storageName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: { id: peSubnetId }
    privateLinkServiceConnections: [
      {
        name: 'blobLink'
        properties: {
          privateLinkServiceId: sa.id
          groupIds: [ 'blob' ]
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
      { name: 'blob', properties: { privateDnsZoneId: privateDnsZoneId } }
    ]
  }
}

resource diag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'storage-to-log'
  scope: blob
  properties: {
    workspaceId: workspaceId
    logs: [
      { category: 'StorageRead', enabled: true }
      { category: 'StorageWrite', enabled: true }
      { category: 'StorageDelete', enabled: true }
    ]
    metrics: [ { category: 'Transaction', enabled: true } ]
  }
}

output storageId string = sa.id
output storageName string = sa.name
output blobEndpoint string = sa.properties.primaryEndpoints.blob
