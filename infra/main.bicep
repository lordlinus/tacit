// tacit infra: AI Search (the organization-wide memory store) + Flex
// Consumption Functions (the serverless MCP runtime), wired keyless via
// managed identity.
//
// One search service holds every team's memory in one shared index set, so
// this deploys once per organization rather than once per team; the index
// count no longer grows with the number of projects onboarded.
targetScope = 'resourceGroup'

@minLength(1)
@maxLength(20)
@description('Short name seed for all resources.')
param environmentName string

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('''AI Search SKU. Default is the consumption-based Serverless tier
(preview): pay per Compute Unit + GB stored, no capacity to provision — but
preview-only regions (westcentralus, switzerlandnorth, japaneast), no SLA, and
no migration to/from dedicated tiers. Use basic/standard for production or
other regions; free for throwaway dev (one per subscription).''')
@allowed(['serverless', 'free', 'basic', 'standard'])
param searchSku string = 'serverless'

@description('''Default project slug for callers that do not pass one. Agents
normally pass `project` on every call, so this is only the fallback; it is not
a per-team setting and does not need changing to onboard a new repo.''')
param project string = 'default'

@description('''Team that memories written through this runtime are attributed
to. Used for `visibility: team` memories. Note this is a *shared* default: the
Functions endpoint authenticates with one system key, so it cannot tell callers
apart. Per-engineer attribution requires the stdio variant, where each person
sets TACIT_TEAM themselves.''')
param team string = ''

@description('''Endpoint of an EXISTING Azure OpenAI or Foundry resource that
already has an embedding model deployed. Set this to reuse what you have; the
template then creates no Azure OpenAI account, and you grant `Cognitive Services
OpenAI User` on that resource to the Function App identity and to the search
service identity yourself (both object ids are template outputs).''')
param embeddingEndpoint string = ''

@description('''Embedding model deployed for hybrid (keyword + vector) search.
Set to an empty string, with no embeddingEndpoint, to skip embeddings entirely:
retrieval then falls back to BM25 + semantic reranking, which needs no second
resource and no per-call cost. Turning it on later is a redeploy plus
`tacit reindex`.''')
param embeddingModel string = 'text-embedding-3-small'

@description('Embedding dimensions. text-embedding-3-* support truncation; 1536 is the accuracy/size knee.')
param embeddingDimensions int = 1536

@description('Object id of the developer running azd, granted search data access for seeding/provisioning.')
param deployerPrincipalId string = ''

@description('''Region for Application Insights and its Log Analytics
workspace. Deliberately separate from `location`: the AI Search Serverless
preview pins the rest of the stack to westcentralus / switzerlandnorth /
japaneast, and Application Insights is not offered in westcentralus. Telemetry
is region-independent, so this costs nothing but a parameter.''')
param monitoringLocation string = 'westus2'

var suffix = toLower(uniqueString(resourceGroup().id, environmentName))
var searchName = 'srch-${environmentName}-${suffix}'
var funcName = 'func-${environmentName}-${suffix}'
var planName = 'plan-${environmentName}-${suffix}'
var storageName = toLower(replace('st${environmentName}${suffix}', '-', ''))
var openAiName = 'aoai-${environmentName}-${suffix}'
var createOpenAi = empty(embeddingEndpoint) && !empty(embeddingModel)
var resolvedEmbeddingEndpoint = !empty(embeddingEndpoint)
  ? embeddingEndpoint
  : (createOpenAi ? openAi!.properties.endpoint : '')

// Search Service Contributor (manage indexes) + Search Index Data Contributor (read/write docs)
var roleSearchServiceContributor = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
var roleSearchIndexDataContributor = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
var roleStorageBlobDataOwner = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b')
// The MCP extension uses host-storage queues (identity-based connection).
var roleStorageQueueDataContributor = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', '974c5e8b-45b9-4653-ba55-5f855dd0fb88')
var roleStorageQueueMessageProcessor = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', '8a0f0c08-91a1-4084-bc3d-661d67233fed')
// Cognitive Services OpenAI User: call the embedding deployment, nothing else.
var roleCognitiveServicesOpenAIUser = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')

resource search 'Microsoft.Search/searchServices@2026-03-01-preview' = {
  name: searchName
  location: location
  sku: { name: searchSku }
  // The query-time vectorizer calls the embedding model as the search service
  // itself, so the service needs an identity even though nothing else here does.
  identity: { type: 'SystemAssigned' }
  // Fully keyless: disableLocalAuth rejects api-keys outright - Entra RBAC is
  // the only way in (mutually exclusive with authOptions, so none is set).
  // Serverless manages capacity itself - replica/partition counts must be omitted.
  properties: searchSku == 'serverless'
    ? {
        disableLocalAuth: true
      }
    : {
        disableLocalAuth: true
        replicaCount: 1
        partitionCount: 1
        semanticSearch: searchSku == 'free' ? 'disabled' : 'free'
      }
}

// Embeddings for the vector half of hybrid search. Keyless like the rest:
// local auth is disabled, so the Functions MI and the developer reach it only
// through Entra RBAC.
resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' = if (createOpenAi) {
  name: openAiName
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: openAiName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource embedding 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (createOpenAi) {
  parent: openAi
  name: embeddingModel
  sku: { name: 'Standard', capacity: 50 }
  properties: {
    model: { format: 'OpenAI', name: embeddingModel, version: '1' }
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take(storageName, 24)
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false // identity-only, matching the keyless posture
    minimumTlsVersion: 'TLS1_2'
    // Not public, not fully closed: access is governed by the Network
    // Security Perimeter below (subscription-inbound rule), which is what
    // lets azd and the Functions host reach the deployment container in
    // policy-locked subscriptions that forbid public storage endpoints.
    publicNetworkAccess: 'SecuredByPerimeter'
  }
}

resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  name: '${storage.name}/default/function-deployments'
}

resource perimeter 'Microsoft.Network/networkSecurityPerimeters@2024-07-01' = {
  name: 'nsp-${environmentName}-${suffix}'
  location: location
}

resource perimeterProfile 'Microsoft.Network/networkSecurityPerimeters/profiles@2024-07-01' = {
  parent: perimeter
  name: 'profile-storage'
}

// Allow inbound only from identities in this subscription - no IPs, no keys.
resource perimeterInbound 'Microsoft.Network/networkSecurityPerimeters/profiles/accessRules@2024-07-01' = {
  parent: perimeterProfile
  name: 'allow-subscription-inbound'
  properties: {
    direction: 'Inbound'
    subscriptions: [
      { id: subscription().id }
    ]
  }
}

resource perimeterStorageAssociation 'Microsoft.Network/networkSecurityPerimeters/resourceAssociations@2024-07-01' = {
  parent: perimeter
  name: 'assoc-storage'
  properties: {
    privateLinkResource: { id: storage.id }
    profile: { id: perimeterProfile.id }
    accessMode: 'Learning'
  }
  dependsOn: [perimeterInbound]
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${environmentName}-${suffix}'
  location: monitoringLocation
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// Without this, a failing MCP invocation surfaces to the client as an opaque
// JSON-RPC -32603 and there is nowhere to look. Telemetry is not optional for
// a server whose only interface is a protocol.
resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${environmentName}-${suffix}'
  location: monitoringLocation
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
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
  tags: { 'azd-service-name': 'api' } // how azd deploy finds its target
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
      // 3.12 is what the remote Oryx build actually resolves, so pinning
      // higher here only desynchronises the two. Consequence: azure-functions
      // stays on 1.x (2.x needs >=3.13), so `mcp_prompt_trigger` is
      // unavailable and MCP prompts work over stdio but not over HTTP. The
      // setup workflow is therefore delivered as a *tool*, which every client
      // and every transport supports. See DESIGN.md.
      runtime: { name: 'python', version: '3.12' }
      scaleAndConcurrency: { maximumInstanceCount: 40, instanceMemoryMB: 2048 }
    }
    siteConfig: {
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
        { name: 'TACIT_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
        { name: 'TACIT_PROJECT', value: project }
        { name: 'TACIT_TEAM', value: team }
        { name: 'TACIT_EMBEDDING_ENDPOINT', value: resolvedEmbeddingEndpoint }
        { name: 'TACIT_EMBEDDING_DEPLOYMENT', value: embeddingModel }
        { name: 'TACIT_EMBEDDING_MODEL', value: embeddingModel }
        { name: 'TACIT_EMBEDDING_DIMENSIONS', value: string(embeddingDimensions) }
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

resource funcStorageQueue 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, functionApp.id, 'queue-contributor')
  scope: storage
  properties: {
    roleDefinitionId: roleStorageQueueDataContributor
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource funcStorageQueueMessages 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, functionApp.id, 'queue-messages')
  scope: storage
  properties: {
    roleDefinitionId: roleStorageQueueMessageProcessor
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// The developer seeding/provisioning from their machine (az login identity).
resource funcOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (createOpenAi) {
  name: guid(openAi.id, functionApp.id, 'openai-user')
  scope: openAi
  properties: {
    roleDefinitionId: roleCognitiveServicesOpenAIUser
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// The search service embeds queries itself (integrated vectorization).
resource searchOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (createOpenAi) {
  name: guid(openAi.id, search.id, 'openai-user')
  scope: openAi
  properties: {
    roleDefinitionId: roleCognitiveServicesOpenAIUser
    principalId: search.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// `tacit seed` and `tacit reindex` embed from the developer's machine.
resource deployerOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (createOpenAi && !empty(deployerPrincipalId)) {
  name: guid(openAi.id, deployerPrincipalId, 'openai-user')
  scope: openAi
  properties: {
    roleDefinitionId: roleCognitiveServicesOpenAIUser
    principalId: deployerPrincipalId
  }
}

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

// azd deploy uploads the package zip with the developer's own identity.
resource deployerStorageBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(storage.id, deployerPrincipalId, 'blob-contributor')
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: deployerPrincipalId
  }
}

output SEARCH_ENDPOINT string = 'https://${search.name}.search.windows.net'
output FUNCTION_APP_NAME string = functionApp.name
output TACIT_EMBEDDING_ENDPOINT string = resolvedEmbeddingEndpoint
output TACIT_EMBEDDING_DEPLOYMENT string = embeddingModel
// Grant these Cognitive Services OpenAI User on your resource when you supply
// an existing embeddingEndpoint; the template cannot assign roles outside it.
output FUNCTION_APP_PRINCIPAL_ID string = functionApp.identity.principalId
output SEARCH_PRINCIPAL_ID string = search.identity.principalId
// Streamable HTTP transport (SSE at /runtime/webhooks/mcp/sse is deprecated).
output MCP_ENDPOINT string = 'https://${functionApp.properties.defaultHostName}/runtime/webhooks/mcp'
