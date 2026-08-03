// ----------------------------------------------------------------------------
// migrationjob.bicep
// Manually-triggered Container Apps Job that runs `alembic upgrade head`.
//
// This runs INSIDE the container environment's VNet, which is the only place
// the Postgres flexible server is reachable from. CD starts this job after
// every deploy and fails the pipeline if the job does not succeed — schema
// drift must never pass silently.
// ----------------------------------------------------------------------------
param location string
param name string
param tags object
param environmentId string
param uamiId string
param uamiClientId string
param image string

@description('Postgres FQDN — passed as a plain env var (not a secret).')
param postgresFqdn string
@description('Postgres database name.')
param postgresDatabase string = 'ctaa'
@secure()
@description('Postgres admin password used to compose the owner DB URL.')
param postgresAdminPassword string

@description('Key Vault URI, so the job resolves the same KEK provider as the apps.')
param keyVaultUri string

@description('ACR login server. The caller must grant AcrPull on the UAMI first.')
param acrLoginServer string = ''

@description('Seconds a single replica may run before it is considered failed.')
param replicaTimeoutSeconds int = 1800

var databaseUrl = 'postgresql+psycopg://app_user:${postgresAdminPassword}@${postgresFqdn}:5432/${postgresDatabase}?sslmode=require'
var databaseOwnerUrl = 'postgresql+psycopg://ctaa_owner:${postgresAdminPassword}@${postgresFqdn}:5432/${postgresDatabase}?sslmode=require'

resource job 'Microsoft.App/jobs@2024-10-02-preview' = {
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
      triggerType: 'Manual'
      // Migrations are not idempotent under concurrency — exactly one replica,
      // and no automatic retry (a half-applied migration must be inspected by
      // a human rather than blindly re-run).
      replicaTimeout: replicaTimeoutSeconds
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      secrets: [
        {
          name: 'database-url'
          value: databaseUrl
        }
        {
          name: 'database-owner-url'
          value: databaseOwnerUrl
        }
      ]
      registries: empty(acrLoginServer) ? [] : [
        {
          server: acrLoginServer
          identity: uamiId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: image
          command: [ 'alembic' ]
          args: [ 'upgrade', 'head' ]
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'APP_ENV',              value: 'prod' }
            { name: 'APP_KEK_PROVIDER',     value: 'keyvault' }
            { name: 'AZURE_KEYVAULT_URL',   value: keyVaultUri }
            { name: 'AZURE_CLIENT_ID',      value: uamiClientId }
            { name: 'POSTGRES_FQDN',        value: postgresFqdn }
            { name: 'POSTGRES_DATABASE',    value: postgresDatabase }
            { name: 'DATABASE_URL',         secretRef: 'database-url' }
            { name: 'DATABASE_OWNER_URL',   secretRef: 'database-owner-url' }
          ]
        }
      ]
    }
  }
}

output jobName string = job.name
output jobId string = job.id
