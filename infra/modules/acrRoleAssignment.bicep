// ----------------------------------------------------------------------------
// acrRoleAssignment.bicep
// Grants AcrPull to the workload UAMI on an existing Azure Container Registry
// in the same resource group. Only needed when the container apps pull from a
// private ACR (i.e. main.bicep param `acrLoginServer` is non-empty).
// ----------------------------------------------------------------------------
param acrName string
param principalId string

// AcrPull role definition (built-in).
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource ra 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, principalId, acrPullRoleId)
  scope: acr
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}
