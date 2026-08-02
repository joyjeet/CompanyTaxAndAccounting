// ----------------------------------------------------------------------------
// frontdoor.bicep
// Azure Front Door Premium + WAF policy.
//   * Premium SKU is required to attach a Private Link origin (Container
//     Apps environment with internal-only ingress).
//   * WAF policy in Prevention mode for prod; Detection mode for non-prod
//     (controlled by `wafMode`).
//   * Managed rule sets: DRS 2.1 + Bot Manager 1.0.
//   * Rate-limiting custom rule on the /auth/* path.
// ----------------------------------------------------------------------------
param afdName string
param wafPolicyName string
param tags object
param originHostName string
@description('Origin private link service id, optional. When set, the origin is reached via Private Link.')
param originPrivateLinkResourceId string = ''
@description('Approval message displayed in the PLS approval workflow.')
param originPrivateLinkRequestMessage string = 'Azure Front Door access for CTAA'
@allowed([ 'Detection', 'Prevention' ])
param wafMode string = 'Prevention'

resource afd 'Microsoft.Cdn/profiles@2024-09-01' = {
  name: afdName
  location: 'global'
  tags: tags
  sku: { name: 'Premium_AzureFrontDoor' }
}

resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2024-09-01' = {
  name: '${afdName}-ep'
  parent: afd
  location: 'global'
  tags: tags
  properties: { enabledState: 'Enabled' }
}

resource originGroup 'Microsoft.Cdn/profiles/originGroups@2024-09-01' = {
  name: 'origin-group'
  parent: afd
  properties: {
    loadBalancingSettings: {
      sampleSize: 4
      successfulSamplesRequired: 3
    }
    healthProbeSettings: {
      probePath: '/healthz'
      probeProtocol: 'Https'
      probeRequestType: 'GET'
      probeIntervalInSeconds: 30
    }
  }
}

resource origin 'Microsoft.Cdn/profiles/originGroups/origins@2024-09-01' = {
  name: 'app-origin'
  parent: originGroup
  properties: {
    hostName: originHostName
    httpPort: 80
    httpsPort: 443
    originHostHeader: originHostName
    priority: 1
    weight: 1000
    enforceCertificateNameCheck: true
    sharedPrivateLinkResource: empty(originPrivateLinkResourceId) ? null : {
      privateLink: { id: originPrivateLinkResourceId }
      groupId: 'managedEnvironments'
      privateLinkLocation: resourceGroup().location
      requestMessage: originPrivateLinkRequestMessage
    }
  }
}

resource waf 'Microsoft.Network/FrontDoorWebApplicationFirewallPolicies@2024-02-01' = {
  name: wafPolicyName
  location: 'global'
  tags: tags
  sku: { name: 'Premium_AzureFrontDoor' }
  properties: {
    policySettings: {
      enabledState: 'Enabled'
      mode: wafMode
      requestBodyCheck: 'Enabled'
    }
    managedRules: {
      managedRuleSets: [
        { ruleSetType: 'DefaultRuleSet', ruleSetVersion: '2.1', ruleSetAction: 'Block' }
        { ruleSetType: 'BotProtection', ruleSetVersion: '1.0', ruleSetAction: 'Block' }
      ]
    }
    customRules: {
      rules: [
        {
          name: 'authRateLimit'
          priority: 100
          ruleType: 'RateLimitRule'
          rateLimitDurationInMinutes: 1
          rateLimitThreshold: 30
          matchConditions: [
            {
              matchVariable: 'RequestUri'
              operator: 'Contains'
              matchValue: [ '/auth/' ]
            }
          ]
          action: 'Block'
        }
        {
          name: 'uploadRateLimit'
          priority: 110
          ruleType: 'RateLimitRule'
          rateLimitDurationInMinutes: 1
          rateLimitThreshold: 60
          matchConditions: [
            {
              matchVariable: 'RequestUri'
              operator: 'Contains'
              matchValue: [ '/documents/upload' ]
            }
          ]
          action: 'Block'
        }
      ]
    }
  }
}

resource policy 'Microsoft.Cdn/profiles/securityPolicies@2024-09-01' = {
  name: 'waf-association'
  parent: afd
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: { id: waf.id }
      associations: [
        {
          domains: [ { id: endpoint.id } ]
          patternsToMatch: [ '/*' ]
        }
      ]
    }
  }
}

resource route 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-09-01' = {
  name: 'default-route'
  parent: endpoint
  properties: {
    originGroup: { id: originGroup.id }
    supportedProtocols: [ 'Https' ]
    patternsToMatch: [ '/*' ]
    forwardingProtocol: 'HttpsOnly'
    httpsRedirect: 'Enabled'
    linkToDefaultDomain: 'Enabled'
  }
  dependsOn: [ origin ]
}

output endpointHostName string = endpoint.properties.hostName
output frontDoorId string = afd.id
output wafPolicyId string = waf.id
