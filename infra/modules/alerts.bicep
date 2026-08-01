// ----------------------------------------------------------------------------
// alerts.bicep
// Operational alerting baseline for production hardening.
// Alerts:
//   * Auth failure spike (log)
//   * RLS error (log)
//   * Service Bus DLQ depth > 0 (metric)
//   * Failed migrations (log)
//   * Backup failure (log)
//   * Cost anomaly (subscription budget — driven via separate budget module)
// ----------------------------------------------------------------------------
param location string
param tags object
param workspaceId string
param appInsightsId string
param serviceBusId string
param actionGroupEmail string

resource ag 'Microsoft.Insights/actionGroups@2024-10-01-preview' = {
  name: 'ag-ctaa-${uniqueString(resourceGroup().id)}'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'ctaaOps'
    enabled: true
    emailReceivers: [
      {
        name: 'oncall'
        emailAddress: actionGroupEmail
        useCommonAlertSchema: true
      }
    ]
  }
}

// Log alert: auth failure spike
resource alertAuthFail 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: 'alert-auth-failure-spike'
  location: location
  tags: tags
  properties: {
    severity: 2
    enabled: true
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    scopes: [ workspaceId ]
    criteria: {
      allOf: [
        {
          query: 'AppTraces | where Properties.event == "auth.failure" | summarize count() by bin(TimeGenerated, 5m)'
          timeAggregation: 'Total'
          operator: 'GreaterThan'
          threshold: 25
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: { actionGroups: [ ag.id ] }
  }
}

// Log alert: RLS error
resource alertRlsErr 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: 'alert-rls-error'
  location: location
  tags: tags
  properties: {
    severity: 0
    enabled: true
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    scopes: [ workspaceId ]
    criteria: {
      allOf: [
        {
          query: 'AppExceptions | where ProblemId has "RLS" or OuterMessage has "row-level security"'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: { actionGroups: [ ag.id ] }
  }
}

// Log alert: failed migrations
resource alertMigration 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: 'alert-migration-failure'
  location: location
  tags: tags
  properties: {
    severity: 1
    enabled: true
    evaluationFrequency: 'PT5M'
    windowSize: 'PT30M'
    scopes: [ workspaceId ]
    criteria: {
      allOf: [
        {
          query: 'AppTraces | where Properties.event == "migration.failed"'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: { actionGroups: [ ag.id ] }
  }
}

// Log alert: backup failure (Postgres/Storage backup signals routed via diag settings)
resource alertBackup 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = {
  name: 'alert-backup-failure'
  location: location
  tags: tags
  properties: {
    severity: 1
    enabled: true
    evaluationFrequency: 'PT15M'
    windowSize: 'PT1H'
    scopes: [ workspaceId ]
    criteria: {
      allOf: [
        {
          query: 'AzureDiagnostics | where Category in ("PostgreSQLLogs") and Message has "backup" and (Message has "fail" or Message has "error")'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: { actionGroups: [ ag.id ] }
  }
}

// Metric alert: Service Bus dead-letter depth
resource alertDlq 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-sb-dlq-depth'
  location: 'global'
  tags: tags
  properties: {
    severity: 2
    enabled: true
    scopes: [ serviceBusId ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'dlqMessages'
          metricNamespace: 'Microsoft.ServiceBus/namespaces'
          metricName: 'DeadletteredMessages'
          operator: 'GreaterThan'
          threshold: 0
          timeAggregation: 'Maximum'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [ { actionGroupId: ag.id } ]
  }
}

// Smart detector on App Insights — failure anomalies
resource smartDetector 'Microsoft.AlertsManagement/smartDetectorAlertRules@2021-04-01' = {
  name: 'failure-anomalies-${uniqueString(resourceGroup().id)}'
  location: 'global'
  tags: tags
  properties: {
    description: 'App Insights detected an anomalous rise in failure rate.'
    state: 'Enabled'
    severity: 'Sev2'
    frequency: 'PT1M'
    detector: { id: 'FailureAnomaliesDetector' }
    scope: [ appInsightsId ]
    actionGroups: { groupIds: [ ag.id ] }
  }
}

output actionGroupId string = ag.id
