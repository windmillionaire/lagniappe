# Testing Writing Tests

Use this guide when adding, reviewing, or asking an agent to add tests. The goal
is to create real coverage without turning the suite into noise.

For a faster agent checklist when starting from an existing test, use
[TESTING_TEST_REVIEW.md](TESTING_TEST_REVIEW.md).

## First Decisions

Before writing code:

1. Read the behavior owner: route, entity/property, widget, template, or helper.
2. Check nearby tests and helpers with `rg`.
3. Pick the smallest test layer that proves the behavior.
4. If source annotations exist, run a focused report:

   ```bash
   venv/bin/python run.py traceability --source path/to/source.py path/to/related.py
   ```

5. If an E2E test is tied to a Jinja macro, add or check `@template` and run:

   ```bash
   venv/bin/python run.py template-contracts test_file.py::test_name
   ```

## Choose The Layer

| Use | When |
| --- | --- |
| Unit | Pure Python behavior, payload construction, validators, permissions math, entity/property logic |
| JavaScript | Frontend module behavior that can run in Node with small platform fakes and no live browser/server |
| E2E | Browser behavior, frontend modules, route integration, visible permissions, Redis/cache/search/sync effects |
| Tooling | Setup/config behavior, report scripts, repository-health checks, offline provider-contract checks |

Do not force browser behavior into unit tests. Do not start the app server for
logic that can be tested directly.

## E2E Shape

Good E2E tests are thin stories over rich helpers. The test function should read
like a user story, even when the flow has a lot of setup, waiting, widget state,
and browser interaction under the hood:

```python
def test_example(get_user):
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    user.locate(home.PROJECT_LIST_TOGGLE).click()
    expect(user.locate(home.PROJECT_LIST)).to_be_visible()
```

Where things belong:

| Need | Put It In |
| --- | --- |
| Reusable entity/scenario data | `testing/definitions/` |
| Page/entity navigation or selectors | `testing/resources/` |
| Shared widget interaction | `testing/elements/` |
| Failure/report/support helpers | `testing/utility/` |
| The user story and assertions | `testing/tests_e2e/` |

Prefer durable selectors from helpers: `data-widget`, `data-role`, `lp-*`, and
resource/element constants. A raw selector in a test is fine only when it is
local to one assertion and would make a helper worse.

Resource `initialize_view()` owns the destination view's structural
`initialized` marker, and `User.go()` calls it automatically. E2E contexts also
register a parser-time `pagereveal` observer because deferred modules are not
guaranteed to see that event. A test that must interact immediately after
deferred entity startup can call the resource's
`wait_for_interaction_readiness()` to await `lagniappe:services-ready` and the
active transition layer. After a direct `page.expect_navigation()` navigation,
call `initialize_view()` before that interaction-specific readiness boundary.

Keep E2E pytest runs sequential. The managed browser test server and test data
prefix are shared, so parallel E2E invocations can tear down each other's data
and server state. When checking multiple focused files or nodeids, pass them to
one pytest command. Frontend bundle preflight uses that same session lock and
defers any development rebuild while an E2E session is live. It also preserves
a completed production bundle; run `npm run dev` explicitly when replacing
production assets with a development build is intentional.

`parallel_safe` is an audit classification, not permission to start concurrent
local pytest sessions. It may be placed on one test or a complete E2E file and
must include a concise reason:

```python
@pytest.mark.parallel_safe(reason="uses one UUID-scoped page and no shared settings")
def test_example(get_user):
    ...
```

Only use the marker after checking that the story creates distinct entities,
does not clear or mutate shared state, does not depend on collection order, and
qualifies every list/result assertion by its own durable identity. Leave an
uncertain test serial. Tests under `001_site` and live-provider tests remain
serial. The ordinary runner continues to execute all E2E tests sequentially;
hosted fan-out is implemented only in the later parallelization phase.

### Touch and responsive interaction

Viewport size and input capability are separate browser-context contracts.
`user.mobile = True` changes the current page to the standard mobile viewport,
but it cannot add touch support to an existing context. Request touch support
when the user is created, then use Playwright's tap action so Chromium produces
the real event sequence:

```python
user = get_user(Users.OWNER, has_touch=True)
page = user.go(Pages.test_table_submission)
user.mobile = True

row = page.info_form.locator("tbody tr").first
row.tap(position={"x": 12, "y": 12})
expect(row.locator("[data-role='row-actions']")).to_be_visible()
```

