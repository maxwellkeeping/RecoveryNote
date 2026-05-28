// ─────────────────────────────────────────────────────────────────────────────
// RecoveryNote + client-llm-wiki — Shared Azure infrastructure
//
// Deploy with:
//   az deployment group create \
//     --resource-group <your-rg> \
//     --template-file infra/main.bicep \
//     --parameters infra/main.bicepparam
//
// Copy infra/main.sample.bicepparam → infra/main.bicepparam and fill in secrets.
// Do NOT commit main.bicepparam to source control.
// ─────────────────────────────────────────────────────────────────────────────

@description('Base name used to derive all resource names.')
param appName string = 'recoverynote'

@description('Azure region. Defaults to the resource group\'s location.')
param location string = resourceGroup().location

@description('PostgreSQL administrator login name.')
param postgresAdminUser string = 'pgadmin'

@description('PostgreSQL administrator password. Must not contain @ or ? characters.')
@minLength(8)
@secure()
param postgresAdminPassword string

@description('Flask SECRET_KEY value. Use a long random string (32+ characters recommended).')
@minLength(16)
@secure()
param secretKey string

@description('Object ID of the identity running this deployment. Grants it Key Vault Secrets Officer so secrets can be written during deployment. Get with: az ad signed-in-user show --query id -o tsv. Leave empty if you have already pre-assigned Key Vault Secrets Officer on the vault.')
param deployerObjectId string = ''

@description('PostgreSQL Flexible Server SKU. Change if B1ms capacity is unavailable in your region (e.g. Standard_B2ms).')
@allowed(['Standard_B1ms', 'Standard_B2ms', 'Standard_D2s_v3'])
param postgresSkuName string = 'Standard_B1ms'

@description('Whether to deploy the client-llm-wiki Node.js app alongside RecoveryNote.')
param deployWiki bool = true

@description('NextAuth secret for client-llm-wiki. Use: openssl rand -base64 32')
@secure()
param wikiAuthSecret string = ''

@description('Anthropic API key for client-llm-wiki AI features.')
@secure()
param wikiAnthropicApiKey string = ''

@description('Microsoft Entra application (client) ID used by RecoveryNote SSO.')
param entraClientId string = ''

@description('Microsoft Entra application client secret used by RecoveryNote SSO.')
@secure()
param entraClientSecret string = ''

@description('Microsoft Entra tenant ID used by RecoveryNote SSO.')
param entraTenantId string = ''

@description('Comma-separated list of Entra group object IDs allowed to sign in. Leave empty to allow all tenant users.')
param entraAllowedGroupIds string = ''

@description('Optional callback URL override for Entra sign-in. Leave empty to default to https://<webapp>/auth/callback.')
param entraRedirectUri string = ''

// ── Derived names ──────────────────────────────────────────────────────────────
var suffix         = take(uniqueString(resourceGroup().id), 8)
var planName       = '${appName}-plan'
var webAppName     = '${appName}-${suffix}'
var wikiAppName    = 'clientwiki-${suffix}'
var kvName         = '${take(appName, 10)}-kv-${take(suffix, 6)}'
var pgServerName   = '${take(toLower(appName), 15)}-pg-${suffix}'
var dbName         = 'recoverynote'
var wikiDbName     = 'clientllmwiki'
var loginEndpoint = environment().authentication.loginEndpoint
var resolvedEntraAuthority = empty(entraTenantId) ? '' : '${loginEndpoint}${entraTenantId}/v2.0'
var resolvedEntraRedirectUri = !empty(entraRedirectUri) ? entraRedirectUri : 'https://${webApp.properties.defaultHostName}/auth/callback'

// ── App Service Plan (Linux, B1 Basic — supports both apps with always-on) ───
resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  kind: 'linux'
  sku: {
    name: 'B1'
    tier: 'Basic'
  }
  properties: {
    reserved: true
  }
}

// ── Web App (RecoveryNote — Python/Flask) ──────────────────────────────────────
// App settings are applied in a child config resource below, after KV secrets
// exist and the managed identity has been granted access.
resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: webAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
  }
}

// ── Web App (client-llm-wiki — Node.js/Next.js) ───────────────────────────────
resource wikiApp 'Microsoft.Web/sites@2023-12-01' = if (deployWiki) {
  name: wikiAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'NODE|18-lts'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appCommandLine: 'node server.js'
    }
  }
}

// ── Key Vault ──────────────────────────────────────────────────────────────────
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: false
    softDeleteRetentionInDays: 7
    enableSoftDelete: true
    accessPolicies: concat(
      // Deployer — write secrets during deployment
      !empty(deployerObjectId) ? [
        {
          tenantId: subscription().tenantId
          objectId: deployerObjectId
          permissions: { secrets: [ 'get', 'list', 'set', 'delete' ] }
        }
      ] : [],
      // Web app managed identity — read secrets at runtime
      [
        {
          tenantId: subscription().tenantId
          objectId: webApp.identity.principalId
          permissions: { secrets: [ 'get', 'list' ] }
        }
      ],
      // Wiki app managed identity — read secrets at runtime
      deployWiki ? [
        {
          tenantId: subscription().tenantId
          objectId: wikiApp.?identity.?principalId ?? ''
          permissions: { secrets: [ 'get', 'list' ] }
        }
      ] : []
    )
  }
}

