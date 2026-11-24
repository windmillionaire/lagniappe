# Installing Lagniappe with an AI Assistant (Zero-Terminal Guide)

You can install and deploy your own private Lagniappe instance on Google Cloud
using a desktop or IDE AI assistant with local tool execution (such as Claude
Desktop/Cowork, Codex, Antigravity, or Cursor) **without opening a terminal**
and **without pasting passwords or API keys into your AI chat**.

## How it keeps secrets out of chat and workspace files

When the assistant runs `./setup.sh --agent --answers answers.json --json`:

1. **Non-secret choices only in chat:** You answer plain-English questions in
   chat (workspace name, Google Cloud project ID, region, owner name/email,
   email provider, whether to enable AI or error monitoring). The installer
   **rejects** any `answers.json` containing secret-like keys (exit code `2`).
2. **One-shot localhost browser vault for secrets:** Whenever provider
   credentials are needed (Google OAuth Web client secret, Gmail App Password or
   Resend/SMTP password, Redis Cloud connection password, or optional Sentry
   DSN), the installer starts a temporary `127.0.0.1` web page with a random
   256-bit single-use URL token and opens it in your browser. You paste
   credentials directly into that local browser form, click **Test & Save**, and
   the vault validates and writes them straight from RAM to **GCP Secret
   Manager** (`lagniappe-runtime-secrets`) and **Identity Platform**, then
   immediately shuts down.
3. **Zero secrets on local disk:** `SECRETS_BACKEND: secret_manager` keeps
   `config/files/lagniappe_settings.yaml` free of runtime secrets. At startup,
   App Engine hydrates secrets directly from Secret Manager using its
   least-privilege runtime service account (`roles/secretmanager.secretAccessor`
   scoped only to `lagniappe-runtime-secrets`).

> **Honest threat-model note:** If a local desktop agent runs shell commands
> under your own Google Cloud owner session, a compromised or malicious agent
> could intentionally query Secret Manager via `gcloud`. This architecture
> eliminates **accidental** secret exposure — no secrets in chat logs, tool
> stdout, `answers.json`, workspace files, or App Engine upload bundles — and
> verifies the finished installation with read-only `./setup.sh doctor`.

## Prerequisites

Before starting, have:

- A Google account with a Google Cloud billing account (or willingness to link
  one in the browser when prompted).
- Python 3.14, Git, and the Google Cloud CLI (`gcloud`) installed (your AI
  assistant can check for these and guide you to official download links if any
  are missing).
- A Redis Cloud account (free 30 MB Essentials tier for testing, or a paid
  Essentials/Flex/Pro plan for production/TLS) — the browser vault includes a
  direct link to open Redis Cloud when you reach that step.

## Quick-Start Prompt for Your AI Assistant

Open a fresh conversation in your local desktop or IDE AI assistant and paste
this short prompt:

```text
Help me install and deploy Lagniappe to my own Google Cloud project. Clone
https://github.com/windmillionaire/lagniappe into a local folder, read
documentation/INSTALL_WITH_AI.md, and follow the Assistant Playbook to walk me
through the install. Never ask me to paste passwords or API keys in chat.
```

## Assistant Playbook (Instructions for the AI)

If the user asked you to install Lagniappe using this guide, follow these rules
strictly:

1. **Workspace & prerequisites:** Agree on a clean local folder (or use the
   cloned checkout you are already in) and verify that `git`, Python 3.14, and
   `gcloud` are installed. If any tool is missing, link the user to its official
   installer and wait until it is available.
2. **Never handle secrets in chat or files:** NEVER ask the user to paste any
   password, API key, OAuth client secret, Redis password, Sentry DSN, or JSON
   credential file in chat. NEVER write any secret into `answers.json`, shell
   arguments, or workspace files, and NEVER hand-craft raw `gcloud` provisioning
   commands when `setup.sh` owns that step.
