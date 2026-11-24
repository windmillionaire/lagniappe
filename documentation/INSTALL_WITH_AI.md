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

## Copy-Paste Prompt for Your AI Assistant

Open a fresh conversation in your local desktop/IDE AI assistant and paste the
prompt below:

```text
Help me install and deploy Lagniappe to my own Google Cloud project using
Lagniappe's built-in agent-assisted installer. Follow these rules strictly:

1. Clone https://github.com/windmillionaire/lagniappe into a clean local folder
   we agree on, and check that Git, Python 3.14, and gcloud are installed.
2. NEVER ask me to paste any password, API key, OAuth client secret, Redis
   password, Sentry DSN, or JSON credential file in chat.
3. NEVER write any secret into answers.json, shell arguments, or workspace
   files, and NEVER hand-craft raw gcloud provisioning commands when setup.sh
   owns that step.
4. Ask me only the plain-English non-secret questions needed for answers.json
   (workspace name, GCP project ID, region, owner name/email, email provider,
   AI/MCP/monitoring choices), write ONLY those non-secret choices to
   answers.json, and run:
     ./setup.sh --agent --answers answers.json --json
5. If setup returns exit code 3 ("status": "needs_input"), ask me only the
   missing non-secret fields listed in missing_fields, update answers.json, and
   rerun the same command.
6. When setup opens Google sign-in or the local browser credential vault
   (http://127.0.0.1:.../vault/...), tell me to complete it in my browser and
   wait until setup finishes.
7. After setup completes, confirm `./setup.sh doctor` exits with 0, confirm no
   secrets exist in config/files/lagniappe_settings.yaml, and give me my live
   Lagniappe URL.
```

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
  "external_ai_enabled": false,
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
- **Migrating an older `local_yaml` install:** Run `./setup.sh secrets migrate` to enable Secret Manager, grant least-privilege access to your runtime service account, publish your existing runtime secrets to `lagniappe-runtime-secrets`, and strip them from `config/files/lagniappe_settings.yaml`.

See [INFRA_SETUP.md](INFRA_SETUP.md) and [INFRA_CONFIG.md](INFRA_CONFIG.md#runtime-secrets-backend-secrets_backend) for technical details.
