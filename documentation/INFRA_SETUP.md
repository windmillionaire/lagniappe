# Infrastructure Setup

The setup system (`installer/`) is an interactive CLI installer that configures a
new Lagniappe instance from scratch. The full installer handles core GCP,
Identity Platform, Redis, optional Sentry, AI defaults/observability, manifest creation,
and deployment. Custom domain, AI-only configuration, Redis transport
security, development tooling, and app-side settings updates are separate
entry-point modes. Replacing an installed checkout with a current remote branch
is the distinct software-upgrade mode. Setup pins its direct dependencies,
while packages owned by those libraries remain resolver-managed. If direct versions drift or
`pip check` finds an incompatible transitive set, setup eagerly re-resolves the
complete direct setup requirement set before importing setup libraries. This
also keeps outdated native modules from being locked during an in-place Windows
upgrade. It is the setup-sized equivalent of the eager resolver transaction
used by `run.py upgrade`.

## Entry Point

Setup resolves the checkout from `runner/context.py`, whose repository root
comes from `Path(__file__)`; it does not infer the checkout from the caller's
working directory. The platform launchers create this checkout's isolated
`venv` on first use and reuse that exact environment thereafter. On macOS and
Linux, the launcher tries a supported `python3` or `python` from `PATH`, then
falls back to the Python reported by Google Cloud CLI. On Windows, it selects
or offers to install a supported standalone Python and deliberately avoids a
virtualenv based on Google Cloud CLI's bundled Python:

```bash
./setup.sh
```

In Windows PowerShell, use `.\setup.cmd`; Command Prompt may use `setup.cmd`.
Launcher arguments are forwarded unchanged, so `./setup.sh doctor` and
`.\setup.cmd doctor` use the same Python entry point and environment.
The launchers do not activate the virtualenv and do not search for another
active environment; they invoke this checkout's interpreter directly. For
direct Python invocation after the environment exists, use
`venv/bin/python -m installer ...` on POSIX or
`venv\Scripts\python.exe -m installer ...` on Windows. Another project's or a
user-level virtualenv is intentionally rejected.

The no-argument installer announces recovery and obtains dependency consent
before preparing its pinned setup packages. Focused commands such as `doctor`,
`repair`, `update`, and `upgrade` prepare those packages at the shared Python
CLI boundary before importing their handlers, then activate the complete gcloud
configuration/account/project saved in this checkout. This makes them work on
the first invocation after a launcher creates the project virtualenv without
inheriting another checkout's ambient gcloud target. An unconfigured checkout
is left alone and a partial saved target fails closed. The full installer owns
its activation later, after new-install selection or recovery has established
the target.

It supports subcommands for running specific steps:

- No args: full installation
- `doctor`: inspect generated files, active gcloud identities, expected
  resources, and read-only provider state after activating this checkout's
  saved target; never repairs drift
- `repair`: explicitly rerun the complete idempotent installation
  reconciliation, then validate the resulting local generation
- `development`: add the test-prefixed Cloud Storage buckets and local
  Python/Node/Playwright toolchain to an existing completed installation; safe
  to rerun
- `url`: App Engine custom-domain setup with provider-neutral manual DNS or
  optional DNS-only Cloudflare automation
- `ai`: configure AI
- `security`: enable, refresh, or disable verified Redis Cloud TLS, then
  optionally redeploy
- `jobs`: idempotently create or update deferred-job recovery infrastructure
  after the corresponding application version has been deployed
- `update`: refresh generated config/index/manifest defaults without replacing
  source code, restore app-saved deployment settings, AI settings, and site
  images, then optionally deploy
- `upgrade [--branch BRANCH]`: replace tracked source with `origin/main`, or
  `origin/BRANCH` when selected, then perform the same configuration,
  restoration, reconciliation, and optional deployment as `update`

Only one subcommand may be selected. Entry points return zero only after
their requested work succeeds; failed validation, provider failure, timeout,
and operator cancellation are nonzero. Setup helpers raise `SetupError`
subclasses, and only the `installer` CLI boundary maps them to process exit
codes.

Operator-facing prose should be passed through `installer.wrap_text()` before it is
printed or used as an input prompt. The helper wraps on word boundaries to the
current terminal width with a one-column margin, caps paragraphs at 100 columns
for readability, preserves intentional line breaks and hanging list indents,
and leaves long indivisible values such as URLs intact. Provider output,
resource identifiers, commands, and other copy-sensitive values should remain
verbatim.

Installation checks are deliberately split by authority:

- `validate_installation()` / `verify_installation()` are read-only and never
  create or retarget a project;
- `activate_installation()` explicitly activates the saved local gcloud
  configuration;
- `initialize_installation()` owns first-time project/settings work; and
- `repair_installation()` explicitly reconciles before validating.

Focused mutating commands that require an already-valid generated deployment
call `prepare_existing_installation()`, whose name makes the local gcloud
activation explicit. `update` and `upgrade` activate the saved target without
validating the existing generation because rebuilding that generation is their
job: `update` preserves a developer's current worktree, while `upgrade`
replaces tracked source from the selected remote branch.

`doctor` is the exception to the provider-mutation boundary. The shared CLI
boundary first activates the saved local gcloud target, but the diagnostic
itself runs outside the setup process lock/journal, reads local files with
explicit UTF-8, and issues only read-only gcloud/provider lookups. It returns
nonzero for missing files, a stale constants generation, identity mismatch, unavailable
resources, or provider drift. It prints `./setup.sh repair` as the next action
but does not invoke it. `repair` is deliberately noisy about its mutation
authority and uses the normal operation journal.

## Recovering an Existing Installation

The owner-only settings download is the supported local recovery snapshot. Its
filename is always `lagniappe_settings.yaml`, including for installations with
a custom application name. On macOS or Linux, recover from a clean checkout
with:

```bash
git clone <lagniappe-source>
cd <lagniappe-source>
mkdir -p config/files
# Save the owner download exactly at:
# config/files/lagniappe_settings.yaml
./setup.sh
```

On Windows, use a regular **PowerShell** window with Git and Google Cloud CLI
on `PATH`. Keep the checkout outside the Google Cloud CLI installation in the
stable per-user local application directory. This native Windows installer
path is implemented and covered by mocked Windows CI, but remains experimental
until a real clean-machine recovery/deploy smoke is complete:

```powershell
$lagniappePath = Join-Path $env:LOCALAPPDATA "Lagniappe"
git clone <lagniappe-source> $lagniappePath
Set-Location $lagniappePath
New-Item -ItemType Directory -Force config/files
# Save the owner download exactly at:
# config/files/lagniappe_settings.yaml
.\setup.cmd
```

PowerShell may resolve the bare `gcloud` command to Google Cloud CLI's
`gcloud.ps1` wrapper and reject it under the default execution policy. Use
`gcloud.cmd` for commands entered directly in PowerShell; this does not require
changing the machine's execution policy:

```powershell
gcloud.cmd auth login
```

Google's macOS installer does not create a separate Cloud CLI shell. Run the
POSIX commands in Terminal, iTerm, or another normal `zsh`/`bash` terminal
after the installer has added `gcloud` to `PATH`.