// ── PostgreSQL Flexible Server ─────────────────────────────────────────────────
resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: pgServerName
  location: location
  sku: {
    name: postgresSkuName
    tier: 'Burstable'
  }
  properties: {
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    version: '16'
    storage: {
      storageSizeGB: 32
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
  }
}

resource postgresDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: postgresServer
  name: dbName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource wikiPostgresDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = if (deployWiki) {
  parent: postgresServer
  name: wikiDbName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// Allow all Azure-internal IPs — required for App Service to reach PostgreSQL without VNet.
resource postgresFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = {
  parent: postgresServer
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// ── Key Vault secrets ──────────────────────────────────────────────────────────
// DATABASE_URL is constructed from the provisioned server FQDN — no copy-paste needed.
resource kvSecretDbUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'database-url'
  properties: {
    value: 'postgresql://${postgresAdminUser}:${postgresAdminPassword}@${postgresServer.properties.fullyQualifiedDomainName}:5432/${dbName}?sslmode=require'
  }
}

resource kvSecretAppKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'secret-key'
  properties: {
    value: secretKey
  }
}

resource kvSecretWikiDbUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (deployWiki) {
  parent: keyVault
  name: 'wiki-database-url'
  properties: {
    value: 'postgresql://${postgresAdminUser}:${postgresAdminPassword}@${postgresServer.properties.fullyQualifiedDomainName}:5432/${wikiDbName}?sslmode=require'
  }
}

resource kvSecretWikiAuthSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (deployWiki && !empty(wikiAuthSecret)) {
  parent: keyVault
  name: 'wiki-auth-secret'
  properties: {
    value: wikiAuthSecret
  }
}

resource kvSecretWikiAnthropicKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (deployWiki && !empty(wikiAnthropicApiKey)) {
  parent: keyVault
  name: 'wiki-anthropic-api-key'
  properties: {
    value: wikiAnthropicApiKey
  }
}

resource kvSecretEntraClientId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(entraClientId)) {
  parent: keyVault
  name: 'entra-client-id'
  properties: {
    value: entraClientId
  }
}

resource kvSecretEntraClientSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(entraClientSecret)) {
  parent: keyVault
  name: 'entra-client-secret'
  properties: {
    value: entraClientSecret
  }
}

resource kvSecretEntraTenantId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(entraTenantId)) {
  parent: keyVault
  name: 'entra-tenant-id'
  properties: {
    value: entraTenantId
  }
}

// ── App Settings ───────────────────────────────────────────────────────────────
// Applied after KV secrets exist and the managed identity has been granted access.
// Secrets never appear in plain text — they are Key Vault references resolved at runtime.
resource webAppSettings 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: webApp
  name: 'appsettings'
  properties: {
    // Tells App Service to run pip install on each deployment
    SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'
    DATABASE_URL: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=database-url)'
    SECRET_KEY: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=secret-key)'
    ENTRA_CLIENT_ID: !empty(entraClientId) ? '@Microsoft.KeyVault(VaultName=${kvName};SecretName=entra-client-id)' : ''
    ENTRA_CLIENT_SECRET: !empty(entraClientSecret) ? '@Microsoft.KeyVault(VaultName=${kvName};SecretName=entra-client-secret)' : ''
    ENTRA_TENANT_ID: !empty(entraTenantId) ? '@Microsoft.KeyVault(VaultName=${kvName};SecretName=entra-tenant-id)' : ''
    ENTRA_AUTHORITY: resolvedEntraAuthority
    ENTRA_ALLOWED_GROUP_IDS: entraAllowedGroupIds
    ENTRA_REDIRECT_URI: resolvedEntraRedirectUri
  }
  dependsOn: [
    keyVault
    kvSecretDbUrl
    kvSecretAppKey
    kvSecretEntraClientId
    kvSecretEntraClientSecret
    kvSecretEntraTenantId
  ]
}

resource wikiAppSettings 'Microsoft.Web/sites/config@2023-12-01' = if (deployWiki) {
  parent: wikiApp
  name: 'appsettings'
  properties: {
    SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'
    DATABASE_URL: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=wiki-database-url)'
    AUTH_SECRET: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=wiki-auth-secret)'
    ANTHROPIC_API_KEY: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=wiki-anthropic-api-key)'
    NEXTAUTH_URL: 'https://${wikiAppName}.azurewebsites.net'
  }
  dependsOn: [
    keyVault
    kvSecretWikiDbUrl
    kvSecretWikiAuthSecret
    kvSecretWikiAnthropicKey
  ]
}

// ── Outputs ────────────────────────────────────────────────────────────────────
output webAppUrl string = 'https://${webApp.properties.defaultHostName}'
output webAppName string = webApp.name
output wikiAppUrl string = deployWiki ? 'https://${wikiApp.?properties.?defaultHostName ?? ''}' : ''
output wikiAppName string = deployWiki ? wikiApp.name! : ''
output keyVaultName string = keyVault.name
output postgresServerFqdn string = postgresServer.properties.fullyQualifiedDomainName
