// ---------------------------------------------------------------------------
// acr-role.bicep
// Grants AcrPull on an existing ACR to a UAMI. Lives in a separate module
// so the role assignment can be scoped to the ACR's resource group, which
// may differ from the caller's.
// ---------------------------------------------------------------------------
param acrName string
param principalId string

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, principalId, 'AcrPull')
  scope: acr
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    // AcrPull built-in role definition ID.
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}