Do not dispatch pointer or touch events manually from an E2E test. Playwright
does not expose a general swipe primitive; movement thresholds and detailed
event-order permutations belong in the JavaScript suite, with E2E retaining a
real tap integration story. Drive layout assertions with a supported viewport,
real content, or a naturally narrow component state rather than assigning
inline width styles from JavaScript.

### Browser failure expectations

Every E2E browser context is monitored for console errors, uncaught page errors,
and failed requests. An ordinary test therefore needs no local listener just to
assert that an operation did not throw: the fixture will fail teardown with the
originating page and request details.

Use the `browser_failures` fixture only when the story deliberately causes a
failure, and keep the scope around the one action that causes it:

```python
def test_replay_retries_one_aborted_sync(get_user, browser_failures):
    user = get_user(Users.OWNER)

    with browser_failures.expect(
        user,
        kind="requestfailed",
        method="POST",
        path="/l/sync",
    ):
        reconnect_with_the_test_route_aborted()
```

An expectation is context-bound and requires its exact count (one by default).
Match the narrowest stable fields: request method/path, exception type/message,
or console type/text. Do not use a suite-wide substring allowlist. For errors
whose browser text includes variable stack locations, use a scoped
`message_contains` or `text_contains` predicate together with the other stable
fields.

When the deliberate failure is an HTTP response that Chromium reports to the
console, use the status-and-path helper and keep the response assertion inside
the same scope:

```python
with browser_failures.expect_http_error(user, status=403, path="/admin"):
    response = user.page.goto(f"{base_url}/admin")
    assert response.status == 403
```

The helper accounts only for that exact console source path and status. It does
not replace an assertion about the returned status, response body, or visible
error state.

For native connectivity transitions, prefer `browser_failures.expect_offline(user)`
around the `user.offline = True` action and its offline assertions. It expects
the exact `HEAD /l/ping` disconnect produced by the browser. Chromium's delayed
console copy of that same ping failure is diagnostic rather than a second
completion boundary. An offline reload that deliberately performs both the
connectivity transition and a new-page health check may use `ping_count=2`. If
the same story also has a document lifecycle that can legitimately schedule one
additional health check, use the bounded `ping_count=2, max_ping_count=3` form.
Keep the upper bound so a retry loop still fails. Scope any expected 503 for an
offline analytics or asset request separately by its exact path; do not fold
those responses into the ping allowance.

If an unrelated request is already in flight when a deliberate offline
transition begins, it may fail zero or a small bounded number of times. Express
that as `count=0, max_count=N` only with an exact method/status/path signature.
The zero minimum makes the failure optional; the upper bound still detects a
loop or an unexpectedly broad outage.

### Browser request interception

Use `scoped_browser_route()` when an E2E story must observe, delay, abort, or
fulfill a browser request. Install the route on `user.page.context` so requests
forwarded through the service worker remain observable, use the narrowest
stable endpoint pattern, and keep the application action plus its visible
outcome inside the route scope:

```python
def fail_ping(route):
    assert route.request.method == "HEAD"
    route.abort("connectionfailed")


with scoped_browser_route(user.page.context, "**/l/ping", fail_ping):
    with browser_failures.expect(
        user,
        kind="requestfailed",
        method="HEAD",
        path="/l/ping",
        failure="net::ERR_CONNECTION_FAILED",
    ):
        trigger_server_health_check()
        expect(user.locate("[data-role='offline']")).to_be_visible()
```

Use `multipart_form_fields()` to inspect a routed `FormData` request without
replacing `window.fetch`. Prefer native browser offline mode for connectivity
stories. Use route abort/fulfill only when the story deliberately injects one
endpoint failure or deterministic provider response, and narrowly expect any
console or request failure that the route produces.

### Network response waits

For a normal browser mutation, use `expect_successful_response()` instead of a
broad `page.expect_response()` glob. It identifies the intended request before
asserting its transport result, so a matching 4xx/5xx response reports the
failure rather than making the test time out:

```python
with expect_successful_response(
    user.page,
    method="PUT",
    path=f"/tasks/{task.key}/update",
    entity_key=task.key,
):
    SpinnerButtons.UPDATE.click(task_form)

expect(task_form).to_be_visible()
```

