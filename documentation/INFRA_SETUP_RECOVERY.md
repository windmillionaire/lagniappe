# Infrastructure Setup Recovery

The Owner-only `lagniappe_settings.yaml` download is the single local recovery
snapshot. It contains runtime settings and secrets, not Datastore entities or
Storage content. Keep an encrypted off-machine copy and treat every plaintext
copy as sensitive.

For application data backup and restore, read
[INFRA_DATA_LIFECYCLE.md](INFRA_DATA_LIFECYCLE.md).

## Recover a checkout

On POSIX:

```bash
git clone <lagniappe-source>
cd <lagniappe-source>
mkdir -p config/files
# Save the Owner download as config/files/lagniappe_settings.yaml
./setup.sh
```

On Windows use a normal PowerShell window, keep the checkout in a stable local
profile directory outside OneDrive redirection, save the file at the same
relative path, and run `setup.cmd`.

When the settings file exists but `lagniappe_dev.yaml` does not, setup announces
recovery before dependency or cloud mutation. It takes the target only from
`GOOGLE_CLOUD_PROJECT` in the snapshot; ambient gcloud state is never a target
candidate.

## Snapshot contract

The flat YAML identifies its schema with:

```yaml
CONFIG_KIND: lagniappe-settings
CONFIG_SCHEMA_VERSION: 3
```

It includes runtime settings, authentication/email/Redis secrets, Owner and
operator identities, and live Site/AI settings merged from Datastore. Service
account key JSON is absent. The runtime database is always `(default)` and is
not configurable.

The download fails if live deployment or AI settings cannot be read; it does
not issue a partial snapshot. Browser previews use a recursively redacted copy.
The attachment response is no-store.

When Redis TLS is enabled, the snapshot embeds the validated CA PEM. Recovery
materializes it at `config/files/redis_ca.pem` before Redis discovery.

## Recovery discovery

Before recreating local development settings, setup validates the snapshot and
cross-checks project, service account, Identity Platform, App Engine, Document
AI, queue, bucket, and Redis identities. Provider discovery reports available,
absent, or unavailable:

- absent resources may be recreated after the operator confirms the target;
- permission, authentication, network, malformed response, and ambiguous
  failures are unavailable and stop the process; and
- live provider values are comparison evidence and cannot silently replace
  snapshot settings.

Recovery aligns both gcloud and ADC to the exact project. Browser
authentication is transactional: if the selected principal or permissions do
not match, setup restores the prior ADC file or removes the rejected new file.

## Doctor and repair

Run after installation, recovery, or a manual configuration edit:

```bash
./setup.sh doctor
```

`doctor` is read-only. It checks generated-file completeness and source marker,
file permissions, saved gcloud/ADC identity, required APIs/resources, runtime
IAM, buckets, Identity Platform, Redis, and focused provider state. It returns
nonzero for drift and prints the repair command.

`./setup.sh repair` is the mutating path. Confirm the reported project and
identities before running it. Repair uses the normal setup lock and journal,
reconciles the installation, and validates the resulting generation.

## Delegated handoff

`./setup.sh handoff` transfers a delegated installation from
`INSTALLER_EMAIL` to the permanent Owner. The Owner must already have a direct
Project Owner binding. The active gcloud/ADC principal must be either the saved
installer or Owner.

After default-no review, the command:

1. grants the Owner bucket operator and exact runtime-account act-as/signing
   bindings;
2. saves the Owner as deployer and gcloud account and clears bootstrap access;
3. deploys that configuration;
4. removes the installer from managed bucket and runtime-account IAM; and
5. removes the installer's direct project IAM bindings and verifies the Owner
   remains.

The operation preserves unrelated IAM members/conditions and runtime
self-bindings. It does not manage Workspace accounts, billing-account IAM, or
organization-level access. A partial handoff can resume from the journal.

## Secret boundaries

Only `lagniappe_settings.yaml` and optional `redis_ca.pem` are included from
`config/files/` in the App Engine upload. Development settings, generation and
operation journals, downloaded OAuth JSON, recovery input copies, temporary
files, and backups remain local.

Successful setup output is built from a safe-field allowlist. It may show
project/resource names, identities, regions, versions, and commands, but never
the settings mapping, passwords, tokens, DSNs, access tokens, or private keys.

## What the snapshot cannot recover

The settings file does not contain application entities, documents, uploads,
or Redis data. The recovery bucket and recovery-set workflow protect those
assets. If both provider data and the recovery bucket are lost, configuration
alone cannot reconstruct the application workspace.
