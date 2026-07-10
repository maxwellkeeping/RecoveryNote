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
| Allowed Group Names |ITOD CRM Internal |
| Allowed Group Object IDs (comma-separated) |f20c6526-f50e-4078-b0d5-9549bb5c23de |

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

- [x] Entra redirect URI exactly matches callback endpoint
- [ ] Allowed user in group can sign in on staging
- [ ] User not in group is denied
- [ ] Local admin can still sign in (break-glass)
- [ ] `/logout` clears session and protected routes require auth again

## 5) Run Notes

Date: 2026-06-30

Operator: GitHub Copilot (automated smoke test)

Staging URL tested: https://recoverynote-gyjdtex5-staging.azurewebsites.net

Result: PARTIAL PASS (automated unauthenticated + redirect checks passed)

Automated checks completed:
- PASS: `/` redirects to `/login`
- PASS: `/login` returns 200
- PASS: Microsoft sign-in option is visible on login page
- PASS: Local username/password fields are visible on login page
- PASS: `/auth/login` redirects to Microsoft tenant `cddc1229-ac2a-4b97-b78a-0e5cacb5865c`
- PASS: `/auth/login` uses client id `a735f573-2c7a-4182-91e9-e8675cdb3f82`
- PASS: `/auth/login` uses redirect URI `https://recoverynote-gyjdtex5-staging.azurewebsites.net/auth/callback`
- PASS: `/auth/login` scope includes `openid profile email User.Read`
- PASS: `/track` redirects to `/login` when unauthenticated
- PASS: `/auth/callback` without auth context fails safe to `/login`

Additional autonomous checks (2026-06-30):
- INFO: Attempted local login with default `admin` / `admin123` returned login page (HTTP 200), so credentials are not valid on staging (expected if password was rotated).
- PASS: `/logout` route is present and redirects to login when unauthenticated.
- INFO: Full logout session-clear verification still requires a successful authenticated session first.

Follow-ups:
- Manual: sign in with an allowed-group user and confirm access to protected pages.
- Manual: sign in with a user not in allowed group and confirm denial behavior.
- Manual: complete local break-glass admin login on staging with current credentials and confirm success.
- Manual: after successful sign-in, call `/logout` and confirm session is cleared and protected routes redirect to `/login`.
