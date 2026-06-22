// ---------------------------------------------------------------------------
// uami.bicep
// Just the User Assigned Managed Identity. Split out so the AcrPull role
// assignment in main-demo.bicep can be authored against its principalId
// BEFORE the container apps try to pull, avoiding the classic ACA + AcrPull
// race where the apps fail to provision with "unable to pull image".
// ---------------------------------------------------------------------------
param name string
param location string
param tags object

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
  tags: tags
}

output id string = uami.id
output principalId string = uami.properties.principalId
output clientId string = uami.properties.clientId
