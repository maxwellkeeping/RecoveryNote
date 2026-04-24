// Sample parameters file for RecoveryNote Bicep deployment.
// Copy this file to main.bicepparam and fill in the secret values.
// Do NOT commit main.bicepparam to source control.

using './main.bicep'

// ── Customise these ───────────────────────────────────────────────────────────

// Base name for all resources (keep it short — max ~15 chars)
param appName = 'recoverynote'

// Azure region — change if you want a different region
// param location = 'canadacentral'

// PostgreSQL admin credentials
// Password must NOT contain @ or ? characters
param postgresAdminUser = 'pgadmin'
param postgresAdminPassword = 'Maxtheax12!'

// Flask SECRET_KEY — generate a strong random string, e.g.:
//   python -c "import secrets; print(secrets.token_hex(32))"
param secretKey = '0620fdaf020347b606b6efc478aab070732d50e470d52c7baac95509886ccd20'

// PostgreSQL SKU — change to 'Standard_B2ms' if B1ms capacity is unavailable in your region.
param postgresSkuName = 'Standard_B1ms'

// Your Azure AD object ID — needed to write secrets to Key Vault during deploy.
// Get it with: az ad signed-in-user show --query id -o tsv
// Leave as empty string '' if you pre-assign Key Vault Secrets Officer manually.
param deployerObjectId = '158d2a0b-08f6-44d3-b9bb-51c4897f6112'
