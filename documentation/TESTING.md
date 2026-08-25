# Testing

This is the command and suite entry point. Read
[TESTING_WRITING_TESTS.md](TESTING_WRITING_TESTS.md) before adding or reshaping
tests, and [TESTING_SERVER.md](TESTING_SERVER.md) before starting a managed
Flask/browser session.

## Suites

| Suite | Location | Use it for |
| --- | --- | --- |
| Unit | `testing/tests_unit/` | Deterministic backend entities, properties, permissions, validation, and services. |
| JavaScript | `testing/tests_js/` | Frontend modules that run in Node with small platform fakes and no live DOM/server. |
| E2E | `testing/tests_e2e/` | Browser/server workflows, DOM, routing, storage lifecycle, rendering, and multi-user behavior. |
| Tooling | `testing/tests_tooling/` | Setup/config smoke, runner, reporters, and repository health. |

Tooling tests must not import `lagniappe.core` or `lagniappe.web` and must not
execute Node. Only E2E may import `lagniappe.web`.

## Dependencies

After completing ordinary installation, install the local toolchain with:

```bash
./setup.sh development
```

It verifies the installation, creates test-prefixed Storage buckets, installs
`requirements-dev.txt`, runs `npm ci`, installs Playwright Chromium, and builds
the development frontend. See
[INFRA_SETUP_DEVELOPMENT.md](INFRA_SETUP_DEVELOPMENT.md).

## Commands

Use the repository virtualenv and runner:

```bash
venv/bin/python run.py test
venv/bin/python run.py test unit
venv/bin/python run.py test js
venv/bin/python run.py test tooling
venv/bin/python run.py test setup
venv/bin/python run.py test e2e

venv/bin/python run.py test testing/tests_unit/test_file.py
venv/bin/python run.py test testing/tests_e2e/003_forms/test_003b_form_builder.py::test_preview_panel
venv/bin/python run.py test -k "category"
venv/bin/python run.py test -v --tb=long
```

Suite aliases expand only the documented suite names. Focused runs use real
pytest paths or nodeids. Multiple aliases may be combined, but an alias and an
explicit path/nodeid in the same command is rejected as ambiguous. Use only the
path when narrowing an alias to one file or test.

The runner asks pytest's configured built-in and installed-plugin parser which
arguments are collection targets, so valued options such as `--color yes`,
`--durations 10`, and `--browser chromium` cannot be mistaken for paths. Short,
long, repeated, and `--name=value` forms follow pytest's normal parsing rules.
An option-only command such as `test -k category` has no explicit target and
therefore uses configured full-suite discovery, including E2E preflight.

One `--` is accepted as the runner-to-pytest separator and is removed before
pytest parsing. Use two (`-- --`) when pytest itself must receive an option
terminator for a dash-prefixed path. Collection targets must be supplied
directly: `--pyargs`, pytest argument files, and targets injected through
`PYTEST_ADDOPTS` or config are rejected because they cannot form a reviewable
runner selection.

E2E targets enable strict unloaded-relation checks automatically. For another
suite:

```bash
venv/bin/python run.py test --strict unit --tb=short
```

The runner activates the checkout's complete saved gcloud target before pytest.
An unconfigured checkout can run offline tests; a partial target fails before
collection. E2E and managed-server startup also verify ADC. Use
`venv/bin/python run.py auth` when alignment is needed.

Start with one nodeid or file. Expand after focused probes pass. E2E pytest,
`test-server`, and browser-review sessions share one managed server/data prefix
and must not run concurrently. Put several nodeids into one pytest invocation.

## Provider contracts

`testing/pytest.ini` excludes provider-changing markers from ordinary runs.
Run read-only drift checks explicitly:

```bash
venv/bin/python run.py test setup -m setup_drift
```

The live runtime contract audits exact IAM and then exercises the configured
runtime credential against Datastore, the runtime Storage buckets, Cloud Tasks,
Scheduler OIDC, Document AI, Vertex AI, Places, and Identity Platform:

```bash
venv/bin/python run.py test setup -m setup_provider
```

It makes billable provider calls, creates test-prefixed state, and must run
alone. Use `-m provider` to run both opt-in groups in one sequential session.
An ordinary `test setup` remains offline.

Setup targets come from one declarative inventory split into ordinary,
`setup_drift`, and `setup_provider` groups. Repository-health coverage requires
every `testing/tests_tooling/test_*_setup_*.py` module to appear exactly once,
so adding a setup module cannot silently omit it from the alias.

## Markers

| Marker | Meaning |
| --- | --- |
| `unit`, `js`, `e2e`, `tooling` | Suite ownership. |
| `ai` | Live AI behavior with a longer operation budget and result report. |
| `setup_drift` | Read-only provider/config audit. |
| `setup_provider` | Sequential live-provider runtime contract. |
| `unfinished` | Explicit backlog stub, excluded by default. |

An `ai` E2E test receives `request.node.ai_results`. Record prompts, safe
responses, entity snapshots, and generated output there so real provider calls
leave a reviewable artifact.

## Test layout

| Directory | Contents |
| --- | --- |
| `testing/definitions/` | Durable scenario data and expected values. |
| `testing/resources/` | Page/domain resources, navigation, and focused selectors. |
| `testing/elements/` | Reusable UI operations for stable components. |
| `testing/utility/` | Harness protocols, reporters, fakes, and support code. |
| `testing/files/` | Schemas, CSVs, and other test assets. |

Keep the `testing/` root clean. Place test files by suite, not by the location
of a helper they happen to import.

## Traceability and template tools

```bash
venv/bin/python run.py traceability --changed --check
venv/bin/python run.py traceability --source lagniappe/core/tools/cache/core.py
venv/bin/python run.py traceability --test testing/tests_unit/test_file.py
venv/bin/python run.py template-contracts --changed --check
venv/bin/python run.py traceability --styles
```

`run.py test` records exact outcomes in `testing/evidence/latest.json`.
Traceability checks whether referenced tests are current for their declared
source/template/style dependencies. Use:

- [TESTING_TRACEABILITY_TOOL.md](TESTING_TRACEABILITY_TOOL.md) for syntax and
  report behavior;
- [TESTING_SOURCE_REVIEW.md](TESTING_SOURCE_REVIEW.md) when reviewing source
  ownership;
- [TESTING_TEST_REVIEW.md](TESTING_TEST_REVIEW.md) when reviewing a test; and
- [TESTING_TEMPLATE_CONTRACTS.md](TESTING_TEMPLATE_CONTRACTS.md) for Jinja DOM
  contracts.

## Artifacts and evidence

Generated artifacts live under `reports/`:

- browser screenshots/HTML: `reports/test_failures/`;
- rich test reports: `reports/test_reports/`;
- curated UI reviews: `reports/browser_reviews/`;
- managed server state: `reports/test-server.*`;
- hosted bundles: `reports/hosted-e2e/`; and
- traceability/template/style reports at their named report paths.

`testing/evidence/latest.json` is tracked current evidence, not a run log. It
keeps one result per exact nodeid and only the newest session invocation
metadata. Semantic fingerprints ignore comments, documentation, generated
evidence, GitHub workflow files, and the random build ID while retaining
behavior-bearing source/template dependencies. Review failed tracebacks before
commit because diagnostics must not contain credentials or private data.

Hosted release testing imports evidence from the exact committed production
candidate. See [TESTING_HOSTED_E2E.md](TESTING_HOSTED_E2E.md).
