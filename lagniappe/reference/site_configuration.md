---
title: Configuration and Recovery Settings
related:
- site_maintenance
- site_installation_access
---
Configuration provides an Owner-only preview and recovery download of the installation's settings. It is useful before setup changes, recovery, or moving the working copy to another machine.

Sensitive values are redacted in the on-screen preview. **Download Settings File** returns the recovery `lagniappe_settings.yaml` for this installation. General help and search never include live credentials or secret values.

When `SECRETS_BACKEND` is `secret_manager`, runtime credentials and API keys are stored in Google Cloud Secret Manager (under `SECRETS_SECRET_NAME`, default `lagniappe-runtime-secrets`) rather than inside the downloaded file. The downloaded YAML is still sufficient to recover a working copy in the same Google Cloud project—setup reads secrets directly from Secret Manager. To inspect, rotate, or export the raw secret values yourself (for example, when moving to a different project or cloud account), open **Google Cloud Console → Security → Secret Manager** for your project and view the `current` version of `SECRETS_SECRET_NAME`, or run `gcloud secrets versions access current --secret=lagniappe-runtime-secrets --project=YOUR_PROJECT_ID` (substituting your `SECRETS_SECRET_NAME` and `GOOGLE_CLOUD_PROJECT` values).

On `local_yaml` installations, **Download Settings File** includes plaintext credentials and other secrets needed by setup. Store any downloaded `lagniappe_settings.yaml` privately: do not commit it, attach it to an ordinary help request, or include it in shared screenshots. A redacted preview is not a replacement for the complete recovery backup.

Recovering a working copy also requires the appropriate cloud and provider identities. Possessing the settings file does not grant Google Cloud IAM permissions or automatically transfer billing, DNS, authentication email, or external accounts.

For recovery and handoff steps, see the [Installation manual](/manual/installation).
