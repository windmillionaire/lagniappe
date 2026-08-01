# TODO: E2E Hardening

This document is an execution backlog for making the browser suite more
trustworthy, deterministic, and representative of real user behavior. It was
created after a read-only audit of `testing/tests_e2e/` on 2026-08-01.

The audit found useful coverage throughout the suite. The goal is not to force
every setup operation through the UI or ban all JavaScript and direct HTTP.
The goal is to make each test fail for the behavior named by the test, with as
little dependence as possible on shared state, private implementation details,
or test-only shortcuts.

## How to use this backlog

Work through one checklist item or one small file cluster at a time. Keep each
change reviewable; this is not intended to become a suite-wide mechanical
rewrite.

Before changing a test, read:

- [TESTING_WRITING_TESTS.md](TESTING_WRITING_TESTS.md)
- [TESTING_TEST_REVIEW.md](TESTING_TEST_REVIEW.md)
- [TESTING_SOURCE_REVIEW.md](TESTING_SOURCE_REVIEW.md) when changing source
  annotations or deciding whether a test actually covers an annotated symbol
- [SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md) before changing polling,
  offline replay, `EditWatcher`, or collaborative state tests
- [FRONTEND_VIEWS.md](FRONTEND_VIEWS.md) before changing view/component
  reconciliation tests

Use focused real paths or nodeids while iterating, for example:

```text
venv/bin/python run.py test testing/tests_e2e/007_categories/test_007a_category_index.py::test_name
```

Do not run E2E sessions in parallel against the managed testing server. After
a focused test passes, run its file and then the smallest related cluster.
Run the full E2E suite only when the accumulated changes justify it.

## Decision rules

Use these rules before modifying a candidate:

1. **Test behavior through the public boundary that owns it.** A user workflow
   belongs in browser E2E; a JavaScript component state machine belongs in the
   JS suite; pure backend logic belongs in the unit suite; an authorization or
   HTTP protocol contract may appropriately use a direct request.
2. **Setup is not the assertion.** Direct entity creation is acceptable for an
   isolated precondition when entity creation is not the behavior under test.
   It is not a substitute for performing the claimed action through the UI.
3. **Prefer real triggers.** Navigation, focus, reconnect, collaborator edits,
   viewport changes, and form submission should use browser-visible actions
   when practical. Calling `_lp_view`, `EditWatcher`, or reconciliation methods
   directly makes an E2E test sensitive to implementation structure.
4. **Assert both transport and outcome when useful.** A response wait should
   identify the intended request and verify success; a retrying browser
   assertion should then verify the visible result. Reload or use a fresh
   browser context when persistence or cache invalidation is part of the claim.
5. **Use dedicated mutable state.** A test that mutates permissions, cache
   invalidation, completion state, visibility, or filters should not reuse an
   identity or entity whose later state matters to another test.
6. **Do not hide product defects in fixtures.** If the public workflow cannot
   produce or observe the expected state, record the product gap instead of
   clearing it with a server-side save, DOM fabrication, or a global error
   allowlist.

Direct JavaScript, backend setup, and HTTP requests are not inherently weak.
They need to be intentional and at the correct testing boundary.

Unless a path starts with `testing/`, candidate test paths below are relative
to `testing/tests_e2e/`.

## Audit snapshot

These counts are search signals, not automatic defects:

| Signal | Audit count |
|---|---:|
| E2E Python files | 76 |
| `page.evaluate()` calls | 112 across 35 files |
| In-page `fetch` calls or overrides | 16 |
| Private `_lp_view`, `_lp_widget`, or `_lp_component` access | 25 |
| Direct local/session storage access | 20 |
| Synthetic event dispatches | 8 |
| Explicit sleep or fixed-timeout waits | 4 |
| Monkeypatch mentions | 113 across 13 files |
| `__wrapped__` route calls | 25 |
| `expect_response` waits | 174 |
| Direct `Entities.<Type>.create(...)` setup | 79 |
| Direct `Entities.save(...)` setup | 36 |
| Files using `requests` or `context.request` | 9 |

