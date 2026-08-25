# Testing Traceability

`testing/utility/traceability.py` connects durable source symbols to the tests
that exercise them. It is designed to answer three practical questions:

1. What is this code for, and where is its behavioral evidence?
2. Did the relevant tests run against the working tree being handed off?
3. Did a source, test, or annotation change leave a stale or ambiguous link?

The annotation remains `@testable`; the tool and command are named
`traceability` because the report is about evidence and ownership, not a claim
that every referenced test is sufficient.

## Everyday workflow

Use the repository runner:

```bash
venv/bin/python run.py traceability --check
venv/bin/python run.py traceability --changed --check
venv/bin/python run.py traceability --source path/to/source.py
venv/bin/python run.py traceability --test test_file.py::test_name
venv/bin/python run.py traceability --feature-dimension feature:dimension
venv/bin/python run.py traceability --styles
```

The default terminal and Markdown reports are concise: a summary and stable
findings. Add `--verbose` for the full inventory, TODO roadmap, reverse links,
and advisory taxonomy review.

With no focus option, the command is the complete repository inventory: source
ownership and current test evidence plus all template contracts and the full
style/icon pipeline. A strict repository-health pass is therefore:

```bash
venv/bin/python run.py traceability --check --fail-on warning
```

`--changed [BASE]` includes tracked, staged, and untracked paths. `BASE`
defaults to `HEAD`. It is the preferred final-task view because it reports the
changed sources and tests together and requires every relevant test to have a
passing result for its current declared code dependencies.
For tracked Python files, source and test focus is narrowed to symbols touched
by the diff hunks, so editing one test does not audit unrelated historical tags
in the same file. An untracked file is treated as wholly new and checked in
full.
It also folds affected template-contract errors and warnings into the same
check; use the dedicated template command for exhaustive selector evidence.

## Closing the agent feedback loop

Tests run through `run.py test` automatically record outcomes in
`testing/evidence/latest.json`. This tracked manifest is the repository's
reviewable evidence that the maintainer ran the relevant tests on configured
infrastructure. It keeps only the most recent result
for each exact test nodeid and only the newest pytest session's invocation
metadata. Separate focused results are merged even when the working tree
changes. A merge prunes results whose test module or source test definition has
been deleted while retaining unselected tests that still exist. Failed results also
record `failed_phase` and a bounded pytest `traceback`; `traceback_truncated`
identifies the rare result whose traceback exceeded the manifest limit. Each
result records a semantic snapshot, and
remains current only while its test file plus the source and template paths
connected through traceability metadata are behaviorally unchanged. Python
comments and docstrings, JavaScript comments, documentation, and report
artifacts do not invalidate behavioral evidence. The random production
`BUILD_ID` assignment in `config/constants.py` is also normalized because it
identifies generated assets rather than a source change; hosted provenance
records the concrete deployed build ID separately. Changing any other
referenced implementation or template does invalidate evidence.

The manifest is excluded from its own behavior snapshot, so recording a test
result does not immediately make that result stale. GitHub workflow files are
also excluded because they do not change application behavior. Main release CI
invokes the pre-created hosted `all` job through keyless WIF, then writes only
its validated evidence follow-up commit. The current-head continuation checks
that the tracked evidence is the sole child change and names the exact hosted
candidate and semantic source snapshot. It does not repeat a traceability pass:
the complete hosted suite has already refreshed every test result. The
continuation requires no access to private application infrastructure.

Test-evidence provenance records the command, generation time, and
content-derived behavior snapshot. It intentionally omits Git commit and
working-tree identities: squashes, rebases, and audited history rewrites do not
change the evidence when the relevant behavior-bearing files are identical.
CI currentness is determined from the manifest's per-path semantic
fingerprints, not from a commit SHA. General traceability reports still include
Git provenance for local diagnostics.

Test-run schema 3 stores each unique path/fingerprint pair once in the
top-level `fingerprint_pairs` table. Snapshot records contain integer references
to that table; the reporter reconstructs the same path maps before checking
currentness.

This dependency graph is deliberately declared rather than guessed. Keep
`@tests`, `@source`, `@scaffolding`, and `@template` links accurate; a shared
helper with meaningful behavior should be represented by one of those
ownership paths.

