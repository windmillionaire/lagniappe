# Testing

This is the entry point for the Lagniappe test suite. For instructions on
writing or reviewing tests, start with [TESTING_WRITING_TESTS.md](TESTING_WRITING_TESTS.md).

## Suites

| Suite | Location | Use For |
| --- | --- | --- |
| E2E | `testing/tests_e2e/` | Browser/server workflows, frontend behavior, routes, permissions visible in UI, Redis/cache-backed integration |
| JavaScript | `testing/tests_js/` | Frontend module behavior that runs in Node without a live browser or server |
| Unit | `testing/tests_unit/` | Deterministic backend behavior that does not need the live app server |
| Tooling | `testing/tests_tooling/` | Setup/config smoke tests, repository-health tests, reporter tests, docs/tooling checks |

Use the JavaScript suite for module behavior that can be isolated with small
platform fakes. Keep real DOM behavior, route integration, and user workflows
in E2E. Shared Node discovery and execution live in
`testing/tests_js/conftest.py`.

## Developer Dependencies

`requirements.txt` is the App Engine/runtime dependency file. After completing
the ordinary guided installation, install the complete local toolchain with:

```bash
./setup.sh development
```

The command is additive and safe to rerun. It verifies the existing
installation, creates the test-prefixed Cloud Storage buckets, installs
`requirements-dev.txt`, runs `npm ci`, installs Playwright Chromium, and builds
the development frontend. The dev requirements include the runtime dependencies
plus pytest and Playwright packages used by the test harness.

## Main Commands

Use the project virtualenv for Python commands:

```bash
venv/bin/python run.py test
venv/bin/python run.py test unit
venv/bin/python run.py test e2e
venv/bin/python run.py test js
venv/bin/python run.py test tooling
venv/bin/python run.py test setup

venv/bin/python run.py test testing/tests_e2e/003_forms/test_003b_form_builder.py
venv/bin/python run.py test testing/tests_e2e/003_forms/test_003b_form_builder.py::test_preview_panel
venv/bin/python run.py test tooling testing/tests_tooling/test_007_run_py_test_command.py

venv/bin/python run.py test -k "category"
venv/bin/python run.py test -- -k "category"
venv/bin/python run.py test -v --tb=long
```

Focused runs use real pytest paths or nodeids.
When a suite alias is combined with an explicit path or nodeid, the explicit
target wins and the alias is treated only as a harmless scope hint.

Before starting pytest, the runner activates the complete gcloud configuration,
account, and project saved in this checkout's `lagniappe_dev.yaml`. The
activation also exports the project environment inherited by pytest and any
Flask subprocess. An unconfigured checkout remains usable for offline tests,
while a partially configured target fails before collection instead of using
ambient gcloud state.

E2E targets automatically turn unloaded-relation diagnostics into test
failures, including focused E2E nodeids and the unscoped full suite. Use the
runner-level `--strict` flag when the same checks are wanted for another suite:

```bash
venv/bin/python run.py test --strict unit --tb=short
venv/bin/python run.py test --strict testing/tests_e2e/007_categories/test_007a_category_index.py::test_generate_pages_explain_prompt_from_category_tools
```

For long or risky checks, start with focused nodeids or one file and expand
only after probes pass. Avoid broad E2E/full-suite runs when you need a test
run you can cancel or diagnose quickly.

Run E2E/browser-server work sequentially. Separate E2E pytest invocations,
`test-server`, and `browser-review` all use the same managed testing server and
test data prefix; whichever session finishes first will tear down shared state
for the others. Put multiple focused files or nodeids in one pytest command
instead of launching them in parallel. E2E pytest takes an advisory session
lock and cleans stale test data before starting the server, so overlapping
pytest invocations should fail early with a clear message and interrupted runs
should be less likely to poison the next run.

### Hosted Tests

