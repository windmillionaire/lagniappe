# Infrastructure Configuration

The `config/` package is the runtime-safe configuration surface uploaded with
the application. It reads fixed YAML/JSON files, exposes settings through a
`SETTINGS` singleton, and owns validation contracts shared by the application
and local tooling. Repository-local orchestration lives in `runner/`; install,
recovery, repair, and update workflows live in `installer/`. Both local
packages are excluded from App Engine uploads.

## File Discovery (`__init__.py`)

`config/__init__.py` derives the application root from its own
`Path(__file__)`, with `LAGNIAPPE_CONFIG_ROOT` available only for isolated
tests. It never imports `runner/` or `installer/`, searches upward, or depends
on the caller's current working directory. Two key paths are established:

- **`APP_DIR`**: The root application directory (where `main.py` lives)
- **`CONFIG_FILE_DIR`**: The `config/files/` directory containing YAML config files

The current config files use fixed names:

- `lagniappe.yaml`
- `config/browser_protocol.json`
- `config/files/lagniappe_dev.yaml`
- `config/files/lagniappe_generation.json`
- `config/files/lagniappe_settings.yaml`
- `index.yaml`
- `package.json`
- `lagniappe/web/static/manifest.json`

## Enums

### Environment

Three application environments:

| Value | Used For |
|---|---|
| `DEVELOPMENT` | Local dev server |
| `TESTING` | Test server for Playwright e2e tests |
| `PRODUCTION` | Deployed on Google App Engine |

### Directory

Maps logical directory names to filesystem paths, including `APP`, `CONFIG`,
`JS_CHUNKS`, `REPORTS`, `TEST_FAILURES`, `TEST_REPORTS`, and `SITE_IMAGES`.
`Directory.clean()` removes a directory and `Directory.get_or_create()` /
`Directory.create()` ensure it exists.

### File

Maps logical file names to absolute paths. Current members include
`APP_YAML`, `BROWSER_PROTOCOL_JSON`, `DEV_YAML`, `APP_SETTINGS_YAML`,
`INDEX_YAML`, `PACKAGE_JSON`, `MANIFEST_JSON`, `GENERATION_JSON`,
`MANAGED_TEST_SERVER_PID`, and `MANAGED_TEST_SERVER_LOG`.
Provides utility methods:

| Method | Description |
|---|---|
| `exists()` | Checks if the file exists |
| `load()` | Parses YAML or JSON based on the enum name |
| `save(data)` | Writes YAML or JSON based on the enum name |

## Settings (`__init__.py`)

The `SETTINGS` singleton loads config file data at import time and keeps mutable
dicts for setup/deploy flows. `SETTINGS.save()` writes the complete generated
set; `SETTINGS.save(File.APP_SETTINGS_YAML, ...)` targets only the named files.
Unchanged documents are not replaced.

Generated writes use explicit UTF-8/LF serialization and a same-directory
temporary file. The writer rejects empty documents, flushes and fsyncs before
`os.replace`, and fsyncs the parent directory where supported. Secret-bearing
settings use mode `0600` on POSIX and a best-effort restricted `icacls` rule on
native Windows. A failed Windows ACL restriction produces an explicit warning
so the operator knows to protect the file manually; the native Windows
installer remains experimental pending a real clean-machine smoke. Once all
six generated documents exist and are nonempty, `lagniappe_generation.json`
commits the SHA-256 source generation of `config/constants.py`. The volatile
`BUILD_ID` line is excluded so frontend builds do not invalidate setup.
Deploy verifies that source marker and the presence of every generated
document. It does not hash `package.json`, the web manifest, or generated
installation content.
`BUILD_ID` is intentionally not an app setting: frontend builds refresh the
tracked `BUILD_ID` constant in `config/constants.py`, and runtime `CONFIG`
uses that constant for cache busting.

## Canonical Recovery Snapshot

The owner-only configuration download is a flat YAML recovery snapshot with
the fixed filename `lagniappe_settings.yaml`. It copies the persisted settings,
tokens, passwords, and other application secrets. Service-account key JSON is
not part of the supported settings contract. It is not a shareable diagnostic
export. The response is an attachment with `Cache-Control: no-store` and
`Pragma: no-cache`. Browser configuration previews use a separate recursively
redacted copy and never render secret values.

