# Infrastructure Local Runner

`run.py` and `runner/` provide repository-local orchestration for development,
tests, builds, deployment, hosted tests, versioning, and dependency upgrades.
They are excluded from App Engine uploads.

## Process and path boundary

`runner/context.py` resolves the repository root, project virtualenv, supported
platform commands, and exact external executables. Paths do not depend on the
caller's current directory. `runner/process.py` runs argument-list subprocesses
and provides the shared error/exit boundary.

## Gcloud and ADC

`runner/gcloud.py` activates the complete gcloud configuration saved in
`lagniappe_dev.yaml`. It verifies configuration name, account, and project as a
unit and exports the selected project for child pytest/Flask processes.

An unconfigured checkout may run offline tooling. A partial saved target fails
before collection or app startup instead of using ambient gcloud state.

`runner/adc.py` verifies that ADC belongs to the saved human source and project,
or already represents the runtime account. Development and test commands do not
modify credentials. Use the explicit flow when alignment is needed:

```bash
venv/bin/python run.py auth
```

Application initialization turns verified human ADC into a short-lived runtime
credential. Installer commands keep using the human operator identity for
provider provisioning.

## Main command families

| Command | Owner |
| --- | --- |
| `run.py test ...` | `runner/pytest_routing.py`, `runner/testing.py`, and pytest configuration. |
| `run.py test-server ...` | Managed Flask server and test-data lifecycle. |
| `run.py browser-review ...` | Browser evidence and curated report tools. |
| `run.py traceability ...` | Source/test/template/style evidence. |
| `run.py template-contracts ...` | Jinja/selector contracts. |
| `run.py hosted-e2e ...` | Hosted App Engine/Cloud Run lifecycle. |
| `run.py release-check ...` | Frozen release-tree validation. |
| `run.py version ...` | Coordinated package/settings/release-note version. |
| `run.py icons` | Material Symbols registry subset refresh. |
| `run.py upgrade` | Maintainer dependency upgrade. |
| deployment command | `runner/deploy.py`. |

Testing commands and server concurrency rules are in [TESTING.md](TESTING.md).
Hosted infrastructure is in [TESTING_HOSTED_E2E.md](TESTING_HOSTED_E2E.md).

`run.py test` resolves targets with pytest's configured built-in and installed
plugin parser while suppressing conftest loading during this preflight parse.
The resulting immutable target selection drives alias expansion, strict-load
policy, frontend preparation, ADC requirements, and the final pytest command.
Project CLI options that must participate in routing are registered by the
lightweight `runner.pytest_routing` plugin rather than suite conftests.

## Development server

`runner/development.py` activates the saved gcloud target, verifies ADC, and
starts Flask with `FLASK_ENV=development`. It never opens an authentication
browser. Google clients run as the runtime service account. The command is
intentionally long-lived with no fixed timeout. The runner starts Flask and its
debug reloader in an owned process group, forwards SIGINT/SIGTERM, and cleans up
that group if the foreground runner exits exceptionally.

## Test server

E2E startup checks the authored frontend inputs against
`reports/test-frontend-bundle.json` and runs `npm run dev` only when generated
development output is absent, incomplete, or stale. It performs this check
before pytest imports application configuration so the test and Flask
processes share one `BUILD_ID`.

The managed server records PID/log files under `reports/`, resets browser
artifact folders at start, and stops the server before cleaning test-prefixed
provider/cache state on teardown. E2E and managed browser sessions share one
server/data namespace and must run sequentially.

## Version and dependency commands

`run.py version set X.Y.Z` updates `package.json`, the lockfile's root version,
generated application settings, the matching release note, and the applicable
version in the error-reporting privacy notice. It does not change that notice's
effective date unless its substance changes.

`run.py upgrade` updates Node, npm, and the direct Python requirement sets,
validates with npm audit/pip check, and writes a detailed report. It does not
fetch or replace repository source; `./setup.sh upgrade` owns source replacement.

## Material Symbols

`run.py icons` is the explicit networked maintainer action for refreshing the
official Material Symbols subset from semantic IDs in `src/style/icons.yaml`.
Normal builds use the vendored WOFF2 and do not contact Google Fonts. Reusing an
existing semantic icon needs no refresh.

## Adding runner behavior

- Keep runtime-safe validation in `config/` when the deployed application also
  needs it.
- Keep local orchestration in `runner/` and provider installation in
  `installer/`.
- Resolve paths through `runner/context.py`.
- Pass subprocess arguments as lists and keep failure messages actionable.
- Add setup/config/repository-health coverage under `testing/tests_tooling/`.
