---
title: External AI Connections
related:
- ai_tools
- permissions
- user_settings
---
External AI connections let a compatible assistant search your Lagniappe workspace and prepare reviewed proposals using your own AI client. The installation must enable external access, and you need a managed, non-public account.

## Connect an assistant

For **MCP**, add the installation's MCP server URL to your client and follow the Lagniappe sign-in prompt. The **AI connections** screen shows the account's email address. Choose **Allow** to connect that account, or **Cancel** if it is the wrong one. A local Lagniappe package is not required.

For an HTTP-capable assistant, create a key under **My Page / User Settings / External agent API**. The installation's client skill is available at `/api/v1/client-skill.md` using that key. Store credentials in the client's secret settings, rather than in shared prompts or files.

Connection addresses appear below this help when your account can use them. The manual's AI chapter has setup steps for individual clients. **AI connections** shows your signed-in email and which clients are connected.

## Questions and proposals

Ordinary questions can be answered directly without creating a saved Plan. A Plan is needed when you request a saved answer or proposed workspace changes. Review and execute those changes in Lagniappe.

External access is independent of your None/Ask/Create tier for the installation's configured provider. Record permissions still apply. Revoke keys or AI connections through their account controls when a client no longer needs access.
