// ----------------------------------------------------------------------------
// monitoring.bicep
// Log Analytics workspace + Application Insights (workspace-based).
// Diagnostic settings are wired by each module via the workspaceId output.
// ----------------------------------------------------------------------------
param location string
param workspaceName string
param appInsightsName string
param tags object
@description('Retention in days. 365 for prod (SOC 2 evidence), 90 for non-prod.')
param retentionInDays int = 90

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionInDays
    features: { enableLogAccessUsingOnlyResourcePermissions: true }
  }
}

resource ai 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

output workspaceId string = law.id
output workspaceCustomerId string = law.properties.customerId
output appInsightsId string = ai.id
output appInsightsConnectionString string = ai.properties.ConnectionString
