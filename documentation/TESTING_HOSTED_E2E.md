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

## Coordinated E2E workers

The opt-in EXP-026 harness uses the same coordinator locally and inside one
Cloud Run job. The original selection remains a quick pilot; `=all` selects
every complete E2E case (including live provider contracts), not the unit,
JavaScript or tooling suites:

```bash
venv/bin/python run.py test --experiments
# After creating an exact committed hosted candidate:
venv/bin/python run.py hosted-e2e execute --experiments
# The whole E2E suite, with the same three-worker coordinator:
venv/bin/python run.py test --experiments=all
venv/bin/python run.py hosted-e2e execute --experiments=all
# Six-worker trial, with a candidate sized for it:
venv/bin/python run.py test --experiments --experiments-workers=6
venv/bin/python run.py hosted-e2e create --experiments-workers=6
venv/bin/python run.py hosted-e2e execute --experiments=all
```

The bounded selection contains representative existing browser cases and five
coordination checks, with three pytest/browser processes by default against
one server URL. It covers forms, documents, mobile Pages, Tasks, Categories,
search, file previews, messaging and site settings, plus quota fallback,
task-history cleanup, and global Home ETag regression stories. Each sequential
story worker reuses its own Administrator through `get_admin`; each test still
gets an isolated browser context. The Administrator has explicit CREATE AI
entitlement as well as ordinary administrative permissions.

Local runs accept `--experiments-workers=1` through `=6`. Hosted creation records
the count and execution inherits it: 1–3 use one B2 instance with three Gunicorn
processes and a 2-CPU/4-GiB Cloud Run driver; 4–6 use one B8 instance with six
Gunicorn processes and a 4-CPU/8-GiB driver. The larger profile is a trial sizing,
not a measured throughput guarantee. The coordinator remains one Cloud Run job,
with multiple browser workers sharing the candidate URL. A worker override
cannot exceed the hosted candidate's declared capacity. Capacity changes require
a new candidate, and interrupted creation cannot resume with a different count.

Pytest first collects exact parameter cases and fixtures. An AST inventory
follows direct enum references, local and imported test helpers/constants and fixture functions.
Markers provide the first partition: `e2e_serial` reserves a quiet phase;
`e2e_group("owner")` (or another named group) keeps its cases together on one
ordinary worker without blocking unrelated groups. Groups are placed first,
then ungrouped cases fill the available capacity. Per-test resource claims
still apply, including conflicts crossing group boundaries.
Cases are balanced across the selected long-lived workers using the most
recent passing E2E durations in `testing/evidence/latest.json`; unmeasured cases
use the median duration (five seconds without history). Timings only guide
placement and never count as current evidence. Hosted creation exports only a
duration map from the committed evidence into the image, outside its source
tree; old result records remain excluded. Each worker reserves a test's
direct named resources through setup, call and teardown, releasing them before
the next test. Overlapping claims wait; independent tests can run together even
when an intermediate test references both resources. Claims are conservative
exclusive reservations, not inferred read/write permissions. This does not traverse the related entity graph:
Pages sharing a Form or Category can run together. Dynamic resource lookups still need review; use explicit enum members where
possible. Import discovery follows named helpers under `testing/`, not arbitrary
application calls or the related-entity graph.
`@pytest.mark.e2e_serial` puts stories requiring whole-site quietness into an
exclusive batch after the parallel workers finish. Owner access alone is not
exclusive. Public-user, user-index, provider and site-settings stories are part
of the concurrent trial; their directly named resources still reserve affected
records. New tests do not choose a worker or batch manually.
Environment-reset checks use `@pytest.mark.e2e_serial(phase="before")` and finish
before protocol checks or ordinary stories create fixtures. Workers publish
atomic progress counts; the coordinator prints those counts every 30 seconds.

A run-local locked registry shares enum keys between processes, making lazy
prerequisite creation idempotent. Its lock covers fixture creation only; the
scheduler controls test conflicts. Per-test reservations use OS file locks in
the private run directory shared by the local or Cloud Run workers. They acquire
all claims together, release partial acquisitions before waiting, check outer
authority while waiting, and fail after ten minutes instead of hanging forever.
Process exit releases locks; the coordinator still reaps browser descendants
before cleanup. `resource-events.jsonl` records wait, acquisition and release
times per worker so the trial can distinguish execution from conflict waiting.
Resources retain keys across tests and
forget cached Python entity snapshots after each test. A later `.entity` access
re-fetches from Datastore; browser-only uses of `.key` do not. No cached browser
cookies are shared between the Administrator accounts.

The five small coordination checks exercise overlapping independent workers,
serialized shared-Page mutations, an exclusive barrier, and continued work
after another worker's teardown. They run before the broader story batches.

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
old passing evidence cannot fill a missing worker. The pilot reports focused scope; the complete coordinated selection reports
`e2e` scope. Both use the ordinary artifact upload/import path and preserve
non-E2E evidence. Neither claims the all-suite release validation scope.

`--experiments` here selects the harness trial; it does not enable application
experiments mode or measurement diagnostics. Ordinary suite execution remains serial. Full coordinated runs automatically
collect exact parameter cases; no manual target list or 50-nodeid override is
needed. Shared-cache reset and assertions about unchanged global revision
snapshots run exclusively. Ordinary
all-access stories use `get_admin`; Owner/permission-specific stories keep
their exact identities. Tests retain collection order within each worker;
there is no cross-worker order guarantee or work stealing. This remains an opt-in trial while full-suite reliability is
validated. The browser runner and App Engine server have
separate CPU/memory budgets; increasing browser concurrency does not require
additional server URLs.

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
