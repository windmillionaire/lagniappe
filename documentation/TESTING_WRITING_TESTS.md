# Testing Writing Tests

Use this guide when adding or reshaping tests. For a systematic review of an
existing test, also read [TESTING_TEST_REVIEW.md](TESTING_TEST_REVIEW.md).
Commands and suite setup live in [TESTING.md](TESTING.md).

## Start With the Smallest Faithful Layer

Read the source owner, nearby tests, and relevant architecture documentation
before writing a test. Then choose the cheapest layer that can faithfully prove
the behavior.

| Layer | Use it for |
| --- | --- |
| Unit | Deterministic backend entities, properties, permissions, validation, retries, and service logic without a live app server. |
| JavaScript | Frontend module behavior that can run in Node with small platform fakes and does not require a real DOM or server. |
| E2E | User workflows or browser lifecycle behavior that requires a real browser/server boundary, DOM, routing, storage, rendering, or multi-user interaction. |
| Tooling | Setup/config smoke tests, repository health, reporters, and runner behavior. Tooling tests must not import `lagniappe.core` or `lagniappe.web`, or execute Node. |

Do not keep procedural coverage in E2E merely because an E2E test can reach it.
Parsing, ordering, idempotence, queue deletion, retry classification, and
similar mechanics normally belong in unit or JavaScript tests. Let E2E prove
the visible or persisted result that depends on those mechanics.

## Write a Thin E2E Story

An E2E test should read as one user story:

1. Arrange only the state needed by the story.
2. Perform the real user action.
3. Observe the exact causal boundary when one is needed.
4. Assert the final visible or persisted outcome.

Prefer durable accessible roles, labels, and `data-role` or `data-widget`
contracts. Avoid generated IDs, transient child nodes, CSS decoration, private
component fields, and unqualified `first` or `last` locators.

Use `User.go()` for ordinary setup navigation. It checks the navigation status,
resets offline/mobile state, and waits for an initialized authenticated view
when the resource requires one. Navigate by a real link, history action, or
native browser control only when that navigation behavior is part of the story.

Keep helpers at the lowest reusable level:

| Scope | Location |
| --- | --- |
| One story | The test function |
| One file or feature | The test module or its definition helper |
| Reusable UI operation | `testing/elements/` or `testing/resources/` |
| Reusable E2E protocol/lifecycle boundary | `testing/utility/` |

Do not hide the outcome assertion inside a broad helper. A reader should be
able to see what behavior makes the test pass.

E2E sessions share a managed server and fixed test namespace. Never run E2E
pytest, `test-server`, or `browser-review` sessions in parallel. Put multiple
focused nodeids in one pytest invocation.

## Synchronize on the Cause, Assert the Outcome

Playwright locator assertions retry, so a visible-state expectation is usually
the best final assertion. It is not always a sufficient synchronization
boundary.

Retain the exact response, poll, replay, replacement, transition, or service
worker acknowledgement when either of these is true:

- the pre-action DOM could already satisfy the final visual assertion; or
- the action replaces or reconciles the nodes being observed.

For a normal mutation, match the request narrowly and then assert the UI:

```python
with expect_successful_response(
    user.page,
    method="POST",
    path="/l/pages/update",
    entity_key=page.key,
):
    update_button.click()

expect(user.locate("[data-role='saved-status']")).to_have_text("Saved")
```

The response is a transport boundary, not proof that DOM reconciliation has
finished. When an action replaces a widget, re-locate it from a durable root
after the boundary before asserting or interacting again:

```python
with expect_successful_response(user.page, method="POST", path="/l/update"):
    old_form.get_by_role("button", name="Save").click()

current_form = user.locate("[data-role='editor']")
expect(current_form.get_by_label("Status")).to_have_value("Complete")
```

For an ordinary same-page transition where old DOM cannot falsely satisfy the
assertion, use a locator expectation directly. Do not add background waits as a
ritual.

### Cross-document interaction readiness

`SiteResource.wait_for_interaction_readiness()` is a targeted boundary for an
authenticated, same-origin cross-document navigation whose startup transition
or deferred services can temporarily block pointer input. Call it after the
native link or history navigation and before the first interaction:

