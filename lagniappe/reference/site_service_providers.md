---
title: Service Provider Links
manual_section: personalization
related:
- site_settings
- site_deployment
- site_installation_access
---
Service Provider Links opens the outside dashboards supporting this Lagniappe installation. Following a link does not change a setting inside Lagniappe or grant access to that provider account.

Use the appropriate dashboard for the question:

- **App Engine** for application versions, runtime logs, and instance behavior.
- **Identity Platform** for configured sign-in services and authentication accounts.
- **Cloud Storage** for managed buckets and stored assets.
- **Billing** for project usage and charges.
- The configured Redis, DNS, and email providers for their service health and setup.

Account changes in those systems can affect login, uploads, processing, and deployment immediately. Some configuration changes also need a setup update and deployment before the app can use them.

Application Administrator status and cloud/provider permissions are separate. Ask the Owner or responsible operator for the appropriate access when a dashboard rejects your account. Use the installation workflow for coordinated configuration and handoff changes instead of assuming a provider edit updates every dependent service.
