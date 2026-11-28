---
title: Configuration and Recovery Settings
category: site_administration
keywords:
  - configuration
  - recovery settings
  - lagniappe_settings.yaml
  - secret manager
  - secrets
  - download settings file
  - secrets backend
  - local_yaml
related:
  - site_maintenance
  - site_installation_access
  - account_security
  - backups_archives
---
Configuration gives the primary Owner a redacted on-screen preview and full recovery download (`Download Settings File`) of installation settings before upgrades, recovery, or machine moves.

General help and search never contain live credentials, and only the Owner can open or download recovery configuration from **Admin → Site Settings**.

## Secret Manager vs. local YAML installations

- When `SECRETS_BACKEND` is `secret_manager`, runtime credentials and API keys live in Google Cloud Secret Manager (`SECRETS_SECRET_NAME`, defaulting to `lagniappe-runtime-secrets`) rather than inside the downloaded file. The downloaded YAML is still sufficient to recover a working copy inside the **same** Google Cloud project because setup pulls runtime secrets directly from Secret Manager.
- To view, rotate, or export raw secret values when moving to a *different* project or cloud account, open **Google Cloud Console → Security → Secret Manager** for the `current` version of `SECRETS_SECRET_NAME`, or run `gcloud secrets versions access current --secret=lagniappe-runtime-secrets --project=YOUR_PROJECT_ID` (substituting your `SECRETS_SECRET_NAME` and `GOOGLE_CLOUD_PROJECT`).
- On `local_yaml` installations, **Download Settings File** (`lagniappe_settings.yaml`) includes plaintext credentials and keys needed by setup—store it privately, never commit it, and never attach it to ordinary help requests or screenshots (a redacted preview cannot replace a full backup).

Recovering a working server also depends on matching cloud/provider identities; holding `lagniappe_settings.yaml` alone does not grant Google Cloud IAM roles or transfer billing, DNS, auth email, or external accounts. See [Installation](/manual/installation) for complete recovery and handoff steps.