Every snapshot identifies its contract with:

```yaml
CONFIG_KIND: lagniappe-settings
CONFIG_SCHEMA_VERSION: 3
```

Schema 3 stores `RUNTIME_SERVICE_ACCOUNT_EMAIL` and
`INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL` as explicit, non-secret identities.
It is the only current export and runtime contract. Recovery upgrades schema 2
documents to schema 3, rejects other schema versions, and requires both
identities explicitly. Snapshot construction accepts the schema scalar in its
serialized string or parsed integer representation and always emits the
canonical integer value.

The download merges the current Datastore `site/deployment` keys and `site/ai`
keys into their ordinary flat application-setting names. If those live records
cannot be read, the download fails instead of issuing a partial snapshot.
Their metadata `version` fields are not application settings and are not
exported.

When Redis TLS is enabled, `REDIS_CA_PEM` embeds the validated CA bundle and
`REDIS_CA_CERT` remains the stable project-relative
`config/files/redis_ca.pem` path. Recovery materializes and validates the PEM
before Redis discovery, keeping the one-file local recovery contract.

The downloaded values are the settings authority during recovery. Live
provider resources are read-only comparison evidence and cannot silently
overwrite the snapshot. Datastore application records, uploaded files, Storage
objects, and Redis data are application data rather than settings and are not
covered by this file.
Document AI processor names may contain the provider's numeric project number
rather than its textual project ID. Recovery accepts that canonical form only
long enough to authenticate the saved project, then requires the numeric parent
to match the provider-reported `projectNumber` before querying the processor.

The file is ignored by Git but deliberately included in the App Engine upload
as the production runtime configuration. Keep an encrypted off-machine copy
and treat every plaintext copy as a secret. Temporary files, editor backups,
the local generation manifest, and development settings are excluded from the
upload. `./setup.sh doctor` validates the complete generated-file checksum set,
owner-only POSIX permissions, active gcloud identity, and expected read-only
provider state; `./setup.sh repair` is the separately named command authorized to
reconcile drift.

| Property | Source | Description |
|---|---|---|
| `APP` | `APP_SETTINGS_YAML` | Core application settings. Booleans, integers, lists, and dicts are parsed from YAML-safe strings. |
| `BROWSER_PROTOCOL` | `BROWSER_PROTOCOL_JSON` | Read-only versioned names for cross-worker browser events and connectivity state. Shared by Python producers and the frontend build. |
| `DEPLOY` | `APP_YAML` | App Engine deployment config. |
| `DEV` | `DEV_YAML` | Raw development config. |
| `GCLOUD_CONFIG` | `DEV["gcloud_config"]` | Active gcloud config with `NAME`, `ACCOUNT`, `PROJECT`, and the preflight-selected `BILLING_ACCOUNT`. |
| `DEV_CONFIG` | `DEV["dev_settings"]` | Development server overrides. |
| `TEST_CONFIG` | `DEV["test_settings"]` | Test server overrides. |
| `dev_config` | `APP` + `DEV_CONFIG` | Merged development runtime settings. |
| `test_config` | `APP` + `TEST_CONFIG` | Merged test runtime settings, including `BASE_URL`. |

The managed testing profile enables activity analytics and AI observability so
their owner-only HTTP contracts are deterministic in E2E runs. Explicit
`TEST_CONFIG` values are applied afterward and can still disable either feature
for focused configuration tests.

`SOURCE_URL` is an optional application setting used by the Manual's Open
Source card. Setup defaults it to the canonical Lagniappe repository and
preserves an operator-authored repository, fork, tag, or commit URL on later
refreshes. Set it to an empty string to hide the link.

