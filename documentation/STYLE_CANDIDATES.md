# Style Candidate Review

Use this guide for the advisory cleanup candidates emitted by style
traceability. The registry, compiled-candidate, CSS-ownership, build-parity, and
unknown-reference findings are contracts; repeated or long strings are prompts
for semantic review, not automatic rewrites.

```bash
venv/bin/python run.py traceability --styles
venv/bin/python run.py traceability --style dropdown.panel
venv/bin/python run.py traceability --style-source src/style/navigation.css
venv/bin/python run.py traceability --style-consumer src/script/widgets/home/tasks.mjs
```

The default run writes `reports/style-traceability.md` and the machine-readable
`reports/style-manifest.json`. Generated static bundles are deliberately out of
scope.

## Review order

1. Resolve schema, alias, unknown-reference, declared-surface, CSS-owner,
   compiled-candidate, and generated-registry errors.
2. Remove definitions only after dynamic family use and both consumer surfaces
   have been checked.
3. Review repeated extensions. Add a semantic variant when the suffix describes
   a recurring role; keep conditional state and local placement at the call
   site.
4. Review exact raw matches in context. Generic fragments can coincidentally
   match a semantic style and should not inherit an unrelated owner.
5. Resolve equal registry values with an alias only when the roles are the same.
   Otherwise use a targeted `duplicate-style-value` exception with a reason.

## Registry ownership

Every leaf in `src/style/styles.yaml` is a typed record:

```yaml
dropdown:
  panel:
    classes: absolute z-50 hidden
    intent: floating option panel shared by combobox variants
    surfaces: [frontend]
```

Optional metadata has distinct meanings:

- `markers` are emitted DOM/JavaScript behavior markers that do not generate
  Tailwind output;
- `hooks` are emitted classes backed by authored CSS selectors;
- `css` lists the authored stylesheets containing `/* @style ... */` rules;
- `alias` shares another semantic role's emitted value;
- `exceptions` suppress one exact diagnostic against one named target.

Short state classes such as `hidden`, `opacity-50`, and `pointer-events-none`
usually remain local. Long utility strings belong in the registry when they
name a durable component role, especially when server and frontend code must
construct the same element.

## CSS ownership

`src/style/pipeline.json` classifies every authored stylesheet. Files classified
as `semantic` require each selector to have a nearby `/* @style id */` owner.
Structural, theme, editor, asset, and vendor rules stay visible in the manifest
without being forced into semantic records. A semantic record that emits a CSS
hook must link back to every contributing stylesheet.

The candidate validator loads `src/style/main.css` through Tailwind's own design
system. Registry tokens must compile or be declared as a behavior marker or CSS
hook. This catches misspelled and inert utility tokens without reading generated
static output.

## Evidence and handoff

Template-contract tests are linked to styles consumed inside their referenced
macros. Use `@style semantic.id` on a test for a direct component, state,
responsive, or JavaScript-created contract. Test-result snapshots contain
per-style fingerprints, so changing one registry record invalidates only its
declared evidence; owned CSS remains conservatively invalidated by stylesheet.

After a style change:

```bash
npm run dev
venv/bin/python run.py traceability --styles --check --fail-on warning
venv/bin/python run.py test testing/tests_tooling/test_006_style_traceability.py
venv/bin/python run.py test testing/tests_js/test_018_style_pipeline.py
venv/bin/python run.py template-contracts --changed --check
venv/bin/python run.py traceability --changed --check
```

Report intentional advisory leftovers by semantic role and reason. Do not use a
lower candidate count as evidence that the cleanup was correct.