The method and path are always required. Use `query` when query parameters are
part of the request identity, `request_payload_contains` when concurrent calls
share a route, and `response_check` only for response-payload assertions. Use
`entity_key` only when the route returns the `X-Lagniappe-Entity-Revisions`
header. Keep the visible postcondition after the wait, and reload or use a
fresh context when durable state is part of the story.

Do not remove the causal background boundary merely because a later visual
assertion exists. Keep the response, poll, replay, replacement, transition, or
service-worker acknowledgement when pre-action DOM could already satisfy that
assertion or when the action replaces the nodes being observed. After the
boundary completes, locate the current control again from a durable root and
assert the visible result. The boundary provides synchronization; the visible
or persisted result remains the success criterion.

For persisted document replay after replacing or reloading the page, use
`expect_offline_sync_replay()` with the durable sync ID. It installs the
`/l/sync` response listener before navigation, waits for that sync ID's
IndexedDB rows to drain, awaits the new view's current sync manager and its own
`ready` replay, and verifies the expected number of successful matching
responses. Do not make ordinary `User.go()` or view initialization await this
background work; normal application startup intentionally remains non-blocking.

Deliberate non-success responses are a different contract: retain a raw
Playwright response wait and assert the expected status/body explicitly.

### Manual HTTP contracts

Use a direct `requests` or Playwright request-context call only when HTTP is
the behavior under test: forged authorization, validators such as ETag/304,
byte ranges, signed/provider URLs, or cross-entity not-found boundaries. When
the application can perform the request, trigger it through the visible UI or
a real browser lifecycle and inspect the resulting browser response instead.
A direct forged request may supplement that story when the browser correctly
hides the forbidden action.

A retained direct request must assert more than its status. Check the relevant
content type and response schema or body, plus protocol headers such as ETag,
`Content-Range`, `Content-Length`, cache policy, redirects, or error metadata.
Use `assert_lagniappe_error_response()` for direct Lagniappe 403/404 responses;
it verifies the common HTML error envelope and absence of an entity-revision
acknowledgement. Provider errors should validate their provider-specific JSON
or XML shape.

For a forged mutation, use a unique attempted value and compare the relevant
entity, revision/history, notification, and asset state before and after the
request. Reload or navigate again when the unchanged state is visible in the
product. Authenticate manual requests from the real browser context, include
the current CSRF token for mutations, set a finite timeout, and disable
redirect following when a redirect would hide the contract being asserted.

### Polling and reconciliation waits

Use `expect_poll_result()` when an E2E story needs to observe the polling
protocol. Give it the exact subscription ID (for example,
`view:entity:<key>`, `edit:<key>`, or `document:<sync-id>`) and put the public
lifecycle action inside the context:

```python
with browser_failures.expect_offline(user):
    user.offline = True

# Arrange the external committed change while this browser is offline.
with expect_poll_result(
    user.page,
    subscription_id=f"view:entity:{project.key}",
):
    user.offline = False
```

The helper only observes and validates a successful natural `POST /l/poll`; it
does not invoke the polling coordinator. Prefer a visible tab change, a
collaborator save, or a native offline/online transition for E2E stories. Keep
ordinary-cadence waits deliberate and rare because they add real wall-clock
time. Never call a view's polling/sync manager, watcher check, private refresh
method, reconciliation method, or private task promise from an E2E test. Put
low-level state-machine and DOM reconciliation permutations in the JavaScript
suite.

### Browser conditions and deterministic time

Wait on the boundary that owns asynchronous completion. Use a precise network
response plus a retrying visible assertion for browser workflows. When the
condition lives only in browser state, such as an IndexedDB offline queue, use
a shared `page.wait_for_function()` helper that reports the expected condition
and the final observed state. Scope queue waits to the mutation record ID or
document sync ID created by the story; an all-store `exact=0` assertion can be
invalid when a reused browser context contains unrelated durable work. Headless
replay may use an explicit longer bound when it must load and reconcile an
editor before sending. A storage read failure must remain a failed condition,
not masquerade as an empty queue. Do not build Python `monotonic()`/`sleep()`
loops or call `wait_for_timeout()` to let the application settle.

Use native Playwright lifecycle changes for offline/online behavior. Headless
Chromium does not reliably emit a real window focus transition when pages are
brought to the front, so exact focus/blur listener plumbing belongs in the
JavaScript suite; E2E should use another public lifecycle action such as reload,
navigation, or reconnect. Never pair a native connectivity change with a
manually dispatched copy of the same event.