Setup requests Application Default Credentials itself. For a new project, it
waits until the project has been created before opening that authentication
flow and assigning the ADC quota project. Before either ADC browser path, setup
instructs the operator to choose **Select all** when Google displays granular
permission controls. The requested access authorizes the Google Cloud CLI and
local setup code to act as the operator in their own project—in practical
terms, the operator is granting the permissions to themselves. It does not
grant the Lagniappe maintainer access to their account, project, or
credentials. Every requested permission is required to configure, verify, or
deploy the installation.

When the canonical settings file exists and `lagniappe_dev.yaml` does not,
setup announces recovery before installing dependencies or changing
configuration. It takes the target only from the snapshot's
`GOOGLE_CLOUD_PROJECT`; the ambient gcloud project is never a recovery
candidate. The authenticated account becomes the installer/deployer, while the
recovered `ADMIN_EMAIL` remains the application owner.

Before recreating `lagniappe_dev.yaml`, setup validates the file's schema and
cross-checks its project, service-account, Identity Platform, App Engine, OCR, queue, and
bucket identities. It then authenticates CLI and ADC against that exact project
and performs read-only discovery of saved service-account, App Engine,
deployed-version, queue, OCR, Identity Platform, Storage, and Redis markers. Discovery
reports `AVAILABLE`, `ABSENT`, or `UNAVAILABLE`. Permission, authentication,
network, malformed-response, and ambiguous failures are `UNAVAILABLE` and stop
recovery; they are never treated as permission to create a replacement.

The snapshot remains authoritative for settings. Surviving provider state is
compared with it but does not silently replace it. Missing resources may be
recreated only by the normal post-confirmation installer steps in the recovered
project. Recovery preserves monitoring, Sentry, AI, Redis, domain, and other
saved choices; use the focused setup modes when deliberate reconfiguration is
needed.

