# Testing Managed Server

The managed test server runs the same Flask configuration and fixed test data
prefix used by E2E. Use it for manual or agent browser exploration. Do not run
it alongside E2E pytest, hosted E2E, or another browser-review session.

## Lifecycle

```bash
venv/bin/python run.py test-server --start
venv/bin/python run.py test-server --teardown
```

Startup:

- verifies gcloud/ADC for the checkout;
- checks frontend inputs and generated output, running `npm run dev` only when
  the bundle is stale or incomplete;
- starts Flask with `FLASK_ENV=testing` at configured `BASE_URL`;
- probes `/l/ping` immediately within one 20-second monotonic readiness budget,
  deriving finite connect/read timeouts from the remaining time and reporting
  only the last connection or HTTP state on timeout;
- resets E2E artifact folders; and
- records PID/log files under `reports/`.

Teardown stops Flask before deleting test-prefixed Datastore/cache data. The
E2E session lock prevents most overlap, but callers still own sequential use.

## Seed packs

Use `--load` to create realistic data from normal E2E definitions:

```bash
venv/bin/python run.py test-server --start --load project-review
```

| Pack | Useful for |
| --- | --- |
| `project-review` | Project page, model tasks, Task filters, assignees, due dates, and form submissions. |
| `category-review` | Category Page index, filters, facets, public Page, and document asset. |
| `form-index-review` | Page/Task Forms, complex schemas, and relationship columns. |
| `page-review` | Page form, varied Tasks, and an empty document for editor work. |
| `search-review` | Cross-facet full search and pagination. |
| `task-index-review` | Personal/Page Tasks, due/assignment/model/form data, and completed contrast. |
| `user-index-review` | Users, Groups, and permission profiles. |

The latest load summary is `reports/test-server-load.json`.

## Login

Testing mode supports the E2E test-user handoff:

```text
http://127.0.0.1:5000/users/login?test_user=admin@test.com
```

The configured test Owner is created when absent. Other requested test Users
must already exist or the route returns 403.

## Browser review

Use `browser-review capture` for initial screenshots and diagnostics, then
explore the live UI and curate `review.json` before rendering. The complete
workflow, report schema, screenshot guidance, and coverage-review rules are in
[TESTING_BROWSER_REVIEW.md](TESTING_BROWSER_REVIEW.md).

## Manual provider workflows

Use the managed server for selected provider flows that need real Cloud Tasks
or callbacks and are not stable ordinary E2E stories, including:

- deferred Page generation and notification/list refresh;
- file extract/summary callbacks and authoritative status replacement; and
- a remote Ingress stop/restart run.

Keep provider experiments sequential, narrowly scoped, and cleaned through
normal server teardown.

## Failure guard

E2E teardown fails on unaccounted browser console errors, page errors, and
failed requests. An intentional failure must use a narrowly scoped
`browser_failures.expect(...)` or `expect_offline(...)` context. Do not add a
global ignore.

Diagnostic mode inventories events without failing otherwise passing tests:

```bash
venv/bin/python run.py test e2e --browser-failure-diagnostics
```

It writes `reports/test_runs/browser_failure_diagnostics.json` and still
enforces explicit expectations.
