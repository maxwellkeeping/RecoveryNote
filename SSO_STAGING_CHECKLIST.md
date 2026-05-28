# RecoveryNote SSO Staging Runbook

This format is optimized for quick completion during setup.

## 1) Quick Fill Sheet

Complete this first.
| Field | Your Value |
|---|---|
| Staging App URL |https://recoverynote-gyjdtex5-staging.azurewebsites.net |
| Callback URL (`https://recoverynote-gyjdtex5-staging.azurewebsites.net/auth/callback`) |https://recoverynote-gyjdtex5-staging.azurewebsites.net/auth/callback|
| Entra App Name |recoverynote-staging-sso |
| Application (Client) ID |a735f573-2c7a-4182-91e9-e8675cdb3f82 |
| Directory (Tenant) ID | cddc1229-ac2a-4b97-b78a-0e5cacb5865c|
| Client Secret Value | <IN_KEY_VAULT_ONLY_ROTATE_SECRET> |
| Allowed Group Names | |
| Allowed Group Object IDs (comma-separated) | |

## 2) Portal Checklist

- [ ] App registration created (single-tenant)
- [ ] Redirect URI added (Web): `<staging-url>/auth/callback`
- [ ] Client secret created and copied
- [ ] API permissions added: `openid`, `profile`, `email`, `User.Read`
- [ ] Admin consent granted
- [ ] Groups claim added to ID token
- [ ] Access group(s) created/selected
- [ ] Pilot users assigned to access group(s)
- [ ] Local break-glass admin login verified

## 3) Deployment Values (Copy/Paste)

Paste these into `infra/main.bicepparam` for staging:

```bicep
param entraClientId = '<CLIENT_ID>'
param entraClientSecret = '<CLIENT_SECRET_VALUE>'
param entraTenantId = '<TENANT_ID>'
param entraAllowedGroupIds = '<GROUP_OBJECT_ID_1>,<GROUP_OBJECT_ID_2>'
param entraRedirectUri = ''
```

Notes:
- Leave `entraRedirectUri` empty to auto-use `https://<webapp>/auth/callback`.
- Use explicit `entraRedirectUri` only if your callback differs.

## 4) Validation Checklist

- [ ] Entra redirect URI exactly matches callback endpoint
- [ ] Allowed user in group can sign in on staging
- [ ] User not in group is denied
- [ ] Local admin can still sign in (break-glass)
- [ ] `/logout` clears session and protected routes require auth again

## 5) Run Notes

Date:

Operator:

Staging URL tested:

Result:

Follow-ups:
