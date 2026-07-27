# Style Traceability Migration Ledger (Archived)

Status: completed on 14 July 2026 and archived as implementation history.

This records the completed no-visual-change migration. For current architecture
and commands, use [INFRA_BUILD.md](../INFRA_BUILD.md),
[TESTING_TRACEABILITY_TOOL.md](../TESTING_TRACEABILITY_TOOL.md), and
[STYLE_CANDIDATES.md](../STYLE_CANDIDATES.md).

## Goal

Starting from a semantic UI role, a developer or agent should be able to find:

- its typed `styles.yaml` record, intent, and server/frontend consumers;
- behavior markers and authored CSS hooks;
- the exact CSS rules and stylesheet ownership class that contribute to it;
- the Python and virtual-JavaScript runtime values;
- whether each utility token is understood by the real Tailwind design system;
- template-contract or explicit test evidence and whether that result is current;
- aliases, deliberate equal-value exceptions, and cleanup candidates.

The registry describes semantic ownership. Structural layout, pseudo-elements,
animations, editor internals, design tokens, and third-party CSS remain CSS.

## Implementation ledger

Implemented on 14 July 2026:

- `src/style/registry.schema.json` is the shared Python/Node contract. Every
  record has exactly one of `classes`/`alias`, a nonblank intent, declared
  surfaces, and validated optional markers, hooks, CSS owners, and targeted
  exceptions.
- Registry IDs use lower-camel path segments. Redundant `default`/`element`/
  `cell` nesting and stale leaves were removed; the only one-child namespace was
  flattened. Runtime consumers were migrated directly because compatibility is
  not required before publication.
- All active records have observed-surface metadata. The current registry has
  229 used definitions, no unused definitions, no unknown references, no
  cross-surface extensions, and no unexplained equal-value groups.
- Equal roles use aliases (`modal.actions -> filters` and the project editor
  toolbar container). Distinct roles with equal current values use exact
  `duplicate-style-value` exceptions naming the peer and reason.
- The old `custom.css` has been split, in original cascade order, into focused
  structural and semantic stylesheets. `pipeline.json` classifies every authored
  CSS input as pipeline, structural, semantic, theme, editor, asset, or vendor.
- Semantic CSS uses local `/* @style ... */` owners. Registry hooks must be
  emitted, resolve to an owned selector, and link back to each contributing
  stylesheet. Semantic-classified selectors without an owner are errors.
- DOM/JavaScript markers are distinct from CSS hooks. This lets behavior APIs
  such as `form-element` remain discoverable without pretending they emit CSS.
- The candidate validator loads `main.css` with Tailwind's own design-system
  API. All 441 current registry candidates compile or are declared markers/CSS
  hooks. This pass removed inert `search-result`, `space-between`, `prose`, and
  `prose-slate` tokens without changing generated CSS.
- Python generation, the virtual JavaScript module, and the style reporter use
  the same normalization rules and schema. Generated Python parity is a hard
  check.
- `icons.yaml` now follows the same lower-camel ID convention. Its shared
  `icons.schema.json` validates IDs and Font Awesome values in Node and Python;
  all 159 definitions have runtime consumers, and generated Python parity is a
  hard check.
- The style manifest schema is version 3. Its 415 authored selectors include
  rule fingerprints, owner IDs, at-rule context, and ownership class. Style
  fingerprints combine the independent registry-record fingerprint with owned
  rule fingerprints.
- Test-result snapshots include virtual `@style/<id>` fingerprints. A registry
  edit invalidates evidence for the changed record rather than every style in
  the YAML file; owned CSS is conservatively invalidated by stylesheet.
- Tests may declare `@style semantic.id`. Template-contract tests are also
  linked automatically when a style consumer is inside the referenced or
  included macro. The current manifest has roughly 380 representative evidence
  links across more than 120 semantic styles.
- Normal `traceability --changed --check` folds in the style graph whenever
  style sources or consumers changed. A no-focus traceability run includes the
  complete template/style/icon contract inventory. Explicit style queries show
  consumers, fingerprints, and current/stale evidence.
- The standalone style-audit surface and module name are gone. Advisory parsing
  now lives in `testing/utility/style_candidates.py`; interpretation guidance is
  in [STYLE_CANDIDATES.md](../STYLE_CANDIDATES.md).

## Ownership rules

### Registry

Use a semantic record when a role is shared across server and frontend code, is
a durable component/control, or needs a stable CSS/behavior hook. Prefer names
that describe UI responsibility. Add a named variant when the same meaningful
suffix recurs but does not belong on every base use.

### Local utilities

Keep short conditional state, responsive placement, and one-off relationships
local: `hidden`, `opacity-50`, `pointer-events-none`, `mt-4`, or a page-specific
basis are usually clearer at the call site. Repetition is review evidence, not
proof of global ownership.

### CSS

Keep CSS for pseudo-elements, animations, editor/third-party integration,
compound data/ARIA/descendant selectors, media behavior, and design tokens. A
reusable selector hook still needs a semantic registry owner; structural,
theme, editor, asset, and vendor rules are classified rather than forced into
the semantic graph.

## Enforcement

Errors:

- invalid records, IDs, aliases, exception targets, or declared surfaces;
- unknown consumer references or CSS owners;
- hooks/markers not emitted, hooks without owned rules, or backlinks that
  disagree;
- unowned selectors in semantic stylesheets;
- Tailwind candidates that neither compile nor declare a hook/marker role;
- pipeline input/import/transform drift or generated Python mismatch;
- changed styles whose declared evidence has no current passing result.

Warnings:

- truly unused semantic records;
- unreachable or multiply imported authored stylesheets.

Review findings:

- repeated local extensions and raw strings;
- generic raw fragments that happen to match a semantic record;
- changed roles without component-level evidence.

## Advisory baseline at completion

These counts are deliberately not cleanup targets:

- 33 repeated single-surface extensions;
- 120 long and 119 repeated raw class strings;
- 12 raw strings that mechanically match registry values.

Most exact matches are generic fragments such as `text-kind-default`,
`font-semibold`, or `flex flex-col gap-2`; replacing them with an unrelated
semantic owner would reduce a count while making the code less clear. The
remaining repeated extensions are predominantly local state or layout. Review
them family by family when that UI is already being changed.

## Validation recorded at completion

The results below are historical migration evidence, not a statement about the
current working tree or release test status.

- `npm run dev` regenerated the Python style map and frontend assets.
- The explicit style check reports 229/229 used definitions, 441 validated
  candidates, 159/159 used icon definitions, 415 authored selectors, no
  errors, and no warnings.
- Focused tooling/style checks, template contracts, the complete tooling,
  JavaScript, and unit suites passed.
- The split CSS, concatenated in import order and stripped only of comments,
  is byte-identical to the old `custom.css`; declarations and cascade order did
  not change.
- The single-threaded full E2E run exposed a collaborative-sync/persistent-submit
  ordering race. The follow-up made the form flush pending sync before its PUT;
  a DOM-free Node regression test and the focused signature asset-lifecycle
  story then passed.

Future optional refinements, not blockers:

- improve generic intent wording when individual component families are next
  reviewed;
- add direct `@style` evidence for more JavaScript-created/responsive states;
- consider selector-level CSS snapshot keys if whole-stylesheet invalidation
  proves too coarse in practice;
- revisit utility-heavy roles only after ownership data shows a concrete
  maintenance benefit. Shared server/frontend strings and small Tailwind tweaks
  remain valuable and should not be discarded merely to reduce CSS/YAML mixing.
