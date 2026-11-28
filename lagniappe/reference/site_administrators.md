---
title: Administrators
category: site_administration
keywords:
  - administrators
  - owner
  - admin role
  - site administrators
  - revoke admin
  - handoff
related:
  - permissions
  - create_user
  - site_settings
  - site_installation_access
---
Administrators operate day-to-day workspace content, users, user groups, data imports, backups, and site settings, while the primary Owner controls who holds Administrator status.

The Administrator roster appears under **Admin → Site Settings** for the **Owner**.

## Adding or removing Administrators

- As the **Owner**, add an eligible managed user to grant Administrator privileges, or remove an additional Administrator when they should return to ordinary managed permissions. Removing Administrator status keeps their regular account intact—use **Users** when an account should be deleted completely.
- **Privileged boundaries**: Additional Administrators cannot edit or delete the Owner or another Administrator, and cannot open secret-bearing **Configuration** or **Installation Access** handoff controls.

## Application roles vs. cloud & AI access

- Holding Administrator status inside Lagniappe does **not** grant Google Cloud IAM roles, external service dashboards, or automatic site-funded AI credits (users still keep their own **None / Ask / Create** tier).
- If an installer helped deploy the site under a temporary Administrator role, removing them here is only part of handoff—complete [Installation Access and Handoff](/help/site_installation_access) with `./setup.sh handoff` so cloud bindings and setup metadata match.