The recent cache-invalidation failure is the clearest example of why this work
matters: a shared user retained invalidation state, and a fixture-side repair
could conceal whether normal navigation actually invoked `/verify-user`.
Cache-invalidation tests should use a dedicated user, cause invalidation through
the behavior under test, then navigate through the UI and explicitly observe
verification. Do not reintroduce a fixture helper that silently repairs the
user or cookie.

## Priority 0: eliminate cross-test and harness blind spots

These items have suite-wide blast radius and can turn unrelated tests into
timing or ordering failures.

### E2E-H01 — Isolate every test that mutates durable shared state

- [ ] Inventory tests that mutate user permissions, cache invalidation,
  completion state, visibility, shared filters, or shared definitions.
- [ ] Give each mutating story a dedicated user/entity definition or an
  idempotent fixture whose entire lifecycle belongs to that story.
- [ ] Remove module-level "already seeded" flags where their truth can outlive
  or disagree with datastore state.
- [ ] For each repaired cluster, run the affected tests individually, in file
  order, and in reverse order where practical.

Start with:

- `testing/tests_e2e/007_categories/test_007b_category_filters.py` —
  `_CATEGORY_FILTER_CONTEXT_READY`
- `testing/tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py`
  — `_SORT_PAGES_SEEDED`
- `testing/tests_e2e/006_tasks/test_006d_task_permissions.py` — the shared
  `Tasks.test_view_only_page_task` is read and later completed
- all permission and cache-invalidation stories, including the user/settings
  changes that prompted this audit

Acceptance criteria:

- A test can be rerun immediately without inheriting its prior mutation.
- Reversing two tests in a repaired cluster does not change their outcome.
- No fixture changes an invalidation or permission flag merely to make the next
  test start clean.
- Cache verification is observed through a real browser navigation and the
  relevant `/verify-user` request, not inferred from a backend save.

### E2E-H02 — Make unexpected browser failures first-class test failures

- [ ] Extend the E2E page instrumentation to collect console errors,
  uncaught `pageerror` events, and failed requests.
- [ ] First run the collector in diagnostic mode to classify current noise.
- [ ] Add narrowly scoped expectations for tests that deliberately cause
  network failures, offline behavior, or browser errors.
- [ ] Once classified, fail teardown on any unexpected event.

Current gap: `testing/tests_e2e/conftest.py` records console messages but
generally prints them only after another assertion has already failed. Failed
requests are not a universal failure, and `pageerror` is only asserted in an
isolated page-tabs test.

Implementation notes:

- Prefer a small scoped context manager/fixture for expected errors over global
  substring ignores.
- Match an expected error by the narrowest stable attributes available: request
  method and path, exception type/message, and count.
- An expected-error scope should fail if the expected error never happens or
  happens more often than intended.
- Offline tests will need explicit request-failure expectations; ordinary tests
  should not inherit them.

Acceptance criteria:

- A deliberately introduced unhandled browser exception fails an ordinary E2E
  test.
- A deliberate offline failure passes only inside its explicit expectation.
- Teardown reports the originating URL/request and enough detail to diagnose
  the event.

### E2E-H03 — Establish a strong shared network-wait contract

- [ ] Add or standardize a helper that matches the intended method and
  endpoint, checks `response.ok`/status, and can optionally validate the entity
  key or request/response payload.
- [ ] Convert the broadest `"**/update"` and `"**/create"` waits first.
- [ ] Pair the response assertion with a retrying visible postcondition.

Good first clusters because they contain many response waits:

- `testing/tests_e2e/006_tasks/test_006b_page_tasks.py`
- `testing/tests_e2e/007_categories/test_007a_category_index.py`
- `testing/tests_e2e/005_pages/test_005a_page_tabs.py`
- `testing/tests_e2e/002_home/test_002j_home_tools.py`

Do not mechanically replace all 174 occurrences. Some endpoint patterns are
already precise; inspect the action and payload before choosing a matcher.

