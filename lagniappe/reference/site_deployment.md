---
title: Deployment Settings
related:
- site_settings
- site_maintenance
- offline
- site_service_providers
---
Deployment settings save supported App Engine preferences for the next setup update. Saving them does not deploy the application. Run `./setup.sh update`, then deploy, to apply the generated configuration.

## Scaling and capacity

**Basic scaling** lets an idle installation stop its instances. The next request may wait for startup. **Automatic scaling** uses the configured warm-instance settings to reduce that delay, with different ongoing resource use.

Instance class selects the available memory and CPU. Basic scaling uses B classes; automatic scaling uses F classes. Worker count controls how many application workers run within an instance, so additional workers also consume memory.

Automatic scaling separates **Min Idle**, the warm-instance target, from **Max**, the instance limit. Min Idle can be zero and cannot exceed Max. Basic scaling uses only the maximum instance count. F2 and B2 installations support at most three Lagniappe workers per instance.

Open **Service Provider Links / App Engine** for runtime logs and instance activity, or **Billing** for the project's usage and charges. Those dashboards require their own Google Cloud permissions.

The installation chapter covers the longer setup and deployment procedure.
