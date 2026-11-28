---
title: Service Provider Links
category: site_administration
keywords:
  - service provider links
  - app engine
  - identity platform
  - cloud storage
  - billing
  - redis
  - dns
  - resend
  - cloud dashboards
related:
  - site_settings
  - site_deployment
  - site_installation_access
  - backups_archives
---
Jump straight to the external cloud and provider dashboards powering this Lagniappe instance from **Admin → Site Settings → Service Provider Links**.

Opening a provider link never alters settings inside Lagniappe or grants access to those provider consoles—each service checks its own sign-in and cloud permissions.

## Which dashboard to open

- **App Engine**: Application versions, runtime logs, traffic, and instance behavior.
- **Identity Platform**: Configured sign-in providers and authentication accounts.
- **Cloud Storage**: Managed storage buckets and stored file assets.
- **Billing**: Project usage, quotas, and hosting costs.
- **Redis, DNS, and Email providers**: Service health, domain verification, and delivery setup.

Changes in external consoles (like credentials, domains, or provider keys) can affect sign-in, file processing, and email immediately, while some infrastructure changes also require `./setup.sh update` and a deploy so Lagniappe picks them up. Application Administrator access inside Lagniappe does not grant Google Cloud IAM roles—ask the Owner or cloud operator if a console rejects your sign-in, and use [Installation Access and Handoff](/help/site_installation_access) for coordinated ownership transfers.
