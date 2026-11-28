---
title: Account Security
category: permissions_and_users
keywords:
  - account security
  - password
  - sign in
  - google sign in
  - identity platform
  - reset password
  - forgot password
  - verify email
  - remember me
  - session
  - sign out
  - api key
related:
  - user_settings
  - create_user
  - site_configuration
---
Manage how you sign in, reset passwords, control API keys, and end sessions for your account.

Authentication runs through **Google Identity Platform**. Open **Navigation → Account Settings** (your **My Page** **Settings** view) for account-level controls, or read the [Security manual](/manual/security) for how cookies, CSRF checks, Content Security Policy, Owner vs. Administrator boundaries, and Secret Manager work together.

## Signing in and managing passwords

- **Google or email sign-in**: Choose **Sign in with Google** when enabled, or **Sign in with email**.
- **First-time password setup**: Users created without signing in yet see **Create your password** (**Choose a password**), which sends a verification link to your email before your first sign-in.
- **Returning sign-in and reset**: Returning email users enter their password (with an optional **Remember me** checkbox). If you forget your password, select **Forgot your password?** → **Send Reset Email**, then use the emailed link to open **Create a new password**.
- **Email addresses**: On your own account, your **Email** field in **Settings** is read-only. Administrators can change an ordinary user's email; the configured Owner's email cannot be changed through in-app settings.

## API keys, AI connections, and Owner options

- **External agent API**: Generate or revoke personal API keys (`Generate API key` shows the full secret once only; `Revoke API key` disables it immediately).
- **Manage AI connections**: Review or authorize OAuth connections for external MCP assistants.
- **Owner inbound controls**: The Owner can separately toggle **Send messages and mention me** and **Assign tasks to me** under **Allow managed users to**.

## Ending your session

Use **Navigation → Sign out** to end the current browser session cleanly. For site-wide credentials, recovery, and Administrator boundaries, see [Configuration and Recovery Settings](/help/site_configuration).
