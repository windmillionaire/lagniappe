# Hosted E2E Testing

Hosted testing runs the ordinary unit, JavaScript, tooling, and
pytest/Playwright E2E suites in one Cloud Run job close to the application's
GCP resources. It deploys an exact zero-traffic App Engine candidate and imports
normal traceability evidence without exposing application secrets to GitHub.

## Architecture

```text
trusted clean commit with production build
  -> hosted-e2e create
       run source-quality, traceability, and release gates
       export exact commit
       deploy zero-traffic App Engine e2e version
       build/update matching Cloud Run job
  -> local command or GitHub WIF invokes the job
       acquire shared Redis lease
       clean test-prefixed data
       run selected suites against exact version
       upload reports, JUnit, evidence, manifest-last
  -> validate and merge exact-source evidence
  -> hosted-e2e teardown removes runnable version/job
```

An inert App Engine anchor remains as the service traffic owner. Teardown keeps
the reusable Artifact Registry repository, Secret Manager mounts, WIF provider,
result bucket, service accounts, and anchor.

## Security boundary

GitHub receives no settings, Redis credential, service-account key, or test
login secret. A protected `hosted-e2e` environment uses Workload Identity
Federation restricted to the configured repository, workflow, and environment.
Its invoker can execute the exact Cloud Run job and read only the dedicated
seven-day result bucket.

The runner image excludes `config/files/`. Secret Manager mounts the settings
and optional Redis CA into the Cloud Run job. The App Engine version receives
settings through the trusted local deployment boundary.

Dynamic application/testing routes are gated. A run exchanges an ID token for
one Secure, HttpOnly, SameSite=Strict host cookie only after exact source,
version, runtime identity, and shared-lease validation. Static compiled assets
remain public like production assets. Internal `/process` routes retain their
Cloud Tasks/Scheduler OIDC checks.

Reserved E2E hostnames can soft-route after version deletion, so production
Flask rejects the reserved host pattern with a marker-bearing 404. Setup,
create, and teardown probe that guard before handling runnable versions.

## One-time setup

Complete installation, deploy current production, and run development setup.
Then:

```bash
venv/bin/python run.py hosted-e2e setup --github-repository OWNER/REPOSITORY
```

The idempotent command creates the dedicated application runtime, MCP-package
runtime, and invoker accounts, Artifact Registry repository, result bucket,
settings/CA Secret Manager mounts, WIF pool/provider, scoped IAM, and App Engine
anchor. The package runtime receives no application project roles, test-bucket
roles, or Secret Manager access: its only data permission is
`roles/storage.objectCreator` on the result bucket. The deployer may attach that
identity to the job, and the Cloud Run service agent may mint its runtime token.
Setup removes stale direct project, test-bucket, artifact-bucket, and secret
grants from that dedicated identity; conditional grants fail closed for operator
review instead of being guessed or retained. It reconciles the service-account
policy in the same way and reads every relevant policy back before recording
success. Repository-driven package-job create/update and execution repeat that
read-only exact IAM assertion. The release workflow's narrower WIF identity
verifies the configured package-job service-account name before its direct
execution; it cannot read project-wide IAM policies. `hosted-e2e status
--environment mcp-package` reports
`identity_valid` and any `identity_error` so drift is visible before execution.
Non-secret identifiers are written to `reports/hosted-e2e/setup.json`.

The setup record includes a fingerprint of the stable API, IAM-role, bucket,
and anchor requirements. `create` refuses a stale record and tells the operator
to rerun the idempotent setup command, so a reused runtime service account
cannot silently miss roles added after its original setup.

Create a protected GitHub environment named `hosted-e2e` and copy these values
from setup output:

| Variable | Value |
| --- | --- |
| `GCP_PROJECT_ID` | `project` |
| `GCP_RESOURCE_REGION` | `region` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `provider_resource` |
| `GCP_E2E_INVOKER_SERVICE_ACCOUNT` | `invoker_email` |

They are resource identifiers, not secrets. Environment review is appropriate
because execution consumes provider resources and mutates test-prefixed data.

## Create and execute

Freeze and commit the complete candidate first:

```bash
npm ci
npm run build
# Commit source and generated release output.
venv/bin/python run.py hosted-e2e create --base origin/main
```

`create` requires a clean committed production build. It exports that exact
commit for both artifacts, never rebuilds, never edits canonical
`lagniappe.yaml`, and deploys with `--no-promote`. Before gcloud activation or
provider mutation, it runs npm source checks, Ruff, tooling tests, full
structural traceability, and the release check against the clean local HEAD.
Creation does not require current local test evidence; the hosted job produces
that evidence when it runs the candidate's suites.

`--base` selects the comparison point and defaults to `origin/main`, then `main`.
Interrupted create state is recorded under `reports/hosted-e2e/state.json`;
rerunning from the same commit resumes completed phases. A different commit
requires teardown first.

Run all complete suites:

```bash
venv/bin/python run.py hosted-e2e execute
```

The default `all` scope includes unit, JavaScript, tooling, E2E, setup drift,
and live provider contracts while excluding `unfinished`. `--suite full` runs
E2E only. Trusted local diagnosis can pass one or more real paths/nodeids under
`testing/tests_e2e/` with repeated `--target`; the container validates the
bounded target again. GitHub exposes only fixed `all` and `full` scopes.

