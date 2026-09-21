---
title: Configuration and Recovery Settings
related:
- site_maintenance
- site_installation_access
---
Configuration provides an Owner-only preview and recovery download of the installation's settings. It is useful before setup changes, recovery, or moving the working copy to another machine.

Sensitive values are redacted in the on-screen preview. **Download Settings File** returns the complete recovery file, including credentials and other secrets needed by setup. General help and search never include those live values.

Store the downloaded `lagniappe_settings.yaml` privately. Do not commit it, attach it to an ordinary help request, or include it in shared screenshots. A redacted preview is not a replacement for the complete recovery backup.

Recovering a working copy also requires the appropriate cloud and provider identities. Possessing the settings file does not grant Google Cloud IAM permissions or automatically transfer billing, DNS, authentication email, or external accounts.

For recovery and handoff steps, see the [Installation manual](/manual/installation).
