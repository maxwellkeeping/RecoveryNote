# Staging Changelog

Last updated: 2026-07-03

## Current staging candidate

Branch head: `feature/fy-ending-year` at `3a62da7`

## Highlights

### Entra SSO and access control
- Added Entra SSO flow and staging configuration wiring (`4d225ba`).
- Added and later removed temporary SSO diagnostics endpoint after validation (`9ac42da`, `0424da3`).
- Hardened callback claim parsing and group claim matching (`8beca64`, `abfa180`).
- Switched to ID token group claims and added Graph fallback for group overage cases (`65e6be2`, `baea36f`, `3a62da7`).
- Added runtime dependency for Graph/Authlib path (`4e81da9`).

### Authentication and admin security
- Hardened auth, redirects, path handling, and workflow permissions (`c1ea8ed`).
- Added secure admin reset-link password flow and reset token routes (`e1af6e1`, `d8bcf52`).

### Staging deployment reliability
- Improved staging release stability by retrying transient OneDeploy conflicts (`329deeb`).

### Business logic and admin workflow
- Scoped Agreement ID sequence by cluster and fiscal year (`ab8372d`).
- Added lookup governance updates and copy-flow improvements (`3faa00f`, `55c7c94`).

### Maintenance
- Applied Black formatting for CI consistency (`3046b1c`).

## Commit log (newest first)

| Date | Commit | Change |
|---|---|---|
| 2026-05-28 | `3a62da7` | Request Graph scope for Entra overage fallback |
| 2026-05-28 | `baea36f` | Handle Entra group overage via Graph fallback |
| 2026-05-28 | `d8bcf52` | Add admin password reset routes and token flow |
| 2026-05-28 | `abfa180` | Improve Entra group claim matching robustness |
| 2026-05-28 | `8beca64` | Harden Entra callback claim parsing |
| 2026-05-28 | `65e6be2` | Use ID token group claims in Entra callback |
| 2026-05-28 | `0424da3` | Remove temporary SSO diagnostics endpoint |
| 2026-05-28 | `a5d6839` | Fix SSO diagnostics status calculation |
| 2026-05-28 | `4e81da9` | Add requests dependency for Authlib runtime |
| 2026-05-28 | `f0ed0b1` | Expose Authlib import error in SSO diagnostics |
| 2026-05-28 | `9ac42da` | Add temporary SSO diagnostics endpoint |
| 2026-05-28 | `4d225ba` | Add Entra SSO flow and staging config wiring |
| 2026-05-19 | `329deeb` | Retry staging deploy on transient OneDeploy conflicts |
| 2026-05-19 | `e1af6e1` | Add secure admin reset-link password flow |
| 2026-05-07 | `c1ea8ed` | Harden auth, redirects, paths, and workflow permissions |
| 2026-05-07 | `3046b1c` | Apply Black formatting for CI |
| 2026-05-07 | `ab8372d` | Scope agreement ID sequence by cluster and FY |
| 2026-05-07 | `55c7c94` | Refine lookup admin and split month limit sources |
| 2026-05-06 | `3faa00f` | Add lookup governance and copy flow updates |
| 2026-05-05 | `205e354` | Revert "Use OIDC login for slot release workflow" |

## Staging verification focus
- Validate allowed-group sign-in succeeds and non-member sign-in is denied.
- Confirm local break-glass admin login still works after SSO changes.
- Confirm `/logout` clears session and protected routes redirect to `/login`.
- Smoke test admin password reset-link flow end to end.
- Verify OneDeploy retry logic behavior in release workflow logs.