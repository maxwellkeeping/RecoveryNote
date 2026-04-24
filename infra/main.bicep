// ─────────────────────────────────────────────────────────────────────────────
// RecoveryNote — Azure infrastructure
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

// ── Derived names ──────────────────────────────────────────────────────────────
var suffix       = take(uniqueString(resourceGroup().id), 8)
var planName     = '${appName}-plan'
var webAppName   = '${appName}-${suffix}'
var kvName       = '${take(appName, 10)}-kv-${take(suffix, 6)}'
var pgServerName = '${take(toLower(appName), 15)}-pg-${suffix}'
var dbName       = 'recoverynote'

// ── Well-known role definition IDs ─────────────────────────────────────────────
var kvSecretsUserRoleId    = '4633458b-17de-408a-b874-0445c86b69e6' // Key Vault Secrets User
var kvSecretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7' // Key Vault Secrets Officer

// ── App Service Plan (Linux, F1 Free) ─────────────────────────────────────────
resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  kind: 'linux'
  sku: {
    name: 'F1'
    tier: 'Free'
  }
  properties: {
    reserved: true
  }
}

// ── Web App ────────────────────────────────────────────────────────────────────
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
      appCommandLine: 'gunicorn --bind=0.0.0.0 --timeout=120 --workers=2 app:app'
      alwaysOn: false      // required for F1 Free tier
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
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
    enableRbacAuthorization: true
    softDeleteRetentionInDays: 7
    enableSoftDelete: true
  }
}

// ── Role: deploying identity → Secrets Officer (write secrets during deploy) ───
// Only created when deployerObjectId is provided.
resource kvDeployerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerObjectId)) {
  name: guid(keyVault.id, deployerObjectId, kvSecretsOfficerRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsOfficerRoleId)
    principalId: deployerObjectId
    principalType: 'User'
  }
}

// ── Role: web app managed identity → Secrets User (read secrets at runtime) ───
resource kvWebAppRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, webApp.id, kvSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRoleId)
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
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
  dependsOn: [kvDeployerRole]
}

resource kvSecretAppKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'secret-key'
  properties: {
    value: secretKey
  }
  dependsOn: [kvDeployerRole]
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
  }
  dependsOn: [
    kvWebAppRole
    kvSecretDbUrl
    kvSecretAppKey
  ]
}

// ── Outputs ────────────────────────────────────────────────────────────────────
output webAppUrl string = 'https://${webApp.properties.defaultHostName}'
output webAppName string = webApp.name
output keyVaultName string = keyVault.name
output postgresServerFqdn string = postgresServer.properties.fullyQualifiedDomainName