Acceptance criteria:

- The wait cannot be satisfied by an unrelated concurrent create/update.
- A 4xx/5xx response fails at the transport assertion with a useful message.
- The test also proves the visible state, and reloads or opens a fresh context
  when persisted state is part of the contract.

## Priority 1: restore public behavior to user-journey tests

These tests often exercise valuable behavior, but currently force the desired
state through implementation-private controls.

### E2E-H04 — Replace private index refresh calls with real refresh triggers

- [ ] Review every `_lp_view.refresh(true)` call and identify the real product
  event it is standing in for.
- [ ] Use a second actor, real create/update, reconnect, focus/tab change, or
  natural polling to cause refresh.
- [ ] If the behavior is only the view's reconciliation algorithm, move the
  detailed cases to `testing/tests_js/` and retain one real E2E integration
  story.

Candidate files:

- `003_forms/test_003a_forms.py`
- `004_projects/test_004f_project_filters.py`
- `006_tasks/test_006c_task_index.py`
- `007_categories/test_007a_category_index.py`
- `007_categories/test_007b_category_filters.py`
- `008_users/test_008a_user_index.py`

Acceptance criteria:

- The E2E test never calls `_lp_view.refresh` directly.
- The visible update follows a public event that production users can cause.
- Any extracted JS test names the component contract rather than pretending to
  be a full user journey.

### E2E-H05 — Remove direct `EditWatcher`, sync, polling, and reconciliation control

- [ ] Replace direct `EditWatcher.check()`, `_lp_view.sync`,
  `PollingCoordinator.trigger`, and `_pollingReconcileTask` calls with the
  corresponding browser lifecycle event where possible.
- [ ] Move direct state-machine and DOM reconciliation cases into the JS suite.
- [ ] Keep one E2E story per important integration path: reconnect sync,
  collaborator edit, poll reconciliation, and offline replay.

High-value candidates:

- `004_projects/test_004b_info.py` — direct `EditWatcher.check()`
- `010_sync/test_010d_form_state_split.py` — direct sync, watcher, and polling
  calls
- `006_tasks/test_006b_page_tasks.py` — pauses the watcher, changes its
  fingerprint, and calls `_refreshCollectionComponents`; also invokes
  `postreconcile` after fabricating component state
- `004_projects/test_004d_document.py` — waits on a private polling task
- `011_files/test_011c_file_processing_reconciliation.py` — fabricates DOM and
  dataset state before reconciliation

Possible real triggers include switching between two pages/actors,
`bring_to_front`, browser offline/online transitions, a collaborator save, and
waiting for the application's normal poll. Confirm actual production behavior
in the frontend and sync documentation before choosing one.

Acceptance criteria:

- E2E assertions are driven by public browser lifecycle or user actions.
- Low-level reconciliation permutations live in JS tests.
- A reconnect produces the expected sync exactly once; the test does not both
  toggle connectivity and manually dispatch the same event unless duplicate
  handling is itself the target.

### E2E-H06 — Remove fabricated authorization and readonly DOM state

- [ ] Replace DOM attributes that manufacture permission state with a real user
  whose server-rendered permissions produce that state.
- [ ] Where a visual state has no public setup route, use isolated backend setup
  before navigation, not DOM mutation after rendering.

Start with
`testing/tests_e2e/007_categories/test_007a_category_index.py`, which sets
`#tools.dataset.readonly` and then treats the result as evidence for readonly
fields.

Acceptance criteria:

- The rendered page is readonly because of server/application state.
- The test asserts both unavailable editing controls and an attempted forbidden
  action where authorization behavior matters.
- No test claims permission coverage based solely on a client-side dataset or
  class mutation.

### E2E-H07 — Replace in-page `window.fetch` interception with browser routing

- [ ] Convert fetch replacement/wrapping to Playwright routing and request
  observation.
- [ ] Use actual browser offline mode for connectivity stories when it matches
  production behavior; use route abort/fulfill for a deliberately injected
  endpoint failure.
