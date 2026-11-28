---
title: Maintenance
category: site_administration
keywords:
  - maintenance
  - apply updates
  - refresh cache
  - rebuild search index
  - site updates are current
  - cache refreshed
related:
  - site_configuration
  - site_deployment
  - search
  - backups_archives
---
Apply required application data migrations and rebuild derived search cache from stored records under **Admin → Site Settings → Maintenance**.

Every action displays live status and detailed results directly in the Maintenance panel.

## Applying site updates

- **Apply Updates** runs data migrations needed for the installed code version (the button reads **Applying Site Updates** while active, then reports **Site updates are current**).
- **Refresh Cache** stays disabled until pending site updates finish.
- If **Site updates need attention** appears, inspect the listed failure details and direct links to affected records, fix the underlying issue if needed, and run **Apply Updates** again to retry.

## Refreshing cache

- **Refresh Cache** reconstructs derived server cache and packaged Help search entries from stored records—use it after an upgrade or Redis state loss rather than as routine maintenance.
- While running, the button shows **Refreshing Cache** and finishes with **Cache Refreshed** (searches and filtered tables may temporarily return partial results while rebuilding). If **Cache refreshed with errors** appears, review the skipped records and errors listed beneath the count.
- Packaged help articles update automatically whenever a new version changes them or the cache rebuilds. The Owner can also inspect redacted settings or download recovery configuration from [Configuration and Recovery Settings](/help/site_configuration).
