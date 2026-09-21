---
title: Maintenance
related:
- site_configuration
- site_deployment
- search
---
Maintenance applies site updates and rebuilds the cache. Each action shows its progress and results in the Maintenance panel.

## Apply Updates

**Apply Updates** runs the data updates required by the installed version. The button shows **Applying Site Updates** while they run. The panel shows **Site updates are current** when they finish. **Refresh Cache** stays disabled until these updates are complete.

If the panel shows **Site updates need attention**, the list below identifies the failed update and its error. It also includes links to affected records when available. **Apply Updates** retries the failed update.

## Refresh Cache

**Refresh Cache** rebuilds derived server data from stored records and packaged help. Use it when an upgrade or lost Redis state requires reconstruction, rather than as routine housekeeping.

The button shows **Refreshing Cache** while the rebuild runs, then **Cache Refreshed**. Searches and lists may be incomplete during the rebuild. If the panel says **Cache refreshed with errors**, it lists the skipped records and their errors below the record count.

Help articles update automatically when a new application version changes them or the cache needs rebuilding.

## Configuration

The Owner can open Configuration for a redacted preview and download the complete recovery settings. That download contains secrets. Store it privately and use it only for the intended setup, recovery, or migration workflow.
