# Native JavaScript Tests and Migration

JavaScript behavior tests live in `testing/tests_js/`. New tests are ordinary
`test_*.mjs` modules using `node:test` and `node:assert/strict`. Pytest discovers
each named case and runs it in a fresh Node process. Continue using the repo
runner: selection, failures, reports, and traceability evidence stay in pytest.

Read [TESTING_WRITING_TESTS.md](TESTING_WRITING_TESTS.md) and
[TESTING_TEST_REVIEW.md](TESTING_TEST_REVIEW.md) before migrating a test.
The completed example is `testing/tests_js/test_045_offline_queue.mjs`.
Harness contracts are exercised in `test_000_native_harness.mjs` and
`test_000_native_runner.py`; the latter intentionally tests the Python bridge.

## Commands and case declarations

Install the Node version in `.nvmrc` and run `npm ci` after dependency changes.
`upgrade-dependencies` advances the development versions together; release
freeze validates the concrete versions recorded in the checkout.

```bash
venv/bin/python run.py test testing/tests_js/test_045_offline_queue.mjs
venv/bin/python run.py test testing/tests_js/test_045_offline_queue.mjs::test_offline_replay_retries_rebased_record_before_later_record
venv/bin/python run.py test js -k offline_replay
venv/bin/python run.py test js --collect-only
venv/bin/python run.py test js --lf
```

Use literal, unique names matching `test_[A-Za-z0-9_]+`. Declare cases directly
at module scope with `test("test_name", callback)`. Named or default imports of
`test` from `node:test` are accepted. Do not use `describe`, `.only`, dynamic
names, test factories, nested `t.test`, or registrations inside loops. A loop
of scenarios *inside* one case is fine; include the scenario name in assertion
messages. Use multiple literal cases when failures need separate pytest IDs.

`test.skip` skips a case. `test.todo` marks it unfinished; default pytest
selection excludes unfinished items. Neither creates passing evidence. Runtime
`t.skip()` also remains a skip. Node test options support `timeout` and `signal`;
the outer process has a 30-second limit regardless of a larger Node timeout.

Collection parses declarations with Babel. It never imports the test/application,
runs cases, or regenerates registries. Keep application initialization inside
the case when it depends on browser globals. Console output is captured
separately from the structured Node reporter protocol.

## Choose the smallest environment

| Behavior | Fixture or boundary |
| --- | --- |
| Pure module behavior | Import the production module and assert its results. No browser fixture. |
| DOM structure, attributes, forms, events | `createBrowser(t, options)` from `../utility/js/environment.mjs`. |
| Actual storage operations, upgrades, rollback | `installIndexedDB(t)` and the application's storage exports. |
| HTTP wrapper behavior | Keep the real request module; replace fetch with `mockFetch(t, handler)`. |
| A consumer of an HTTP or other module | Replace that imported boundary with `esmock.strict`. |
| Retry/debounce/scheduling | `useClock(t, { now })` and Node's mock timers. |
| Layout, actual navigation, worker lifecycle, browser upload durability | Retain the real-browser E2E test. |
| Service-worker script behavior | A dedicated worker VM sandbox, with test logic in `.mjs`. |

### Plain modules

This example can be placed directly in a `test_*.mjs` file:

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";
import { iconDefinition } from "../../src/script/shared/icons.mjs";

test("test_page_icon_lookup", () => {
  assert.deepEqual(iconDefinition("page"), { glyph: "draft", fill: 1 });
  assert.equal(iconDefinition("missing.icon"), null);
});
```

Production relative imports include their extension; directory imports name
`index.mjs`. Styles and icons are normal generated modules. Never restore a
virtual import or create a test-only copy of a production module. Full boot
entries that import CSS remain build entry points; import the behavior owner
in module tests and leave bundling checks in the build contract tests.

### DOM setup and constructor ownership

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";
import { createBrowser } from "../utility/js/environment.mjs";

test("test_form_value_and_event", (t) => {
  createBrowser(t, {
    html: '<form><input name="title" value="Draft"></form>',
  });
  const form = document.querySelector("form");
  assert.equal(new FormData(form).get("title"), "Draft");
  let title;
  form.addEventListener("saved", (event) => { title = event.detail.title; });
  form.dispatchEvent(new CustomEvent("saved", { detail: { title: "Saved" } }));
  assert.equal(title, "Saved");
});
```