The opt-in hosted runner deploys one zero-traffic App Engine `e2e` version and
can execute the normal unit, JavaScript, tooling, and pytest/Playwright E2E
suites in one Cloud Run job. This keeps direct Datastore/Storage/Redis helpers
close to their providers and lets either a trusted local command or secret-free
GitHub WIF invocation start the same job. A Redis lease serializes hosted and
local E2E access to the fixed `test-` namespace. `create` consumes an already
committed production build and exports that exact commit for both hosted
artifacts; it does not run the frontend build.

```bash
venv/bin/python run.py hosted-e2e setup --github-repository OWNER/REPOSITORY
venv/bin/python run.py hosted-e2e create
venv/bin/python run.py hosted-e2e execute
venv/bin/python run.py hosted-e2e results --latest
venv/bin/python run.py hosted-e2e status
venv/bin/python run.py hosted-e2e teardown
```

The default `all` scope runs every ordinary suite; `pilot`, E2E-only `full`, and
trusted local focused dispatch remain available. Execution does not change
local evidence. A local or CI-triggered run is imported explicitly with
`results --latest` from the same candidate commit. Evidence import is a manual
release step and the reviewed manifest becomes an ordinary follow-up commit;
the workflow has no repository write permission. See
[TESTING_HOSTED_E2E.md](TESTING_HOSTED_E2E.md) for the production-build order,
security model, one-time setup, GitHub variables, lifecycle, artifact behavior,
and failure recovery.

### Browser failure guard

E2E teardown fails on an unaccounted console error, uncaught `pageerror`, or
failed browser request. The failure includes the user/context, page URL, and
event details, and captures the usual browser artifact first.
Playwright's exact `net::ERR_ABORTED` navigation cancellations are reported in
diagnostic output but are not treated as failures; they are browser lifecycle
cancellation, not a completed request failing in the application.
Chromium's exact `Transition was skipped` page error is handled the same way:
cross-document View Transitions may be cancelled by navigation after the new
document has already loaded successfully.

When a test deliberately exercises one of those failures, scope its exact
request or error instead of adding a global ignore:

```python
with browser_failures.expect(
    user,
    kind="requestfailed",
    method="POST",
    path="/l/sync",
):
    reconnect()
```

For a native offline transition, use the convenience scope. It requires the
failed `HEAD /l/ping` request, so an offline test cannot silently stop
exercising the connection boundary. Chromium's duplicate
`ERR_INTERNET_DISCONNECTED` console diagnostic is recorded but ignored because
its delivery can lag behind the path-bearing network event:

```python
with browser_failures.expect_offline(user):
    user.offline = True
    expect(user.locate("[data-role='offline']")).to_be_visible()
```

The scope requires the expected event to occur exactly once; it fails when the
event is missing or repeated. Use `message_contains` or `text_contains` only
when a browser error includes variable stack-location text.

To inventory browser events without making otherwise passing tests fail, run a
sequential diagnostic session:

```bash
venv/bin/python run.py test e2e --browser-failure-diagnostics
```

It writes `reports/test_runs/browser_failure_diagnostics.json`. Diagnostic mode
does not relax scoped-expectation checks.

## Manual Browser Test Server

Use `test-server` when you want the same testing Flask server that E2E uses,
but kept alive for manual or agent-driven browser evaluation:

```bash
venv/bin/python run.py test-server --start
venv/bin/python run.py test-server --start --load project-review
venv/bin/python run.py test-server --start --load category-review
venv/bin/python run.py test-server --start --load form-index-review
venv/bin/python run.py test-server --start --load page-review
venv/bin/python run.py test-server --start --load search-review
venv/bin/python run.py test-server --start --load task-index-review
venv/bin/python run.py test-server --start --load user-index-review
venv/bin/python run.py test-server --teardown
```

