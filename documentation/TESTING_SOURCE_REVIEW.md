# Testing Source Review

Use this as the final traceability pass after adding, changing, or reviewing
source code. The broad annotation pass is complete; going forward, source
annotations should be maintained incrementally. For changed source symbols,
check that behavior has an accurate `@testable` decision, that referenced tests
or stubs represent the announced tags, and that helper code is either owned by a
better source symbol or intentionally suppressed.

Start with `documentation/TESTING_TRACEABILITY_TOOL.md` for the annotation contract.
For general test-writing conventions, use `documentation/TESTING_WRITING_TESTS.md`.
When starting from an existing test rather than a source symbol, use
`documentation/TESTING_TEST_REVIEW.md`.

## Goal

For each new, changed, or focused source symbol, decide whether the annotations
are truthful and useful:

- new behavior that needs traceability is tagged or deliberately marked
  `@testable false` / `infrastructure`;
- referenced tests or unfinished stubs make the declared `feature:dimension`
  expectations believable;
- tests do not get credit for behavior they only execute incidentally; and
- discovered gaps remain visible through `@todo`, unfinished stubs, or focused
  feature/dimension gaps.

The review should improve the roadmap. It should not turn annotations into a
large fake coverage database.

## Review One Symbol

1. Run a focused report:

   ```bash
   venv/bin/python run.py traceability --source path/to/source.py --no-report
   ```

   Add `--suggest-sources` when you need candidate tests for a new or changed
   source owner. For several related files, pass multiple source paths or use
   the directory form:

   ```bash
   venv/bin/python run.py traceability --source path/to/first.py path/to/second.py --no-report
   venv/bin/python run.py traceability --source path/to/folder --suggest-sources --no-report
   ```

2. Open the source symbol and read what it actually does.
3. Read its `@testable`, `@tests`, `@scaffolding`, `@features`,
   `@dimensions`, `@pair`, `@covered-by`, and `@reason` tags.
4. Open every referenced test, including tests matched by globs and tests
   inferred from any referenced scaffold helpers.
5. Check each declared `feature:dimension` pair against real assertions or E2E
   observations in the referenced tests.
6. Prefer fixing misleading annotations over adding more tags.

Ask these questions:

- Is this source symbol really the behavior owner?
- Should this helper point to a more load-bearing symbol with `@covered-by`?
- Does each referenced test assert the behavior, or does it merely execute the
  code along the way?
- Are the features broad and the dimensions reusable? Use exact `@pair` tags
  when separate feature/dimension lists would imply combinations the symbol
  does not own.
- Would the report tell a future reader where to focus?

## E2E Source Ownership

E2E tests often cover a full route/template/JavaScript/helper workflow. Do not
let that breadth push all tags onto the route or exported JavaScript class.
Point the precise `feature:dimension` pair at the symbol that determines the
behavior.

Use this ownership order when reviewing an E2E annotation:

1. The behavior owner gets the precise source tags. For access restrictions,
   this is usually the property, permission/access method, route branch, or
   JavaScript event/request method that makes the behavior true.
2. Route functions, templates, and exported JavaScript classes can own broad
   rendering or workflow contracts, but they should not collect every downstream
   dimension just because the E2E test passes through them.
3. Test helper methods in `testing/resources` or `testing/elements` can be
   referenced with `@scaffolding` when the helper is the place where the E2E
   interaction is exercised. The helper should stay unannotated; the focused
   test body is the evidence that it is used.

Some UI expectations are owned by Jinja templates, generated markup, or styles
that are outside the source-symbol inventory. Do not move those expectations to
an incidental route or JavaScript method just to make the focused report clean.
Use `@template` on the test when the template contract is the best pointer, keep
route/class tags to the broader render or workflow contract they truly own, and
leave a visible gap or `@todo` when the source inventory cannot yet name the
real owner.

When a route, class, or widget has a long list of explicit `@tests`, pause and
review the shape:

- If the symbol truly owns a whole file or folder-level workflow, prefer a
  focused nodeid glob such as `@tests tests_e2e/003_forms/test_003c_*` or
  `@tests tests_e2e/003_forms/*`.
- If only some dimensions belong to that symbol, split the annotation. Keep the
  broad route/class tags broad, then annotate behavior-owning children or
  backend properties with the precise dimensions and representative tests.
- If the source is JavaScript and the relevant E2E evidence lives in a page
  resource helper, use `@scaffolding testing/resources/...::Helper.method`
  on the JavaScript method. Do not add nodeid comments to the helper.
