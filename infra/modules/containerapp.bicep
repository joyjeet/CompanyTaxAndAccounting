// ----------------------------------------------------------------------------
// containerapp.bicep
// One reusable container app definition for API or worker roles.
// Secrets are referenced via Key Vault using the supplied UAMI identity.
// ----------------------------------------------------------------------------
param location string
param name string
param tags object
param environmentId string
param uamiId string
param uamiClientId string
param image string
@allowed([ 'api', 'worker', 'ui' ])
param role string = 'api'
param minReplicas int = 1
param maxReplicas int = 10
param keyVaultUri string
param appInsightsConnectionString string
@description('Postgres FQDN — passed as plain env var (not a secret).')
param postgresFqdn string
@description('Postgres database name.')
param postgresDatabase string = 'ctaa'
@description('Storage account name (for Blob via Identity).')
param storageAccountName string
@description('Service Bus FQDN.')
param serviceBusFqdn string
@description('Application runtime environment value consumed by app.core.config.Settings.app_env.')
@allowed([ 'local', 'test', 'staging', 'prod' ])
param appEnv string = 'prod'
@description('Application auth mode consumed by app.core.config.Settings.app_auth_mode.')
@allowed([ 'jwt', 'test' ])
param appAuthMode string = 'jwt'
@description('Comma-separated CORS origins (API only).')
param corsOrigins string = ''
@description('Service Bus queue name (worker scale target).')
param queueName string = 'extraction-jobs'

@description('ACR login server (e.g. ctaaprodeus.azurecr.io). When supplied, the container app is configured to pull from this ACR using the UAMI. The caller is responsible for granting AcrPull on the UAMI before deployment.')
param acrLoginServer string = ''

@description('Readiness probe HTTP path. Defaults to /readyz (which performs a DB SELECT 1). For smoke deploys where the DB credentials are not yet wired, set to /healthz to keep the replica in rotation regardless of DB state.')
param readinessPath string = '/readyz'

@description('Revision suffix. Defaults to a deterministic hash of the image + readiness path so that the suffix changes whenever those change, avoiding the "revision already exists" failure on redeploy. Override only when you need a human-friendly suffix.')
param revisionSuffix string = take(uniqueString(image, readinessPath), 10)

var commonEnv = [
  { name: 'APP_ENV',                     value: appEnv }
  { name: 'APP_AUTH_MODE',               value: appAuthMode }
  { name: 'APP_KEK_PROVIDER',            value: 'keyvault' }
  { name: 'AZURE_KEYVAULT_URL',          value: keyVaultUri }
  { name: 'AZURE_CLIENT_ID',             value: uamiClientId }
  { name: 'APP_CORS_ORIGINS',            value: corsOrigins }
  { name: 'POSTGRES_FQDN',               value: postgresFqdn }
  { name: 'POSTGRES_DATABASE',           value: postgresDatabase }
  { name: 'AZURE_STORAGE_ACCOUNT',       value: storageAccountName }
  { name: 'AZURE_SERVICEBUS_FQDN',       value: serviceBusFqdn }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
  // OTEL exporter is wired by Azure Monitor OpenTelemetry distro on startup.
  { name: 'OTEL_SERVICE_NAME',           value: name }
  { name: 'OTEL_RESOURCE_ATTRIBUTES',    value: 'service.name=${name},service.role=${role}' }
]

var appIngress = role == 'worker' ? null : {
  external: true
  targetPort: role == 'ui' ? 8080 : 8000
  transport: 'auto'
  allowInsecure: false
  traffic: [ { latestRevision: true, weight: 100 } ]
}

var workerScale = [
  {
    name: 'sb-queue-depth'
    custom: {
      type: 'azure-servicebus'
      metadata: {
        queueName: queueName
        namespace: split(serviceBusFqdn, '.')[0]
        messageCount: '5'
      }
      identity: uamiId
    }
  }
]

var apiScale = [
  {
    name: 'http-concurrent'
    http: { metadata: { concurrentRequests: '40' } }
  }
]

var uiScale = [
  {
    name: 'http-concurrent'
    http: { metadata: { concurrentRequests: '60' } }
  }
]

resource app 'Microsoft.App/containerApps@2024-10-02-preview' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uamiId}': {} }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: appIngress
      maxInactiveRevisions: 3
      registries: empty(acrLoginServer) ? [] : [
        {
          server: acrLoginServer
          identity: uamiId
        }
      ]
    }
    template: {
      revisionSuffix: revisionSuffix
      containers: [
        {
          name: name
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: commonEnv
          probes: role == 'worker' ? [] : [
            {
              type: 'Liveness'
              httpGet: { path: role == 'ui' ? '/' : '/healthz', port: role == 'ui' ? 8080 : 8000 }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: role == 'ui' ? '/' : readinessPath, port: role == 'ui' ? 8080 : 8000 }
              initialDelaySeconds: 5
              periodSeconds: 15
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: role == 'api' ? apiScale : (role == 'ui' ? uiScale : workerScale)
      }
    }
  }
}

output fqdn string = role == 'worker' ? '' : app.properties.configuration.ingress.fqdn
output appId string = app.id