The encrypted settings snapshot does not itself contain application data.
Lagniappe's minimal provider-data recovery workflow is described in
[Disaster-Recovery Backups](#disaster-recovery-backups).

### Disaster-Recovery Backups

Setup provisions a fifth, production-only `recovery` bucket alongside the
private, public, history, and export runtime buckets. The recovery bucket uses
the same stable settings-derived naming contract, but it is not exposed through
runtime `DataServices`, has no browser CORS policy, and grants neither the
runtime service account nor `allUsers` setup-managed bucket access. Setup
grants the recorded human installer/deployer object administration on this
bucket and the four runtime buckets so terminal backup and restore commands can
read and write their objects. Keep the encrypted canonical settings and its key
off-machine: the saved `GIBBERISH` value is what lets a fresh checkout
rediscover this bucket.

Create a manual recovery set with:

```bash
venv/bin/python run.py backup create
venv/bin/python run.py backup list
```

One recovery set contains a complete managed export of the default Datastore
mode database and a recursive copy of every live object in each of the four
runtime buckets. The copies run sequentially and the Datastore export is not a
point-in-time snapshot, so the set intentionally has a fuzzy start-to-finish
consistency window. A `complete` manifest is created last; failed or abandoned
sets are not listed or restorable. Versioned, noncurrent, and soft-deleted
Storage objects are outside this first recovery contract.

For a disaster in which the application database and runtime buckets were
deleted, restore the canonical settings into a fresh checkout, run the normal
installer/repair flow against the exact recovered project, and then use:

```bash
venv/bin/python run.py backup list
venv/bin/python run.py restore BACKUP_ID --dry-run
venv/bin/python run.py restore BACKUP_ID
```

The recovery bucket and selected complete set must still exist. If that bucket
was also permanently deleted, the canonical settings alone cannot reconstruct
application data. This first version deliberately keeps recovery data in the
same project; cross-project or offline replication can be added later.

An actual restore requires App Engine to be disabled or have no
traffic-serving versions. It verifies the exact saved/active project,
settings-derived bucket identities, manifest paths, Datastore mode and
location, and required artifacts before asking for a typed project-and-backup
confirmation. It then makes each runtime bucket exactly match the snapshot,
deleting extra live objects, bulk-deletes every existing Datastore entity, and
imports the selected export. If the default database was deleted, restore
recreates it in the recorded location. Redis is not backed up; its cache is
flushed after a successful data import. Leave the application offline until
smoke checks pass, then re-enable it manually.

This is intentionally a manual, full-backup baseline. It does not schedule or
prune sets, replicate them outside the project, preserve Cloud Storage bucket
configuration, or capture Cloud Tasks, indexes, and other provider control
plane state. Setup and deployment reconstruct the setup-owned bucket metadata,
IAM, and indexes.

After installation, recovery, or any manual config edit, use:

```bash
./setup.sh doctor
```

In Windows PowerShell, use:

```text
.\setup.cmd doctor
```

If it reports drift, first verify that its saved project and identities are the
ones you intend to change, then run the printed `./setup.sh repair` command. A
successful install prints an allowlisted final summary of the application,
installer/deployer/owner/runtime identities, resource names, regions,
Lagniappe/Python/runtime versions, deployment state, and exact doctor/repair
commands. It never serializes the settings mapping and therefore cannot print
private keys, passwords, tokens, Flask secrets, legacy messaging API keys, or a Sentry
DSN.

## Keyless Runtime Authentication

All runtime Google clients use project-bound Application Default Credentials
(ADC). App Engine obtains ADC from the service account attached in
`lagniappe.yaml`; setup and provider provisioning continue to use the
authenticated human installer ADC. Ordinary setup never creates a
user-managed service-account key.

The canonical schema stores two explicit identities:

- `RUNTIME_SERVICE_ACCOUNT_EMAIL` is attached to App Engine, owns runtime
  consumer permissions, and signs Storage URLs;
- `INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL` is placed in Cloud Tasks and
  Scheduler OIDC tokens and is verified by internal process routes.

They must match. Setup enables
`iamcredentials.googleapis.com` and grants
`roles/iam.serviceAccountTokenCreator` only on that exact service-account
resource to the runtime account and saved deployer. This supplies
`iam.serviceAccounts.signBlob` for remote Storage URL signing. It also retains
the exact-resource `roles/iam.serviceAccountUser` bindings required for App
Engine attachment and internal OIDC token creation. Neither role is granted at
project scope.

Schema 2 and the two explicit identity settings are the only supported
configuration contract. Runtime startup and recovery fail closed when that
contract is absent. No other identity inputs are accepted.

### Local ADC for development and tests

Human ADC is reserved for setup, repair, and provider provisioning:

```text
gcloud auth login
gcloud auth application-default login --project=PROJECT_ID
```

The runtime clients reject ADC whose discovered project differs from the saved
project. Authenticate local app execution explicitly with:

```text
venv/bin/python run.py auth
```

That interactive command selects and checks the saved gcloud account first,
refreshes its login when stale, selects the saved project second, and finally
writes human ADC for that exact account and project. Local development, E2E,
and managed test-server commands only verify that source credential; they never
open a browser or mutate authentication. On a mismatch they stop before
importing the app and direct the operator back to `run.py auth`.

When Flask initializes in development or testing,
`CONFIG.google_credentials` creates a short-lived impersonated credential for
`RUNTIME_SERVICE_ACCOUNT_EMAIL` from that human source. Every application
Google client receives the runtime credential and exercises the same IAM
identity as App Engine. No key file is created or loaded. The auth command uses
the equivalent of:

```text
gcloud auth application-default login ACCOUNT --project=PROJECT_ID
```

The authenticated human needs Token Creator on the exact runtime account.
Setup and repair continue using the human source ADC; the underprivileged
runtime identity never provisions or reconciles the installation. No downloaded
private key or
`GOOGLE_APPLICATION_CREDENTIALS` key file is part of the supported workflow.
Backup and restore remain privileged operator commands executed by the saved
human gcloud CLI identity; they do not load human ADC into the application.

## Dependency Files

`requirements-installer.txt` pins bootstrap-only installer clients and console
helpers. `requirements.txt` is deployment-facing and contains dependencies
needed by the App Engine runtime. Local developer and test tooling belongs in
`requirements-dev.txt`, which includes `requirements.txt` plus pytest and
Playwright harness packages. When setup discovers a missing package, it looks
up the exact pin in these files and refuses an undeclared ad-hoc install.
Before the default installer imports configuration or provider clients, it
checks every dependency used by that flow against installed distribution
metadata, installs all missing or version-mismatched exact pins in one pip
transaction, revalidates the imports and versions, and runs `pip check`.

Direct Python dependencies are intentionally exact-pinned in the three
requirements files. Python transitive resolution remains intentionally loose:
the upgrade command resolves all direct targets together with eager transitive
updates, runs `pip check`, writes back every direct pin, and leaves a detailed
local report for review before the test suite is accepted. npm uses the
committed `package-lock.json` for exact direct and transitive resolution. This
is the project reproducibility policy; a separate Python lock/hash file and
formal SBOM are not required release artifacts.

## Development Installation

Lagniappe does not use a synthetic configuration for development. The
application and its browser/server tests depend on the ignored configuration,
GCP project, Identity Platform, and Redis resources created by ordinary setup. Developer
onboarding is therefore intentionally two-stage:

```bash
./setup.sh
./setup.sh development
```

The ordinary installer creates the production installation and may be completed
without accepting its final deployment prompt. It does not create test-prefixed
buckets. `development` then verifies the saved installation and active Google
Cloud identity, provisions the four test-prefixed buckets, checks Node/npm and
the `package.json` engine range, installs `requirements-dev.txt`, runs `npm ci`,
installs Playwright Chromium, and runs `npm run dev`. It is additive and
idempotent: it never replaces the installation config or provisions duplicate
production resources.

Native Windows development, test-server, and E2E process management are
intentionally unsupported. Windows developers must use WSL2 and the POSIX
commands above. Native Windows support is limited to ordinary install,
recovery, update, and deploy through PowerShell and `setup.cmd`; those ordinary
operator workflows do not require WSL2.

Ordinary setup also adds `SOURCE_URL`, defaulting to the canonical repository.
An operator can replace it with a fork, tag, or commit URL, or set it to an
empty string to hide the Manual's Source link. Setup/update refreshes preserve
that authored value.

`.nvmrc` supplies the recommended Node version. `package.json` accepts
`^22.18.0 || >=24.11.0`, matching the floors imposed by the current frontend
toolchain. The dependency upgrade command updates `.nvmrc` to the exact Node
version installed during the upgrade.

If ordinary setup opted into the maintainer Sentry project, development setup
requires the developer to replace that DSN with their own or disable error
reporting before dependency installation proceeds. This keeps development
failures out of maintainer telemetry. A normal non-development installation
may remain default-off, opt into the maintainer project, or use an
operator-supplied Sentry DSN.

## Installer Portability Contract

Ordinary install, recovery, update, and deploy are designed for Linux and
macOS terminals and for native Windows PowerShell. `setup.sh` and `setup.cmd`
locate Python 3.12 or newer, create the checkout's `venv` if it is missing, and
run `python -m installer` from it. At process start, every installer mode
verifies that the running interpreter is this checkout's `venv`.

On native Windows, `setup.cmd` deliberately rejects Google Cloud CLI's bundled
Python. That distribution places third-party packages in its base `Lib`
directory alongside the standard library; child virtualenvs must retain that
directory on `sys.path`, so packages such as gRPC and cryptography otherwise
leak into an apparently isolated environment. The launcher prefers an existing
standalone Python. When none is available, it asks before using WinGet to
install `Python.Python.3.14` for the current user. If the existing generated
`venv` reports Google Cloud CLI's bundled Python as its base, the launcher
removes and recreates only that generated `venv`. It also rejects any newly
created environment whose `sys.path` still exposes the bundled Python.

On macOS and Linux, `setup.sh` uses a suitable host Python and retains Google
Cloud CLI's interpreter only as a fallback. Both launchers run Python with `-E`
so host `PYTHON*` variables cannot add external packages to the project
environment; generated repair commands retain the same isolation. The shared
`runner/context.py` module resolves the repository root and the exact `gcloud`,
`git`, `node`, and `npm` executables once. Generated repair commands use
`sys.executable`; provider calls use argument-list subprocesses rather than
shell expressions.

The frontend build uses a portable Node runner instead of POSIX-only npm
script syntax. Setup initializes Windows console translation through Colorama,
honors non-TTY and `NO_COLOR` output, and falls back to ASCII status markers
when Unicode is unsafe. Setup, config, and report tooling explicitly read and
write UTF-8.

Secret configuration and setup-state files use owner-only modes on POSIX.
Native Windows applies a best-effort restricted ACL with `icacls`; if that ACL
cannot be applied, setup emits a warning and the operator must protect the
file manually. Local setup tests exercise mocked platform branches and
installation workflows. Hosted CI runs source-quality and traceability checks
on Ubuntu; neither replaces real clean-machine installation smoke tests.
Development and test workflows on Windows use WSL2.

## Installation Flow (`installer/install.py`)

The full installation runs these steps in order:

1. **Runtime, recovery, and dependency gate** -- requires Python 3.12+ running
   from the project virtualenv; announces the canonical recovery-file shape
   before dependency changes; ensures pip and gcloud are available; validates
   the exact setup dependency pins as one transaction; and runs `pip check`.
2. **Identity and target preflight** -- obtains a validated application name;
   selects a confirmed, syntax-valid project ID
   with a randomized suggestion for new installs; activates and re-reads the
   named gcloud configuration/account/project; identifies the ADC principal,
   ADC project, and quota project; and performs read-only project, billing
   account, project billing, and required-API checks. Before those provider
   checks, setup saves a local, non-secret resume draft containing the chosen
   name and CLI target; the completed configuration replaces that draft. An
   Billing-account discovery is deferred for a new project because the project
   and its bootstrap APIs do not exist yet. An empty billing-account listing is
   not treated as an authentication failure. The ambient gcloud project is
   offered only when its active configuration name exactly matches the
   normalized installation name. Declining that existing project continues to
   the randomized new-project suggestion; declining a proposed new project
   exits setup. Every value prompt that displays a bracketed suggestion
   explicitly says that Enter accepts it and substitutes that value before
   validation. This includes randomized project IDs, the default administrator
   name, and suggested email/SMTP values. Choice prompts use the conventional
   capitalized Enter default, such as `Y` in `[Y/n]` or `N` in `[y/N]`.
3. **Draft and mutation confirmation** -- for recovery, validates the exact
   target and surviving resources before recreating the development file. It
   then writes the complete generated local draft, displays a concise
   **Configuration** summary with the identities, target, application owner,
   planned or existing runtime service-account email, and API state, and asks
   `Continue with installation?` with a default-no confirmation.
4. **Confirmed project preparation** -- for an existing project, explicitly
   aligns and re-verifies ADC before confirmation. For a new project, creates
   only the confirmed randomized or entered ID, enables the Cloud Resource
   Manager, Service Usage, and Cloud Billing bootstrap APIs, and then repeats
   billing-account discovery before aligning ADC. Setup automatically selects
   the sole accessible open billing account and links it. When no account is
   discoverable, setup opens the target project's Google Cloud billing page
   and directs the operator to link an existing account. It then discovers and
   saves the linked account and verifies billing and Service Usage access
   before general API enablement.
   Some Google Cloud project lookup failures cannot distinguish an unused ID
   from an inaccessible existing project. Setup treats that ID as a creation
   candidate, and Google Cloud rejects it without changing an existing project
   if the ID is unavailable.
5. **GCP services and runtime boundary** -- enables required APIs, creates or
   reconciles the runtime service account and its narrow IAM, sets up App
   Engine after an explicit immutable-location confirmation, persists the
   provider's actual location/hostname, provisions the production and recovery
   Storage buckets, creates the Cloud Tasks queue, and creates the OCR
   processor.
6. **Domain, authentication email, and Identity Platform**
   -- asks whether the operator already has a custom domain. When they do,
   setup creates the App Engine mapping, reconciles or prints its DNS records,
   and tests an operator-selected SMTP provider directly. Otherwise it opens a
   Google account picker for App Passwords and tests a Gmail or Google
   Workspace mailbox over SMTP/STARTTLS as the zero-domain bootstrap. It then
   initializes standalone Identity Platform against the selected public
   origin and enables email/password authentication.
7. **Admin/OAuth** -- sets the admin user, opens the target project's current
   Google Auth Platform Clients page, and guides the remaining one-time
   registration and Web OAuth client creation. If the platform is not
   registered yet, the operator uses **Get started**, chooses the external
   audience, and finishes the short app-information flow before creating the
   client. Setup registers the resulting client with Identity Platform but
   does not persist its client secret.
8. **Redis** -- configures Redis Cloud connection details, offers verified TLS,
   and tests access using the same connection options as the app.
9. **Optional monitoring** -- asks whether privacy-reduced errors may go to the
   maintainer under the
   [error-reporting privacy notice](../ERROR_REPORTING_PRIVACY.md); after
   declining, the operator may configure their own Sentry DSN instead.

The required-API preflight lists enabled services once before confirmation.
The mutation phase reuses that confirmed set: when no required APIs are
pending, it makes no additional `gcloud services list` calls. When services are
missing, it announces that API enablement may take up to five minutes and
enables them in one bounded command. A defensive fallback for
callers without preflight state performs one enabled-service listing with a
60-second timeout rather than one unbounded lookup per API.
Google may report a newly enabled service before its backend is ready. Setup
treats `SERVICE_DISABLED` during that propagation window as transient; the
first IAM and Identity Platform operations report bounded retry progress
instead of dumping the provider's structured error.
   Existing consent and destination are preserved by default on reruns.
10. **AI defaults** -- sets default primary, utility, and Gemini image model
   names when missing, offers the AI model change flow, and records an explicit
   default-off `AI_OBSERVABILITY` choice.
11. **Version/manifest** -- updates stored version when package metadata is
    newer and creates the PWA manifest if needed.
12. **Deployment** -- deploys indexes and the app to Google App Engine using
    the generated files already present in the repository, then creates the
    deferred-job recovery schedule during a quiet wrapping-up phase after a
    successful deployment. The schedule is installed proactively because
    future jobs need it even when no job exists during installation. If
    deployment is deferred, setup prints the separate `jobs` command. If
    recovery provisioning fails after deployment, update reports a
    warning, leaves the successful deployment intact, and returns nonzero;
    active deferred jobs may fail until the operator repairs the schedule with
    `./setup.sh jobs`. The deploy helper announces its ten-minute upper wait
    estimate before handing progress output to `gcloud`.

App Engine discovery and confirmation have separate terminal lifecycles.
Discovery's progress context exits completely before setup prints the immutable
location warning and calls `input()`, so an animated terminal redraw cannot
cover or consume the response. EOF is a typed cancellation with instructions to
rerun in an interactive terminal. Only an affirmative response starts the
creation request and a new progress context. The long-running operation has a
300-second timeout, and its initial discovery/create RPCs each have a 60-second
timeout; timeout or ambiguous transient failure explains that Google may still
complete the application and that rerunning setup will discover and reuse it.
Permission, invalid-location, conflict, and other provider failures remain typed
nonzero exits. Existing applications skip the confirmation and reuse their
provider-reported immutable location and hostname.

Custom domain mapping is available during the default install when the
operator already owns a domain; `url` remains the post-install entry point.
Redis TLS is offered during a fresh Redis setup and can be changed later with
`security`. Site images, deployment settings, and AI model settings are saved
from the owner-only Admin settings page and applied with `update`.

## Module Breakdown

### Config Files (`installer/create_config.py`)

Creates/verifies `lagniappe.yaml`, `config/files/lagniappe_dev.yaml`, and
`config/files/lagniappe_settings.yaml`. Uses template constants from
`config/constants.py` for default values, validates required files, and can
create fresh settings from the active gcloud account and selected project.
The canonical settings file carries `CONFIG_KIND: lagniappe-settings` and
`CONFIG_SCHEMA_VERSION: 3`. Recovery accepts that current schema, upgrades
schema 2 snapshots, and rejects missing, unknown, or inconsistent identity
metadata rather than retargeting the installation.
`BUILD_ID` is not written to local settings; it is tracked in
`config/constants.py` so updated source checkouts receive the repo's current
asset cache-busting value.
Fresh setup never treats gcloud's `(unset)` text or command errors as project
or account values. It stores structured success/unset/error results, fails
closed when the activated CLI identity cannot be re-read exactly, and saves the
chosen billing account beside the named gcloud configuration for review.
Setup does not require `AI_OBSERVABILITY`, but it asks for an explicit
default-off choice after the model prompts. Existing values are preserved by
default on install/recovery reruns.
If the ADC quota project check finds credentials tied to a different account or
project, setup opens `gcloud auth application-default login ... --project=...`
and retries the quota-project assignment. Setup continues only after the ADC
principal, ADC project, and ADC quota project exactly match the selected CLI
account and target. A new project is the one unavoidable two-stage case: the
confirmed project must exist before ADC can name it. Setup first enables the
management APIs that ADC's quota-project permission check depends on, repeats
billing-account discovery, then forces a transactional ADC login for the new
target before billing or later provider mutations. If setup fails or is
cancelled before the new principal's permissions are confirmed, the previous
ADC file is restored.
Interactive ADC authentication is transactional across that verification. If
the authenticated principal does not match or lacks the required project-level
installer/deployer permissions, setup restores the ADC file that existed
before authentication. If there was no prior file—or the already-selected ADC
is the rejected credential—setup removes it so the next setup run reopens the
browser flow. Credentials are kept only after the project permission preflight
passes.

These generated installation files are intentionally ignored by git so source
upgrades do not overwrite installation-specific state. `./setup.sh upgrade`
replaces tracked source before rebuilding them; `./setup.sh update` rebuilds
them from the source already in the checkout.

Generated configuration is persisted transactionally. `Settings.save()` may
target one generated file; unchanged files are not replaced. Writes use
explicit UTF-8/LF serialization, a same-directory temporary file, flush/fsync,
and `os.replace`. Empty output is rejected. The canonical settings and
development settings use owner-only POSIX mode and a best-effort restricted
Windows ACL. After a complete set exists,
`config/files/lagniappe_generation.json` records the SHA-256 source generation
of `config/constants.py`, excluding its volatile `BUILD_ID` line. Deploy
requires all six generated files to exist and be nonempty, and refuses a
missing, invalid, or stale constants generation. Content changes to
`package.json`, the web manifest, or a developer's generated configuration do
not by themselves invalidate the generation marker.

Only `config/files/lagniappe_settings.yaml` and an optional
`config/files/redis_ca.pem` are re-included from `config/files/` in the App
Engine upload. The settings file contains runtime secrets and the CA file is
runtime trust material; keep both secure. Development settings, generation and
operation journals, recovery inputs, temporary files, and backups remain
local.

The setup CLI holds `config/files/.lagniappe_setup.lock` and updates an
owner-only, secret-free operation journal. An interrupt reports the last
completed step, completed resource mutations/identifiers, and the exact safe
resume command. Concurrent setup processes fail before provider work.

Redis TLS uses `REDIS_TLS` plus the conditional `REDIS_CA_CERT` setting. The
managed CA bundle lives at `config/files/redis_ca.pem`; setup stores that
project-relative path so it resolves both locally and after App Engine upload.
The CA bundle is public trust material, not a client private key. It remains in
the ignored config directory across upgrades even when TLS is later disabled.
The owner download also embeds the PEM in `REDIS_CA_PEM` when TLS is enabled.
Recovery validates that PEM in a temporary file and atomically recreates the
managed CA path before testing the recovered Redis endpoint.

### GCP Setup (`installer/gcloud.py`)

Handles Google Cloud project creation and API enablement. Creates the App Engine
application in the specified region and manages the `lagniappe.yaml`
configuration file for deployment.

App Engine and the other regional services deliberately use separate settings.
`APP_ENGINE_LOCATION` uses App Engine spellings such as `us-central`, while
`RESOURCE_REGION` uses regional-service spellings such as `us-central1`.
Both settings are required. For a new App Engine application, setup displays
the selected permanent location and requires a default-no confirmation
immediately before creation. For an existing application, setup reads
`locationId` and `defaultHostname` from the provider and persists them; rerun
and recovery never submit a location change or synthesize an `appspot.com`
hostname. Recovery stops on a saved/provider location or hostname mismatch.

The built-in workflow keeps three identities explicit:

| Identity | Setup source | Authority |
| --- | --- | --- |
| Installer/provisioner | Active `GCLOUD_CONFIG.ACCOUNT`, recorded as `INSTALLER_EMAIL` | Select/create the project, verify billing, enable APIs, provision resources, and reconcile IAM |
| Deployer/operator | Active `GCLOUD_CONFIG.ACCOUNT`, recorded as `DEPLOYER_EMAIL` | Deploy indexes/App Engine, run terminal backup/restore operations, and `actAs` only the attached runtime account |
| Runtime service account | `RUNTIME_SERVICE_ACCOUNT_EMAIL` | Application data and consumer APIs, ADC, and remote signed-URL signing |

The installer and deployer are the same authenticated principal in the
built-in deployment flow, but they remain separate from the application owner
and runtime service account. Setup tests the active principal's required
project-scoped installer and deployer permissions with the Resource Manager
`testIamPermissions` API. Bucket metadata and bucket IAM permissions are not
valid project-resource checks; setup tests the active installer's permissions
through each managed bucket's Cloud Storage `testIamPermissions` endpoint after
the bucket exists and before reconciling it. Runtime object permissions are not
part of that human preflight: during reconciliation, setup grants
`roles/storage.objectAdmin` to the recorded human operator on all managed
buckets and separately grants the runtime service account its bucket-scoped
roles on the four application buckets. For an existing project, the
project-scoped check happens after ADC alignment and before any local draft or
cloud mutation. A new project must first be created before project permissions
can be tested; setup then performs the project-scoped check before billing, API
enablement, or resource provisioning. Missing permissions are reported by
installer/deployer boundary and resource. Setup does not grant project-wide
human roles to repair them; its human Storage grant is confined to Lagniappe's
managed buckets. When billing must be linked, preflight also calls the Cloud
Billing `testIamPermissions` endpoint for
`billing.resourceAssociations.create` on a billing account selected from the
CLI listing and checks `resourcemanager.projects.createBillingAssignment` on
the project. For a new project, setup repeats CLI billing-account discovery
after creating the project and enabling the bootstrap management APIs. A sole
open account is selected and linked automatically. When CLI discovery still
returns no open account, setup instead uses Google Cloud's project-specific
billing page and directs the operator to link an existing account, then
verifies the resulting project billing state and records the linked account ID.

Setup never grants deployment roles to the runtime account. A deployer needs
the existing equivalent of `roles/appengine.deployer`,
`roles/cloudbuild.builds.editor`, `roles/datastore.indexAdmin`, and
`roles/storage.objectAdmin`; setup checks the concrete permissions used by
deploy/index commands on project resources instead of changing those
project-wide human grants. The setup-managed bucket grant covers Lagniappe
backup/restore operations; storage-object access for deployment also applies to
provider-managed staging buckets and is exercised by the deployment itself.
Setup reconciles `roles/iam.serviceAccountUser` and
`roles/iam.serviceAccountTokenCreator` only on the exact attached runtime
service account for:

- the human deployer, so App Engine can attach the account; and
- the runtime service account itself, because Cloud Tasks uses that same
  account as its OIDC subject and Storage signed URLs use IAM `signBlob`.

Token Creator is the available predefined role containing
`iam.serviceAccounts.signBlob`; exact-resource binding prevents it from
becoming a project-wide impersonation grant. Setup enables the Service Account
Credentials API and doctor/recovery verify both the API and these signing
members.

The runtime project role set is:

- `roles/datastore.user`;
- `roles/firebaseauth.editor`, the narrower named role containing the Identity
  Platform account lookup/delete and OOB email-code permissions;
- `roles/cloudtasks.enqueuer` plus `roles/cloudtasks.taskDeleter`;
- `roles/documentai.apiUser`; and
- `roles/aiplatform.user`.

`roles/serviceusage.serviceUsageConsumer` is intentionally absent until the
opt-in live runtime contract demonstrates that it is required. Runtime
credentials never receive App Engine deployer, Cloud Build editor, Service
Usage Admin, project IAM, key administration, Cloud Tasks Admin, or
project-wide Storage roles. Upgrade/repair also removes the retired messaging
roles listed in `REMOVED_RUNTIME_PROJECT_ROLES`.

`configure_storage_buckets()` runs with installer ADC. Ordinary install,
repair, and update modes create or reconcile the four deterministically named
production buckets plus the recovery bucket. Only `development` requests the
four test-prefixed counterparts. New buckets explicitly use the `US` location
and `STANDARD` default storage class;
existing bucket locations are retained, while default storage-class drift is
reconciled to `STANDARD`. Setup preserves any operator-managed retention,
soft-delete, and lifecycle policies. It enables uniform bucket-level access,
reconciles CORS, grants the recorded human installer/deployer
`roles/storage.objectAdmin` on every managed bucket, grants the runtime account
`roles/storage.objectAdmin` plus bucket-metadata read through
`roles/storage.legacyBucketReader` on those buckets only, and grants
`allUsers` object viewing only on each managed public bucket. Runtime startup
reads those application-managed buckets and fails with a setup repair
instruction if one is absent; it does not create buckets, patch metadata, edit
bucket IAM, or delete buckets. Test cleanup deletes objects while preserving
the setup-owned buckets.

All managed IAM writes request policy version 3 and submit the same policy
object with its provider etag. Reconciliation consolidates duplicate
unconditional bindings for the Lagniappe member, preserves unrelated members
and every conditional binding, and skips writes when the desired state already
exists. An unexpected conditional broad-role grant on the runtime account is
reported for manual resolution rather than silently modified.

`create_deferred_job_reconciler()` enables the Cloud Scheduler API and
idempotently creates or updates `lagniappe-deferred-jobs-reconciler` in the app
region. Every five minutes it sends the exact JSON body
`{"reconcile": true}` to `/process/jobs/reconcile`, using the deployed runtime
service account as the OIDC identity and the exact route URL as the audience.
The route verifies the token through the same internal-task authentication
boundary used by Cloud Tasks. Enabling Cloud Scheduler provisions its managed
service agent, so setup does not invoke the optional `gcloud beta` component;
it verifies the managed agent's project role before creating the job.

The identities deliberately have different responsibilities:

- Google's managed Cloud Scheduler service agent,
  `service-PROJECT_NUMBER@gcp-sa-cloudscheduler.iam.gserviceaccount.com`, is
  ensured `roles/cloudscheduler.serviceAgent` on the project.
- The runtime application service account from
  `RUNTIME_SERVICE_ACCOUNT_EMAIL`
  is only attached as the Scheduler job's OIDC caller. It is not granted
  Scheduler Admin and the running application never calls the Scheduler API.
- `INTERNAL_CALLER_SERVICE_ACCOUNT_EMAIL` records that exact expected caller.
  Task creation, Scheduler configuration, and server-side token verification
  all read the same setting; recovery requires it to match the attached
  runtime account for this release.
- The deployer and runtime OIDC subject retain their exact-resource
  `roles/iam.serviceAccountUser` and
  `roles/iam.serviceAccountTokenCreator` bindings on that runtime service
  account.
  The operator running setup must already be authorized to enable the API,
  create/update Scheduler jobs, and change those IAM bindings.

When setup owns the deployment, fresh install and `update` invoke
this provisioning step automatically after a successful application deploy.
The focused `jobs` command exists for manual deployments and idempotent repair;
it is not an additional mandatory step after a setup-managed deployment. It
runs the normal installation verification first, including activation of the
gcloud configuration declared by this checkout. A provisioning failure during
`update` does not roll back the application because the version
has already deployed. Setup prints the repair command, reports the deployment
as complete, and returns a nonzero command status so automation does not miss
the unavailable Scheduler repair. The focused `jobs` command remains strict.

Internal task endpoints return `401` for missing or invalid OIDC and `400` for
authenticated but malformed payloads. They do not acknowledge either case
with `204`/`200`. A `5xx` response is reserved for a processing or
infrastructure failure that the queue or Scheduler may retry; deliberately
terminal application outcomes are recorded and acknowledged normally.

For an existing installation whose deployment is managed manually, use this
rollout order:

1. Commit and push the application/index/setup changes to the release branch.
2. Deploy that application version and the generated indexes.
3. From the deployed checkout and its selected gcloud configuration, run
   `./setup.sh jobs`.

The focused `jobs` mode does not fetch or reset code. A separately deployed
test/staging instance needs
its own `jobs` run against that instance's project, URL, region, runtime
service account, and gcloud account. Local unit, JavaScript, tooling, and E2E
tests do not call Cloud Scheduler or mutate IAM; they mock the provisioning
commands or call the reconciliation logic directly.

### Identity Platform

`installer/identity.py` initializes standalone Identity Platform:

- Calls `projects.identityPlatform.initializeAuth` and requires the resulting
  subtype to be standalone `IDENTITY_PLATFORM`; any other existing
  authentication subtype is a provider conflict
- Accepts the provider's already-initialized response, and gives a fresh
  project's API activation a bounded retry window with visible progress
- Enables email/password sign-in, preserves existing authorized domains, and
  adds the App Engine or custom-domain host
- Stores a public auth client config containing only project ID and Web API
  key
- Sends the confirmed ADC target as `x-goog-user-project` so API quota is
  charged to the selected project
- Reports failed REST calls as a compact HTTP status, Google status/reason,
  and provider message instead of printing the request URL and complete
  structured response

The generic authenticated Google REST helpers live in
`installer/google_provider.py`. Setup re-reads Identity Platform after
reconciliation and fails closed unless the subtype is `IDENTITY_PLATFORM`,
email/password remains enabled, and the authorized domain remains intact.

#### Retiring resources from older installations

Schema-2 recovery upgrades to schema 3 and discards `FIREBASE_CONFIG`.
Upgrade/repair removes the runtime Cloud Messaging IAM role. It deliberately
does not delete cloud APIs, Web Apps, or project resources because that is an
operator-owned destructive action and an older deployed version may still use
them.

After the schema-3 release is deployed and rollback to an FCM-dependent version
is no longer required, the operator may remove the obsolete Firebase Web App,
Web Push certificate, and Messaging API/resource configuration in Google
Cloud/Firebase Console. Keep Identity Platform itself: authentication still
uses it, and Google names its Identity Platform permissions and token verifier
with `firebaseauth`/`verify_firebase_token` identifiers.

`installer/auth_email.py` runs immediately before Identity Platform setup. If the
installation does not already have a custom domain, it first asks whether the
operator wants to configure one. The custom-domain branch performs the normal
App Engine mapping and DNS flow, defers OAuth registration until the later
admin step, and then runs the provider-neutral SMTP test. The zero-domain
branch:

- accepts any Gmail or Google Workspace mailbox that can create a Google App
  Password; the mailbox does not need project IAM or application-owner access;
- opens a Google account picker for App Passwords and explains the 2-Step
  Verification requirement, Google's app-password warning, and the limited
  purpose of sending verification and password-reset messages from the chosen
  mailbox on its owner's behalf;
- tells the operator to enter `Lagniappe` in Google's App name box, click
  **Create**, and copy the displayed password, and explains that the sender
  name is what message recipients see;
- waits for the operator to confirm that they are ready before opening the
  Google App Passwords page;
- accepts the visibly pasted 16-character app password, uses
  `smtp.gmail.com:587` with STARTTLS, and sends a test message to the same
  mailbox; interrupted connections and other transient transport failures are
  retried once and reported separately from explicit SMTP rejections, while
  certificate validation uses both the local trust store and the setup-pinned
  `certifi` CA bundle and never falls back to unverified TLS;
- saves `AUTH_EMAIL_CONFIG` only after the test succeeds.

The Gmail path deliberately bootstraps an operator who does not yet have an
application domain. Both the fresh custom-domain branch and the later
`./setup.sh email` command offer Resend first. When the saved application-domain
configuration identifies Cloudflare, setup opens Resend's Domain Connect path;
Resend owns that short-lived Cloudflare authorization and publishes its
email-specific DNS records. Setup then opens Resend's API-key page and supplies
the documented fixed SMTP values (`smtp.resend.com`, implicit TLS port `465`,
username `resend`). The operator copies the exact verified sending domain
shown by Resend; setup derives `noreply@SENDING_DOMAIN`, requires the sender to
match that domain, and then asks for the Sending access API key and test
recipient. The application domain and Resend sending domain may differ (for
example, `example.com` and `mail.example.com`).

For another provider, setup collects the provider name, host, port, STARTTLS or
implicit SSL/TLS mode, username, password or API key, sender address, sender
name, and a test recipient. The operator verifies the sending domain and
publishes the provider's SPF and DKIM records first. New settings are saved only
after the test message succeeds; a failed test leaves the previous sender
unchanged. The later command requires `CUSTOM_DOMAIN` and can deploy the saved
settings immediately. The temporary Cloudflare API token used by the App Engine
domain flow is never persisted, and Cloudflare never receives or exposes the
email-service credential.

At runtime, Lagniappe uses authenticated ADC and
`accounts:sendOobCode` with `returnOobLink: true` to obtain an OOB code without
asking Google to send an email. The code is embedded in the existing
`/users/login` verification or password-reset URL on the configured Google
login origin (including a custom domain), and the configured SMTP service sends
that URL. The browser never receives the runtime Google access token or SMTP
password/API key.

Recovery checks live standalone Identity Platform state. Missing, forbidden,
mismatched, and unavailable states remain distinct and cannot silently replace
the canonical snapshot.

### Admin (`installer/admin.py`)

Creates the initial admin user configuration. Before this stage, setup has
already initialized standalone Identity Platform;
Google Auth Platform does not expose a separate public Service Usage toggle for
general Google Sign-In client registration. Admin setup opens the target
project's Google Auth Platform Clients page. When Google shows **Google Auth
Platform not configured yet**, the operator clicks **Get started**, completes
the app information, external audience, and contact information, then creates a
Web application client with the displayed App Engine JavaScript origin and
redirect URI. Google prohibits programmatic creation or modification of these
general OAuth clients, so setup asks for the resulting client ID and secret,
registers them as Identity Platform's Google provider, and persists only the
public client ID. On later setup runs, a matching enabled Google provider is
reused without asking for its secret. If the saved client no longer matches
the provider, setup asks for that client's secret and reconciles the provider;
the secret is sent to Google and is never saved locally.

Setup also maintains optional agent-access settings in
`config/files/lagniappe_settings.yaml`: `AGENT_ACCESS_ENABLED`,
`AGENT_ACCESS_EMAIL`, `AGENT_ACCESS_NAME`, and `AGENT_ACCESS_CODE`. New or
refreshed installs get the option disabled by default; non-empty local edits are
preserved, and missing email/name/code values are filled when setup refreshes
the config. Agent login uses the configured email as a normal user account so
browser-review permissions can be managed by reassigning that user's groups from
the normal user settings UI.

### AI (`installer/ai.py`)

Configures Google Vertex AI models for text generation (form schema generation, document assistance) and image generation (site images, page images). Sets model names and location in app settings.
The ordinary setup flow also offers the separate, default-off owner-only AI
generation observability setting and preserves the existing choice on reruns.

### Redis (`installer/redis.py`)

Configures Redis Cloud as the caching layer. On a fresh installation it opens
the Redis Cloud console and explains how to sign in or create an account, create
or select a database, keep its public endpoint and default user enabled, and
copy the public endpoint and default-user password from the current Essentials
or Pro configuration screens. It then prompts for those values, provides
instructions for setting the `volatile-ttl` eviction policy, and offers
server-verified TLS. Redis Cloud exposes database TLS on paid Essentials/Flex
and Pro plans, not Free Essentials plans. A failed fresh-install connection
clears the entered endpoint, port, and password without retaining them, then
defaults to prompting for all three again inside the same setup run.

The TLS flow instructs the operator to enable TLS in Redis Cloud, leave Mutual
TLS unchecked, download and unzip the certificate archive, and place the
extracted `redis_ca.pem` at `config/files/redis_ca.pem`. Setup validates that
managed file and opens a verified TLS connection before saving settings. Failed
validation or connection tests leave the prior settings unchanged. Runtime and
setup use the same Redis client option builder, including required certificate
and hostname verification. The interactive explanation compares this to HTTPS
for the server-to-server connection and makes clear that TLS wraps, rather than
replaces, Redis password authentication. If the connection check offers to
install `redis`, it means the Python client library only, not a local Redis
server; using the same client as the application verifies its actual TLS,
authentication, and Redis protocol path.

Run `./setup.sh security` to enable or refresh TLS on an existing
installation or to disable it after first disabling TLS in Redis Cloud. The
standalone flow tests the new transport mode before saving and offers immediate
deployment. Delaying that deployment can make newly opened app connections
fail because Redis Cloud applies TLS changes to new connections. The unused CA
bundle is retained when TLS is disabled for an easy rollback.

Mutual TLS client keys, CIDR allow-list automation, and Private Service Connect
remain outside this setup flow.

### Security (`installer/security.py`)

Owns the standalone `security` status/action menu and deployment prompt. Redis
provider instructions, certificate installation, settings mutation, and
connection tests remain in `installer/redis.py` so fresh and standalone setup share
one implementation.

### Image (`installer/image.py`)

Handles site branding images (favicon, PWA icons, OpenGraph image). Can generate defaults or accept custom uploads. Saves images to the static directory and updates the site image version in settings.

### Optional (`installer/optional.py`)

Optional post-install configuration:

- **Error monitoring**: Default-off Sentry integration that asks whether to
  enable monitoring instead of treating the generated disabled default as a
  prior operator choice. Enabling continues to a detailed consent prompt. The
  reporter sends bounded structural request metadata, removes raw
  form/JSON/query values, filenames, full URLs, identity context, and
  non-allowlisted headers, and recursively redacts recognized credentials.
  Error messages and stack traces remain diagnostic text, so the prompt
  explicitly describes the remaining limits rather than claiming anonymity.
  An opted-in normal installation can use the maintainer project or supply its
  own DSN. `./setup.sh development` rejects the maintainer DSN and requires an
  operator-owned DSN or disabled monitoring.
- **AI model change**: Switch between available Vertex AI models and explicitly
  choose whether the default-off `AI_OBSERVABILITY` summaries are enabled

### Development (`installer/development.py`)

Owns the additive `development` workflow described above. It deliberately
checks for a completed ordinary installation before importing installation
configuration, verifies the saved Google Cloud context, creates only the
test-prefixed bucket family, then validates the local toolchain, enforces the
development Sentry destination rule, installs dependencies, and creates the
development frontend bundle.

### Update and Upgrade (`installer/upgrade.py`)

`update` applies app-saved settings without replacing source code. `upgrade`
first replaces tracked source and then runs that same current-version
application flow:

1. Verifies the current installation is valid
2. For `upgrade`, warns that tracked local changes will be discarded, records
   their status and diffs under `reports/upgrade-local-changes-*.md`, fetches
   remotes, and resets to `origin/main` or the `origin/BRANCH` selected with
   `--branch`; `update` skips this source-replacement step
3. Reconciles setup dependencies against the replaced checkout
4. Reloads config/create-config modules from the code now on disk
5. Rebuilds generated config, indexes, and manifest defaults without removing
   existing app data or configured settings
6. Verifies required app settings and reports any missing values as a
   non-destructive follow-up
7. Reconciles the runtime service account, exact-resource IAM, and
   setup-managed Storage buckets
8. Restores custom site images if they exist
9. Restores saved deployment settings if available
10. Restores saved AI model settings if available
11. Optionally deploys immediately

The upgrade confirmation names its exact reset target. Its hard reset replaces
tracked files but does not remove the ignored installation configuration or
untracked files. Operators maintaining a fork should merge releases themselves
and use `update`; `upgrade` is the replacement workflow for ordinary
installations that follow a remote Lagniappe branch.

When release notes require a stored-data migration, complete the deployment,
then use **Admin → Site Settings → Maintenance → Apply Updates** followed by
**Refresh Cache**. Setup does not run application data migrations
automatically. See [DATA_MIGRATIONS.md](DATA_MIGRATIONS.md) for the authoring,
failure-recovery, and durable upgrade procedure. Pending migrations accumulate
in version order for installations that skip releases; completed entries remain
complete across later builds. Startup baselines bundled migrations only when it
has just seeded a truly empty database.

### Runtime Storage Configuration

Cloud Storage bucket provisioning and metadata are owned by
`installer.gcloud.configure_storage_buckets`, using the shared naming and CORS
contract in `config.storage`. Setup and update create or get the private,
public, history, export, and operator-only recovery buckets and enable uniform
bucket-level access. The four runtime buckets receive the browser CORS policy
and bucket-scoped runtime IAM; the recovery bucket receives neither. Runtime
`DataServices` only gets the four expected runtime buckets and fails with an
actionable setup-repair message when one is absent.

### Verification (`installer/verify.py`)

`validate_installation()` performs read-only local generation, deploy-surface,
and gcloud availability checks. `prepare_existing_installation()` is the
explicit activation-plus-validation composition used by focused mutating
commands. `repair_installation()` is the explicit full-reconciliation command;
it reruns the installer, then validates only after successful reconciliation.

`installer/doctor.py` is the broader read-only operator diagnostic. It does not
import the mutable configuration singleton until a complete local file set is
available and does not acquire the operation journal. The `installer` CLI
boundary has already activated the checkout's complete saved gcloud target
before dispatching it; the doctor handler itself never retargets gcloud.

### Utilities (`installer/utils.py`)

Shared helpers:

- `ensure_datastore_dependency()` / `ensure_storage_dependency()` -- shared
  Google client dependency guards for image and deployment restore flows
- `validate_input(prompt, ...)` -- decorator factory for validated user input with retry loop
- `run_gcloud_command(command)` -- subprocess wrapper for gcloud CLI
- `deploy_to_app_engine()` -- delegates to `runner.deploy.deploy()` in publish-only
  mode, deploying indexes and app without rebuilding JS or incrementing version
- `print_summary()` -- displays the allowlisted secret-safe final summary

### Package Install (`installer/package_install.py`)

Bootstrapping utilities that work before any dependencies are installed:

- `ensure_pip_is_available()` -- checks for pip, attempts `ensurepip` if missing
- `ensure_setup_dependencies()` -- validates installed versions, installs all
  missing/mismatched exact pins together, revalidates, and runs `pip check`
- `install_if_missing(module)` -- exact-pin and import guard used by focused
  setup modes after the default transaction
- Setup spinners are tracked so missing-package prompts and pip output pause any
  active `yaspin` spinner before reading from stdin.
- Native Windows uses static progress lines instead of animated `yaspin`
  output. Captured gcloud subprocesses have stdin closed so an unexpected
  provider prompt cannot wait invisibly; the ADC quota-project command also
  runs noninteractively with a one-minute timeout. Project and billing IAM
  permission probes are bounded to 30 seconds each.

### Constants (`config/constants.py`)

Template values, default configurations, the PWA manifest template, and the Sentry DSN.

## Custom Domain (`installer/domain/`)

A sub-package handling App Engine custom-domain mapping plus either optional
Cloudflare DNS-only automation or provider-neutral manual DNS setup.

### Flow

1. **`installer/domain/instructions.py`** -- explains the process to the user
2. **`installer/domain/validation.py`** -- validates the hostname and scoped token
3. **`installer/domain/manual.py`** -- guides Search Console ownership verification
4. **`installer/domain/gcp.py`** -- discovers or creates the App Engine mapping and
   verifies its exact provider-returned `resourceRecords`
5. DNS setup (one of):
   - **`installer/domain/cloudflare.py`** -- uses a temporary zone-scoped API token
     to reconcile only those records with `proxied: false`
   - **`installer/domain/manual.py`** -- prints those same records for another DNS
     provider
6. **`installer/domain/oauth.py`** -- provides instructions for updating the Google
   OAuth redirect URI and JavaScript origin
7. **`installer/identity.py`** -- adds the custom host to Identity Platform
   authorized domains and moves the email action-handler callback to the custom
   `/users/login` URL

### Cloudflare Features

Cloudflare is an optional DNS convenience, not a traffic or security layer in
the supported installer. Setup uses bearer-token authentication, lists the
zones visible to the token, selects the longest matching suffix, and reconciles
the App Engine records by provider ID. It records prior non-secret DNS values
for interrupted-run repair. It never enables proxying or calls WAF, bot,
ruleset, cache, browser-check, or zone-security APIs. Operators may configure
those independently after installation.
