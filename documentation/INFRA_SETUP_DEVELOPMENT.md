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
installs and checks the repository's pinned `uv` executable, installs
development Python dependencies, runs `npm ci`, installs Playwright Chromium,
and builds the development frontend. It never creates duplicate production
resources or replaces application settings.

The managed `uv` bootstrap is independent of the application virtualenv's
packages. It downloads the fixed official archive declared in
`clients/lagniappe_mcp/uv-bootstrap.json`, accepts redirects only to declared
release hosts, verifies its exact size and SHA-256 before extraction, and
installs only the declared regular-file member after also verifying that
member's own SHA-256. Every later check verifies the installed executable's
exact bytes before executing it at
`venv/tools/uv/<version>/uv`. Re-running development setup keeps a verified
copy or atomically repairs an invalid copy. A missing, corrupt, or unsupported
artifact fails closed without selecting an ambient `uv`; rerun
`./setup.sh development` for repair.

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

The initial MCP package trial's managed development toolchain is pinned for
Linux x86_64 with GNU libc (including matching WSL2 environments) and for Intel
and Apple Silicon macOS. Each tuple has independently verified
archive-size/archive-digest/member-digest evidence. Other tuples fail closed
rather than downloading an unverified or ambient executable. This development
bootstrap support does not expand the first user-installable MCP release's
separate Linux x86_64 runtime support claim.

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
| `clients/lagniappe_mcp/uv-bootstrap.json` | Exact managed-uv archive/member digests and host policy. |
| `clients/lagniappe_mcp/uv.lock` | Standalone adapter build/test dependency environment. |

Installer modes validate exact direct Python pins before importing provider
clients, install all missing/mismatched pins in one transaction, recheck imports
and versions, and run `pip check`. A third-party installer import must either be
covered by that bootstrap transaction or be preceded in the same execution
scope by `install_if_missing` for an exactly pinned distribution. A tooling AST
contract enforces this boundary. Undeclared ad-hoc installs are rejected.

Python dependency upgrades resolve direct requirements together with eager
transitive updates, run `pip check`, and write direct pins only after validation.
The detailed before/after report is written under `reports/`.

`.nvmrc` records the recommended Node version; `package.json` defines the
accepted engine range. `npm ci` uses the committed lockfile.

Adapter dependencies never enter `requirements.txt`,
`requirements-dev.txt`, or the application virtualenv. Repository adapter
commands synchronize `clients/lagniappe_mcp/.venv` from its own lock through
the managed `uv` executable.

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