`INSTALLER_EMAIL` and `DEPLOYER_EMAIL` record the Google identities selected by
the current setup run. The built-in flow uses the active
`GCLOUD_CONFIG.ACCOUNT` for both responsibilities, including during recovery,
while preserving `ADMIN_EMAIL` as the distinct application owner.
`AUTH_EMAIL_CONFIG` stores an authenticated SMTP transport: provider label,
host, port, STARTTLS or implicit SSL/TLS mode, username, password or API key,
sender address, and sender name. Fresh setup creates this schema directly from
the chosen SMTP provider when a custom domain is configured, or from a Gmail
or Google Workspace mailbox and Google App Password as the no-domain
bootstrap. Once a custom domain is configured, `./setup.sh email` can replace
the sender with any SMTP provider. Its Resend shortcut fills the provider's
fixed SMTP transport values and uses a domain-scoped Sending access API key as
the SMTP password; Resend's optional Cloudflare Domain Connect authorization
remains browser-owned and is not stored in application configuration. The
sender does not need project IAM and does not need to match the installer,
deployer, application owner, or administrator.
`RUNTIME_SERVICE_ACCOUNT_EMAIL` is the App Engine attachment and Storage
signed-URL account. `INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL` is the identity
expected in Cloud Tasks and Scheduler OIDC tokens. They are equal for this
release, but remain separate settings so client authority and internal request
authentication do not depend on credential JSON. These fields document
responsibility; they do not themselves grant IAM roles.

Runtime Google clients share project-bound Application Default Credentials
(ADC). Startup fails when the explicit identities are missing, and client
initialization fails when ADC is unavailable, cannot identify a project, or
targets a project other than `GOOGLE_CLOUD_PROJECT`. App Engine supplies ADC
from the attached runtime account. Local development and testing begin with
project-bound human ADC, then `CONFIG.google_credentials` creates and caches
short-lived impersonated credentials for `RUNTIME_SERVICE_ACCOUNT_EMAIL`.
Their Flask processes and Google clients therefore use the deployed runtime IAM
boundary without a private key.

Successful setup output is built from an explicit safe-field allowlist. It may
show identities, project/resource names, regions, versions, and commands, but
never dumps the `APP` mapping. In particular it omits service-account private
keys, `GIBBERISH`, `SECRET_KEY`, Redis passwords, legacy messaging API keys, Sentry
DSNs, SMTP passwords/API keys, and access tokens. Legacy schema-2 recovery
also discards the retired `FIREBASE_CONFIG` value.

Google locations are intentionally split:

- `APP_ENGINE_LOCATION` stores App Engine's immutable location spelling, such
  as `us-central`;
- `RESOURCE_REGION` stores the regional-service spelling used by Cloud Tasks
  and Cloud Scheduler, such as `us-central1`; and
- `INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL` stores the exact service-account
  email expected in internal Cloud Tasks and Scheduler ID tokens.

Both location settings are required. The `us-central`/`us-central1` and
`europe-west`/`europe-west1` pairs are normalized explicitly; other regional
identifiers retain their provider spelling. For this release the configured
OIDC subject must be the attached runtime service account.

Redis transport security is controlled by `REDIS_TLS`, which defaults to
`false`. When enabled, `REDIS_CA_CERT` must name a
readable PEM CA bundle; setup stores the project-relative
`config/files/redis_ca.pem` path. The shared connection builder resolves that
path against the application root and configures redis-py with TLS, required CA
verification, and hostname checking. Invalid enabled configurations fail
instead of falling back to plaintext. Redis initializes lazily, and the JSON
cache shares the same verified client.

`config/constants.py` owns the one-hour Gunicorn request timeout. Deployment
settings generation applies that timeout to the App Engine `entrypoint`.
Basic-scaled App Engine services support requests longer than an hour; the
shared Cloud Tasks HTTP target still bounds a single deferred delivery attempt
to 30 minutes.

Agent access is configured in app settings with `AGENT_ACCESS_ENABLED`,
`AGENT_ACCESS_EMAIL`, `AGENT_ACCESS_NAME`, and `AGENT_ACCESS_CODE`. Setup adds
these keys disabled by default and preserves non-empty user-edited values on
later refreshes. If access is enabled but the email, name, or code is missing,
setup fills those defaults so the option remains usable after updates. Agent
login uses the configured email as a normal user account; owners can change that
user's access by reassigning groups from the agent user's settings page.

