# Hosted E2E

Hosted E2E is an opt-in way to run the existing pytest/Playwright suite close
to Datastore, Cloud Storage, App Engine, and Redis without copying application
secrets into GitHub Actions. It uses the same tests, resources, direct backend
helpers, fixed `test-` data prefix, cleanup, and traceability-result plugin as a
local E2E run.

The operator deploys one exact, zero-traffic App Engine version and a matching
Cloud Run job from a clean commit. A local command or the manual GitHub
workflow then invokes that same job. Teardown deletes the runnable version and
job; an inert `e2e-anchor` version remains as the service's traffic owner.

## Security Boundary

GitHub receives no settings file, Redis credential, service-account key, or
application bootstrap secret. The `hosted-e2e` GitHub environment uses Google
Workload Identity Federation to impersonate a dedicated invoker account. Its
provider condition is restricted to:

- the configured `OWNER/REPOSITORY`;
- `.github/workflows/hosted-e2e.yml`;
- the `hosted-e2e` GitHub environment; and
- view and execute-with-overrides permissions on the exact Cloud Run job.

The Cloud Run job runs as a separate E2E runtime service account. Secret
Manager mounts `lagniappe_settings.yaml` and, when configured, the managed
Redis CA certificate directly into that job from separate secrets. All of
`config/files/` is excluded from the image and result artifacts. The result
bucket uses uniform access with public access prevention. The App Engine
version receives the normal settings only through the trusted local App Engine
deploy, the same boundary used by a production deploy.

The version URL is not an open testing site. Only `/testing/health` and the
bootstrap exchange are initially reachable. The exchange requires a Google ID
token for the exact version origin, the configured runtime identity, the exact
source/version metadata, and ownership of the shared Redis lease. That token
can be exchanged only once for the lease-owning run. The server then issues an
HTTP-only, Secure, SameSite=Strict `__Host-` cookie bound to the run, source,
and version. The test descriptor sends static assets through Flask as well, so
the request gate covers them. App-internal `/process` callbacks retain their
separate exact Cloud Tasks OIDC validation.

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
git add -- \
  config/constants.py \
  lagniappe/web/static \
  lagniappe/web/start/styles/icons.py \
  lagniappe/web/start/styles/styles.py
# Stage the rest of the reviewed release candidate, then commit it.
venv/bin/python run.py hosted-e2e create
```

`create` does not edit or replace the canonical `lagniappe.yaml`. It writes an
owner-only temporary descriptor, deploys with `--no-promote`, validates the
exact version's health metadata, updates the Cloud Run job, and removes the
descriptor. It never rebuilds frontend assets. Instead it requires the commit's
`build.json`, service worker, and `config/constants.py` to identify one
production build, exports that exact Git commit, and uses the export for both
the App Engine version and runner image. Incidental generated-static churn in
the operator checkout therefore cannot change either artifact. The App Engine
export receives the canonical runtime settings through the same trusted local
deployment boundary; the runner image still excludes them and receives its
settings only from Secret Manager. Both artifacts and browser assets use the
committed build ID. The version permits zero idle instances and receives no
service traffic.

Run the short infrastructure/login pilot first, then the full suite:

```bash
venv/bin/python run.py hosted-e2e execute --suite pilot
venv/bin/python run.py hosted-e2e execute --suite full
```

Both commands execute the same `lagniappe-e2e` Cloud Run job used by CI. The
hosted runner skips local Flask startup, local frontend rebuilding, and local
gcloud activation inside pytest. Direct Datastore/Storage/Redis fixture calls
therefore execute from the regional job while browser HTTP calls use the exact
App Engine version URL.

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
`create`, selecting `pilot` or `full`. The workflow reads the configured source
from the job and refuses to execute if it differs from `github.sha`. It uses WIF
only to describe and invoke that exact job; it has no project-wide Cloud Run
viewer role and cannot read either mounted secret or download result objects.
The workflow uses its job-scoped override permission to select `pilot` or
`full`; the container entry point rejects other command-line suite values.
It does not check out, rebuild, commit, or create a branch in the repository.

Local and GitHub dispatches are consequently two front doors to the same job,
not separate test implementations.

## Evidence And Reports

Every job uploads the following under
`gs://ARTIFACT_BUCKET/executions/EXECUTION/`:

- `manifest.json`, including commit, version, build ID, suite, and exit status;
- `evidence.json`, produced by the normal pytest traceability plugin;
- `junit.xml`; and
- `reports.tar.gz`, containing E2E failure/report output.

A local `hosted-e2e execute` downloads that execution under
`reports/hosted-e2e/results/EXECUTION/` and automatically merges its per-test
outcomes and semantic snapshots into `testing/evidence/latest.json`. Existing
unselected test evidence is preserved, just as it is after a focused local
pytest run. The merged provenance records the hosted execution, job, service,
commit, version, and selected suite.

A CI-triggered run deliberately does not update the repository. From a checkout
still at the exact candidate commit used by `create`, import its result during
the release flow:

```bash
venv/bin/python run.py hosted-e2e results --latest
```

The import merges only when both the result commit and semantic source-tree
snapshot equal the local checkout. A different source is still available with
`--download-only` but cannot contaminate the tracked evidence manifest. A
failed suite also imports its failed outcomes and tracebacks, so `latest.json`
truthfully represents the latest selected run.
Review it before committing for the same reasons as local evidence. The merge
is ordinary follow-up release work: commit the reviewed
`testing/evidence/latest.json` on the existing `next/*` or `hotfix/*` branch.
No CI evidence branch or repository write permission is required. Because that
evidence-only commit changes `HEAD`, import first; the semantic snapshot remains
valid after the evidence commit even though the hosted execution records its
candidate commit as provenance.

## Failure Recovery

`reports/hosted-e2e/state.json` records a creating, ready, failed, or torn-down
lifecycle without storing credentials. If create or execution is interrupted:

1. Run `hosted-e2e status`.
2. Use `hosted-e2e results --latest` if an execution reached artifact upload.
3. Run `hosted-e2e teardown` to remove any partial runnable version/job and CORS
   origin.
4. Return to a clean commit and run `create` again.

Do not run local E2E, hosted E2E, `test-server`, or browser-review sessions
against the shared test data concurrently.