- [ ] Assert the application-visible reaction as well as the intercepted
  request.

Candidates:

- `005_pages/test_005g_page_document_ai.py`
- `005_pages/test_005f_page_image.py`
- `011_files/test_011a_file_tabs.py`
- `001_site/test_001d_offline.py`

Acceptance criteria:

- Native `fetch` remains intact.
- Request interception is installed and removed within the test's scope.
- Offline/error behavior is not implemented by monkeypatching application
  globals from `page.evaluate()`.

## Priority 2: put tests at the correct suite boundary

This improves readability and reduces E2E runtime, but should follow the
suite-wide isolation work unless a file is already being touched.

### E2E-H08 — Reclassify route functions invoked through `__wrapped__`

- [ ] Inventory E2E tests that call decorated Flask routes through
  `__wrapped__`, create bare request contexts, or monkeypatch route imports.
- [ ] For pure decision/transformation logic, extract a runtime-safe helper to
  `lagniappe/core/` and cover it in `testing/tests_unit/`.
- [ ] For an HTTP/route contract, exercise the actual managed server through
  browser navigation or an authenticated HTTP request.
- [ ] Keep full-browser coverage only when rendering or frontend behavior is
  part of the contract.

Initial candidates:

- `002_home/test_002n_file_consumer_routes.py`
- `008_users/test_008e_site_settings_routes.py`
- `008_users/test_008f_recovery_settings.py`
- `011_files/test_011d_asset_route_loading.py`
- pure/non-browser portions of `001_site/test_001c_error_reporting.py`
- early tests in `001_site/test_001f_edited_entities.py`
- pure portions of `010_sync/test_010d_form_state_split.py`

Important boundary constraint: unit tests may not solve this by importing
`lagniappe.web`. Extract pure logic when unit coverage is appropriate. Tooling
tests may import neither `lagniappe.web` nor `lagniappe.core`.

Acceptance criteria:

- A route test passes through Flask's real decorator/auth/error boundary.
- A unit test imports only the extracted non-web logic it owns.
- E2E files no longer act as a miscellaneous home for tests that need no live
  browser or server.

### E2E-H09 — Split AI adapter evaluation from full browser stories

- [ ] Review direct adapter calls and test request contexts in the home AI
  report/deferred-job tests.
- [ ] Move deterministic proposal/application and adapter contracts to unit
  coverage where possible.
- [ ] Retain focused E2E stories that start through the UI, observe the durable
  job lifecycle, and verify the visible applied result.

Candidate cluster:

- `002_home/test_002l_home_tools_ai.py`
- `002_home/test_002m_home_ask_ai.py`
- `002_home/test_002o_deferred_jobs.py`

Acceptance criteria:

- Deterministic backend branches are cheap, isolated unit tests.
- At least one browser story proves the actual UI-to-job-to-visible-result
  integration.
- A direct adapter invocation is not presented as evidence that the browser
  workflow works.

### E2E-H10 — Explicitly classify structural evidence tests

- [ ] Document/mark `test_999_structural_evidence.py` as instrumentation and
  structural-contract coverage rather than a user journey.
- [ ] Keep its monkeypatching where it is necessary to observe structural
  behavior, but do not use it to justify browser behavior that has no real E2E
  story.
- [ ] Check its source annotations under that classification.

Acceptance criteria:

- Reports and reviewers can distinguish structural evidence from live user
  behavior.
- Instrumentation-specific JavaScript is not copied into ordinary E2E tests.

## Priority 3: localized durability improvements

These are worthwhile, but most have less cross-suite impact and can be repaired
opportunistically by file cluster.

### E2E-H11 — Replace synthetic interaction and layout shortcuts

- [ ] Use a touch-capable browser context and Playwright touchscreen/coordinates
  for touch behavior instead of manually dispatching pointer events.
- [ ] Use a real viewport or naturally narrow container instead of assigning
  inline widths from JavaScript.