AI model routing is configured in app settings with `AI_MODEL`,
`AI_UTILITY_MODEL`, `AI_IMAGE_MODEL`, and `AI_LOCATION`. The location is kept at
`global`. Owner-only Admin settings persist model choices in the Datastore
`site/ai` entity. That entity is the live authority for both the Admin form and
new AI generations, with deployed `CONFIG` values used when it is unavailable
or absent. Each generation resolves its model once and keeps it through
retries, tool calls, and structured final passes. `./setup.sh update` restores
the entity into
`config/files/lagniappe_settings.yaml` before deployment. `config/ai_models.py`
owns the curated Gemini model fallback list, live SDK discovery, retry defaults,
and the direct pricing URL. `config/ai_settings.py` owns validation and
application of saved model settings.

`AI_OBSERVABILITY` is a separate, default-off operator choice with a runtime
fallback of `false`. The ordinary installer asks whether to store owner-only AI
generation summaries, and preserves the existing choice on reruns/recovery.
The key remains absent from required settings and generated defaults. This
flag does not enable
page-view analytics, and `ANALYTICS` does not enable AI generation summaries.
The Analytics blueprint and owner directory link are available when either flag
is enabled, but tracking routes, queries, sections, and clear controls remain
dataset-specific.

Organize report generation leaves the service tier unset on its initial request,
which uses Gemini's Standard PayGo tier, and routes later durable attempts through
Priority PayGo with `X-Vertex-AI-LLM-Request-Type: shared` and
`X-Vertex-AI-LLM-Shared-Request-Type: priority`. The tier follows the whole
retry attempt, including missing-file summaries, proposal repair, and
form-submission completion.
Foreground AI calls retain five provider SDK attempts; calls inside a deferred
job use at most two, leaving outage recovery to the durable retry schedule.
Deferred jobs classify SDK timeouts, connection failures, and retryable HTTP
responses for durable retry.

Each worker attempt has a 24-minute wall-clock deadline inside Cloud Tasks' 30
minute delivery deadline. Its five-minute Datastore lease is renewed every 60
seconds, including while a provider call blocks, and control checks run between
provider rounds and tool handlers. Normal retry delays are 60, 180, and 600
seconds; quota retries are 60 and 300 seconds plus up to 30 seconds of positive
jitter. The reconciler uses a two-minute grace period, runs every five minutes,
and fails work that remains active for three hours. Its setup-owned Cloud
Scheduler job is enabled only while the transactionally maintained
`site/deferred-jobs-control` record contains recovery-required jobs; an empty
reconciliation repairs that record and pauses future runs immediately.
Independently, a two-minute
feedback task keeps long-running state visible while a provider request remains
active. Terminal deferred-job failures wait briefly for Sentry delivery before
the Cloud Tasks request returns so App Engine suspension cannot strand a queued
error event. Deleting an active job cannot revoke a Cloud Tasks request that is
already executing, so long preparation stages verify their lease before
durable writes; a missing job or replaced lease ends that request as a
cancellation rather than recreating or failing its deleted domain record.

The reconciler depends on the generated `jobs(status, modified asc)` and
`jobs(dispatch_state, modified asc)` Datastore indexes and an OIDC-authenticated
Cloud Scheduler job. Provisioning and IAM ownership are documented in
[INFRA_SETUP.md](INFRA_SETUP.md).

When `AI_OBSERVABILITY` is enabled, each live deferred generation updates its
same opaque summary row before and after provider/tool stages. The owner
Analytics dashboard separates those in-flight rows from completed aggregates
and marks a row stale after two missed heartbeat intervals. Prompt text, tool
arguments/results, file content, and entity/user identifiers remain excluded.

Gemini implicit context caching requires no application cache object. Organize
prompts put stable instructions before report-specific instructions, summaries,
and evidence so repeated requests have the longest practical shared prefix.
When `AI_DEBUG` is enabled, response usage breadcrumbs include prompt, cached
content, output, thought, and total token counts plus the reported traffic type.
The app does not create explicit cached-content resources for these short-lived
jobs; caching reduces repeated-prefix processing but does not replace quota
backoff or Priority service.

Production Sentry no longer needs a messaging-provider span filter. Application
poll failures retain their normal route/HTTP diagnostics.

