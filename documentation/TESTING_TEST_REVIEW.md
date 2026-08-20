# Testing Test Review

Use this as the final traceability pass after adding, changing, or reviewing a
test file, folder, or nodeid. The broad annotation pass is complete; going
forward, the job is incremental maintenance. From a test, a reader should find
the source behavior it proves; from source annotations, a reader should find the
tests that genuinely assert or observe that behavior.

Treat this as more than a test-tagging pass, but keep the scope to the focused
tests and any source behavior they actually prove. The end state is:

- focused test annotations have been verified whether they were already present
  or not;
- focused tests that prove product, source, UI, route, or tooling behavior have
  accurate annotations;
- source owners for the focused behavior are present, accurately tagged, and
  linked back to the tests for every truthful `feature:dimension` pair;
- appropriate `@todo` items or unfinished stub tests have been added for real
  gaps; and
- nearby source behavior touched by the change is either covered, intentionally
  suppressed with `@covered-by` or `@reason`, or represented by a visible
  `@todo` / unfinished stub when it is a real future gap.

Start with `documentation/TESTING_TRACEABILITY_TOOL.md` for tag syntax and feature/dimension
guidelines. After identifying source symbols, use
`documentation/TESTING_SOURCE_REVIEW.md` to verify that the source claims
and referenced tests are truthful.

## Start With The Test

Run the reverse report:

```bash
venv/bin/python run.py traceability --test test_file.py::test_name
venv/bin/python run.py traceability --test testing/tests_unit/test_003_submission.py
```

The `--test` report shows:

- focused test nodeids and parsed `@features`, `@dimensions`, `@pair`, `@template`, and
  `@todo` tags;
- per-test `feature:dimension` mappings to source symbols that both reference
  the test and declare the same pair; and
- annotated focused tests whose `feature:dimension` pairs are missing
  corresponding source tags.

Before editing tags, read the test body and answer:

1. What behavior does this test assert or observe?
2. Is the behavior unit-level source logic, isolated JavaScript module logic,
   browser/route/template behavior, or tooling/report behavior?
3. Which source symbol appears to own the behavior, and which files are only
   helpers, fixtures, page resources, or setup?
4. Do the current test annotations, if any, describe that behavior precisely?
5. Does a source symbol for each truthful `feature:dimension` pair reference the
   test and declare the same pair?
6. Does the test establish the durable state relevant to its assertion, or
   does it depend on one exact mutation from an earlier test?
7. If the test creates or mutates a record in a living accumulated datastore,
   does it keep and select that record by its durable key rather than text or
   position among older records?

Do not tag a test merely because it executes code. Test tags describe what a
future reader should look for in the assertions, tooling checks, or E2E
observations.

## Path A: Test Already Has Tags

Use this path when the reverse report shows parsed test metadata.

1. Compare the existing `@features`, `@dimensions`, `@pair`, `@template`, and `@todo`
   tags with what the test actually proves.
2. Open every source symbol listed in the test's `feature:dimension` mappings.
   These are existing source-to-test links for the annotated pairs.
3. If a pair has no mapped source symbol, use the test tags, assertions, nearby
   tests, helpers, route names, selectors, imports, and `rg` to find the likely
   behavior owner. Do not treat execution or import evidence as ownership by
   itself.
4. If the test tags are too broad, misleading, or only describe incidental code
   execution, narrow or remove them.
5. If a behavior owner exists but does not reference this test, add the test
   nodeid or a focused glob to that source symbol's `@tests` only when the test
   really covers the source claim, and make sure the source declares the same
   truthful `feature:dimension` pair.
6. For each linked, newly linked, or corrected source symbol, run the workflow in
   `documentation/TESTING_SOURCE_REVIEW.md`.

If the test has `@template`, run the template contract report for the same
target:

```bash
venv/bin/python run.py template-contracts test_file.py::test_name
```

Keep `@template path.html::macro` only when the Jinja macro skeleton is part of
the contract under test, such as stable `lp-*` or `data-*` attributes consumed
by frontend code or selectors. Rendering a page that happens to include a macro
is not enough. The template report is intentionally informational rather than
exhaustive: for complex Jinja conditionals, loops, or page-level macros, prefer
the smallest useful template pointer plus the nearest route, JavaScript, or
backend behavior owner.

