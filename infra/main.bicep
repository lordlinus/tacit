// foundry-memory infra: AI Search (the memory store) + Flex Consumption
// Functions (the serverless MCP runtime), wired keyless via managed identity.
targetScope = 'resourceGroup'

@minLength(1)
@maxLength(20)
@description('Short name seed for all resources.')
param environmentName string

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('AI Search SKU. No consumption SKU exists for AI Search; basic is the cheapest production tier, free works for dev (one per subscription).')
@allowed(['free', 'basic', 'standard'])
param searchSku string = 'basic'

@description('Project slug baked into the function app settings (one index pair per project).')
param project string = 'contoso-payments'

@description('Object id of the developer running azd, granted search data access for seeding/provisioning.')
param deployerPrincipalId string = ''

var suffix = toLower(uniqueString(resourceGroup().id, environmentName))
var searchName = 'srch-${environmentName}-${suffix}'
var funcName = 'func-${environmentName}-${suffix}'
var planName = 'plan-${environmentName}-${suffix}'
var storageName = toLower(replace('st${environmentName}${suffix}', '-', ''))

// Search Service Contributor (manage indexes) + Search Index Data Contributor (read/write docs)
var roleSearchServiceContributor = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
var roleSearchIndexDataContributor = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
var roleStorageBlobDataOwner = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b')

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: searchName
  location: location
  sku: { name: searchSku }
  properties: {
    replicaCount: 1
    partitionCount: 1
    // Keyless-first: Entra tokens accepted; api keys stay possible for portal tooling.
    authOptions: { aadOrApiKey: { aadAuthFailureMode: 'http401WithBearerChallenge' } }
    semanticSearch: searchSku == 'free' ? 'disabled' : 'free'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take(storageName, 24)
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
  }
}

resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  name: '${storage.name}/default/function-deployments'
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  kind: 'functionapp'
  sku: { tier: 'FlexConsumption', name: 'FC1' }
  properties: { reserved: true }
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: funcName
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}function-deployments'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      runtime: { name: 'python', version: '3.12' }
      scaleAndConcurrency: { maximumInstanceCount: 40, instanceMemoryMB: 2048 }
    }
    siteConfig: {
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'FOUNDRY_MEMORY_BACKEND', value: 'search' }
        { name: 'FOUNDRY_MEMORY_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
        { name: 'FOUNDRY_MEMORY_PROJECT', value: project }
      ]
    }
  }
}

// Function MI: read/write memory docs + create indexes on first run.
resource funcSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, functionApp.id, 'search-data')
  scope: search
  properties: {
    roleDefinitionId: roleSearchIndexDataContributor
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource funcSearchService 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, functionApp.id, 'search-service')
  scope: search
  properties: {
    roleDefinitionId: roleSearchServiceContributor
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource funcStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, functionApp.id, 'blob-owner')
  scope: storage
  properties: {
    roleDefinitionId: roleStorageBlobDataOwner
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// The developer seeding/provisioning from their machine (az login identity).
resource deployerSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(search.id, deployerPrincipalId, 'search-data')
  scope: search
  properties: {
    roleDefinitionId: roleSearchIndexDataContributor
    principalId: deployerPrincipalId
  }
}

resource deployerSearchService 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(search.id, deployerPrincipalId, 'search-service')
  scope: search
  properties: {
    roleDefinitionId: roleSearchServiceContributor
    principalId: deployerPrincipalId
  }
}

output SEARCH_ENDPOINT string = 'https://${search.name}.search.windows.net'
output FUNCTION_APP_NAME string = functionApp.name
output MCP_SSE_ENDPOINT string = 'https://${functionApp.properties.defaultHostName}/runtime/webhooks/mcp/sse'