- [ ] Move low-level event-sequence contracts to JS tests when Playwright cannot
  express the relevant primitive accurately.

Candidates:

- `005_pages/test_005b_page_submissions.py` — hand-built touch/pointer sequence
- `006_tasks/test_006b_page_tasks.py` — inline `maxWidth` and fabricated DOM
  reconciliation state

Acceptance criteria:

- The browser generates the event sequence whenever the story claims real user
  input.
- Layout assertions are based on a supported viewport/component state.

### E2E-H12 — Replace storage surgery with user-visible reset or clean contexts

- [ ] Decide whether each local/session storage access is testing the storage
  contract or merely forcing setup.
- [ ] For setup, prefer a fresh context or the product's reset/clear UI.
- [ ] Keep direct storage access only when the key/value lifecycle is the
  explicit contract, and assert the corresponding visible behavior.

Candidate clusters include user settings, category mobile/index tests, task
index/history tests, form-index mobile tests, and page-tabs tests.

Acceptance criteria:

- Ordinary workflow tests do not pass only because they inject/remove a private
  storage key.
- Storage-contract tests identify the key as part of the durable public
  contract and also prove its UI consequence.

### E2E-H13 — Replace fixed waits and Python polling where event waits exist

- [ ] Consolidate offline replay polling on a retrying browser condition rather
  than a Python loop plus `wait_for_timeout(100)`.
- [ ] Prefer a visible history/network event over repeatedly querying Datastore.
- [ ] Test expiration with an already-expired artifact or controlled clock
  rather than sleeping for two seconds.
- [ ] Use real focus/online events where Playwright can produce them, and avoid
  manually dispatching a second copy.

Candidates:

- `010_sync/test_010c_offline_replay.py`
- `006_tasks/test_006f_task_history.py`
- `001_site/test_001g_setup_provider_contracts.py`
- focus/reconnect helpers in `001_site/test_001d_offline.py`

Direct `/poll` requests in `001_site/test_001f_edited_entities.py` and
`002_home/test_002o_deferred_jobs.py` may be correct when the poll protocol is
the explicit subject. A visible reconciliation story should normally let the
application perform its own poll.

Acceptance criteria:

- No repaired test depends on elapsed wall-clock time when an observable event
  or deterministic timestamp can express the condition.
- A timeout failure reports the unmet application condition.

### E2E-H14 — Tighten non-retrying browser assertions

- [ ] Replace raw `count()`, `all()`, `inner_text()`, and `get_attribute()`
  checks with Playwright `expect(...)` when the value may settle asynchronously.
- [ ] Prefer exact cardinality/text/attribute assertions over broad truthiness.

Initial examples:

- `004_projects/test_004h_document_history.py` — raw `count() >= 4`
- `003_forms/test_003a_forms.py` — `links.all()` followed by immediate text reads
- raw attribute assertions in `008_users/test_008c_user_settings.py` and
  `002_home/test_002j_home_tools.py`

Acceptance criteria:

- Assertions retry until their named condition or a useful timeout.
- Cardinality and text expectations are as exact as the product contract
  permits.

### E2E-H15 — Audit direct backend setup without banning it

- [ ] Review direct creates/saves when touching a file and label each use as
  isolated precondition, backend verification, or shortcut around the claimed
  behavior.
- [ ] Replace only the shortcut category with UI action or a separate actor.
- [ ] Ensure direct setup uses dedicated entities rather than shared mutable
  definitions.
- [ ] Keep browser-visible assertions as the primary evidence; backend reads
  may supplement them.

Reasonable direct setup includes otherwise unreachable failure records,
histories, pagination volumes, and content needed for a permission test when
content creation is not the subject. It is weak when a test claims that the UI
created or updated the same state that setup wrote directly.

Acceptance criteria:

- Every direct write has a clear setup or supplementary-verification purpose.
- The action named by the test is still performed at the public boundary.
- Persistence claims survive reload or a fresh browser context.

### E2E-H16 — Strengthen legitimate manual HTTP contract tests

