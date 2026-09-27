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
       run complete suites or individual nodeids against exact version
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
and optional Redis CA into separate directories under `/var/run/secrets/` in
the Cloud Run job. Image symlinks expose the fixed `config/files/` paths;
mounting both secrets directly there would make their directory volumes collide.
The App Engine version receives
settings through the trusted local deployment boundary.

Dynamic application/testing routes are gated. A run exchanges an ID token for
one Secure, HttpOnly, SameSite=Strict host cookie only after exact source,
version, runtime identity, and shared-lease validation. Static compiled assets
remain public like production assets. Internal `/process` routes retain their
Cloud Tasks/Scheduler OIDC checks.

Non-browser API clients need the same run cookie in addition to their ordinary
API bearer credential. The managed MCP boundary test forwards only this cookie
to its direct HTTP calls and isolated driver's test-only transport, bound to
the exact application origin. It is never forwarded to storage URLs or added
to the product adapter, whose requests remain bearer-only. Keep the cookie out
of test artifacts and diagnostics just like the API key.

Reserved E2E hostnames can soft-route after version deletion, so production
Flask rejects the reserved host pattern with a marker-bearing 404. Setup,
create, and teardown probe that guard before handling runnable versions.

## One-time setup

Complete installation, deploy current production, and run development setup.
Then:

```bash
venv/bin/python run.py hosted-e2e setup --github-repository OWNER/REPOSITORY
```

The idempotent command creates the dedicated application runtime and invoker
accounts, Artifact Registry repository, result bucket, settings/CA Secret Manager
mounts, WIF pool/provider, scoped IAM, and App Engine anchor. Non-secret
identifiers are written to `reports/hosted-e2e/setup.json`.

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

With no targets, execution includes unit, JavaScript, tooling, E2E, setup drift,
and live provider contracts while excluding `unfinished`. There is no suite
selector. GitHub always runs this complete selection.

For trusted local diagnosis, repeat `--target` to select individual test nodeids
from any of the four suites, including native JavaScript cases:

```bash
venv/bin/python run.py hosted-e2e execute \
  --target testing/tests_e2e/001_site/test_001a_environment.py::test_database_setup \
  --target testing/tests_js/test_008_service_worker.mjs::test_no_store_static_response_is_not_cached
```

Targets must name existing files under `testing/tests_unit/`, `testing/tests_js/`,
`testing/tests_tooling/`, or `testing/tests_e2e/`, followed by `::test_name` (or a
Python class and test method). Python parameter IDs may select one instance.
Files, directories, suite aliases, wildcards, duplicates, traversal, commas, and
control characters are rejected. At most 50 nodeids of 512 characters each are
accepted. Local dispatch and the container both validate file scope and nodeid
syntax; pytest collection validates that each selected case exists.

The job acquires the shared lease, removes stranded test-prefixed state, seeds
the same persistence prerequisites as local startup, and runs one pytest
session. Direct fixtures execute from Cloud Run; browser requests target the
exact App Engine version. The runner image includes Git and POSIX process
inspection tools because repository and test-session contracts run in that
same container. It also installs `libatomic1`, required by the Node runtime
copied into the Python-based image. Local execution follows status and imports
results by default.

## MCP coverage

Shared adapter tests run in the pinned internal package environment; remote HTTP,
OAuth, attachment and terminal-upload tests remain in the normal test selections.
`test_013b_agent_api_mcp.py` exercises the shared adapter against the live API
without starting a local stdio server. Remote HTTP protocol behavior is covered
by `testing/tests_unit/test_033c_mcp_server.py` and OAuth by `test_013d_remote_mcp_oauth.py`.

The public-wheel installation suite, packaging container, `mcp-package` runner
lifecycle and separate GitHub packaging job have been retired. The release gate
now depends on the ordinary quality/evidence job. Previously created packaging
jobs, service accounts and images are not automatically deleted by this source
change; retire those exact obsolete resources separately. The active remote MCP
service and ordinary hosted-E2E resources are independent of them.

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

## Coordinated worker pilot

The opt-in EXP-026 harness trial uses the same bounded coordinator locally and
inside one Cloud Run job:

```bash
venv/bin/python run.py test --experiments
# After creating an exact committed hosted candidate:
venv/bin/python run.py hosted-e2e execute --experiments
```

This selects five small browser cases, with at most two worker processes active
against one server URL. Each case creates its own Administrator account; none
pretends to be the singleton Owner. Independent cases use separate Pages and
Tasks. Two shared-Page cases use a declared conflict lane, followed by an
exclusive verification barrier. The second independent case continues after
the first worker's session teardown to verify that its data/server survive.

Only the coordinator acquires and renews the shared lease and performs global
setup/cleanup. Workers inherit an exact run/server binding through temporary
private context files, monitor coordinator/lease liveness, and never clean or
release shared state. In hosted runs the coordinator exchanges the single-use
Google bootstrap token once and supplies its run-scoped cookie to each private
worker context; ordinary browser user sessions remain distinct. The scheduler stops and reaps active worker process groups
before outer cleanup on cancellation, timeout or lost authority. This cannot
undo provider writes that were already in flight when authority was lost.

Worker logs, browser diagnostics, HTML reports and JUnit have separate paths
under `reports/e2e-pilot/ATTEMPT/`. The coordinator checks exact selected-nodeid,
attempt and source identity, merges JUnit, then records ordinary traceability
evidence once. Missing/crashed workers become explicit failed selected results;
old passing evidence cannot fill a missing worker. Hosted execution remains a
focused run and uses the ordinary artifact upload/import path.

`--experiments` here selects the harness trial; it does not enable application
experiments mode or measurement diagnostics. Ordinary suite execution remains
serial. This is an explicit case inventory, not a general `-n` option: additional
cases need a fixture/conflict audit. Owner-specific and global-settings tests
need exclusive scheduling; broad-access tests can use distinct Administrators.
The pilot launches one process per case; batching multiple audited tests per
process and broader suite scheduling remain later work.

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

A successful complete `all` run replaces the local test inventory, removing
retired node IDs and old parameter variants. Failed or partial runs merge into
existing evidence so unselected tests and earlier failures remain visible. Both
the execution manifest and its evidence must report success before a complete
import replaces prior results.

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
