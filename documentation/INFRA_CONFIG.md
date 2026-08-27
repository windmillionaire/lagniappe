# Infrastructure Configuration

`config/` is the runtime-safe configuration package uploaded with the Flask
application. It reads fixed YAML/JSON files, validates settings shared by the
application and local tooling, and exposes the `SETTINGS` singleton. It never
imports `installer/` or `runner/`; both are local-only packages excluded from
App Engine uploads.

Use the adjacent guides for configuration-producing workflows:

| Guide | Covers |
| --- | --- |
| [INFRA_SETUP.md](INFRA_SETUP.md) | Installer commands and high-level flow. |
| [INFRA_SETUP_CLOUD.md](INFRA_SETUP_CLOUD.md) | GCP resources, IAM, buckets, domains, and runtime identity. |
| [INFRA_SETUP_RECOVERY.md](INFRA_SETUP_RECOVERY.md) | Recovery snapshot, doctor/repair, and checkout recovery. |
| [INFRA_RUNNER.md](INFRA_RUNNER.md) | Repository-local command and gcloud/ADC boundary. |
| [INFRA_DEPLOYMENT.md](INFRA_DEPLOYMENT.md) | Deployment, release preparation, handlers, and update/upgrade. |

## Fixed files

`config/__init__.py` derives the repository application root from its own path,
not the caller's current directory. `LAGNIAPPE_CONFIG_ROOT` exists only for
isolated tests.

| File | Role |
| --- | --- |
| `lagniappe.yaml` | Generated App Engine deployment descriptor. |
| `index.yaml` | Generated Datastore indexes. |
| `config/browser_protocol.json` | Versioned browser/service-worker vocabulary. |
| `config/files/lagniappe_settings.yaml` | Secret-bearing runtime settings and recovery snapshot. |
| `config/files/lagniappe_dev.yaml` | Local gcloud target and dev/test overrides. |
| `config/files/lagniappe_generation.json` | Generated-file source marker. |
| `package.json` | Application version and frontend toolchain. |
| `lagniappe/web/static/manifest.json` | Generated PWA manifest. |

`Directory` and `File` enums expose the known project paths and parse/save
helpers. Do not add dynamic path discovery or upward searching to runtime
configuration.

## Settings writes

`SETTINGS` loads file data at import and keeps mutable dictionaries for setup
and deployment workflows. `SETTINGS.save()` writes the generated set; passing a
specific `File` writes only that target. Unchanged documents are not replaced.

Writes use UTF-8/LF, a same-directory temporary file, flush/fsync,
`os.replace`, and a parent-directory fsync where supported. Empty documents are
rejected. Secret-bearing files receive owner-only POSIX mode and a restricted
Windows ACL where available.

After all generated files exist, `lagniappe_generation.json` records the
SHA-256 generation of `config/constants.py`, excluding the random `BUILD_ID`
line. Deploy verifies the marker and every generated document. Frontend builds
write `BUILD_ID` to `config/constants.py`; it is not an application setting.

## Runtime projections

| Projection | Source |
| --- | --- |
| `APP` | Application settings YAML. |
| `DEPLOY` | App Engine YAML. |
| `DEV` | Local development YAML. |
| `GCLOUD_CONFIG` | Saved name, account, project, and billing account. |
| `DEV_CONFIG`, `TEST_CONFIG` | Environment-specific overrides. |
| `dev_config`, `test_config` | Runtime settings merged with the matching overrides. |
| `BROWSER_PROTOCOL` | Shared versioned browser protocol JSON. |

Environments are `development`, `testing`, and `production`. Local testing may
enable analytics/AI observability for deterministic E2E contracts; explicit
test overrides still take precedence.

## Identity and credentials

Configuration names distinct responsibilities:

| Setting | Responsibility |
| --- | --- |
| `ADMIN_EMAIL` | Singleton application Owner. |
| `INSTALLER_EMAIL` | Human who provisioned the project. |
| `DEPLOYER_EMAIL` | Human authorized to deploy and run operator data workflows. |
| `BOOTSTRAP_ADMIN_EMAIL` | Exact temporary application bootstrap identity, or empty. |
| `RUNTIME_SERVICE_ACCOUNT_EMAIL` | App Engine attachment and runtime Google client identity. |
| `INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL` | Expected Cloud Tasks/Scheduler OIDC subject. |

