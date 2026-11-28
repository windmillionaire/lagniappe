---
title: Installation Access and Handoff
category: site_administration
keywords:
  - installation access
  - handoff
  - setup.sh handoff
  - deployer
  - installer
  - google cloud iam
  - ownership transfer
related:
  - site_administrators
  - site_configuration
  - site_service_providers
---
Installation Access separates Lagniappe's in-app Owner and Administrator roles from Google Cloud IAM and outside service accounts—live details are visible only to the Owner.

When a delegated installer helped spin up the site, completing a formal handoff ensures your permanent deployer holds control and automatic installer bootstrap is disabled.

## Completing a clean handoff

- Seeing `"Application handoff configured"` confirms deployed settings identify the permanent deployer and block future installer auto-bootstrap; it does **not** prove every outside cloud IAM binding or copied settings backup was removed.
- **Step 1 (Owner)**: Sign in and remove the installer's temporary Administrator role under **Admin → Site Settings → Administrators**.
- **Step 2 (Installer / Deployer)**: Run `./setup.sh handoff` from the installation checkout (or follow the recovery and authentication steps in the [Installation manual](/manual/installation) using the private recovery YAML if that checkout isn't available). Setup verifies the managed transfer before dropping the installer's direct project binding, since the web app itself never administers Google Cloud IAM.
- **Transfer dependencies first**: Move authentication email, billing, DNS, Redis, Resend, and any copied exports or `lagniappe_settings.yaml` backups before suspending an installer account.