For expiration behavior, create an already-expired artifact or control the
clock used to issue it. A fixed sleep is appropriate only when elapsed latency
is itself the visible contract, such as proving a loading state paints while a
request is deliberately held.

### Retrying browser assertions

Playwright locator getters such as `count()`, `all()`, `inner_text()`, and
`get_attribute()` return an immediate DOM snapshot. Do not use those snapshots
as the final evidence for browser state that may still reconcile. Express the
condition with `expect(locator)` so a failure reports the named unmet state:

```python
expect(results).to_have_text(["First", "Second", "Third"])
expect(item).to_have_attribute("data-key", re.compile(r"\S+"))
key = item.get_attribute("data-key")
```

List-valued text expectations assert order and exact cardinality together.
When the product contract is only a lower bound, retry on the last required
item, such as `expect(options.nth(3)).to_be_visible()` for at least four
options, rather than snapshotting `count()`. For a JSON-valued attribute, first
expect the attribute to be present or match its stable content, then read and
parse it for supplementary structural assertions.

Raw reads remain appropriate for transporting a durable identifier after its
attribute expectation, capturing an already-settled baseline for a later
retrying comparison, or choosing an idempotent setup branch that ends in an
exact retrying postcondition. They are not a substitute for the browser-visible
assertion.

### Direct backend writes in E2E

Direct creates and saves are allowed only when they are either an isolated
precondition or supplementary backend verification. When reviewing a test,
ask whether each direct write is setup, supporting persistence evidence, or a
shortcut around the behavior the test claims. No special annotation is
required; add an ordinary explanatory comment only when the purpose is not
clear from the test.

Give exact lifecycle stories a dedicated entity, and establish shared
prerequisites idempotently against the current datastore. Backend reads may
supplement the claim, but a browser workflow still needs primary visible
evidence and a reload, navigation, reconnect, or fresh browser context when it
claims persistence.

Replace convenience mutations with the visible action or a separate browser
actor. In particular, do not complete/uncomplete a task, edit another user's
visible state, or inject page/form content directly when that mutation is part
of the story.

The accumulated E2E datastore intentionally resembles a living system. Reuse
named users and entities when the story only needs them to exist, and establish
the relevant precondition idempotently each time instead of assuming an earlier
test performed one exact mutation. Select anything created by a test using its
returned durable key, not matching text or list position; older records with
similar content are valid accumulated data. Use a unique entity when the test
asserts an exact mutation lifecycle, such as empty-to-populated, active-to-
completed, rename, reassignment, or deletion. Do not broadly clean shared data
to make a test isolated: isolate its claimed transition while preserving the
suite's realistic history.

Process-local "already seeded" booleans are not valid E2E state. They can
disagree with the datastore after a focused rerun, fixture reset, or failed
setup. A setup helper should retrieve or create its durable entities on every
call and conditionally establish only the properties the current story needs.

### Browser storage and persistence

`get_user` creates an isolated browser context for each test; preference state
written by an earlier test context is not reused. Treat that fresh context as
the baseline for ordinary table, settings, and navigation stories. Do not use
`page.evaluate()` or `page.wait_for_function()` to inject, remove, or wait on a
`localStorage` or `sessionStorage` key merely to force setup.

When a workflow needs a non-default preference, establish it through the
visible control that owns it. Assert the immediate UI result, then navigate or
reload and assert the restored UI when persistence is the claim. Use a product
reset/clear control when the same story must return to defaults. Remove reloads
whose only purpose was to apply a private storage deletion, but retain reloads
that are the public persistence boundary under test.

Exact key/value lifecycle belongs in the JavaScript suite when it is a durable
frontend contract. Such a test should name the key, cover save/load/clear as
applicable, and prove the resulting component state. Keep E2E coverage focused
on what the user sees rather than the storage mechanism that produced it.

Permission and session changes that request client-cache invalidation need an
explicit browser acknowledgement in the test that caused them:

- use a dedicated user definition instead of mutating a shared suite identity;
- prefer initial groups or access tiers in `testing/definitions/` when the
  mutation itself is not under test;
- when the mutation is under test, navigate as the affected user and observe
  the service worker's `POST /l/validate-user` response with a browser-context
  response event;
- assert the response accepted the cache-clear confirmation and the persisted
  `invalidate_cache` flag is false before the test ends.