`createBrowser` returns the jsdom instance. Defaults are an empty document,
`https://lagniappe.test/`, and `formData: "dom"`. It installs curated globals,
including DOMParser, events, storage, and DOM constructors, and closes the
window/restores globals at cleanup. It disables subresource loading and fails
on unaccounted jsdom errors. Create one browser per case. For a scenario loop,
reset its DOM explicitly instead of swapping globals under cached imports.

Call it **before** dynamically importing modules that create DOMParser objects,
read navigator, or initialize browser singletons. A new document does not reset
ESM modules. Each pytest case's fresh Node process provides that isolation;
do not add query-string cache busting or production reset hooks.

The default uses jsdom's FormData/File/Blob family, including `new FormData(form)`.
For binary persistence, use `createBrowser(t, { formData: "native" })` and create
Node-native FormData/File/Blob values explicitly. Native FormData does not
accept a DOM form constructor argument. IndexedDB cloning uses Node's native
structuredClone; jsdom File wrappers are not a reliable binary persistence
format. Assert stored bytes and filename metadata, not just a successful put.
The native helper contract test demonstrates the supported binary round trip.
Use E2E for the combined actual file-input, serialization, and browser durability
boundary. Do not implement a replacement structured-clone engine in tests.

### Network boundaries

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";
import { createBrowser, mockFetch } from "../utility/js/environment.mjs";