## Local Runner Boundary

`runner/context.py` resolves the repository root, project virtualenv, supported
platform commands, and exact external executable paths shared by `run.py` and
`installer/`. It does not go to App Engine. `runner/process.py` provides the
shared argument-list subprocess adapter.

### GCloud Switcher (`runner/gcloud.py`)

Manages multiple GCloud CLI configurations for switching between
accounts/projects. Deployment, development-server startup, test startup, every
`run.py test` invocation, and focused installer modes use it to ensure the
checkout's saved GCP target is active.

**`config_gcloud()`** is the main entry point. It reads `SETTINGS.GCLOUD_CONFIG`:

1. Checks if the correct configuration is already active (no-op if so)
2. Verifies the account is authenticated (exits with instructions if not)
3. Creates the configuration if it doesn't exist
4. Activates it

`runner.gcloud.activate_repository_gcloud()` is the shared installer/runner
boundary. It does nothing when the checkout has no saved target, rejects a
partial `NAME`/`ACCOUNT`/`PROJECT` triple, and otherwise delegates to
`config_gcloud()`. Successful verification exports the active configuration
and project environment variables so child pytest and Flask processes inherit
the same project selected in the CLI. E2E and managed test-server startup also
use `runner/adc.py` to verify the separate Application Default Credentials
principal, project, and quota project. Development and testing accept the saved
human principal as the impersonation source or an already-impersonated runtime
principal, and perform a read-only authentication preflight. Any mismatch stops
before application import and directs the operator to
`venv/bin/python run.py auth`. Only that explicit runner command may refresh
the saved gcloud account login, open a browser, write human ADC, or correct its
quota project. Installer commands also require the saved human account.

## Commands

### Runtime Authentication (`runner/adc.py`, `runner/gcloud.py`, `run.py`)

`venv/bin/python run.py auth` is the explicit interactive boundary for local
application credentials. It selects the checkout's saved gcloud account,
checks whether that account token needs to be refreshed, selects the saved
project, and then writes human ADC for that exact account and project. The
command is idempotent when ADC already matches the saved principal, project,
and quota project. Development and testing commands never invoke this
interactive flow themselves; application configuration turns the saved human
credential into the short-lived runtime credential during startup.

### Data Disaster Recovery (`runner/data_recovery.py`, `run.py`)

`venv/bin/python run.py backup create` creates one full, fuzzy recovery set for
the production default Datastore mode database and all four runtime Cloud
Storage buckets. `backup list` shows only sets whose completion manifest was
written successfully.

