# Hosted Tests

Hosted testing is an opt-in way to run the normal unit, JavaScript, tooling,
and pytest/Playwright E2E suites in one Cloud Run job without copying
application secrets into GitHub Actions. E2E work runs close to Datastore,
Cloud Storage, App Engine, and Redis and uses the same resources, direct
backend helpers, fixed `test-` data prefix, cleanup, and traceability-result
plugin as a local run.

The operator deploys one exact, zero-traffic App Engine version and a matching
Cloud Run job from a clean commit. A local command or the manual GitHub
workflow then invokes that same job. Teardown deletes the runnable version and
job; an inert, revisioned `e2e-anchor` version remains as the service's traffic
owner and returns the same rejection marker for soft-routed stale hostnames.

## Security Boundary

GitHub receives no settings file, Redis credential, service-account key, or
application bootstrap secret. The `hosted-e2e` GitHub environment uses Google
Workload Identity Federation to impersonate a dedicated invoker account. Its
provider condition is restricted to:

- the configured `OWNER/REPOSITORY`;
- `.github/workflows/hosted-e2e.yml`;
- the `hosted-e2e` GitHub environment; and
- view and execute-with-overrides permissions on the exact Cloud Run job; and
- object-viewer access on the dedicated seven-day result bucket.

The Cloud Run job runs as a separate E2E runtime service account. Secret
Manager mounts `lagniappe_settings.yaml` and, when configured, the managed
Redis CA certificate directly into that job from separate secrets. All of
`config/files/` is excluded from the image and result artifacts. The result
bucket uses uniform access with public access prevention. The App Engine
version receives the normal settings only through the trusted local App Engine
deploy, the same boundary used by a production deploy.

The runner installs the complete Python and Node development-test dependency
sets, including the pinned provider clients required for the live-provider E2E
module. The default hosted `all` scope includes the `setup_drift` and
`setup_provider` probes. These exercise only the authority available through
the runner's configured runtime identity and keep their normal test-prefixed
cleanup contracts.

The version URL is not an open testing site. Only `/testing/health` and the
bootstrap exchange are initially reachable. The exchange requires a Google ID
token for the exact version origin, the configured runtime identity, the exact
source/version metadata, and ownership of the shared Redis lease. That token
can be exchanged only once for the lease-owning run. The server then issues an
HTTP-only, Secure, SameSite=Strict `__Host-` cookie bound to the run, source,
and version. Registered application and testing routes pass through Flask's
request gate. The test descriptor retains the normal App Engine static
handlers for compiled JavaScript, CSS, fonts, images, and other public build
artifacts; those files contain no application settings, credentials, or test
data and are served exactly as they are by a normal deployment. Someone who
learned the short-lived random version hostname could therefore fetch its
compiled frontend, but could not reach dynamic application data or test APIs.
The descriptor replaces production's terminal static `404.html` catch-all with
a dynamic handler, so unknown-route tests reach Flask and retain their real
HTTP status.
App-internal `/process` callbacks retain their separate exact Cloud Tasks OIDC
validation.

App Engine can soft-route a request for a deleted version hostname to the
default service. The normal application's Flask request boundary therefore
rejects reserved `e2e-<16 hex>-dot-e2e-dot-...appspot.com` hosts and returns a
marker-bearing 404. Setup, create, and teardown each probe a nonexistent
reserved version and require that exact marker. This makes deletion safe for
stale dynamic browser URLs and delayed task requests even if production changed
during a run; hosted E2E refuses to start or delete its version until the guard
is present in production. Canonical production static handlers may still serve
their already-public immutable assets for a soft-routed static path, but no
dynamic application route is reachable through the stale hostname.

## One-Time Setup

Complete normal installation, deploy the current application normally, and run
`./setup.sh development` first so the production soft-routing guard, test bucket
family, and local toolchain exist. From a trusted operator checkout, run:

```bash
venv/bin/python run.py hosted-e2e setup --github-repository OWNER/REPOSITORY
```

Setup is idempotent. It enables the required Google APIs and creates or
reconciles the two dedicated service accounts, Artifact Registry repository,
seven-day result bucket, two Secret Manager mount targets, Workload Identity
pool/provider, bucket-scoped access, and inert App Engine anchor. It prints and
records the non-secret resource identifiers in
`reports/hosted-e2e/setup.json`.
On the exact E2E runtime account, setup also reconciles the narrowly scoped
act-as and token-signing grants needed by that runtime and the trusted deployer;
the live IAM contract verifies those grants without giving the runtime
project-wide provisioning authority.