```python
link.click()
destination.wait_for_interaction_readiness()
user.locate("[data-role='action']").click()
```

It is intentionally not part of `User.go()`. Most direct setup navigations need
only view initialization, later same-page transitions should use their own
visible/workflow boundary, and public pages do not load the authenticated
bundle or its readiness markers. Never call this helper on a public page.

Some cold-loaded controls expose their portal before asynchronous activation
has finished replacing its options. If the component publishes `aria-busy`,
wait for that public contract to clear and then re-query the option or control.

### Polling, offline replay, and service workers

Use `expect_poll_result()` to observe a natural `/l/poll` result for one exact
subscription. Do not inspect private manager state or poll application entities
from Python while waiting for a browser workflow.

Use `expect_offline_sync_replay()` when reconnect/reload must replay a specific
persisted mutation. Match the sync identity and request content, then assert the
fresh visible or persisted result. Queue internals and replay idempotence belong
in JavaScript tests unless the browser lifecycle is the behavior under test.

When user/session changes set `invalidate_cache`, arm a `page.context` response
wait for the service worker's exact `POST /l/validate-user` acknowledgement
before the navigation that consumes it. Assert `cacheCleared` before checking
that the persisted flag is false. A page-scoped wait can be lost across the new
document that performs this acknowledgement.

### Time and browser conditions

Use Playwright expectations and product-visible readiness contracts. Do not use
`time.sleep()`, `page.wait_for_timeout()`, arbitrary cooldowns, or enlarged
timeouts to cover an unexplained race. A longer timeout is appropriate only
when the product operation itself has a known longer budget, such as a real
provider call.

Capture one-time values only after the relevant state has settled. Prefer
`expect(locator).to_have_text(...)` or `to_have_attribute(...)` to immediate
`inner_text()`, `is_visible()`, or attribute snapshots.

Use `user.offline`, the clock helpers, and real browser input capabilities to
create browser conditions. Changing viewport size does not create touch input;
request `get_user(..., has_touch=True)` and use `tap()` when touch behavior is
the story. Do not dispatch synthetic events as a substitute for user input.

## Own State and Cleanup

Each test must leave shared runtime state safe for the next sequential test.
Suite teardown is a final safety net, not a substitute for restoring state
before another test runs.

- Give created users, entities, files, tasks, provider resources, and other
  mutable objects unique identities.
- Make shared prerequisites idempotent; do not rely on a prior test having run.
- Do not assert collection-wide counts or ordering when the story only owns one
  item.
- Do not clear an entire datastore kind, cache, queue, bucket prefix, or browser
  store to remove one test's data.
- Restore global settings, provider configuration, roles, and identities in a
  `finally` block through the production mutation path where practical.
- Delete only the exact Redis/cache keys, Cloud Tasks, provider objects, or
  storage objects the test created.
- Use a dedicated identity for administrative, permission, or authentication
  mutation stories so restoration failures cannot weaken a common fixture.

If the visible workflow mutates browser storage, arrange and clean it through
the same UI or browser lifecycle. Use the existing narrowly scoped offline
helpers when storage itself is the lifecycle boundary; do not manipulate
`localStorage` or IndexedDB directly from an E2E story.

Direct backend writes are appropriate for arranging prerequisites that the
story does not claim to create. They are not appropriate when they bypass the
route, permission, validation, queue, or UI behavior named by the test.

## Network and Expected Browser Failures

Use `expect_successful_response()` for ordinary successful browser requests.
Match method, parsed path, entity/query identity, and request payload when
needed so unrelated background traffic cannot satisfy the wait. For an
intentional non-success contract, use a narrowly matched raw Playwright
response expectation and assert its exact status.

Use direct HTTP requests only when the protocol itself is under test, such as
forgery protection or malformed payload handling. Carry the browser's cookies
and CSRF token, set a finite timeout, and keep a final user-visible assertion
when the test claims a browser story.

The E2E browser failure guard fails tests on unaccounted console errors,
`pageerror` events, and failed requests. If failure is intentional, scope its
exact method/path/message with `browser_failures.expect(...)` or use
`browser_failures.expect_offline(user)`. Never add a broad global ignore.