Do not clear `invalidate_cache` directly from an E2E fixture or support helper.
That bypasses the session cookie and service-worker protocol, can leave a stale
client invalidation request behind, and moves the resulting failure into an
unrelated later test. Service-worker requests are not reliably visible through
a page-level response listener, so use `user.page.context.expect_event(...)`
for this acknowledgement.

Use real pytest paths or nodeids for focused `run.py test` commands. The runner
expands only suite aliases such as `unit`, `e2e`, `js`, `tooling`, and `setup`.

Numeric test filename prefixes are organizational, not runner aliases. The
number groups a broad workflow in a stable browsing order; an optional letter
identifies a smaller story within that workflow. In E2E, this also makes the
intentional seed/state progression visible when the full suite runs
sequentially. Always invoke the real path even when discussing a test by its
short prefix.

It is okay, and usually preferred, to add a definition, element helper, or
resource method while filling in a test. The goal is not to avoid helpers; the
goal is to put repeated meaning in the layer that owns it.

### Definitions, Resources, Elements

Use `testing/definitions/` for named test data and scenarios. Definitions
describe what exists or should be created: users, projects, pages, categories,
forms, upload files, schema fields, permissions, and other reusable fixtures or
scenario variants. They should be easy for tests to name without rebuilding the
same payload inline.

Files named `*_definitions.py` own dataclasses, payload builders, or related
definition families. A companion plural module may expose enums whose members
give those definitions stable scenario names. These data enums are distinct
from resource classes/enums: resources own navigation, selectors, and browser
interaction with the application.

Use `testing/elements/` for reusable UI component behavior. Elements own the
details of browser and JavaScript interaction: spinner buttons, tabs, modals,
dropdowns, lists, tables, comboboxes, upload controls, hover-only controls,
disabled/loading states, and other widgets. If every test that clicks a create
button also needs to prove the spinner, disabled state, or success transition,
put that check in the element helper rather than repeating it in each test.

Use `testing/resources/` for reusable page and entity flows. Resources generally
correspond to real application pages, routes, entities, or stable page sections.
They own selectors and methods such as creating an entity, opening a tab,
opening a particular form, navigating to a page, selecting an attached form, or
finding a row for a known definition. Resource methods should compose
definitions and elements so tests can stay at the story level.

As a rule of thumb:

- add a definition when a test needs named data, a reusable scenario, or a
  payload that should be shared across files;
- add an element when the behavior is a reusable widget interaction or visual
  state;
- add a resource method when the behavior is a reusable page/entity action;
- keep one-off business assertions in the test when extracting them would hide
  the story.

Avoid hiding the important assertion. A helper should make the story clearer,
not turn the test into a list of mysterious verbs.

## Unit Test Shape

Unit tests should cover deterministic backend behavior:

- entity/property transformations;
- condition/filter/permission logic;
- serialization and payload builders;
- setup validators and provider request construction under mocks.

Avoid importing the full Flask app, starting the server, or relying on browser
state. If the behavior depends on routes, Redis-backed UI state, or frontend
event plumbing, it probably belongs in E2E.

Unit tests should not import `lagniappe.web` or route modules. If route logic is
pure enough for unit coverage, move that logic into `lagniappe.core` first and
test the core helper there.

### Unit Current User

Unit entity fixtures use `CONFIG.TEST_CURRENT_USER` as the ambient authenticated
user. Prefer calling `entity.to_ai()` and `entity.to_filter_index()` without a
user argument unless the test is specifically proving behavior for a second
identity. For those cases, create an explicit `TestUser` or test entity user and
pass it with `user=...`.

Do not attach ad hoc `test_user` attributes to entities. Permission behavior
should go through the real `allowed()` / `has_permission()` path, even when the
entity itself was created with `testing=True`.

For focused debugging, use config or environment flags:

```bash
DEBUG_TRACING=1 venv/bin/python run.py test unit --tb=short
venv/bin/python run.py test --strict unit --tb=short
```

## Tooling Test Shape

Tooling tests belong in `testing/tests_tooling/` and use
`@pytest.mark.tooling`. They should not inherit E2E server setup or unit-suite
entity/cache cleanup unless they explicitly need it.

Good candidates:

- setup/config smoke checks;
- report parser/classification tests;
- repository-health checks;
- read-only provider/API drift probes that skip cleanly when unavailable.

Tooling tests must not import `lagniappe.core` or `lagniappe.web`, or execute
Node. Core application behavior belongs in unit tests, route and browser
integration belongs in E2E, and isolated frontend behavior belongs in the
JavaScript suite.

