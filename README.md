# Lagniappe

Lagniappe is a private, self-hosted workspace for structured records,
collaborative documents, tasks, files, search, and permissions. Read about why
it exists and see examples in
[Why Lagniappe?](https://lagniappe.site/pages/public/74faecaf), or read the
fuller [manual](https://lagniappe.site/manual/).

Lagniappe runs in your own Google Cloud project rather than in a centralized
Lagniappe SaaS account. The normal install path is the guided setup script; npm,
Rollup, `requirements.txt`, and local dev-server commands are for people
developing or customizing the application code.

See the [release history](documentation/releases/) for version notes.

## Install

You do not need to build the frontend or install developer dependencies to set
up a normal Lagniappe instance. The setup script does the main work.

You will need:

- A Google Cloud account with billing enabled
- A Redis provider account
- Python 3.12 or newer, supplied by the current Google Cloud CLI installer or
  installed separately
- Git
- The [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)

Both Google Cloud and Redis are required. Lagniappe has no reduced,
provider-free, or local-only operating mode.

From the repository root:

```bash
git clone https://github.com/windmillionaire/lagniappe.git && cd lagniappe
gcloud auth login
gcloud auth application-default login
./setup.sh
```

On Windows, run `setup.cmd` in the Google Cloud CLI Shell or Command Prompt.
The platform launcher creates Lagniappe's isolated `venv` once, reusing Google
Cloud CLI's bundled Python when available, and then starts the guided setup
flow. It walks through configuration files, Google Cloud services, App Engine,
Identity Platform, Redis, optional AI settings, generated
site assets, and deployment.
Google clients use Application Default Credentials: setup runs as the
authenticated human installer, while App Engine uses its attached runtime
service account. Lagniappe does not require a downloaded service-account key.

For the user-facing install guide, see
[installation.html](https://lagniappe.site/manual/installation).
For the technical installer internals, see
[INFRA_SETUP.md](documentation/INFRA_SETUP.md).

To replace an existing ordinary installation with the latest `origin/main`,
refresh its generated settings, and optionally deploy it, run:

```bash
./setup.sh upgrade
```

The command confirms the exact reset target and warns before discarding tracked
local modifications. Forks should merge source changes themselves and use
`./setup.sh update` to apply the resulting checkout without replacing it.

## After Install

The app deploys to Google App Engine in your cloud project. Your records live
in Datastore, files live in Cloud Storage, auth is handled through Google
Identity Platform, and Redis supports search, filters, cache, and revisioned
collaborative-document state. Browser updates use adaptive polling.

The operator owns infrastructure monitoring, backups, restoration testing,
provider retention settings, and account security. Project support is
best-effort through the public repository; there is no hosted service or
guaranteed support channel. General questions may also be sent to
[support@lagniappe.site](mailto:support@lagniappe.site).

Optional reports sent to the maintainer are governed by the
[error-reporting privacy notice](ERROR_REPORTING_PRIVACY.md), also published at
[lagniappe.site/reporting_privacy](https://lagniappe.site/reporting_privacy).

Light personal or small-team usage is usually inexpensive, but there is no
fixed price. Cost depends on App Engine settings, Redis plan, storage, OCR, AI
usage, and provider pricing. Set Google Cloud budget alerts during setup.

## Developers

If you are changing the code, building frontend assets, running the app locally,
or opening a pull request, complete the ordinary guided installation first,
then run:

```bash
./setup.sh development
```

That additive step creates the test-prefixed Cloud Storage buckets and installs
the development/test dependencies, locked frontend packages, Playwright
Chromium, and a development frontend build. Start with
[CONTRIBUTING.md](CONTRIBUTING.md) for prerequisites, the Sentry rule for
development installations, and test commands.

For full local E2E/provider testing, use short-lived
runtime impersonation as documented in
[INFRA_SETUP.md](documentation/INFRA_SETUP.md#local-adc-for-development-and-tests);
switch ADC back to the human installer before running setup or repair.

The backend is Flask on Google Cloud Platform. Local development supports
Python 3.12 and newer; deployment currently targets the App Engine
`python314` runtime. The frontend is vanilla ES modules bundled with Rollup and
styled with Tailwind CSS v4. Architecture, conventions, and system docs are
indexed in [documentation/OVERVIEW.md](documentation/OVERVIEW.md).

Development and tests are supported on Linux, macOS, and WSL2. Native Windows
development is intentionally unsupported; use WSL2. Ordinary installation,
recovery, update, and deployment can run natively in Google Cloud CLI Shell or
Command Prompt, but that installer path remains experimental until its real
clean-machine recovery/deploy smoke is complete. PowerShell is not supported.

## Security

Report suspected vulnerabilities privately as described in
[SECURITY.md](SECURITY.md). Do not include vulnerability details in a public
issue.

## License

Copyright (C) 2026 Caleb Wright. See [COPYRIGHT](COPYRIGHT).

Lagniappe is licensed under the
[GNU Affero General Public License, version 3 or later](LICENSE).
Third-party software, font, and icon notices are collected in
[THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES/README.md).
