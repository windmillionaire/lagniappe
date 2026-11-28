---
title: Permissions
category: permissions_and_users
keywords:
  - permissions
  - roles
  - owner
  - administrator
  - editor
  - viewer
  - grants
  - access control
  - view edit create delete assign publish
related:
  - restrictions
  - user_groups
  - site_administrators
  - public_permissions
---
Permissions determine which workspace resources each person can view, edit, create, delete, assign, or publish through individual grants and user group memberships.

Lagniappe enforces all permissions on the server before rendering pages or returning search, filter, or AI tool results.

## How grants combine and cascade

- **Hierarchy**: Higher grants imply lower ones on the same resource—**Edit** includes **View**; editing a category also permits creating new pages inside it; creating categories, projects, forms, or users requires the dedicated creation grant; **Assign** and **Publish** govern those specific actions.
- **Broad vs. specific grants**: Broad grants cover an entire resource type, while specific grants target one category, project, page, or user group. Permission screens hide redundant specific rows already implied by a broad grant—so an omitted row often means the user already holds broader access.
- **Additive grants, narrowing restrictions**: Group memberships and individual grants combine by taking the **strongest** grant; page and form **Restrictions** then narrow access for ordinary users rather than adding extra permissions.

## Roles at a glance

- **Owner**: Full workspace access plus exclusive control over the Administrator roster, secret-bearing configuration, and privileged Administrator accounts.
- **Administrators**: Manage ordinary content, users, groups, backups, and site settings, without ability to edit the Owner, other Administrators, or Owner-only secrets.
- **Managed and Public users**: Managed users receive tailored group and individual grants; signed-in **Public** accounts follow the site's limited [Public Permissions](/help/public_permissions) policy (distinct from anonymous visitors reading a published page document).