When the report lists evidence from `testing/resources/` or `testing/elements/`,
read it as selector evidence only. Direct constants, common helpers, and narrow
resource properties such as `project.info_form` can confirm that a test touched
a stable widget or control contract. They do not prove that the helper's whole
workflow, every Jinja branch, or the owning route/widget behavior is covered;
source annotations still need to point at the behavior owner for each truthful
`feature:dimension` pair. When a behavior-owning source symbol uses
`@scaffolding`, the helper is evidence for that source symbol only when the
focused test body calls it.

## Path B: Test Has No Tags Yet

Use this path when a new or focused test has no parsed metadata.

1. Decide whether the test is worth tracking. Tiny harness smoke tests,
   repository-health checks, or tests whose value is only collection plumbing
   may need no metadata.
2. Identify the behavior the test proves before choosing names. Features should
   be broad product or system areas; dimensions should be reusable aspects,
   modes, risks, or behaviors.
3. Locate the source behavior owner before committing to tags. The incremental
   pass is not complete if only the test receives annotations; source symbols
   must also be annotated or intentionally suppressed.
4. For unit tests, good feature candidates often map to backend classes in
   `lagniappe/core/entities/` or `lagniappe/core/properties/`, though not always
   one-to-one. Names like `task`, `email-input`, `text-input`, or
   `number-input` are useful features; names like `ai-value` and `filter-value`
   are better dimensions.
5. For E2E tests, the feature often stays aligned with the backend
   entity/property and its corresponding JavaScript class or template contract.
   E2E dimensions can describe UI/workflow aspects such as `email-input-ui`,
   `email-table-cell`, `submit`, `update`, `sync`, or `sort`.
6. Add the smallest truthful test block:

   ```python
   # @features submission
   # @dimensions readonly table-edit
   def test_submission_readonly_table_edit():
       ...
   ```

   Do not force the tags down to one feature or two dimensions when a
   parameterized loop genuinely asserts a broader cross-product. For example,
   `@features text-input email-input number-input` with
   `@dimensions ai-value filter-value` is appropriate if each generated
   `feature:dimension` pair is actually tested.
7. For E2E tests, add `@template path.html::macro` only when the test is meant
   to exercise the template skeleton as part of the UI contract. It is fine for
   template tags to be non-exhaustive when a smaller, precise pointer is more
   helpful than a noisy page-level macro.
8. Rerun the reverse report and use missing `feature:dimension` mappings, the
   test's helpers/resources, route names, selectors, imports, and `rg` to
   confirm or find the source behavior owner.
9. Annotate source according to `documentation/TESTING_TRACEABILITY_TOOL.md`:
   `@testable true` with this test in `@tests` when the symbol owns the
   behavior, or `@testable false` with `@covered-by` when the symbol is a helper
   covered through a better owner.
10. Rerun the reverse report until every truthful test `feature:dimension` pair
    maps to at least one referenced source symbol with the same pair.
11. Run the source-review workflow for each source symbol you linked or changed.

During either path, add gap markers when the file shape calls for them. If an
existing test mostly covers a behavior but exposes a real missing assertion, add
a clear `@todo` to that test. If a separate future test is more appropriate for
the test layer, add an `@pytest.mark.unfinished` stub in the unit, E2E, or
tooling suite that matches the behavior and file naming pattern; keep matching
`@features`, `@dimensions`, and `@todo` on the stub. Do not count a stub as real
coverage unless unfinished coverage is intentionally the clearest signal.

## Finish

Run the narrow relevant checks:

```bash
venv/bin/python run.py test path/to/test_file.py
venv/bin/python run.py traceability --test path_or_nodeid
venv/bin/python run.py traceability --source path/to/source.py path/to/related.py
venv/bin/python run.py template-contracts path_or_nodeid
```

Use the template command only for tests with `@template`. Run the full
traceability report only when the review touches several source files or when
you want final repository-wide verification:

```bash
venv/bin/python run.py traceability --changed --check
```

Before handing off, record what changed: the behavior the focused test proves,
final test tags, source symbols reviewed or updated, any remaining `@todo` or
unfinished stub, and the commands run.