Runtime Google clients use project-bound Application Default Credentials.
App Engine obtains them from the attached service account. Local development
and tests start from the saved human ADC and impersonate the runtime account
through `CONFIG.google_credentials`. Project mismatch or missing explicit
identities fails before provider clients are used. No service-account key file
is part of this contract.

Application roles and AI entitlement live on User entities, not in these
identity settings.

For delegated installations, the Owner-only **Admin / Site Settings /
Installation Access** projection shows these non-secret identities and the
authentication-email service, sender, and SMTP login. The section and its JSON
payload are absent when Installer and Owner are the same account. It reports
application handoff configuration as complete only when
the saved deployer is the distinct permanent Owner and bootstrap access is
empty. That state does not claim live IAM convergence: the Owner must follow
the project-IAM link and verify the historical installer separately. The panel
warns when the authentication-email sender or SMTP login still matches the
installer, because that Workspace mailbox must be reconfigured before it is
suspended or deleted. Additional Administrators likewise receive neither the
panel nor its JSON payload.

## Regions and provider settings

`APP_ENGINE_LOCATION` stores App Engine's immutable spelling, such as
`us-central`. `RESOURCE_REGION` stores the regional service spelling used by
Cloud Tasks and Scheduler, such as `us-central1`. Both are required.

Redis uses `REDIS_TLS`, `REDIS_CA_CERT`, and the normal endpoint/password
settings. Enabled TLS requires a readable CA PEM and hostname verification;
invalid TLS configuration never falls back to plaintext. Setup can embed the
PEM as `REDIS_CA_PEM` in the recovery snapshot and materializes the fixed local
path during recovery. The setup handoff directs operators to create or reuse a
Redis Cloud database on Google Cloud in this same `RESOURCE_REGION`; its free
30 MB Essentials choice is for disposable test installations, while the
installer's configurable TLS flow requires a paid plan. The required
`volatile-ttl` policy is edited on that database page and is not considered
saved until the Redis Cloud **Review changes** confirmation completes.

Authentication settings and their public/secret boundaries are documented in
[AUTHENTICATION.md](AUTHENTICATION.md). AI email configuration is documented in
[AI_EMAIL.md](AI_EMAIL.md).

## AI settings

Deployed defaults include `AI_MODEL`, `AI_UTILITY_MODEL`, `AI_IMAGE_MODEL`, and
`AI_LOCATION`. The Datastore `site/ai` row is the live authority for new
generations and the Administrator form; deployed values are the fallback.
Each top-level generation resolves one model and pins it through its calls.
The current defaults are `gemini-3.7-flash` for primary generation,
`gemini-3.5-flash-lite` for utility work, and `gemini-3.1-flash-image` for image
generation, using the `global` endpoint. Existing saved `site/ai` choices are
preserved across update and restore operations rather than silently replaced.

`config/ai_models.py` owns the curated model catalog, live discovery, caching,
capability filters, and pricing URL. `config/ai_settings.py` validates saved
choices. `AI_OBSERVABILITY` is an independent default-off operator choice; it
does not enable page-view analytics, and `ANALYTICS` does not enable AI
generation summaries.

Detailed generation and job behavior belongs in [AI_CONTEXT.md](AI_CONTEXT.md)
and [BACKEND_JOBS.md](BACKEND_JOBS.md), not in runtime configuration.

## Error reporting and agent access

Backend and browser Sentry destinations are separate settings. Both paths
remove request payloads and identity context, allowlist structural request
metadata, redact recognized credentials, and bound nested context. Error
messages and stack traces remain diagnostic content.

Backend tracing and profiling use the optional `SENTRY_TRACES_SAMPLE_RATE` and
`SENTRY_PROFILE_SESSION_SAMPLE_RATE` settings. Each accepts a finite value from
`0.0` through `1.0`; both default to `1.0` for backward-compatible reporting.

Optional agent access uses `AGENT_ACCESS_ENABLED`, `AGENT_ACCESS_EMAIL`,
`AGENT_ACCESS_NAME`, and `AGENT_ACCESS_CODE`. Successful login resolves to a
normal User and normal group permissions.

## Runtime-safe exports

Runtime code imports only configuration surfaces:

```python
from config import SETTINGS, Directory, Environment, File
```

Local commands import `runner/` directly. Installer modules import their
concrete orchestration owners. Do not re-export local runner or installer
functions from `config`.
