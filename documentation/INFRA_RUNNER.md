# Infrastructure Local Runner

`run.py` and `runner/` provide repository-local orchestration for development,
tests, builds, deployment, hosted tests, versioning, and dependency upgrades.
They are excluded from App Engine uploads.

## Process and path boundary

`runner/context.py` resolves the repository root, project virtualenv, supported
platform commands, and exact external executables. Its `UV_CLI` is derived
only from the version in `clients/lagniappe_mcp/uv-bootstrap.json` and resolves
to `venv/tools/uv/<version>/uv`; it never consults `PATH`. Paths do not depend
on the caller's current directory. `runner/process.py` runs argument-list
subprocesses and provides the shared error/exit boundary.

`runner/uv_bootstrap.py` is a standard-library-only install/check boundary for
that executable. Developer and CI provisioning explicitly run:

```bash
venv/bin/python -m runner.uv_bootstrap install --non-interactive
venv/bin/python -m runner.uv_bootstrap check
```

Adapter-dependent commands do not download or repair this tool implicitly. A
missing, byte-mismatched, or wrong-version managed copy stops with the exact
`./setup.sh development` repair command.

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
| `run.py mcp ...` | Standalone adapter development shim in its locked environment. |
| `run.py mcp-artifact build|check` | Immutable adapter release and public deploy artifacts. |
| `run.py release-check ...` | Frozen release-tree validation. |
| `run.py version ...` | Coordinated package/settings/release-note version. |
| `run.py icons` | Material Symbols registry subset refresh. |
| `run.py upgrade` | Maintainer dependency upgrade. |
| deployment command | `runner/deploy.py`. |

## Standalone MCP package environment

`runner/mcp_environment.py` is the one-way bridge from repository tooling into
the standalone package. It verifies the manifest-selected managed `uv`, runs
the exact locked synchronization command

```bash
venv/tools/uv/<version>/uv sync --project clients/lagniappe_mcp --locked --group test \
  --python <current-project-python> --no-managed-python --no-python-downloads --no-config
```

and invokes only `clients/lagniappe_mcp/.venv/bin/python -I` for adapter code.
The bridge removes inherited `UV_*` configuration, pins the current project
interpreter explicitly, disables managed-Python downloads, and ignores ambient
uv configuration files. Local preparation checks that the environment shares
that interpreter's base prefix and that Python 3.14, the MCP SDK, pytest, `uv-build`, and
the editable adapter source resolve from that isolated environment. The hosted check instead
requires the adapter itself to be installed inside the prebuilt environment,
so copied images do not depend on an editable source path. Both hosted images
first install the locked test group without the project, then install the copied
first-party source offline with build isolation disabled. That second layer can
therefore use only the exact `uv-build` backend installed from `uv.lock`.
Adapter pytest runs use
the shared `testing/pytest.ini` with `--noconftest`, disabled plugin
autodiscovery, and only the explicit AnyIO plugin, keeping Lagniappe application
imports and the root virtualenv out of the package suite. The sync also sets
uv's no-build policy for third-party source distributions while still allowing
the first-party editable project build. A stale lock, failed sync, unexpected
interpreter, missing binary dependency, or ambient dependency resolution is a
hard failure with development-setup repair guidance.

The default and `unit` test selections split MCP coverage into that locked
environment: both `testing/tests_unit/test_033_mcp_adapter.py` and the
standalone `clients/lagniappe_mcp/tests/` transport suite run exactly once
there, while the root pytest process explicitly ignores them. Focused paths or
nodeids beneath either location take the same bridge. The runner validates and
merges the isolated outcomes into ordinary traceability evidence and combines
the two pytest exit statuses without treating an empty companion selection as
a failure.

`mcp` and `mcp-artifact` are explicit early dispatches: they run before gcloud
configuration and never import the adapter into the application virtualenv.
`mcp-artifact build` first synchronizes the exact locked test/build group
without installing the project, then invokes the locked `uv-build` backend
offline with build isolation disabled. It produces the wheel twice with a fixed source epoch,
requires identical bytes, prevents an existing version from being rebound to a
new digest, and promotes the wheel into the ordinary-Git release ledger. It
then creates the separate public deploy tree after the production frontend
build. `mcp-artifact check` independently verifies wheel metadata and RECORD,
the exact dependency-wheel graph, compatibility/source digests, supported
release set, byte and file ceilings, frontend-build freshness, and release
inputs that are tracked, clean, and already committed rather than merely
staged. The current wheel must exactly match every current package-source byte;
retained historical wheels instead keep their immutable ledger digest and
closed wheel structure, because an intentional new version necessarily changes
the current source tree. The OpenAPI compatibility digest hashes a canonical,
origin-neutral serialization of the frozen OpenAPI document, rather than the
Python source bytes that construct it, so comments and formatting do not alter
compatibility while any schema change does.

`release-check` validates MCP inputs from the exact prospective Git index. Once
the standalone package exists in a release candidate, a missing, stale,
corrupt, rebound, or untracked wheel/ledger input fails the release even when a
different working-tree copy would validate. Candidates from before the MCP
package was introduced remain valid without fabricating release inputs.

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

E2E startup validates `build.json` against all declared frontend sources and
every recorded generated artifact, then consults
`reports/test-frontend-bundle.json`. It preserves a coherent current production
build; missing, partial, corrupt, or stale output is replaced with
`npm run dev`, including an old production build after source changes. It
performs this check before pytest imports application configuration so the test
and Flask processes share one `BUILD_ID`.

Local E2E and the managed server acquire `reports/test-session.json` plus the
shared Redis data lease before frontend, artifact, or test-data mutation. The
record includes nonce-bound process start identities; Flask publishes the same
nonce and PID from testing-only health. The managed keeper and server log live
under `reports/`. Teardown signals only a fully verified recorded process group
before cleaning test-prefixed provider/cache state. `test-server --status` is
read-only and `--recover` is the fail-closed stale-owner path.

## Development deployment

`run.py deploy` is the developer shortcut for the current generated
configuration. It validates the production frontend against its declared
sources and complete artifact inventory, preserving a current bundle and
running `npm run build` only when that validation reports stale or incomplete
output. After that final frontend operation it assembles and validates the MCP
deploy tree from durable release inputs; publish-only mode validates the
already-built tree and never invokes the managed uv bootstrap. Installation and configuration changes should still use
`setup.sh update`; installer deployment consumes a validated prebuilt bundle
and does not require Node.js or npm.

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