- If a JavaScript widget owns real browser behavior that is not represented
  yet, add a focused `@pytest.mark.unfinished` E2E stub in the nearest test
  file and point the behavior-owning source method at that unfinished test. For
  broad orchestrators, keep the class `@testable infrastructure` and put the
  unfinished tags on the smaller stage/action methods.
- Treat `--source --suggest-sources` results for generic JavaScript lifecycle
  names (`create`, `update`, `render`, `activate`, etc.) as low-confidence
  unless they include stronger evidence such as a shared `feature:dimension`,
  explicit source path mention, shared `@template`, or a specific widget/path
  context. These generic-name filters live in `traceability.yaml` under
  `suggestions`, and the default config suppresses those weak suggestions.

For example, a forms route may reasonably point at a file glob for the builder
page workflow, while `RestrictedTo`, `Entity.restricted_access`,
`FormIndex.forms`, and `FormSettings._addRestriction` carry the narrower
restriction, owner-only, group-only, or index-filter tags.

For reusable Python mixins, prefer a class-level `@testable infrastructure`
decision when the mixin defines a protocol used by many concrete properties.
Keep direct method annotations for distinct mixin-owned behavior. For concrete
subclasses that rely on inherited mixin behavior, make the subclass the visible
contract and use a representative test pointer or focused glob such as
`@tests tests_unit/test_003a_submission_basic.py::*`. The mixin remains easy to
find in the class definition, and the subclass tells the roadmap which tests
exercise that inherited behavior. Do not create synthetic child tags just to
name every inherited getter/setter.

## Outcomes

### Existing Coverage Is Good

Leave the tags alone. If a referenced test is representative rather than
exhaustive, that is fine. This tool is informational.

### Minor Gap

If the test mostly covers the source behavior but misses a small edge case, add
`@todo` to the relevant test.

```python
# @features cache
# @dimensions redis-connection
# @todo cover cache index recreation after cleanup/reset
def test_cache_setup():
    ...
```

Do not add a new source dimension for every tiny missing branch. Use `@todo`
when the existing feature/dimension pair is still the right description.

### Major Gap

If important changed behavior is not covered, make the gap visible without
pretending it is covered.

Preferred pattern:

1. Add a focused new dimension to the source symbol.
2. Leave the existing `@tests` list pointing only at tests that currently
   provide real coverage.
3. Add an `@pytest.mark.unfinished` test stub with matching `@features`,
   `@dimensions`, and a clear `@todo`.
4. Run `venv/bin/python run.py traceability --changed --check`.

Because the unfinished stub is not referenced by the source yet, the reporter
will continue to show the missing `feature:dimension` pair as a gap. The stub
records the intended future test.

```python
# Source annotation
# @testable true
# @tests tests_unit/test_permissions.py::test_allowed_action_lattice
# @features permissions
# @dimensions action-lattice owner-override
def allowed(...):
    ...
```

```python
import pytest


# @features permissions
# @dimensions owner-override
# @todo assert owner-specific resource access before inherited fallback
@pytest.mark.unfinished
def test_allowed_owner_override():
    pass
```

When the test is implemented, remove `@pytest.mark.unfinished`, add real
assertions, add the new nodeid to the source `@tests` list if it is not already
covered by a glob, and rerun the report. The gap should disappear.

Alternate pattern: if you intentionally reference an unfinished stub from
`@tests`, the reporter will treat it as unfinished coverage rather than a
feature/dimension gap. Use that only when unfinished coverage is the clearer
signal.

## What Not To Do

- Do not tag a test with a feature/dimension pair just because it executes the
  source symbol.
- Do not add many features and dimensions to one symbol to describe every
  downstream workflow.
- Do not use `@covered-by` as a dumping ground. Point to the best behavior owner.
- Do not add a skipped or unfinished test just to silence the report.
- Do not remove a source dimension because it is inconvenient if it describes a
  real missing expectation.

## Finish

Before stopping, run the focused source report for the files or folders you
touched:

```bash
venv/bin/python run.py traceability --source path/to/source.py --no-report
```

Run the full report only when the change spans several areas or you want final
repository-wide verification:

```bash
venv/bin/python run.py traceability --changed --check
```

Unfinished coverage and TODOs are grouped by folder in the verbose report.

If you added or changed tests, run the narrow relevant pytest command as well.
For unfinished stubs, confirm they are marked `@pytest.mark.unfinished` so the
default test run does not try to execute placeholder work.