- [ ] Keep direct HTTP for forged authorization attempts, ETag/304 behavior,
  Range requests, signed/provider URLs, and cross-entity 404 contracts.
- [ ] Assert status, response schema/content type/headers, and absence of
  forbidden side effects.
- [ ] Use the UI for actions that are available there; use the direct request as
  an additional adversarial assertion where appropriate.

Examples worth preserving as HTTP-level tests include authorization probes in
`006_tasks/test_006d_task_permissions.py`, ETag behavior in
`002_home/test_002i_home_activity.py`, and document history/range contracts in
`004_projects/test_004h_document_history.py`.

Acceptance criteria:

- A forbidden request proves no entity, revision, notification, or other side
  effect was produced.
- Protocol tests verify the relevant headers/body, not status alone.

## Suggested execution order

The priorities above are also the recommended dependency order:

1. **Foundation:** E2E-H01, then the diagnostic half of E2E-H02.
2. **Harness enforcement:** classify expected failures, enforce E2E-H02, and
   introduce E2E-H03 in one high-traffic file.
3. **Real triggers:** work through E2E-H04 to E2E-H07 one feature cluster at a
   time. Sync/offline files should be handled together enough to avoid creating
   competing helper conventions.
4. **Suite boundaries:** E2E-H08 to E2E-H10. Move only behavior whose ownership
   is clear; extraction may require source annotations and unit coverage.
5. **Opportunistic cleanup:** E2E-H11 to E2E-H16 while relevant files are open.

If only a few days are available, complete H01-H03 and one representative
private-refresh/sync cluster. Those changes should provide the largest
reliability gain and establish patterns for the remaining work.

## Definition of done for each converted test

A converted test should satisfy all applicable statements:

- [ ] It fails if the named public behavior is broken.
- [ ] It does not depend on state left by another test.
- [ ] Its mutable user/entities are dedicated or reset through the same public
  lifecycle the product uses.
- [ ] It does not invoke private frontend control paths unless that internal
  contract is explicitly the subject; those cases normally belong in JS tests.
- [ ] Network waits identify the intended request and assert success.
- [ ] Browser-visible assertions are retrying and as exact as practical.
- [ ] Persistence/cache claims are checked after reload or in a fresh context.
- [ ] Deliberate browser/network errors are narrowly expected; unexpected ones
  remain fatal.
- [ ] Direct HTTP or backend writes have a documented role and do not replace
  the claimed UI action.
- [ ] The focused nodeid, its file, and the smallest related cluster pass.
- [ ] `venv/bin/python run.py template-contracts` is run when `@template` tags
  or template contracts change.
- [ ] `venv/bin/python run.py traceability --changed --check` is run after
  moving/renaming annotated tests or changing inventoried source symbols.

## Handoff notes for agents

- Start by restating the behavior a test claims and identifying its public
  trigger. If that cannot be done, stop and classify the test before editing.
- Search the production frontend for the private method being called. Its
  callers usually reveal the browser event the E2E test should reproduce.
- Do not turn every direct request or entity factory into UI setup. Security and
  protocol tests need lower-level access, and large fixture setup is often more
  deterministic outside the UI.
- Do not add global sleeps, retries around the whole test, broad exception
  swallowing, or teardown repairs. Those reduce the diagnostic value of the
  suite.
- Do not solve expected browser errors with a repository-wide ignore list.
  Expectations should live beside the test that deliberately causes them.
- When moving coverage between suites, preserve or improve source annotations.
  A moved test should still be honest evidence for the referenced symbol.
- If the UI lacks a reliable way to trigger behavior that users depend on,
  treat that as a possible product defect. Do not silently retain a private
  test-only trigger just to keep the test green.
- Record completed item IDs and any intentional exceptions in this document so
  later work does not repeat the audit.

## Completion log

Add short entries here as items land. Include the item ID, affected cluster,
the focused verification performed, and any intentional exception that remains.

| Date | Item | Cluster | Result / remaining exception |
|---|---|---|---|
| | | | |
