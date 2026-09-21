---
title: Administrators
related:
- permissions
- create_user
- site_settings
- site_installation_access
---
Administrators manage ordinary Lagniappe content, users, groups, ingress, exports, and site settings. The primary Owner controls who holds this role.

## Assign or remove the role

Use the Administrator roster as the Owner to add an eligible managed user or remove an additional Administrator. Removing the role keeps the managed account active; use Users when an account should be deleted.

An additional Administrator cannot edit or delete the Owner or another Administrator. Privileged account changes must be made by the Owner. Secret-bearing Configuration and installation handoff controls also remain Owner-only.

## Separate systems of access

Application Administrator status does not grant a Google Cloud IAM role or access to outside provider accounts. It also does not automatically raise the person's site-funded AI tier.

If someone is helping with installation, distinguish their temporary application role from their cloud and provider access. Removing an Administrator in Lagniappe does not finish an infrastructure handoff. Use the installation-access guidance and setup workflow for that work.