## JavaScript Test Shape

JavaScript behavior tests belong in `testing/tests_js/` and use
`@pytest.mark.js`. They execute source modules in Node without starting Flask or
a browser. Use the shared `run_node` fixture for executable discovery, working
directory, timeouts, and subprocess failure reporting. Keep behavior-specific
VM contexts and small browser-platform fakes in the focused test module.

If the assertion depends on layout, browser event propagation, rendered Jinja,
route responses, or a realistic DOM, use E2E instead.

## Annotations

Use annotations as a roadmap, not as fake coverage.

Source symbols in inventoried paths should eventually have one of:

```python
# @testable true
# @tests tests_unit/test_example.py::test_behavior
# @features submission number-input
# @dimensions readonly formatting
```

```python
# @testable false
# @covered-by lagniappe/core/properties/home.py
# @reason helper-owned-by-property
```

For base architecture or infrastructure symbols:

```python
# @testable infrastructure
```

For tests:

```python
# @features projects
# @dimensions create-manual search
# @template home/projects.html::create
# @todo add attributes check
# Review note: consider extracting repeated info-tab setup into Project.open_info().
def test_create_project_manual_mode(get_user):
    ...
```

`@features` and `@dimensions` imply their full cross-product. When a test or
source owns only selected combinations, use repeated exact tags instead:

```python
# @pair projects:create-manual
# @pair search:project-result
```

Features should be broad product areas. Dimensions should be reusable aspects
of those features. The `feature:dimension` pair should tell a future reader what
behavior to look for.

`@suggestion` is not a supported tag because an untracked annotation looks more
durable than it is. Use an ordinary comment for readability or helper ideas.
Use `@todo` when a concrete missing behavior should remain visible in
traceability reports.

## Gaps

If referenced tests mostly cover the behavior but miss a small edge case, add a
test `@todo`.

If the gap is major:

1. Add a focused new dimension to the source.
2. Add an `@pytest.mark.unfinished` test stub with matching `@features`,
   `@dimensions`, and `@todo`.
3. Do not reference the stub from source until it has real assertions unless
   unfinished coverage is the clearest signal.

Do not tag a test just because it executes code on the way to another outcome.
Prefer moving helper symbols to `@covered-by` when a more load-bearing symbol
owns the behavior.

## Browser Review While Writing E2E

Use [REPORTS_BROWSER_REVIEW.md](REPORTS_BROWSER_REVIEW.md) (`@REPORTS_BROWSER_REVIEW`) when tests,
stubs, or helper code describe a story that should be inspected in the real UI.
This is useful when you want an agent to recreate the flows in a folder, compare
the rendered experience to the tests, and write a curated browser review with
product feedback and important coverage recommendations.

Typical prompt shape:

```text
Read @REPORTS_BROWSER_REVIEW and review testing/tests_e2e/004_projects/.
Start the test server, log in as admin, recreate the user stories covered by
these tests, and write a browser review that includes UX/source feedback plus
important missing, brittle, or over-specified coverage you notice.
If you make test changes, add @todo comments or unfinished test
stubs in the relevant test file and mention those changes in the report.
```

The browser report should stay curated. Product findings can cover hierarchy,
readability, affordances, visual bugs, confusing states, and concrete UI/source
suggestions. Coverage findings should name the focused test file or folder and
stay limited to important user-visible risks. Durable test-maintenance backlog
belongs close to the tests themselves:

- add `@todo` to an existing test for known missing coverage;
- add an ordinary review comment for a possible test/helper improvement;
- add an `@pytest.mark.unfinished` stub when the missing story deserves its own
  future test.

## Template Contracts

Use `@template path.html::macro` on UI/E2E tests when the template skeleton is
part of the contract under test. The reporter extracts `lp-*` and `data-*`
attributes, checks obvious frontend handlers, and shows which tests touched
which selectors.

For `lp-create` and `lp-update`, the reporter also counts
`SpinnerButtons.CREATE.click(...)`, `SpinnerButtons.UPDATE.click(...)`, and
uniquely resolved helper methods that call them.

## Before Finishing

Run the narrowest useful test command, then the relevant report:

```bash
venv/bin/python run.py test path/to/test_file.py
venv/bin/python run.py traceability --changed --check
venv/bin/python run.py template-contracts test_file.py
```

If you changed commands, annotation conventions, test layout, setup behavior, or
agent-facing workflow, update `documentation/`.
