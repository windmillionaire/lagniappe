---
title: External AI Connections
category: ai_and_automation
keywords:
  - external ai
  - mcp
  - rest api
  - client skill
  - claude
  - chatgpt
  - oauth
  - manage ai connections
  - external agent api
  - automatic plan execution
  - answer question
related:
  - ai_tools
  - permissions
  - user_settings
  - account_security
---
Connect compatible external AI assistants via MCP or the REST API to search your workspace, answer questions, and draft reviewable plans within your permissions.

The installation must enable external AI access, and you must sign in with a managed, non-public account. When enabled for your account, your server's **Connection name**, **MCP server**, and **Skill URL** appear automatically below this article.

## Connecting an assistant

- **Remote MCP**: Add this site's MCP server URL to your assistant and follow the sign-in prompt. On the **Manage AI connections** screen (**Navigation → Account Settings** / **My Page → Settings**), verify the displayed account email and choose **Allow** (or **Cancel** if it is the wrong account). No local package installation is required.
- **REST API clients**: Generate a personal token under **External agent API** in **Account Settings** and point HTTP-capable tools to `/api/v1/client-skill.md`. Always store tokens in secret configuration rather than shared prompts or repository files.

## Answering questions vs. running Plans

- Ordinary questions and task lookups run directly through read-only tools without creating a saved Plan.
- Requests for saved answers or workspace updates start a Plan. By default, review and execute proposals in Lagniappe; when both the site and your **Automatic plan execution** user setting allow it, safe plans can run automatically while form schema updates, deletes, review items, and flagged issues still pause for browser review.
- External AI access works independently of your site **None / Ask / Create** provider tier because external clients use their own AI provider, while workspace permissions remain strictly enforced. Revoke keys or OAuth connections in **Account Settings** anytime.
