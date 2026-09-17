---
title: Installation Access and Handoff
manual_section: personalization
related:
- site_administrators
- site_configuration
- site_service_providers
---
Installation Access separates the Lagniappe Owner and Administrator roles from Google Cloud IAM and external provider accounts. Its live identity details are available only to the Owner.

“Application handoff configured” means the deployed settings identify the permanent deployer and no longer allow automatic installer bootstrap. It does not prove that every outside permission or copied backup has been removed.

## Complete a handoff

The Owner signs in and removes the installer's temporary role from **Admin / Administrators**. The installer then runs `./setup.sh handoff` from the installation working copy. If that copy is unavailable, follow the recovery and authentication steps in the [Installation manual](/manual/installation) using the private settings backup.

The setup workflow verifies the managed transfer before removing the installer's direct project binding. The running web application cannot administer human Google Cloud IAM.

Transfer dependencies before suspending an installer account. Authentication email, billing, DNS, Redis, Resend, and other provider accounts may still rely on it. Also account for configuration backups and exports copied outside Lagniappe's managed storage. See the installation chapter for the complete setup procedure.