`--start` runs the app with `FLASK_ENV=testing`, uses the configured test
`BASE_URL` and test data prefix, resets `reports/test_failures/` and
`reports/test_reports/`, and writes local runtime files to
`reports/test-server.pid` and `reports/test-server.log`. Before Flask starts,
the command compares frontend build inputs and outputs with
`reports/test-frontend-bundle.json` and runs `npm run dev` only when the bundle
is stale, missing, restored, or incomplete. E2E pytest startup performs the
same check before pytest imports application configuration; non-E2E focused
test runs do not invoke npm. `--teardown` stops the background server first,
then cleans test-prefixed datastore/cache data.
Use `--load` with `--start` to seed curated E2E definition data for browser
review; `project-review` creates a project with model tasks, filterable tasks,
an assignee, due dates, and attached-form submissions. `category-review`
creates a category with page-form submissions, filterable pages, an extra
category facet, and a public page with a document asset. `form-index-review`
creates page and task forms with simple and complex schemas, plus related
categories and projects for index relationship columns. `page-review` creates a
page with form data and varied page tasks while leaving the document empty for
live editor review. `search-review` creates cross-facet indexed data for the
shared `filter` query on the full search page. `task-index-review` creates
active personal/page tasks with due dates, assignment, project/model links,
attached-form data, and one completed contrast task that should not appear on
the active index. `user-index-review` creates users, groups, and permission
profiles for reviewing the user table and group-permissions tools. The latest
load summary is written to
`reports/test-server-load.json`.

For agent-driven browser review with screenshots, product feedback, and
important coverage recommendations, read
[REPORTS_BROWSER_REVIEW.md](REPORTS_BROWSER_REVIEW.md) (`@REPORTS_BROWSER_REVIEW`). Browser review
folders are written under `reports/browser_reviews/`.

For manual login, use the same test-user bypass as the E2E login flow:

```text
http://127.0.0.1:5000/users/login?test_user=admin@test.com
```

In `FLASK_ENV=testing`, the `test_user` query logs in the requested test user.
If the requested email is the configured admin email and it does not exist yet,
the route creates it first. Other test-user emails must already exist or the
route returns `403`.

## Manual Provider Workflows

Some workflows depend on real Cloud Tasks or provider callbacks
and should be validated manually instead of kept as skipped E2E tests:

- deferred category page generation completion, including pending-to-complete
  notification replacement and category table refresh;
- file extract/summarize process callbacks from Cloud Tasks, including OCR or
  AI provider completion and the browser-visible authoritative form/status update;
- remote ingress import stop/restart controls in a non-local asynchronous
  import run.

Useful direct pytest commands:

```bash
venv/bin/python -m pytest -c testing/pytest.ini testing/tests_tooling/
venv/bin/python -m pytest -c testing/pytest.ini testing/tests_js/
venv/bin/python -m pytest -c testing/pytest.ini testing/tests_unit/
venv/bin/python -m pytest --collect-only -q -c testing/pytest.ini
```

## Traceability Tools

```bash
venv/bin/python run.py traceability --changed --check
venv/bin/python run.py traceability --source lagniappe/core/tools/cache/core.py
venv/bin/python run.py traceability --source lagniappe/web/routes/users/login.py lagniappe/web/routes/users/logout.py
venv/bin/python run.py traceability --test tests_unit/test_003_submission.py
venv/bin/python run.py traceability --feature-dimension document:save

venv/bin/python run.py template-contracts
venv/bin/python run.py template-contracts test_002b_home_projects.py

venv/bin/python run.py traceability --styles
venv/bin/python run.py traceability --style task.home.group
```

`traceability` checks source annotations against static test discovery and the
current working-tree test-result manifest. Real pytest collection verification
is available with `--verify-collection`.
`template-contracts` checks UI tests annotated with `@template` against Jinja
macro contracts and test selector evidence. `traceability --styles` checks the
typed semantic registry, source consumers, authored CSS selectors, build
pipeline, generated-map parity, and advisory raw-class candidates. These tools
print console reports and write Markdown or machine-readable manifests under
`reports/`.