Create a protected GitHub environment named `hosted-e2e` and add these
environment variables from the setup output:

| Variable | Value |
| --- | --- |
| `GCP_PROJECT_ID` | `project` |
| `GCP_RESOURCE_REGION` | `region` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `provider_resource` |
| `GCP_E2E_INVOKER_SERVICE_ACCOUNT` | `invoker_email` |

These are resource names, not secrets. Environment reviewers are recommended
because a dispatch can consume provider resources and exercise the real test
bucket family.

## Normal Lifecycle

Freeze the candidate, create its canonical production bundle, and commit the
complete source plus generated release output before creating hosted resources:

```bash
npm ci
npm run build
# Commit the complete reviewed candidate with the normal Git "commit all"
# workflow, including the generated production output.
venv/bin/python run.py hosted-e2e create
```

Hosted E2E does not prescribe a separate manual staging workflow. Git may stage
files internally as part of the operator's normal commit-all action. The
important boundary is that the complete reviewed source and generated build
are committed, and the authored worktree is clean, before `create` runs.

`create` does not edit or replace the canonical `lagniappe.yaml`. It writes an
owner-only temporary descriptor, deploys with `--no-promote`, validates the
exact version's health metadata, updates the Cloud Run job, and removes the
descriptor. The temporary descriptor copies the canonical static handler
contract while substituting the test service, runtime identity, scaling, and
fail-closed hosted environment. It never rebuilds frontend assets. Instead it
requires the commit's
`build.json`, service worker, and `config/constants.py` to identify one
production build, exports that exact Git commit, and uses the export for both
the App Engine version and runner image. Incidental generated-static churn in
the operator checkout therefore cannot change either artifact. The App Engine
export receives the canonical runtime settings through the same trusted local
deployment boundary; the runner image still excludes them and receives its
settings only from Secret Manager. Both artifacts and browser assets use the
committed build ID. The version permits zero idle instances and receives no
service traffic.
Because gcloud treats the active root `.gcloudignore` as upload metadata, the
runner-image build carries an exact derived copy from the committed export and
restores it inside the container. Repository-health tests therefore inspect the
same canonical deploy boundary in local and hosted runs.

The runner submits its image build asynchronously and records the provider's
Cloud Build ID before waiting. It also records completed provisioning phases.
If the local process is interrupted, rerunning `create` from the same clean
commit resumes that exact lifecycle: it waits for the recorded build,
recognizes an exact already-deployed version, and safely repeats idempotent
reconciliation. A different commit is rejected until the interrupted
lifecycle is torn down.

With the candidate environment ready, a plain execute runs every normal suite:

```bash
venv/bin/python run.py hosted-e2e execute
```

Use `--suite full` for E2E alone. The default `all` scope expands to `unit`,
`js`, `tooling`, and `e2e` in one pytest session. It overrides only the ordinary
opt-in exclusions and therefore also runs the read-only setup drift probes and
live provider contracts. Tests marked `unfinished` remain excluded. Ordinary
local suite commands retain the marker exclusions from `testing/pytest.ini`.

For trusted local diagnosis, run one or more real E2E files/nodeids without
repeating the complete suite:

```bash
venv/bin/python run.py hosted-e2e execute \
  --target testing/tests_e2e/002_home/test_002d_home_tasks.py::test_create_personal_task_due_today
```

Repeat `--target` to run several cases in one leased pytest session. The job
accepts only bounded, existing Python files beneath `testing/tests_e2e/`; it
rejects pytest options, traversal, control characters, and argument-delimiter
ambiguity. The GitHub workflow deliberately continues to expose only the fixed
`all` and `full` scopes.

Both commands execute the same `lagniappe-e2e` Cloud Run job used by CI. The
hosted runner skips local Flask startup, local frontend rebuilding, and local
gcloud activation inside pytest. Direct Datastore/Storage/Redis fixture calls
therefore execute from the regional job while browser HTTP calls use the exact
App Engine version URL. After acquiring the shared lease, the runner removes
stranded test-prefixed data and replays the persistence portion of application
startup: Redis indexes, reserved Datastore models, and the fresh-install
migration baseline. This matches the local ordering, where the Flask test
server starts and seeds persistence only after cleanup; the already-running
hosted version does not need to be restarted.

Inspect state or tear down the runnable resources with:

```bash
venv/bin/python run.py hosted-e2e status
venv/bin/python run.py hosted-e2e teardown
```

