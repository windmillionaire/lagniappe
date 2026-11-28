---
title: User Groups
category: permissions_and_users
keywords:
  - user groups
  - groups
  - role
  - group permissions
  - team permissions
  - new group
  - public group
related:
  - create_user_group
  - permissions
  - user_settings
  - public_permissions
---
User Groups let authorized administrators maintain shared permission sets for teams and roles so updating one group updates every member cleanly.

Open **Navigation → Users → User Groups** (from the Users header icon) to inspect and manage all roles across your workspace.

## Managing groups and tracing access

- **Controls**: Select **New Group** (`+`) to create a role, pick **Public** to adjust the signed-in public-user policy, or open any existing group to rename it and update permissions. Assign people during user creation or under [User Settings](/help/user_settings).
- **Combining memberships**: Multiple groups add their grants together—removing an action from one group leaves any equivalent grant from another group or personal permission untouched. Page and form [Restrictions](/help/restrictions) still enforce membership checks separately.
- **Specific vs. broad grants**: Use specific category or project grants when a role applies only to one part of the workspace. Naming a group `"Administrators"` or `"Owners"` does **not** grant application Administrator or Owner status; the Owner manages those roles separately.
- **Auditing someone's access**: Check a user's **User Settings** to list their groups, then inspect each group here (plus any page or form restrictions on target records).
