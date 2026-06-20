// ----------------------------------------------------------------------------
// identity.bicep
// User-assigned managed identity used by the container apps as the
// "application identity". RBAC role assignments are issued in the individual
// resource modules (KV, Storage, Service Bus) so each resource owns its own
// least-privilege grant.
// ----------------------------------------------------------------------------
param location string
param uamiName string
param tags object

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: uamiName
  location: location
  tags: tags
}

output uamiId string = uami.id
output uamiPrincipalId string = uami.properties.principalId
output uamiClientId string = uami.properties.clientId
