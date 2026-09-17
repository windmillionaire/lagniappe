---
title: Permissions
manual_section: permissions
related:
- restrictions
- user_groups
- site_administrators
- public_permissions
---
Permissions determine which workspace resources a user can view, edit, create, delete, assign, or publish. Grants can come from user groups and individual permissions.

## Grants and scope

Higher applicable grants include the lower actions defined for that resource. View permits reading; Edit permits updates. Editing a category also permits creating pages within it. Creating categories, projects, forms, or users requires the corresponding creation permission. Assign and Publish control their respective operations.

Broad grants cover a resource area; specific grants cover a particular category, project, page, or group. The permissions display can hide specific rows already covered by a broad grant. A missing row can therefore mean the person already has access through the broader permission.

Group and individual grants combine using the strongest applicable permission. Page and form restrictions add membership requirements for ordinary users; they are not extra grants.

## Roles

The **Owner** has full application access and manages the Administrator roster and privileged accounts. **Administrators** manage ordinary content, users, groups, and site settings, but cannot manage the Owner or other Administrators. Secret-bearing configuration remains Owner-only.

Regular managed users receive their configured grants. Signed-in public users have a separate limited public-permissions policy. Public users are different from anonymous readers of a published page.