See [TESTING_TRACEABILITY_TOOL.md](TESTING_TRACEABILITY_TOOL.md) for annotation syntax and
[TESTING_SOURCE_REVIEW.md](TESTING_SOURCE_REVIEW.md) or
[TESTING_TEST_REVIEW.md](TESTING_TEST_REVIEW.md) for the later review
pass that checks whether referenced tests really cover their source symbols.

## Documentation Map

| Document | Purpose |
| --- | --- |
| [TESTING_WRITING_TESTS.md](TESTING_WRITING_TESTS.md) | Practical guide for adding or reviewing tests |
| [TESTING_TRACEABILITY_TOOL.md](TESTING_TRACEABILITY_TOOL.md) | Source/test annotation contract, current results, and reporter behavior |
| [TESTING_TEMPLATE_CONTRACTS.md](TESTING_TEMPLATE_CONTRACTS.md) | Jinja macro and selector-evidence contract tracking |
| [TESTING_TEST_REVIEW.md](TESTING_TEST_REVIEW.md) | Agent workflow for reviewing annotated or bare tests |
| [TESTING_SOURCE_REVIEW.md](TESTING_SOURCE_REVIEW.md) | Agent workflow for reviewing source annotation quality |
| [REPORTS_BROWSER_REVIEW.md](REPORTS_BROWSER_REVIEW.md) | Agent workflow for browser product and coverage review reports |
| [STYLE_CANDIDATES.md](STYLE_CANDIDATES.md) | Style candidate review workflow for `styles.yaml` reports |

## Test Layout

| Directory | Contents |
| --- | --- |
| `testing/definitions/` | Shared test data and reusable scenario definitions |
| `testing/resources/` | Page/entity helpers, navigation, and page-specific selectors |
| `testing/elements/` | Shared UI primitives such as `List`, `Table`, `Modal`, `Tabs`, and `SpinnerButtons` |
| `testing/utility/` | Failure capture, report writers, fakes, and support helpers |
| `testing/files/` | JSON schemas, entity fixtures, CSVs, and other test assets |

Keep the `testing/` root clean. Miscellaneous helpers belong in
`testing/utility/`; repository-health tests belong in `testing/tests_tooling/`.

## Markers

| Marker | Meaning |
| --- | --- |
| `e2e` | Browser/server end-to-end test |
| `js` | JavaScript behavior test executed in Node |
| `unit` | Backend unit test |
| `tooling` | Setup, config, repository-health, or reporter test |
| `ai` | AI-powered test with longer default timeout |
| `setup_drift` | Opt-in read-only provider/API drift probe |
| `setup_provider` | Opt-in sequential live-provider setup/runtime contract |
| `unfinished` | Backlog test skipped by default |

`testing/pytest.ini` excludes `unfinished`, `setup_drift`, and `setup_provider`
by default.
Provider contracts change independently of the repository and can require
network access, so run the drift probes explicitly when reviewing setup
providers:

```bash
venv/bin/python run.py test setup -m setup_drift
```

Before ordinary E2E or managed test-server startup, authenticate explicitly:

```bash
venv/bin/python run.py auth
```

Test startup verifies that ADC belongs to the checkout's saved human account
and project, or is already using the configured runtime account. It never opens
an authentication browser or changes ADC itself; a mismatch stops with a
`run.py auth` instruction. During application initialization,
`CONFIG.google_credentials` turns human ADC into a short-lived credential for
`RUNTIME_SERVICE_ACCOUNT_EMAIL`. The testing Flask app and its Google clients
therefore use the runtime service account, never the more privileged
installer/deployer identity directly.

