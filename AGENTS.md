# Agent Instructions

These instructions apply to the whole repository unless a more specific
`AGENTS.md` exists in a subdirectory.

## Python

- Use the project virtualenv for all Python commands.
- Prefer `venv/bin/python ...`.
- Prefer `venv/bin/python -m pytest ...`.
- Do not use bare `python` or `pytest` unless the user explicitly asks for it.

## Testing

- Prefer the repo runner for common test commands:
  - `venv/bin/python run.py test`
  - `venv/bin/python run.py test unit`
  - `venv/bin/python run.py test e2e`
  - `venv/bin/python run.py test js`
  - `venv/bin/python run.py test tooling`
  - `venv/bin/python run.py test setup`
  - `venv/bin/python run.py traceability`
  - `venv/bin/python run.py template-contracts`
- Use the shared pytest config at `testing/pytest.ini`.
- E2E targets automatically enable strict unloaded-relation checks. For other
  suites, use the repo runner flag: `venv/bin/python run.py test --strict
  <target>`. Do not rely on shell env prefixes for this.
- `run.py test` only expands the suite aliases above. For focused checks, pass
  real pytest paths or nodeids such as
  `venv/bin/python run.py test testing/tests_e2e/.../test_file.py::test_name`;
  do not use legacy numeric/domain shorthand like `003b`, `003b::test_name`,
  or `home`.
- Keep long or risky test runs cancellable: prefer focused real nodeids or one
  file at a time, expand only after probes pass, and avoid starting broad
  E2E/full suite runs unless the user explicitly asks for them.
- Do not run E2E pytest, `test-server`, or `browser-review` sessions in
  parallel against the managed testing server. The first session to finish will
  run teardown and clear shared test data/server state out from under the
  others.
- Before adding or materially reshaping tests, check
  `documentation/TESTING_WRITING_TESTS.md`.
- When reviewing or annotating an existing test, check
  `documentation/TESTING_TEST_REVIEW.md`.
- Keep the `testing/` root clean. Miscellaneous test utilities belong in
  `testing/utility/`; tooling and repository-health tests belong in
  `testing/tests_tooling/`.
- Test placement:
  - backend unit tests belong in `testing/tests_unit/`;
  - browser/server workflow tests belong in `testing/tests_e2e/`;
  - Node-backed JavaScript behavior that does not require a live browser belongs
    in `testing/tests_js/`;
  - setup, config smoke, repository-health, and reporter tests belong in
    `testing/tests_tooling/`.
- Only E2E tests may import `lagniappe.web`. Tooling tests also must not import
  `lagniappe.core` or execute Node; use the unit and JavaScript suites instead.

## Project Map

- `lagniappe/core/` contains backend entities, properties, definitions, and
  service logic.
- `lagniappe/web/` contains Flask routes, templates, and web integration code.
- `src/script/` contains frontend modules.
- `installer/` contains interactive install, recovery, repair, and update
  workflows.
- `runner/` contains repository-local orchestration shared by `run.py` and the
  installer; it is excluded from App Engine uploads.
- `config/` contains runtime-safe settings, validation, and configuration
  contracts used by the deployed application.
- `documentation/` contains project docs for humans and agents.
- `reports/` contains generated Markdown reports and other durable local report
  artifacts, including Rollup visualizers and E2E failure/report output.
- `testing/` contains pytest suites plus reusable test helpers.

## Documentation Routing

- Use `documentation/OVERVIEW.md` for the full documentation index and
  quick-reference table.
- Use `documentation/BACKEND_ENTITIES.md` before changing entities,
  properties, mixins, indexes, or task scheduling.
- Use `documentation/FRONTEND_VIEWS.md` and
  `documentation/FRONTEND_ELEMENTS.md` before changing view/component/widget or
  form-element behavior.
- Use `documentation/SYNC_ARCHITECTURE.md` before changing sync routes,
  `SyncManager`, offline replay, or collaborative document/form state.
- Use `documentation/INFRA_SETUP.md` and `documentation/INFRA_CONFIG.md` before
  changing setup, deployment, runtime configuration, or runner behavior.
- Treat deferred decision notes as evidence-gated, not as current feature
  specifications. Re-check evidence and feasibility before promoting an item
  to implementation work.

## Source And Docs

- Before adding or reshaping durable classes/functions/methods, check
  `documentation/TESTING_TRACEABILITY_TOOL.md` for the source annotation convention.
- When reviewing whether annotated tests actually cover their referenced source
  symbols, use `documentation/TESTING_SOURCE_REVIEW.md`.
- When reviewing UI/E2E tests with `@template` tags, use
  `venv/bin/python run.py template-contracts`.
- Run `venv/bin/python run.py traceability --changed --check` after adding,
  moving, or renaming source symbols in inventoried paths.
- Update `documentation/` when changing commands, setup behavior, test layout,
  source annotation conventions, or other workflows another developer/agent
  would need to know.
- Prefer updating an existing focused doc over creating a new one unless the
  topic clearly needs its own page.

## Repository Habits

- Use `rg` or `rg --files` for search when available.
- It is okay to run `npm run dev` to rebuild generated frontend assets after
  source changes.
- Treat `lagniappe/web/static/` as disposable generated output. Ignore its
  worktree state completely during normal development: do not inspect, search,
  diff, review, summarize, restore, clean, preserve, or report its changes, and
  never treat its churn as a conflict or a reason to ask the user what to do.
  Tests, builds, and deploys may freely create, modify, or remove files there.
- Do not hand-edit generated static files as source. Change the corresponding
  source files and run the normal build or test workflow when relevant; generated
  static changes and accompanying build-managed `BUILD_ID` churn require no
  special handling or mention.
- When the user asks to write a version message, write a concise release-note
  style summary of what changed. Prefer short entries like "Fixed category
  ownership sync" or "Added build IDs to asset cache busting"; do not write a
  long commit message, implementation narrative, or exhaustive file list unless
  the user asks for that detail.
- Keep edits narrowly scoped to the user request.
- Do not revert unrelated local changes.
