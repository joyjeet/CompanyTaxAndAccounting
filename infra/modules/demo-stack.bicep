// ----------------------------------------------------------------------------
// demo-stack.bicep
// Resource-group-scoped child for main-demo.bicep. Owns every concrete
// resource in the ephemeral demo deployment.
// ----------------------------------------------------------------------------
param location string
param tags object
param names object
param apiImage string
param uiImage string
param acrLoginServer string

@description('Resource ID of the pre-created User Assigned Managed Identity that is granted AcrPull on the registry.')
param uamiId string

@secure()
param postgresAdminPassword string

@secure()
param appTestJwtSecret string

// ---------------------------------------------------------------------------
// Monitoring
// ---------------------------------------------------------------------------
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: names.logAnalytics
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: names.appInsights
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

// ---------------------------------------------------------------------------
// Postgres — public access, smallest Burstable SKU, no HA.
// Random suffix in the name means it never collides with an old soft-deleted
// instance.
// ---------------------------------------------------------------------------
resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: names.postgres
  location: location
  tags: tags
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: 'ctaa_owner'
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 32, autoGrow: 'Disabled' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: {
      // Public access on. We open a firewall rule below for Azure services
      // and the deploy script will add the operator's public IP at runtime.
      publicNetworkAccess: 'Enabled'
    }
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
      tenantId: subscription().tenantId
    }
  }
}

// Force RLS to play nicely with `ctaa_owner` running the migrations and
// then `app_user` running the API. Without `row_security = on` the owner
// would bypass policies even with FORCE RLS, which would break our tenant
// isolation invariants.
resource pgRowSecurity 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  name: 'row_security'
  parent: pg
  properties: { value: 'on', source: 'user-override' }
}

// Allow other Azure services (i.e. the Container Apps env) to reach the
// server. This is the documented "AllowAllAzureServicesAndResourcesWithinAzureIps"
// firewall rule.
resource pgFwAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps'
  parent: pg
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
  dependsOn: [ pgRowSecurity ]
}

resource pgDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  name: 'ctaa'
  parent: pg
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  dependsOn: [ pgFwAzure ]
}

// ---------------------------------------------------------------------------
// Container Apps environment + apps
// ---------------------------------------------------------------------------
resource cae 'Microsoft.App/managedEnvironments@2024-10-02-preview' = {
  name: names.containerEnv
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
    // No VNet config — public env.
  }
}

var pgFqdn = pg.properties.fullyQualifiedDomainName
// app_user runtime role created by the bootstrap script. Password is the
// same as the admin password — this is an ephemeral demo, not prod.
var databaseUrl       = 'postgresql+psycopg://app_user:${postgresAdminPassword}@${pgFqdn}:5432/ctaa?sslmode=require'
var databaseOwnerUrl  = 'postgresql+psycopg://ctaa_owner:${postgresAdminPassword}@${pgFqdn}:5432/ctaa?sslmode=require'

resource apiApp 'Microsoft.App/containerApps@2024-10-02-preview' = {
  name: names.apiApp
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uamiId}': {} }
  }
  properties: {
    environmentId: cae.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
        traffic: [ { latestRevision: true, weight: 100 } ]
        corsPolicy: {
          allowedOrigins: [ '*' ]
          allowedMethods: [ 'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS' ]
          allowedHeaders: [ '*' ]
          allowCredentials: false
        }
      }
      maxInactiveRevisions: 2
      registries: [
        { server: acrLoginServer, identity: uamiId }
      ]
      secrets: [
        { name: 'database-url',       value: databaseUrl }
        { name: 'database-owner-url', value: databaseOwnerUrl }
        { name: 'app-test-jwt-secret', value: appTestJwtSecret }
      ]
    }
    template: {
      revisionSuffix: take(uniqueString(apiImage, 'api'), 10)
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          // Run the idempotent bootstrap (CREATE ROLE app_user + alembic
          // upgrade + seed demo data) BEFORE handing off to uvicorn. This
          // way the container is self-contained and the deploy script just
          // needs to scrape the logs for the seed IDs.
          command: [ '/bin/sh', '-c' ]
          args: [
            'python -m scripts.bootstrap_for_demo && exec uvicorn app.main:app --host 0.0.0.0 --port 8000'
          ]
          env: [
            { name: 'APP_ENV',                value: 'staging' }
            { name: 'APP_AUTH_MODE',          value: 'test' }
            { name: 'APP_KEK_PROVIDER',       value: 'local' }
            { name: 'APP_CORS_ORIGINS',       value: '*' }
            { name: 'APP_LOG_LEVEL',          value: 'INFO' }
            { name: 'DATABASE_URL',           secretRef: 'database-url' }
            { name: 'DATABASE_OWNER_URL',     secretRef: 'database-owner-url' }
            { name: 'APP_TEST_JWT_SECRET',    secretRef: 'app-test-jwt-secret' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString }
            { name: 'OTEL_SERVICE_NAME',      value: names.apiApp }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8000 }
              initialDelaySeconds: 15
              periodSeconds: 30
            }
            // Use /healthz (no DB) for readiness too, so the API container
            // stays in rotation BEFORE the bootstrap script creates app_user.
            // /readyz would block forever otherwise.
            {
              type: 'Readiness'
              httpGet: { path: '/healthz', port: 8000 }
              initialDelaySeconds: 5
              periodSeconds: 15
            }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 2 }
    }
  }
  dependsOn: [ pgDb ]
}

resource uiApp 'Microsoft.App/containerApps@2024-10-02-preview' = {
  name: names.uiApp
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${uamiId}': {} }
  }
  properties: {
    environmentId: cae.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
        traffic: [ { latestRevision: true, weight: 100 } ]
      }
      maxInactiveRevisions: 2
      registries: [
        { server: acrLoginServer, identity: uamiId }
      ]
    }
    template: {
      revisionSuffix: take(uniqueString(uiImage, 'ui'), 10)
      containers: [
        {
          name: 'ui'
          image: uiImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8080 }
              initialDelaySeconds: 5
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/healthz', port: 8080 }
              initialDelaySeconds: 2
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

output postgresFqdn string = pgFqdn
output apiFqdn      string = apiApp.properties.configuration.ingress.fqdn
output uiFqdn       string = uiApp.properties.configuration.ingress.fqdn