The live setup-provider contract first audits the reconciled project, bucket,
and exact service-account IAM bindings. It uses `testIamPermissions` with the
runtime credential to prove deployment, API enablement, project IAM, key
administration, and bucket-administration permissions are absent. It then
exercises that credential against Datastore, all four Storage buckets, Cloud
Tasks, the Scheduler OIDC target, Document AI, Vertex AI, Places, Identity
Platform token verification. Its Scheduler probe also verifies that a
valid OIDC request with an
invalid body receives `400`, not a success acknowledgement. Run it only after
setup has reconciled the test project. It creates
test-prefixed provider state, performs billable API calls, and must run by
itself against the managed testing server:

```bash
venv/bin/python run.py test setup -m setup_provider
```

The `setup` alias resolves either marker to its otherwise uncollected test file,
so no filename is required. Use the runner's `provider` convenience marker to
run both opt-in groups in one sequential session:

```bash
venv/bin/python run.py test setup -m provider
```

The equivalent explicit pytest expression is
`-m "setup_drift or setup_provider"`. A normal
`venv/bin/python run.py test setup` remains offline and excludes both groups.

AI E2E tests marked with `@pytest.mark.ai` automatically get a
`request.node.ai_results` report object. Record prompts, response bodies, entity
snapshots, and generated output there so real provider calls leave durable
review artifacts without requiring a separate `results` fixture. The explicit
`results` fixture still works, and marked AI tests that request it receive the
same report object.

## Reports And Failure Artifacts

Generated artifacts belong under `reports/`:

- E2E screenshots and selected HTML failure dumps: `reports/test_failures/`
- Rich HTML reports from the `results` fixture: `reports/test_reports/`
- Curated browser review folders: `reports/browser_reviews/`
- Managed browser test-server runtime/seed files: `reports/test-server.*`,
  `reports/test-server-load.json`
- Hosted lifecycle state and downloaded result bundles:
  `reports/hosted-e2e/`
- Traceability reports: `reports/traceability*.md`
- Template contract reports: `reports/template-contracts*.md`
- Rollup bundle visualizers: `reports/`

For E2E failures, the harness captures screenshots for each active user page.
HTML dumps are saved when the page content looks like a server error page.
Failed tests also include their pytest traceback and failing phase in
`testing/evidence/latest.json`. Tracebacks larger than 100,000 characters keep
their beginning and end and are marked with `traceback_truncated: true`.
Unlike generated reports, this manifest is tracked. It is current evidence
rather than a run log: it keeps one latest result per exact test nodeid and
invocation metadata for only the newest pytest session. Each test run prunes
results whose test module or source test definition no longer exists while
retaining unselected tests still in the tree. Its semantic snapshots use an interned
path/fingerprint table so snapshots from separate focused runs do not duplicate
the full path strings and hashes. It excludes
`testing/evidence/` and `.github/` from those snapshots so writing evidence or
changing contribution automation does not invalidate application behavior
results. Review the file before committing it: failed results may contain
diagnostic tracebacks, which must not include credentials, private data, or
other sensitive output.

The main release workflow intentionally runs no application tests and receives
no GCP, Redis, or deployment credentials. The maintainer runs the necessary
tests on configured infrastructure and commits the updated evidence manifest
before opening the release pull request. Hosted CI runs Biome, Ruff,
repository-wide traceability, changed-source traceability, and the release-tree
check against the exact base commit. The separate manually dispatched Hosted
E2E workflow uses keyless WIF only to invoke an already-created Cloud Run job;
it receives none of the application's settings or provider credentials.

## Placement Rules

- Put reusable scenario data in `testing/definitions/`.
- Put page/entity-specific navigation and selectors in `testing/resources/`.
- Put reusable widget interactions in `testing/elements/`.
- Put support code and report helpers in `testing/utility/`.
- Put user-story assertions in `testing/tests_e2e/`.
- Put Node-backed frontend module assertions in `testing/tests_js/` when they
  do not require a live browser or server.
- Put pure backend assertions in `testing/tests_unit/`.
- Put setup, config, reporter, and repository-health assertions in
  `testing/tests_tooling/`.