A useful handoff sequence is:

```bash
venv/bin/python run.py test path/to/relevant_test.py
venv/bin/python run.py template-contracts --changed --check  # for template/UI work
venv/bin/python run.py traceability --changed --check
```

The final traceability command fails when a changed or referenced test is not
recorded as passing for the current fingerprint. This makes “tests passed” a
checkable artifact rather than prose in an agent response.

Static AST discovery is the default and does not import the application.
`--verify-collection` is an opt-in diagnostic that compares the inventory with
real pytest collection when collection behavior itself is in question.

## Source annotations

Place tags in the comment or docstring immediately preceding a durable Python
or JavaScript symbol. Annotated exported JavaScript declarations such as
`export const Extension = Factory.create(...)` are inventoried too.

Tested behavior:

```python
# @testable true
# @tests tests_unit/test_example.py::test_normalizes_value
# @matrix normalization : blank-value
def normalize_value(value):
    ...
```

Delegated behavior:

```python
# @testable false
# @covered-by package/public_api.py::save
# @reason private conversion step exercised through the public API
def _convert(value):
    ...
```

Framework or composition plumbing:

```javascript
/**
 * @testable infrastructure
 * @covered-by src/script/views/base/core.mjs::Core.renderComponent
 */
export class ViewComponent {}
```

Supported tags are:

- `@testable true|false|infrastructure`
- `@tests <pytest nodeid or glob>`
- `@source <source path>::<qualified symbol>` on a test
- `@scaffolding <helper path>::<symbol>`
- `@covered-by <source path>::<symbol>`
- `@reason <why direct testing is inappropriate>`
- `@manual`
- `@matrix <features> : <dimensions>` for one allowed Cartesian region
- `@pair <feature>:<dimension>` for one exact, repeatable pair
- `@pairs <feature>:<dimension> [...]` for several exact pairs on one line
- `@template <template.html>::<macro>` on tests
- `@style <semantic.style.id>` on tests for a style-specific DOM or interaction contract
- `@todo <specific missing behavior>` on tests

`@testable true` needs test or scaffold evidence. `@testable false` needs a
reason or source owner. Ownership links must exist, cannot point to themselves,
cannot form cycles, and should ultimately reach tested or infrastructure code.

Use `@matrix` and `@pair` together as one additive behavior language. A matrix
declares one Cartesian region; exact pairs add individual cells. Repeating
either tag unions its cells with the others:

```python
# @matrix home search : permissions
# @matrix search : load
# @pair home:permissions
# @pair export:empty-value
```

This example declares `home:permissions`, `search:permissions`, `search:load`,
and `export:empty-value`. It does not create a product across separate matrix
clauses. This makes compact regular regions and sparse exceptions equally
natural.

Source and test annotations interpret the same cells at different stages:

- A source matrix describes an allowed behavior territory. Each feature and
  dimension axis must be realized by at least one directly linked test; every
  Cartesian cell need not have its own test.
- A source `@pair` is a precise obligation and must be realized exactly by a
  directly linked test.
- A test matrix or pair is exhaustive: it claims the cells its assertions
  actually prove.
- The realized cells of a source-to-test link are the intersection of those
  source and test declarations.

## Direct and related test links

A direct edge may be declared from either end: use source-side `@tests` when
the source owner is the clearest editing point, or test-side `@source` when the
test is the clearest place to maintain the pointer. Do not declare both ends of
the same edge; the reporter synthesizes the reverse view and warns about a
duplicate declaration.

Exact nodeids remain conservative safety rails: an exact direct edge with
missing or disjoint behavior cells is retained for retesting but reported as an
error. Globs and `@scaffolding` first locate candidates, then keep only tests
whose behavior cells overlap the source. A broad declaration that realizes no
edge is an error. This prevents a file or folder pointer from turning every
test it contains into a cascade.

Direct realized edges are hard dependencies. They invalidate semantic test
evidence when their source changes and are required by `--changed --check`.
Other tests that share one of a source's realized cells are shown as soft
related tests, with the matching cells, but do not become owners, dependencies,
or required evidence. Related matching is global and one hop only: another
test's unrelated cells do not expand the graph further.