Use `scoped_browser_route()` for request interception. It always removes the
route in `finally`; an unscoped route can leak into later actions in the same
browser context.

## Targeted Hosted Production Flows

Most E2E tests should remain deterministic and inexpensive. Add a small number
of hosted production-flow contracts when a local adapter cannot prove a
material boundary such as App Engine routing, Cloud Tasks OIDC delivery,
Identity Platform authentication, or a live AI provider response.

For deferred jobs, keep the same visible story in both environments. The local
path can use the deterministic adapter; a `CONFIG.hosted_e2e_runner` branch can
use `dispatch_hosted_deferred_job()` to send the persisted job through Cloud
Tasks and the deployed worker. The helper restores task-queue configuration and
deletes the exact tasks it created, but the test still owns its entity, setting,
provider, and user cleanup.

Mark live AI stories `@pytest.mark.ai`, keep prompts narrow, and require an
exactly verifiable visible result. Real calls and their cost are justified when
they prove provider/tool/context or deferred-delivery integration that mocks
cannot.

Treat “Model returned no text content” as a diagnostic, not automatically as a
model failure. Inspect the provider attempt record, supplied context, tool
arguments/results, response format/schema, and raw safe diagnostics before
changing retries or timeouts. An empty response can expose a prompt, context,
tool, or response-parsing defect.

Hosted jobs must restore shared provider settings and delete created provider
resources in `finally`. On failure, retain privacy-bounded attempt diagnostics
and the exact App Engine version/time window so logs can distinguish provider
latency, worker rejection, and stale browser assertions.

See [TESTING_HOSTED_E2E.md](TESTING_HOSTED_E2E.md) for lifecycle and evidence
commands.

## Definitions, Resources, and Elements

- Definitions hold durable test data and expected values.
- Resources represent pages or domain objects and expose meaningful user
  operations.
- Elements wrap reusable DOM components and their public interaction contract.

Add an abstraction only when it names a stable concept or removes meaningful
duplication. Do not build a second testing API around a one-off selector.

## Other Test Layers

Unit tests belong in `testing/tests_unit/` and should isolate only true external
boundaries. Prefer real domain objects over deep mocks. Use the project current-
user fixture rather than patching unrelated authentication internals.

JavaScript tests belong in `testing/tests_js/`. Use them for deterministic
frontend algorithms, serialization, sync/replay mechanics, and module behavior
that does not need a browser. If a behavior depends on layout, focus, selection,
history, storage lifecycle, or real DOM events, keep the corresponding story in
E2E.

Tooling tests belong in `testing/tests_tooling/`. They test the repository and
runner without importing `lagniappe.core` or `lagniappe.web` and without
executing Node.

## Traceability and Template Contracts

Use supported `@matrix`, exact `@pair`, `@source`, `@template`, and `@todo`
tags as evidence, not decoration. A test should claim only behavior that its
assertions prove. Follow
[TESTING_TRACEABILITY_TOOL.md](TESTING_TRACEABILITY_TOOL.md) before adding or
changing source annotations, and [TESTING_SOURCE_REVIEW.md](TESTING_SOURCE_REVIEW.md)
when judging whether a test really covers a source symbol.

Use `@template path.html::macro` when a template's DOM skeleton is part of the
test contract. Run the template-contract reporter after changing tagged UI
tests or their templates. Use
[TESTING_BROWSER_REVIEW.md](TESTING_BROWSER_REVIEW.md) when the story also needs
human/agent inspection of the rendered experience.

## Before Finishing

Start with a real focused pytest path or nodeid, then expand only as far as the
change warrants:

```bash
venv/bin/python run.py test testing/tests_e2e/003_forms/test_003b_form_builder.py::test_preview_panel
venv/bin/python run.py test testing/tests_e2e/003_forms/test_003b_form_builder.py
venv/bin/python run.py traceability --changed --check
venv/bin/python run.py template-contracts --changed --check
```

Run broad E2E only when the change genuinely requires it. If commands, suite
layout, annotations, setup behavior, or test-writing workflow changed, update
the relevant documentation in the same change.
