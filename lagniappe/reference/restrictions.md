---
title: Page and Form Restrictions
category: permissions_and_users
keywords:
  - restrictions
  - restrict access
  - administrators only
  - save restrictions
  - private page
  - hidden
  - group restriction
related:
  - permissions
  - user_groups
  - tasks
  - page_info
---
Restrictions narrow who can open sensitive pages or forms on top of ordinary workspace permission grants.

Think of normal [Permissions](/help/permissions) as opening doors to categories or workspaces, while Restrictions add a lock on individual pages or forms that need a smaller audience.

## How restrictions work together

- **Permissions first**: Ordinary users still need normal view or edit permission on the content, *plus* they must pass every active restriction source.
- **Multiple groups**: Within a single restriction list (such as a page's allowed groups), belonging to any listed group is enough. When both a page and its attached form enforce restrictions, an ordinary user must belong to at least one group listed on each.
- **Administrators Only**: Selecting **Administrators Only** hides the record from ordinary group members; application Administrators and the Owner bypass content restrictions.
- **Inherited locks**: Tasks and uploaded files can inherit restrictions from their page and form. Assigning someone a task or linking to it does not bypass an active restriction.

## Editing restrictions

Open **Settings → Restrictions** on a page (or **Restrict Access** in Form settings, Category Settings, or Project Settings), pick allowed groups or **Administrators Only**, and click **Save Restrictions** (on another user's page, submit via **User settings**; per-page restrictions are hidden on your own personal **My Page**). The panel separates page and form sources and hides unrestricted ones, so removing a page restriction restores normal access subject to any form restriction still active.