test("test_request_parses_server_html", async (t) => {
  createBrowser(t);
  const network = mockFetch(t, ({ url, method }) => {
    if (url.pathname === "/example" && method === "GET") {
      return new Response('<p data-role="result">Saved</p>', {
        headers: { "content-type": "text/html" },
      });
    }
  });
  const { request } = await import("../../src/script/shared/request.mjs");
  const response = await request.get("/example");
  assert.equal(response.ok, true);
  assert.equal(response.html.querySelector("p").textContent, "Saved");
  assert.equal(network.calls.length, 1);
});
```

The handler receives `{ url, method, input, init }`. `url` is an absolute URL;
`input` and `init` retain the original payload. Return a native Response, throw
an intended error, or return a controlled promise. Returning undefined marks
an unexpected request and fails the case, including when application code
catches the error. Abort signals reject pending mocked fetches. The returned
object exposes `calls` and a Node mock function `fetch`.

For consumer tests, import `esmock` and use:

```javascript
const { OfflineQueue } = await esmock.strict(
  "../../src/script/shared/offlineQueue.mjs",
  {
    "../../src/script/shared/request.mjs": {
      request: { post: t.mock.fn(async () => ({ ok: true })) },
    },
  },
);
```

Paths resolve relative to the file calling esmock. If this call moves into a
helper, update both paths relative to that helper. Strict replacements provide
the named exports used by the consumer; an omitted export must fail. Supply
the complete boundary needed by that case. Keep persistence real when storage
behavior is under test. Avoid wildcard/transitive mocks and replacing methods
on the module under test just to bypass its real dependencies.

### Persistence and time

Install IndexedDB after browser setup and before importing/calling persistence
code. `installIndexedDB(t, window)` returns a fresh factory and installs IDB
constructors on both globalThis and window. Opened connections are tracked and
closed during teardown. Await application operations so assertions observe
committed transactions. To simulate reload, instantiate a new application owner
against the same factory. A new factory represents a fresh database, not reload.

`useClock(t, { now: 1000 })` returns Node's mock timer controller. It coordinates
global and window Date, timeout, and interval functions. Use `clock.tick(ms)`;
await the async operation whose outcome matters after advancing timers.
Animation/layout APIs and all browser scheduling behavior are not implied by
this helper. Keep fake time opt-in; do not make database tests depend on sleeps.

## Migrate one file

1. Read the entire old file and its production owners. List every case,
   scenario, assertion, error branch, and metadata tag. Run the original file
   before changing it, or record any pre-existing failure.
2. Create the matching `.mjs` file. Keep case names. Copy executable test logic
   out of Python strings and replace manual `throw` comparisons with equivalent
   strict assertions. Keep structured error details in assertion messages.
3. Move shared test data into local functions or a `.mjs` helper. Reusable
   infrastructure belongs in `testing/utility/js/`. Python-generated *data* can
   be JSON fixtures; keep Python orchestration only when it is actually testing
   a Python/Node boundary, as the runner tests do. Do not interpolate JS programs.
4. Choose fixtures from the table. Set browser globals before imports. Import
   the real owner and explicitly mock only the required external boundary.
5. Remove import stripping, export rewriting, source concatenation, and VM
   evaluation for ordinary modules. If a private helper was manufactured as an
   export, exercise it through its exported owner. If that cannot preserve the
   assertion, document the obstacle and make a deliberate extraction into a
   production internal module; do not silently drop the assertion.
6. Attach the original `@matrix`, `@pair`, `@source`, `@template`, `@style`, and
   `@todo` comments immediately above each case. Update source `@tests` pointers
   from `.py::name` to `.mjs::name`. Declare a source edge from one end only.
7. Compare the assertion checklist against the new cases. Check both positive
   and failure behavior. A mocked request's call count alone does not prove
   persistence, reconciliation, or user-visible state.
8. Run the new file, an exact nodeid, and its traceability report. Run template
   contracts for tests claiming template coverage. Fix stale links and tag
   drift before removing the old file.
9. Remove the Python wrapper and unused file-local harness. Preserve shared
   legacy helpers still used elsewhere. Run the relevant suite and final checks.

Traceability inventories native cases statically. Their shared runner, helpers,
package/lockfile, and registry inputs participate in evidence invalidation.
Application ownership remains explicitly annotated. Literal selectors in JS
cases participate in template-contract reporting; arbitrary helper-generated
selectors are not inferred. Only tag a template when its real skeleton is part
of the test contract, not merely because a hand-written HTML fixture resembles it.

### Pilot assertion equivalence

| Original replay case | Native proof |
| --- | --- |
| Oldest failure blocks later records | Conflict, non-OK, and error-envelope scenarios preserve both records in memory and IndexedDB; only the oldest request is sent. |
| Completed prefix, retry retained suffix | First record disappears from storage; the failed second record remains and is the next request on retry. |
| Rebase before later record | Real `rebaseSubmit` persists the updated fingerprint while preserving ID/time; sends occur in original/rebased/later order. |
| Handler errors release ownership | Conflict failure keeps both records; post-replay handler failure keeps only the suffix; subsequent replay succeeds. |
| Added full round trip | Real queue submission persists, a new queue reloads it, failure preserves it, successful replay replaces the optimistic DOM and clears storage. |

The old deletion spy became assertions on actual persisted records. Production
`_send` and `_dispatch` now run. A supplied widget callback performs conflict
rebasing through `rebaseSubmit`; its additional queued notification is excluded
from the replay-phase log. This preserves the original ordering assertion while
also exercising the existing public rebase path. All three new dependencies
participate in the round-trip case.

### Service workers

Keep the specialized boundary from `test_008_service_worker.py`: execute the
rendered worker script in a context supplying self, caches, and worker events.
Move test bodies and reusable sandbox code into `.mjs`, use the same named
Node cases and pytest collector, and retain the existing production template
substitutions. This is a script/worker boundary, so `node:vm` remains appropriate
there. Do not introduce worker APIs into the ordinary jsdom fixture or turn
worker tests into live-server tests solely to remove Python strings.

## Troubleshooting and completion checks

| Symptom | Action |
| --- | --- |
| DOMParser/document/navigator unavailable | Establish createBrowser before dynamic production import. |
| Missing module or export | Correct the real path/export or explicit strict mock. Never strip the import. |
| Stale/missing generated styles or icons | Run `node build/generate-registries.mjs`; JS test setup and builds also generate them. Edit YAML, not generated files. |
| File/Blob loses contents | Check constructor mode and assert actual bytes; see the binary persistence boundary above. |
| Caught fetch still fails teardown | The request was not accounted for. Match its URL/method and assert the intended response/error. |
| Test times out | Find the unresolved promise, timer, or listener; await/clean it instead of raising the process limit. |
| Navigation/layout API unsupported | Assert module behavior at an explicit boundary; retain E2E for browser behavior. |
| Metadata or selected nodeid missing | Use a literal top-level test name and immediately preceding metadata; inspect `--collect-only`. |
| Evidence became stale after helper-only changes | Rerun affected native cases; execution dependencies intentionally invalidate them. |

```bash
venv/bin/python run.py test testing/tests_js/test_045_offline_queue.mjs
venv/bin/python run.py traceability --test testing/tests_js/test_045_offline_queue.mjs
venv/bin/python run.py test js
npm run check
venv/bin/python run.py traceability --changed --check
```

For a template-tagged migration, also run `run.py template-contracts` with its
path. Build when production imports or generated registries changed. State any
affected E2E validation left to the release-wide run. A migration is complete
when its assertion checklist is preserved, native cases pass, references point
to the new cases, evidence is current, and the old executable Python strings
are removed. Do not add production behavior changes merely to reduce retesting.

## Remaining migration inventory

The groups below are a starting order, not permission to batch unrelated files.
Migrate one file at a time and re-check the source for its actual dependencies.
The native pilot and native harness are complete; the Python runner tests remain
Python because they exercise the cross-language integration itself.

| Stage | Files | Main boundary |
| --- | --- | --- |
| 1 | `test_010b_document_append_interop.py` | Pure/native modules; narrowly mock package or protocol boundaries as needed |
| 1 | `test_020_shared_utilities.py` | Pure/native modules; narrowly mock package or protocol boundaries as needed |
| 1 | `test_021_browser_protocol.py` | Pure/native modules; narrowly mock package or protocol boundaries as needed |
| 1 | `test_023_entity_name_formatting.py` | Pure/native modules; narrowly mock package or protocol boundaries as needed |
| 1 | `test_026_location_urls.py` | Pure/native modules; narrowly mock package or protocol boundaries as needed |
| 1 | `test_033_identity_platform.py` | Pure/native modules; narrowly mock package or protocol boundaries as needed |
| 1 | `test_036c_form_migrations.py` | Pure/native modules; narrowly mock package or protocol boundaries as needed |
| 1 | `test_048_markdown_paste.py` | Pure/native modules; narrowly mock package or protocol boundaries as needed |
| 2 | `test_011_view_transitions_frontend.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_015_error_tracking_frontend.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_016_combobox_frontend.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_025_pdf_preview.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_027_table_element_frontend.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_031_form_element_loader.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_032_todo_element_frontend.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_033_editor_menu_items.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_034_login_buttons.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_036_form_builder_frontend.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_036b_builder_draft.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_037_html_element_frontend.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_039_file_processing_reconciliation.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_041_editor_decorations.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_042_messaging_frontend.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_043_ai_email_frontend.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_044_agent_api_settings.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_044_user_widget_frontend.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_047_home_report_filters.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_047_public_sharing.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 2 | `test_048_form_controls.py` | DOM and explicit dependency mocks; some editor/file APIs need dedicated fixtures |
| 3 | `test_009_request_csrf.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_010_sync_manager_frontend.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_012_entity_layout_frontend.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_014_direct_upload_retry.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_015_core_submit_frontend.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_017_main_lifecycle.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_019_form_sync_frontend.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_022_refresh_frontend.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_023_deferred_operations.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_024_edit_watcher.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_029_core_startup.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_032_task_settings_lifecycle.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_034_polling_coordinator.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_035_ingress_polling.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_036_notification_state.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_038_startup_specializations.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_040_home_polling.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 3 | `test_046_async_query_lifecycle.py` | DOM, fetch/request boundary, deterministic time; storage where exercised |
| 4 | `test_018_style_pipeline.py` | Real generator/Rollup contracts; move programs to files without removing build coverage |
| 4 | `test_022_build_chunk_versioning.py` | Real generator/Rollup contracts; move programs to files without removing build coverage |
| 4 | `test_032_build_configuration.py` | Real generator/Rollup contracts; move programs to files without removing build coverage |
| 5 | `test_008_service_worker.py` | IndexedDB/private-helper adaptation; service worker retains its own sandbox |
| 5 | `test_028_form_state_split.py` | IndexedDB/private-helper adaptation; service worker retains its own sandbox |
| 5 | `test_045_browser_persistence.py` | IndexedDB/private-helper adaptation; service worker retains its own sandbox |