3. **Keep chat short and conversational — no long questionnaires:** Do NOT ask
   a long numbered list of optional settings. Ask in ONE brief, friendly
   message for just:
   - a short **workspace name**,
   - the permanent Owner's **name and Google email**,
   - whether to **create a new GCP project** (suggest a clean project ID) or use
     an **existing project ID**, and
   - **error reporting (explicit opt-in, off by default):** ask whether they are
     willing to send privacy-reduced crash reports to the Lagniappe maintainer
     (`"capture_errors": true`). Give a brief, honest plea — Lagniappe is a
     solo-maintainer project, so opting in really helps catch bugs early,
     requires no Sentry account, and can be turned off anytime (see
     `ERROR_REPORTING_PRIVACY.md`). Never enable it without their explicit yes;
     if they prefer their own Sentry project instead, set
     `"sentry_mode": "custom"` so the browser vault asks for their DSN.

   Use sensible defaults for everything else (`us-central` / `us-central1`,
   Google Sign-In on, Gmail App Password, built-in AI on, external AI/MCP on —
   which lets assistants like Claude, ChatGPT, Codex, or Gemini connect directly
   to your workspace so you can share things from your phone or desktop and have
   them file or look up pages — analytics on, deploy automatically) unless the
   user asks to change something. Briefly explain external AI/MCP in plain
   English like that when summarizing the defaults so the user knows what it
   does.
4. **Run the agent installer:** Write ONLY those non-secret choices to
   `answers.json` (see the schema below) and run:
   ```bash
   ./setup.sh --agent --answers answers.json --json
   ```
5. **Handle `needs_input` cleanly:** If `setup.sh` exits with code `3`
   (`"status": "needs_input"`), ask the user ONLY for the specific missing
   non-secret field(s) reported in `missing_fields` (for example, choosing
   between multiple open billing accounts), update `answers.json`, and rerun the
   exact same command.
6. **Guide browser steps warmly and clearly:** `setup.sh` automatically creates
   the GCP project, links billing, opens Google sign-in, and opens the one-shot
   `127.0.0.1` credential vault in the browser (and prints the clickable vault
   URL to `stderr` even under `--json`). Be friendly and helpful — tell the user
   when their browser needs attention, briefly explain what they'll set up on
   the credential page (Google Auth Platform Branding + Web OAuth JSON, Gmail
   App Password, Redis Cloud CLI command), invite them to ask questions if
   anything looks unfamiliar, share the localhost vault link if needed, and wait
   until setup finishes. For Google Auth Platform, Lagniappe only requests basic
   sign-in scopes (`email`/`profile`), so do not tell the user to maintain a
   test-user list — just pick **External** audience (and optionally click
   **Publish app** under **Audience** if invited users will sign in with Google).
7. **Verify and finish:** After setup completes, confirm `./setup.sh doctor`
   exits with `0`, confirm no secrets exist in
   `config/files/lagniappe_settings.yaml`, and give the user their live
   Lagniappe URL.

## Non-Secret `answers.json` Reference

```json
{
  "app_name": "My Workspace",
  "project_id": "my-lagniappe-project",
  "admin_name": "Your Name",
  "admin_email": "you@example.com",
  "app_engine_location": "us-central",
  "resource_region": "us-central1",
  "google_signin_enabled": true,
  "auth_email_provider": "gmail",
  "ai_enabled": true,
  "external_ai_enabled": true,
  "capture_errors": false,
  "deploy_now": true
}
```

Supported values for `auth_email_provider`:

- `"gmail"` — Gmail / Google Workspace SMTP (`smtp.gmail.com:587`, STARTTLS) using a 16-character App Password entered in the browser vault.
- `"resend"` — Resend SMTP (`smtp.resend.com:465`, SSL); also supply `"auth_email_sender_email"`.
- `"custom_smtp"` — Supply `"auth_email_host"`, `"auth_email_port"`, `"auth_email_security"` (`"starttls"` or `"ssl"`), `"auth_email_username"`, `"auth_email_sender_email"`, and optional `"auth_email_service"`.

## Resuming, Recovery, and Migrating Existing Installs

- **Interrupted install:** Rerun `./setup.sh --agent --answers answers.json --json`. Already-provisioned GCP resources and already-saved Secret Manager entries are reused automatically; the browser vault only asks for credentials that are still missing.
- **Fresh checkout recovery:** Because `config/files/lagniappe_settings.yaml` holds only non-secret settings plus `SECRETS_BACKEND: secret_manager`, restoring into a new checkout only needs the non-secret settings file and your Google Cloud sign-in — runtime secrets hydrate directly from Secret Manager.
- **Migrating an older `local_yaml` install:** Run `./setup.sh secrets migrate` to enable Secret Manager, grant least-privilege access to your runtime service account, publish your existing runtime secrets to `lagniappe-runtime-secrets`, strip them from `config/files/lagniappe_settings.yaml`, and deploy the updated configuration.

See [INFRA_SETUP.md](INFRA_SETUP.md) and [INFRA_CONFIG.md](INFRA_CONFIG.md#runtime-secrets-backend-secrets_backend) for technical details.
