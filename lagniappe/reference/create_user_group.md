---
title: Creating User Groups
category: permissions_and_users
keywords:
  - create user group
  - new group
  - role permissions
  - group grants
  - team access
related:
  - user_groups
  - permissions
  - user_settings
  - restrictions
---
A user group packages a reusable set of permissions under one role name—ideal for groups like Editors, Staff, Clients, or Reviewers.

Because group membership automatically reflects later edits, designing clean roles makes onboarding and offboarding teammates much simpler than managing every permission per person.

## Steps to create and assign a group

1. Open **Navigation → Users → User Groups** and choose **New Group** (`+`).
2. Enter a clear, recognizable name and create the group.
3. In the permissions panel that opens, choose the resource types or specific categories and projects members should view, edit, create, delete, assign, or publish.
4. Assign people to the group when creating their account or anytime under their [User Settings](/help/user_settings).

## Things to keep in mind

- A group's name never escalates privileges on its own—an ordinary group named `"Administrators"` has no special powers; the Owner manages true Administrator status separately.
- Memberships combine using the strongest applicable grant across all a user's groups (for example, View in one group plus Edit in another equals Edit), while page and form [Restrictions](/help/restrictions) act as extra checks that broad grants do not bypass for ordinary users.
- Favor targeted category or project grants for focused roles so future membership changes stay predictable.