`venv/bin/python run.py restore BACKUP_ID --dry-run` performs restore preflight
without changing data. The command without `--dry-run` requires the application
to be offline and an exact typed confirmation, replaces the live bucket
contents, purges Datastore, imports the selected export, and flushes Redis as a
cache rather than restoring it. See
[INFRA_SETUP.md](INFRA_SETUP.md#disaster-recovery-backups) for the recovery
contract and fresh-install runbook.

### Development Server (`runner/development.py`)

**`run_dev_server()`** activates the checkout's saved gcloud target and verifies
that ADC provides the saved human impersonation source or already uses the
configured runtime account before Flask imports the application. A mismatch
stops with a `run.py auth` instruction; development startup never opens an
authentication browser. During initialization, human ADC is wrapped in the
runtime credential. Flask then starts in debug mode on the configured port with
`FLASK_ENV=development`.

### Release Preparation (`run.py`)

`venv/bin/python run.py release-check [--base REF]` validates a prepared
`next/*` or `hotfix/*` tree before it enters `main`. It compares the prospective
commit with the exact release base, rejects installation-local files, requires
a fresh production build metadata file, service worker, and `BUILD_ID`, and
verifies that the package, package lock, build metadata, and release note use
one stable `X.Y.Z` version. The maintainer runs one canonical production build
after the release tree is frozen; the complete branch is installer-tested
before its main pull request is squash-merged.

### Deployment (`runner/deploy.py`)

**`deploy()`** runs the development deployment pipeline by default:

1. Runs the runtime deploy-surface preflight, which scans uploaded Python files
   for imports from `.gcloudignore`-excluded local packages and third-party
   imports missing from `requirements.txt`.
2. Cleans old JS chunks from `lagniappe/web/static/chunks/`
3. Runs `npm run build` (production Rollup build; when
   `SENTRY_AUTH_TOKEN` is configured, hidden source maps are uploaded to Sentry
   and then removed from static output)
4. Updates the PWA manifest with the current app name and site image version
5. Deploys to Google App Engine via `gcloud app deploy`

Setup uses the same helper in publish-only mode:
`deploy(build_assets=False, deploy_indexes=True, quiet=True,
announce_completion=True)`.
That path still runs the runtime deploy-surface preflight, but it deploys the
generated files already present in the repository without requiring npm and
without inventing or incrementing an application version. Ordinary setup,
`./setup.sh update`, and `./setup.sh upgrade` stamp generated settings with
the resulting checkout's `package.json` version before saving. Deliberate
release version changes are
managed through `venv/bin/python run.py version set <version>`. That command
updates `package.json`, the package-lock root metadata, generated application
settings, the release-note file, and the **Applies to** version in both
`ERROR_REPORTING_PRIVACY.md` and its public HTML template. It does not change
the notice's effective date; update that date only when the notice itself
materially changes.

The App Engine upload filter in `.gcloudignore` root-anchors top-level
development folders such as `/testing/`, `/installer/`, and `/runner/`. Do not
change those to unanchored patterns like `testing/`; gitignore-style matching would also
exclude nested runtime packages such as `lagniappe/web/routes/testing/`.
All `config/files/` content is excluded and then only
`lagniappe_settings.yaml` and the optional `redis_ca.pem` are re-included.
Temporary, backup, development, generation/journal, and recovery-input files
remain local. Deploy prints a warning because the canonical settings contain
runtime secrets and the CA is runtime trust material.

`config/constants.py` is the template source for App Engine static handlers
that setup/update writes back into `app.yaml`. It also carries the
tracked `BUILD_ID` generated by frontend builds. The `/chunks/*.js` handler
must stay before the general `*.js`/`*.mjs` handler. Chunk filenames are stable, but
generated import and precache URLs include the build ID, so the handler uses a
long-lived immutable cache policy without mixing bundle generations.
The CSS handler serves `text/css; charset=utf-8` so bundled stylesheets are
interpreted consistently by browsers and the service-worker cache.
PDF previews also serve PDF.js auxiliary decoder assets from `/pdfjs/wasm/`;
keep those handlers before the general JavaScript handler when changing static
asset routing. The general handler includes `.mjs` so the emitted
`/pdf.worker.min.mjs` module is served as JavaScript instead of falling through
to the final HTML 404 handler.

Dynamic App Engine handlers are an allowlist of the registered blueprint URL
prefixes, a few unprefixed navigable pages, the root page, and App Engine's
`/_ah/` lifecycle routes. Browser protocol routes such as sync, polling, search
fragments, session maintenance, and site settings live under the `/l`
blueprint, so adding one does not expand the root allowlist. The final handler
serves the generated `lagniappe/web/static/404.html` page for every other path.
Obvious probes therefore receive a familiar not-found page without starting
Gunicorn. App Engine static handlers cannot assign a 404 response status, so
this is intentionally a no-index, no-store soft 404. The authored page lives at
`lagniappe/web/static/404.html`; it does not require a frontend build step. Keep
`APP_BLUEPRINT_ROUTE_PREFIXES` synchronized with
`lagniappe/web/start/blueprints.py` and `APP_ROOT_ROUTE_PREFIXES` synchronized
with Home and `main.py` routes; the tooling contract checks both.

### Deployment Settings (`deployment.py`)

Normalizes deployment settings used by setup-generated `lagniappe.yaml`,
update restore, and runtime site-settings validation. This module is
part of the uploaded runtime surface; setup-only Datastore restore helpers stay
in `installer/deployment.py`.

### AI Settings (`ai_settings.py`, `ai_models.py`)

Normalizes AI model settings used by setup-generated app settings and runtime
site-settings validation. Model discovery uses `google-genai` when credentials
and project context are available, but silently falls back to a curated Gemini
catalog and preserves any saved custom current model names.

### Testing (`runner/testing.py`)

**`run_test_server()`** starts a Flask server for e2e tests:

1. Checks the authored frontend inputs and generated development-bundle
   outputs against `reports/test-frontend-bundle.json`; runs `npm run dev` when
   the inputs or outputs are missing, changed, restored, or incomplete
2. Switches to the correct GCloud configuration
3. Starts Flask with `FLASK_ENV=testing` on the test port
4. Filters server output to hide static file requests (fonts, chunks, icons, etc.)
5. Allows a cold Flask import up to roughly 17 seconds to make `/l/ping` healthy
   before treating startup as failed

The repository test runner performs the same preflight before launching pytest
when an E2E target—or the unscoped full suite—is requested. Unit, JavaScript,
tooling, and setup-only runs do not invoke npm. Running the preflight before
pytest ensures the test process and Flask subprocess import the same generated
`BUILD_ID`. E2E targets also automatically set `STRICT_RELATION_LOADS=1`, so
unloaded-relation diagnostics cannot be omitted from browser/server coverage.
All test targets independently activate the complete repository gcloud target
before pytest starts; frontend preparation remains E2E-only.

**`start_managed_test_server()`** and **`teardown_managed_test_server()`**
back `venv/bin/python run.py test-server --start` and `--teardown` for manual
browser review. The managed server uses the same testing environment and port
as E2E, records its PID/log under `reports/test-server.*`, resets E2E artifact
directories on start, applies the same frontend-bundle freshness preflight,
and stops the managed server before cleaning test-prefixed datastore/cache data
on teardown.

**`testing/utility/browser_review.py`** backs
`venv/bin/python run.py browser-review capture/render` for manual or agent UI
critique. It stores raw evidence and the curated HTML report together under
`reports/browser_reviews/<slug>_<timestamp>/`.

**`update_test_indexes()`** creates test-prefixed versions of Datastore indexes (e.g. `kind` → `test-kind`), deploys them, then restores the original index file.

### Material Symbols

Material Symbols Rounded is self-hosted as an official Google Fonts subset.
Semantic records live in `src/style/icons.yaml`; normal builds are offline and
emit the vendored WOFF2 with a content-derived filename. A completed build
keeps only the current Material Symbols asset in the generated font directory.

`venv/bin/python run.py icons` is the explicit maintainer refresh command. It
collects the unique registry glyphs, requests weight 300–600 and fill 0–1 from
Google Fonts, validates the WOFF2 response, updates the adjacent source
metadata and digest, then rebuilds the frontend. Reusing an existing semantic
icon does not require a refresh; adding or changing a glyph does.

### Dependency Upgrade (`runner/upgrade.py`)

**`upgrade_all()`** upgrades all project dependencies:

1. Node.js via nvm (or n), then writes the exact installed version to `.nvmrc`
2. npm packages via npm-check-updates (`ncu -u` + `npm install` + `npm audit fix`)
3. pip packages from setup, runtime, and development requirements (resolves
   all direct requirements and eager transitive updates together)
4. Runs `pip check` to reject an inconsistent resolved environment
5. Updates `requirements-installer.txt`, `requirements.txt`, and
   `requirements-dev.txt` with current installed versions only after dependency
   validation succeeds

The console output is a concise before/after summary, while the full command
output, exact npm/pip version changes, notes, and errors are saved to
`reports/upgrade-*.md`.

The no-argument `venv/bin/python run.py upgrade` command uses this
maintainer-only dependency-upgrade path. It never fetches or resets the
repository.

### Utilities (`runner/process.py`)

**`run_command(command)`** -- subprocess wrapper with error handling. Prints errors and exits on failure when `check=True`.

## Exports (`config/__init__.py`)

The config package exports only runtime-safe configuration surfaces. Local
commands import orchestration directly from `runner/`; the config package does
not re-export runner functions.

```python
from config import (
    SETTINGS,             # Settings singleton
    Environment,          # Environment enum
    Directory,            # Config directory enum
    File,                 # Config-file enum and file helpers
)
```
