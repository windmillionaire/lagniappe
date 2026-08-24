# Styles, Icons, and Source Linting

The frontend style system combines authored CSS with semantic style and icon
registries. One validated source feeds JavaScript, Python/Jinja, Tailwind, and
traceability checks.

## Source layout

| Source | Responsibility |
| --- | --- |
| `src/style/main.css` | CSS entry point and imports. |
| `src/style/*.css` | Global, component, interaction, editor, and responsive rules. |
| `src/style/styles.yaml` | Semantic Tailwind class records. |
| `src/style/icons.yaml` | Semantic Material Symbols records. |
| `src/style/icons.schema.json` | Icon ID and record contract. |
| `src/style/pipeline.json` | Registries, CSS inputs, generated maps, and transforms used by both build modes. |

Prefer the narrow stylesheet that owns a component or behavior. `icons.css` is
the sole owner of icon box geometry, glyph size, line height, and optical
offsets. Component styles may position, color, stack, or hide icons without
redefining that geometry.

## Semantic style records

Leaves in `styles.yaml` are typed records:

```yaml
button:
  submit:
    classes: "..."
    intent: primary form submission action
    surfaces: [server, frontend]
    hooks: []
```

Use an `alias` instead of `classes` when two semantic roles intentionally share
one runtime value. The build rejects untyped leaves, unknown fields, invalid
metadata, missing targets, and alias cycles. After validation, consumers see a
plain string-valued `STYLES` tree.

Not every repeated class string belongs in the registry. Keep local spacing,
responsive, state, and entity-kind variants inline until they represent a
stable reusable role. See
[INFRA_BUILD_STYLE_REVIEW.md](INFRA_BUILD_STYLE_REVIEW.md) when
reviewing advisory extraction findings.

## Semantic icon records

Icon IDs use lower camel case. Each leaf contains a snake-case Material Symbols
`glyph`, an explicit `fill`, and optional validated `weight` or `spin`.
Application code passes the semantic ID to Jinja `render_icon()` or frontend
`createIcon()` / `setIcon()`; it does not use glyph names or library classes.

Rendered markup has an outer `.icon` box and an `.icon-glyph` child. Contextual
`icon-xs` through `icon-2xl` modifiers scale intentionally, while semantic
optical exceptions use `data-icon` selectors in `icons.css`.

The font source and glyph registry are committed under `src/fonts/`. The build
emits the subset with a digest-derived filename so any glyph change creates a
new cache identity.

## Generated consumers

`buildStyles()` in `build/utility.mjs` creates separate virtual `"styles"` and
`"icons"` modules for Rollup. During `generateBundle()` it writes matching
Python dictionaries to:

```text
lagniappe/web/start/styles/styles.py
lagniappe/web/start/styles/icons.py
```

The YAML records are therefore the source of truth on both browser and server
surfaces. Generated Python files are parity artifacts, not edit targets.

## Style and icon checks

Run:

```bash
venv/bin/python run.py traceability --styles
```

The reporter checks:

- known and used style keys;
- repeated extensions and raw-class extraction candidates;
- aliases and duplicate values;
- stylesheet classification and selector ownership;
- Tailwind source reachability and candidate compilation;
- icon schema, consumer coverage, and generated-map parity; and
- template-contract and explicit `@style` test evidence.

Normal runs write `reports/style-traceability.md` and the versioned
`reports/style-manifest.json`. `--json` emits the shared traceability envelope;
`--no-report --no-manifest` provides a console-only pass.

## JavaScript, CSS, and JSON

Biome owns formatting, linting, and import organization for authored files in
`src/script/`, `src/style/`, and `build/`. Generated static output is excluded.

```bash
npm run check
npm run format
```

`npm run check` is non-mutating. `npm run format` writes formatting changes.
The project permits descending specificity and `!important` where state,
responsive, and editor rules require them.

## Python

Ruff performs focused correctness linting and is not the Python formatter:

```bash
venv/bin/python -m ruff check .
```

Its configuration is in `ruff.toml`, targets the project's minimum Python
runtime, and exempts package facades where re-exports require unused or late
imports. Keep the pinned version in `requirements-dev.txt` synchronized with
the repository lock state.

## Change checklist

When adding or changing a shared style or icon:

1. Update the semantic YAML record and its intent metadata.
2. Use the semantic key on each server or frontend surface.
3. Put geometry or behavior in the owning authored stylesheet.
4. Run `npm run dev` to validate and regenerate maps.
5. Run `venv/bin/python run.py traceability --styles`.
6. Add or update focused UI evidence when the rendered contract changes.

For build modes, bundles, cache generations, and releases, see
[INFRA_BUILD.md](INFRA_BUILD.md).
