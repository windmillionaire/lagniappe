# Infrastructure Development Setup

Developer setup builds on a complete installation because local app and browser
tests use the installation's GCP project, Identity Platform, Redis, and ignored
configuration.

```bash
./setup.sh
./setup.sh development
```

The second command is additive and safe to rerun. It verifies the saved cloud
target, creates the three test-prefixed Storage buckets, validates Node/npm,
installs development Python dependencies, runs `npm ci`, installs Playwright
Chromium, and builds the development frontend. It never creates duplicate
production resources or replaces application settings.

## Project virtualenv

`setup.sh` and `setup.cmd` locate a supported Python, create this checkout's
`venv`, and invoke it directly. They do not activate or reuse another virtual
environment. Every installer mode verifies that `sys.executable` belongs to
this checkout.

Use the virtualenv for repository Python commands:

```bash
venv/bin/python run.py test unit
venv/bin/python run.py traceability --changed --check
```

## Supported platforms

Ordinary install, recovery, update, and deploy support Linux/macOS terminals
and native Windows PowerShell. Development, test-server, and E2E workflows on
Windows use WSL2.

On native Windows, `setup.cmd` selects a standalone Python and rejects Google
Cloud CLI's bundled Python because its base packages can leak into child
virtualenvs. It may offer a per-user Python install through WinGet. POSIX setup
uses a suitable host Python and may use gcloud's interpreter only as a fallback.

Launchers run Python with `-E` so host `PYTHON*` variables do not modify the
environment. Paths and provider commands come from `runner/context.py` and are
passed as argument lists. Setup/config/report files use UTF-8 explicitly.

## Dependency ownership

| File | Contents |
| --- | --- |
| `requirements-installer.txt` | Bootstrap-only installer clients and console helpers. |
| `requirements.txt` | App Engine/runtime dependencies. |
| `requirements-dev.txt` | Runtime plus pytest, Playwright, Ruff, and local tooling. |
| `package-lock.json` | Exact frontend direct and transitive dependency tree. |

Installer modes validate exact direct Python pins before importing provider
clients, install all missing/mismatched pins in one transaction, recheck imports
and versions, and run `pip check`. Undeclared ad-hoc installs are rejected.

Python dependency upgrades resolve direct requirements together with eager
transitive updates, run `pip check`, and write direct pins only after validation.
The detailed before/after report is written under `reports/`.

`.nvmrc` records the recommended Node version; `package.json` defines the
accepted engine range. `npm ci` uses the committed lockfile.

## Local authentication

Development and testing use the deployed runtime IAM boundary. Run:

```bash
venv/bin/python run.py auth
```

The command aligns gcloud and human ADC with the saved account/project. Flask
then impersonates `RUNTIME_SERVICE_ACCOUNT_EMAIL` for every Google client.
Development/test startup verifies this state and never opens an authentication
browser itself.

## Error reporting

If the installation uses the maintainer Sentry project, development setup
requires the developer to disable it or supply their own DSN before installing
the local toolchain. This keeps development failures out of maintainer
telemetry.

## Source link

`SOURCE_URL` controls the Manual's Open Source card. Setup defaults it to the
canonical repository; an operator may use a fork/tag/commit URL or an empty
value to hide the link. Configuration refresh preserves the authored choice.