The job acquires the shared lease, removes stranded test-prefixed state, seeds
the same persistence prerequisites as local startup, and runs one pytest
session. Direct fixtures execute from Cloud Run; browser requests target the
exact App Engine version. The runner image includes Git and POSIX process
inspection tools because repository and test-session contracts run in that
same container. Local execution follows status and imports results by default.

## MCP packaging environment

The clean-home packaging test has a separate, closed lifecycle and identity:

```bash
venv/bin/python run.py hosted-e2e create --environment mcp-package
venv/bin/python run.py hosted-e2e status --environment mcp-package
venv/bin/python run.py hosted-e2e execute --environment mcp-package \
  --target testing/tests_e2e/013_agent_api/test_013c_mcp_package_install.py
venv/bin/python run.py hosted-e2e teardown --environment mcp-package
```

Its dedicated Dockerfile and Cloud Build configuration pin the Python base,
uv, pipx, and Codex artifacts and checksums. Its explicit build-context ignore
file re-includes the standalone `/clients/lagniappe_mcp/` source and lock even
though the root App Engine `.gcloudignore` excludes `/clients/`; local package
environments and caches remain excluded. The ordinary hosted image separately
prebuilds the same exact locked, noneditable adapter environment but does not
carry uv or pipx into its final stage.

The standard lifecycle remains `lagniappe-e2e`,
`reports/hosted-e2e/state.json`, the `runner` image repository, and
`reports/hosted-e2e/results/`. The package lifecycle uses
`lagniappe-mcp-package`, `reports/hosted-e2e/mcp-package-state.json`, the
`mcp-package-runner` image repository, and
`reports/hosted-e2e/mcp-package-results/`. Execution names inherit those
different job prefixes. Status, result lookup, and teardown validate the
selected identity before reading or deleting anything; there is no environment
alias or fallback.

Only the public candidate URL, build marker, and advertised wheel metadata enter
the packaging job. The installed adapter and real pinned Codex client run from
fresh per-run homes outside the checkout. A loopback fake API supplies only a
synthetic key for configure/check/client lifecycle coverage; authenticated live
API behavior remains owned by `test_013b_agent_api_mcp.py`.

That clean-home check launches the installed adapter five times through the
official SDK and requires each complete cold `tools/list` catalog within 1.0
second. This deterministic local/process gate protects Codex's unchanged
optional-server grace; the deployed-network and exact target-client timing is
recorded separately before the paired trial.

The release workflow can execute this one exact target only after the existing
source-quality and traceability job succeeds. It checks the candidate commit,
application build marker, public manifest, release ledger, wheel, dependency
graph, package lock, packaging-image contract, immutable image digest, tool
versions, and Linux x86_64/CPython 3.14 platform again before accepting the
result manifest. Package-job output is an attestation gate, not replacement
test evidence: it is never merged or committed. Manual hosted runs are
diagnostic and likewise never merge, commit, or publish test evidence or the
required release status.

## Status and teardown

```bash
venv/bin/python run.py hosted-e2e status
venv/bin/python run.py hosted-e2e teardown
```

The Redis lease serializes local and hosted sessions outside the test cleanup
prefix. Teardown refuses an active execution unless `--force` is explicit,
acquires the data lease before cleanup, deletes only the Cloud Run job and
ephemeral App Engine version, and removes only that version's test-bucket CORS
origin.

Do not run local E2E, hosted E2E, test-server, or browser review concurrently.

## GitHub release path

`.github/workflows/hosted-e2e.yml` accepts trusted manual dispatch and release
pull-request candidates. It resolves the exact pull-request head commit,
then enters the protected environment, verifies that the already-preflighted
Cloud Run job was created from that source, invokes through WIF, and waits for
the result bucket's last-uploaded `manifest.json` completion marker.

The workflow validates and merges evidence, confirms that no tracked file other
than `testing/evidence/latest.json` changed, and non-force pushes an
evidence-only child if the branch head is unchanged. It then dispatches a
current-head continuation that verifies the parent source/snapshot and runs
source lint and release-tree checks without rerunning suites. A scoped final job
publishes the required **Source quality and traceability** status on the exact
evidence head.

Only the execution job enters the protected environment and can mint the GCP
identity or write the branch. Resolver, continuation, and status jobs receive
smaller job-specific permissions. Manual/local results remain diagnostic and
cannot publish or replace the release-pull-request status.

## Artifacts and evidence

Every execution writes beneath
`gs://ARTIFACT_BUCKET/executions/EXECUTION/`:

- `evidence.json`;
- `junit.xml`;
- `reports.tar.gz`; and
- `manifest.json`, uploaded last with source, version, build, suite, times, and
  exit status.

Local downloads live under `reports/hosted-e2e/results/EXECUTION/`. Import
requires both commit and semantic source snapshot to match the checkout. A
different result can be downloaded for diagnosis but cannot merge into tracked
evidence. Failed results import their failures and bounded tracebacks as the
latest selected evidence.

Use manifest start/end timestamps plus its exact App Engine service/version to
query Cloud Logging after a failure. Logs can contain request paths, IPs, and
user agents; narrow and sanitize them before sharing.

## Failure recovery

1. Run `hosted-e2e status`.
2. Resume an interrupted create from the same clean commit.
3. If execution uploaded artifacts, use `hosted-e2e results --latest`.
4. Teardown before abandoning the lifecycle or moving to another commit.

Successful teardown removes downloaded execution bundles after provider and
test-data cleanup. Imported evidence and reusable setup metadata remain.