The Redis lease serializes local and hosted pytest sessions and remains outside
the `test-` cleanup namespace. Its heartbeat expires after an abandoned run.
The hosted runner validates the exact version/source health response before it
can acquire that lease or touch shared test data, so a stale delayed execution
cannot clean data after its version has been removed.
The shared cleanup entry point also refuses to run unless the effective
configuration is testing mode with the exact reserved `test-` prefix.
Teardown checks Cloud Run executions and acquires the data lease before
stranded-data cleanup, then holds that lease until the job and version are
gone. A job racing with teardown therefore cannot begin test-data work. It
refuses to remove an active run unless `--force` is explicit; forced teardown
first cancels listed job executions. It then deletes the Cloud Run job, deletes
only the ephemeral App Engine version, and removes only that version's origin
from test-bucket CORS. The anchor, image repository, mount secrets, WIF
provider, and seven-day artifact bucket remain for reuse.

## Running From GitHub

Dispatch `.github/workflows/hosted-e2e.yml` at the same Git ref used by
`create`; its default `all` choice runs every complete suite, including the
setup drift and live-provider contracts, in its single job. The E2E-only
`full` choice remains available for diagnosis. The
workflow reads the configured source from the job and refuses to execute if it
differs from `github.sha`. It uses WIF only to describe and invoke that exact
job and to download that execution's bundle from the dedicated result bucket;
it has no project-wide Cloud Run viewer role and cannot read either mounted
secret or application/test data buckets. The container entry point also
accepts the separately validated `focused` scope used by the trusted local
command, but the workflow has no focused input or arbitrary target field.
The workflow checks out the exact candidate but does not rebuild it or create a
branch. After the run, it validates and merges the downloaded evidence, checks
that no tracked file except `testing/evidence/latest.json` changed, and uses a
normal `git commit -am` plus non-force push to return that evidence to the
dispatch branch. It rejects tag dispatches and refuses to push if the remote
branch moved away from the tested commit while the suite was running. Branch
protection must permit the workflow's GitHub token to make this evidence-only
follow-up commit.

Local and GitHub dispatches are consequently two front doors to the same job,
not separate test implementations.

## Evidence And Reports

Every job uploads the following under
`gs://ARTIFACT_BUCKET/executions/EXECUTION/`:

- `manifest.json`, including commit, version, build ID, suite, and exit status;
- `evidence.json`, produced by the normal pytest traceability plugin;
- `junit.xml`; and
- `reports.tar.gz`, containing E2E failure/report output.

A focused manifest also records the exact selected nodeids.

Local execution downloads its exact bundle and merges evidence by default:

```bash
venv/bin/python run.py hosted-e2e execute
```

The download is stored under
`reports/hosted-e2e/results/EXECUTION/` and merges its per-test outcomes and
semantic snapshots into `testing/evidence/latest.json`. Existing unselected
test evidence is preserved, just as it is after a focused local pytest run.
The merged provenance records the hosted execution, job, service, commit,
version, and selected suite. Use `execute --no-import-results` for an
exceptional dispatch that should leave its result only in Cloud Storage. The
existing `results --latest`, `--download-only`, and `--skip-report-archive`
options remain available for recovery and selective inspection. Downloads
print their destination and per-file byte progress.

GitHub performs the same validation and merge from its downloaded directory,
then commits the resulting evidence to the exact tested branch before it
reports the suite outcome. Failed runs are therefore preserved too. The final
workflow step still fails when the hosted manifest failed, so committing the
diagnostic evidence cannot turn a red suite green.

The import merges only when both the result commit and semantic source-tree
snapshot equal the local checkout. A different source is still available with
`--download-only` but cannot contaminate the tracked evidence manifest. A
failed suite also imports its failed outcomes and tracebacks, so `latest.json`
truthfully represents the latest selected run.
Locally, review and commit that ordinary follow-up change on the existing
`next/*` or `hotfix/*` branch. In GitHub, the workflow performs that
evidence-only commit automatically. Evidence and reports are excluded from the
semantic source snapshot, so the follow-up commit does not invalidate the
tested snapshot even though provenance retains the exact pre-evidence candidate
commit.

## Failure Recovery

`reports/hosted-e2e/state.json` records a creating, ready, failed, or torn-down
lifecycle without storing credentials. If create or execution is interrupted:

1. Run `hosted-e2e status`.
2. If `create` was interrupted, return to the same clean commit and rerun
   `hosted-e2e create`; the recorded Cloud Build/version phases resume.
3. Use `hosted-e2e results --latest` if an execution reached artifact upload.
4. Run `hosted-e2e teardown` when abandoning that lifecycle or moving to a
   different commit, then create the new candidate.

Do not run local E2E, hosted E2E, `test-server`, or browser-review sessions
against the shared test data concurrently.
