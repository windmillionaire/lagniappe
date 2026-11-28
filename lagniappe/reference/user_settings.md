---
title: User Settings
category: permissions_and_users
keywords:
  - user settings
  - account settings
  - email preferences
  - notification digest
  - ai access
  - ai tier
  - none ask create
  - automatic plan execution
  - auto execute
  - external agent api
  - api key
  - manage ai connections
  - user groups
  - reassign page
related:
  - account_security
  - user_groups
  - permissions
  - messages_notifications
  - external_ai
---
Manage account preferences, notification emails, AI access tiers, automatic plan execution, and API connections in User Settings.

Reach your own settings from **Navigation → Account Settings** (which opens **My Page → Settings**), or inspect another user's **User settings** tab when you are authorized to manage users.

## Personal preferences

- **Notification email**: Managed users choose no notification email, email after five minutes, or a daily digest at **8:00 AM** in your local timezone. Public users instead see **Allow site email** consent (`Allow ... to email me`).
- **Automatic plan execution**: When site and account settings allow it, toggle **Run safe AI plans automatically by default (on-site, API, and MCP)** (plans with form schema changes, review items, or flagged issues still pause for browser review).
- **Owner inbound controls**: On the Owner's own settings, **Allow managed users to** lets the Owner opt in or out of **Send messages and mention me** and **Assign tasks to me** without affecting Owner workspace access.
- **External connections**: Managed users can issue or revoke **External agent API** keys and open **Manage AI connections** for external AI clients regardless of on-site AI provider tier (never share keys in help requests).

## Account administration

- **Ordinary accounts**: Administrators can update ordinary users' **User Group(s)**, **Email**, and AI provider tier (**None**, **Ask**, **Create**—where **Create** includes **Ask**), and manage **User Page** options (**Remove user from page**, **Reassign Page**).
- **Restrictions on changes**: You cannot change your own email here, the configured Owner's email cannot be modified in-app, and only the Owner manages privileged Administrator accounts (even the Owner's AI tier can be lowered without reducing Owner permissions). See [Account Security](/help/account_security) for passwords and sessions.
