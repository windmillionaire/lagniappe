---
title: Site Settings
category: site_administration
keywords:
  - site settings
  - admin
  - installation settings
  - owner controls
  - administrator panel
related:
  - site_maintenance
  - site_administrators
  - site_ai_models
  - site_deployment
  - site_public_pages
  - site_image
  - site_service_providers
  - backups_archives
  - analytics
---
Open **Navigation → Admin** to manage site-wide settings, run data imports, review maintenance and backups, and inspect links to outside cloud services.

Admin organizes operator tools into **Site Settings**, **Import Data**, and **Backups & Archives**, alongside **Navigation → Analytics** for usage and AI observability.

## What Site Settings covers and when changes apply

- **Live settings vs. setup deployments**: Choices under **AI Models**, **Public Pages**, **Administrators**, **Maintenance**, and **Service Provider Links** apply directly to or inspect the running app. Changes under **Deployment Settings** and **Site Image** save preferences first and require `./setup.sh update` plus a deploy to apply to served infrastructure (saving a form never redeploys the whole instance automatically).
- **Owner-only boundaries**: Only the configured primary **Owner** can manage the Administrator roster, access **Installation Access**, or open secret-bearing **Configuration**. General administrator help articles are readable by signed-in users through Search without exposing secrets or granting Admin access.
- **After upgrading**: Visit **Site Settings → Maintenance**—if **Site updates are ready**, run **Apply Updates** first (`Refresh Cache` stays disabled until updates complete). Before making machine changes or migrations, download recovery configuration from [Configuration and Recovery Settings](/help/site_configuration) and check [Backups and Archives](/help/backups_archives).
