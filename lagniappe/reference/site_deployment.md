---
title: Deployment Settings
category: site_administration
keywords:
  - deployment settings
  - app engine
  - scaling
  - basic scaling
  - automatic scaling
  - instance class
  - workers
  - min idle
  - setup.sh update
related:
  - site_settings
  - site_maintenance
  - offline
  - site_service_providers
  - backups_archives
---
Configure App Engine scaling, instance size, and worker concurrency preferences from **Admin → Site Settings → Deployment Settings**.

Saving changes here stores preferences for your next setup run—to apply updated configuration to App Engine, run `./setup.sh update` and deploy from your checkout.

## Scaling and worker options

- **Basic scaling vs. Automatic scaling**: **Basic scaling** allows instances to scale down to zero when idle (the next visitor may wait briefly for startup); **Automatic scaling** keeps warm instances ready according to your **Min Idle** target to minimize cold starts, with different ongoing hosting cost.
- **Instance classes & limits**: Basic scaling uses **B** classes; automatic scaling uses **F** classes. **Worker count** sets application workers per instance (more workers use more memory; **F2** and **B2** support at most **three** Lagniappe workers per instance).
- **Min Idle vs. Max**: Under Automatic scaling, **Min Idle** sets warm instances (`0` or higher, never exceeding **Max**). Basic scaling configures only the maximum instance count.

Check **Service Provider Links → App Engine** for live runtime logs and instance metrics, or **Billing** for usage and spend (both require matching Google Cloud access). See the [Installation manual](/manual/installation) for full deployment details.