Unknown or nearly misspelled traceability tags are diagnosed. `@suggestion` is
not a supported tag; use `@todo` when a missing behavior should remain visible.

## Focus modes

- `--source PATH` inventories one or more files or directories. Add
  `--suggest-sources` to find likely tests for undecided source symbols.
- `--test TARGET` maps a nodeid, file, or folder to its source
  owners. Add `--suggest-sources` to review likely missing owners.
- `--feature-dimension FEATURE:DIMENSION` lists code, tests, templates, and
  links for one behavioral pair.
- `--changed [BASE]` is the final-task view and also correlates current results.

Only one focus mode may be used at a time.

## Style traceability

Style inventory is a first-class traceability mode:

```bash
venv/bin/python run.py traceability --styles
venv/bin/python run.py traceability --style task.home.group
venv/bin/python run.py traceability --style-source src/style/navigation.css
venv/bin/python run.py traceability --style-consumer src/script/widgets/home/tasks.mjs
venv/bin/python run.py traceability --changed --styles --check
```

The default style run writes `reports/style-manifest.json` and
`reports/style-traceability.md`. The version 3 manifest records typed semantic
styles, the validated icon registry and consumers, resolved aliases, source
locations, server/frontend consumers, raw class uses, authored CSS selectors,
input fingerprints, and the build/import pipeline.
Pass `--no-manifest` or `--no-report` for a read-only console run.

Unknown references, alias/schema errors, declared-surface drift, broken CSS
owners/hooks, build-contract drift, unreachable required inputs, missing
transforms, unavailable compiled candidates, and generated-Python drift are
errors. Existing unused styles are warnings. Duplicate values and syntactic
raw/repeated-string candidates remain `review` findings and do not fail checks.

Style records have independent semantic fingerprints in test-result snapshots.
Template-contract tests are linked to records used inside their macros; add
`@style semantic.id` to a test for direct JavaScript-created, responsive, state,
or interaction evidence. A normal `traceability --changed --check` run folds in
the style graph automatically when style sources or consumers changed.

Style queries and the report share the normal versioned finding envelope.
`--baseline` and `--write-baseline` therefore work in style mode too. The
separate manifest has its own schema version and a content fingerprint that
excludes generation time and Git provenance.

## Checks, baselines, and structured output

`--check` returns status 1 for actionable findings. `--fail-on error` is the
default; `--fail-on warning` includes warning-level findings. Configuration and
command errors return status 2.

Baselines contain stable finding IDs, not fragile output text:

```bash
venv/bin/python run.py traceability --json > /tmp/traceability.json
venv/bin/python run.py traceability --write-baseline reports/traceability-baseline.json
venv/bin/python run.py traceability --baseline reports/traceability-baseline.json --check
```

JSON output has a versioned envelope with `schema_version`, `kind`,
`provenance`, `findings`, `finding_ids`, and `report`. Provenance includes the
Git HEAD, working-tree fingerprint, generation time, and command.

Default Markdown paths are `reports/traceability*.md`. Use `--report-path` to
choose another path or `--no-report` for terminal-only inspection.

## Configuration and scope

`testing/utility/traceability.yaml` defines source roots, annotated sources
outside those roots, test roots, scaffold roots, extensions, exclusions, and
suggestion filters. The annotation scan is intentionally broader than the
inventory so annotated files accidentally omitted from configuration become
findings.

Suite placement remains independent of traceability:

- backend logic: `testing/tests_unit/`
- JavaScript without DOM/browser dependency: `testing/tests_js/`
- repository setup/config/tool health: `testing/tests_tooling/`
- browser/server workflows: `testing/tests_e2e/`

Template selector and macro contracts are a related but separate report. See
[TESTING_TEMPLATE_CONTRACTS.md](TESTING_TEMPLATE_CONTRACTS.md).

## Important limits

A link proves that evidence is declared and current; it does not prove that the
assertions are strong. Test review still needs to reject tests that only inspect
source text, imports, or symbol existence without validating behavior. See
[TESTING_TEST_REVIEW.md](TESTING_TEST_REVIEW.md) and
[TESTING_SOURCE_REVIEW.md](TESTING_SOURCE_REVIEW.md).
