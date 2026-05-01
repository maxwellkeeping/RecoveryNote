// Sample parameters file for RecoveryNote + client-llm-wiki Bicep deployment.
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
param postgresAdminPassword = '<REPLACE_WITH_SECURE_PASSWORD>'

// Flask SECRET_KEY — generate a strong random string, e.g.:
//   python -c "import secrets; print(secrets.token_hex(32))"
param secretKey = '<REPLACE_WITH_RANDOM_HEX>'

// PostgreSQL SKU — change to 'Standard_B2ms' if B1ms capacity is unavailable in your region.
param postgresSkuName = 'Standard_B1ms'

// Your Azure AD object ID — needed to write secrets to Key Vault during deploy.
// Get it with: az ad signed-in-user show --query id -o tsv
// Leave as empty string '' if you pre-assign Key Vault Secrets Officer manually.
param deployerObjectId = '<YOUR_OBJECT_ID>'

// ── client-llm-wiki settings ──────────────────────────────────────────────────
// Set to false to skip deploying the wiki app
param deployWiki = true

// NextAuth secret — generate with: openssl rand -base64 32
param wikiAuthSecret = '<REPLACE_WITH_AUTH_SECRET>'

// Anthropic API key for AI features
param wikiAnthropicApiKey = '<REPLACE_WITH_ANTHROPIC_KEY>'
