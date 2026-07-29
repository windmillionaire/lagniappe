# Infrastructure Build System

The build system (`build/`) uses Rollup to bundle the frontend JavaScript and CSS from `src/` into production-ready assets in `lagniappe/web/static/`. Two custom Rollup plugins bridge the frontend and backend by generating shared style constants and processing the service worker.

## Output Structure

```
lagniappe/web/static/
  ├── script.js              # Main app bundle (ESM)
  ├── login.js               # Login bundle (ESM)
  ├── sentry.js              # Conditional browser monitoring bundle (ESM)
  ├── style.css              # Extracted + minified CSS
  ├── sw.js                  # Service worker (from template)
  ├── chunks/                # Code-split chunks
  │     ├── shared.js        # Shared utilities (forced chunk)
  │     └── [name].js        # Lazy-loaded view/widget/element chunks
```

Chunk filenames remain stable on disk, while every generated inter-chunk import
includes the current build ID (for example,
`./chunks/shared.js?v=b824d23e`). The entrypoint and all of its static and
dynamic chunks therefore use one cache generation during a service-worker
update.

`lagniappe/web/static/` is generated build output even though parts of it are
tracked. Do not edit static bundles directly. After source changes that need to
ship generated assets, run `npm run dev` or `npm run build` in an intentional
build-output pass.

### Pull request ownership

Tracked generated output is maintainer-owned. Contributor PRs contain authored
source only and target the active `next/<version>` branch, even when
contributors build locally for testing.
`venv/bin/python run.py pr-clean` restores disposable build output to the PR
merge base, removes untracked build files, and restores only `BUILD_ID`.
Pass `--keep-build` to remove generated paths only from Git's prospective
commit/index while leaving the local build available for testing.
`venv/bin/python run.py pr-check` compares that prospective commit with
an explicit `--base origin/next/<version>` and rejects changes under
`lagniappe/web/static/`, generated Python style maps, installation-local
`config/files/`, the generated root `lagniappe.yaml` and `index.yaml`, and
build-only `BUILD_ID` churn. Unstaged and untracked local generated files are
not PR content and are ignored. The commands retain their `origin/main`,
then `main`, fallback for exceptional use, but a normal source PR should name
its exact target.

The maintainer squash-merges accepted source PRs into `next/*` without
committing their local builds. At release freeze, the maintainer runs one
canonical `npm ci` and `npm run build`, commits the fresh output to `next/*`,
and runs `venv/bin/python run.py release-check --base origin/main`. The
complete branch is installer-tested before its release PR is squash-merged
into `main`. CI therefore forbids build output in source PRs to `next/*` and
requires it in release or hotfix PRs to `main`.

When `SENTRY_AUTH_TOKEN` is configured, production JavaScript source maps are
generated as hidden Rollup outputs, uploaded to Sentry, then deleted from
`lagniappe/web/static/`. Without a token, JavaScript source maps and the upload
plugins are disabled. CSS source maps are not generated.

## Bundles

Three Rollup entry points produce independent bundles:

### Login (`login.mjs` → `login.js`)

The unauthenticated login page. Includes the focused Identity Platform REST
client and the existing custom forms, but not the Firebase Auth SDK. It remains
separate from the main bundle so unauthenticated users do not download the full
app.

### Sentry (`sentry.mjs` → `sentry.js`)

The locally bundled browser SDK and shared event-sanitization configuration.
Templates load it only when production error reporting is enabled. It reads the
installation's configured `SENTRY_JS_DSN`, keeping browser events separate from
the backend `SENTRY_DSN` without hardcoded browser loader keys.

### Main (`main.mjs` → `script.js` + `chunks/`)

The authenticated application. Code-split into chunks via Rollup's dynamic
`import()` statements. The `shared/` directory is forced into a dedicated
`shared` chunk via `manualChunks` so it's loaded once and cached across all
views. The vendored Material Symbols Rounded subset is declared by
`src/style/fonts.css`, bundled into `style.css`, and emitted with the other
self-hosted fonts under `lagniappe/web/static/fonts/`.

## Production vs Development

### Production (`rollup.config.mjs`)

Run via `npm run build`.

- **Minification**: esbuild with legal comments stripped
- **CSS**: Tailwind CSS + cssnano minification
- **Source maps**: With a nonblank `SENTRY_AUTH_TOKEN`, hidden JavaScript source
  maps are generated for Sentry upload and deleted afterward; otherwise they
  are disabled
- **Sentry**: When the upload token is present, source maps are uploaded and the
  release is tagged with `VERSION` from settings
- **Chunk names**: Stable (`chunks/[name].js`) with build-ID query strings in
  generated imports; the service worker warms those exact versioned URLs after
  update, and App Engine serves each versioned URL as long-lived immutable
- **Bundle analysis**: Generates `reports/bundle-stats.html` treemap visualization
- **Version**: `VERSION` is read from `config/files/lagniappe_settings.yaml`
- **Build ID**: A short `BUILD_ID` is generated and written to
  `config/constants.py` for cache busting
- **Build metadata**: `lagniappe/web/static/build.json` records
  `"mode": "production"` for the release gate
- **Service worker precache**: Injects the current dynamic chunk URLs so
  the service worker can warm them after an update
- **Icon font**: Emits the official Material Symbols subset with a
  content-derived filename
- **Browser protocol**: Injects `config/browser_protocol.json` into the
  standalone service-worker template

### Development (`rollup.dev.config.mjs`)

Run via `npm run dev`.

- **No minification**: Readable output for debugging
- **CSS**: Tailwind CSS without cssnano
- **No source maps**: Not needed with unminified output
- **No Sentry**: No source map upload
- **Chunk names**: Stable (`chunks/[name].js`) for easier debugging, with the
  same build-ID query-string contract as production
- **Bundle analysis**: Generates `reports/bundle-stats-dev.html`
- **Version replacement**: Timestamp-based (`new Date().toISOString()`) for dev-only frontend constants
- **Build ID**: A short `BUILD_ID` is generated and written to
  `config/constants.py` for cache busting
- **Build metadata**: `lagniappe/web/static/build.json` records
  `"mode": "development"` and cannot pass the release gate
- **Test-server freshness**: E2E and managed test-server startup hashes the
  authored build inputs plus generated outputs and runs this build only when
  that state is stale or incomplete; the local state record lives at
  `reports/test-frontend-bundle.json`

## Custom Plugins (`utility.mjs`)

### `buildStyles()`

A virtual module plugin that creates the `"styles"` import used throughout the frontend. Serves two purposes:

**JavaScript side**: When any module imports `from "styles"`, Rollup resolves it
to a virtual module containing `ICONS` and `STYLES` as JSON objects parsed from
`src/style/icons.yaml` and `src/style/styles.yaml`.

**Python side**: During `generateBundle()`, writes the same data as Python
dictionaries to `lagniappe/web/start/styles/icons.py` and `styles.py`. These
auto-generated files are used by Jinja templates server-side.

This ensures a single YAML source of truth for all style constants across both JavaScript and Python.

Icon IDs use lower camel case. Each leaf is a structured Material Symbols
record with a snake-case `glyph`, explicit `fill` value, and optional validated
`weight` or `spin`.
`src/style/icons.schema.json` is consumed by both the Node build and Python
traceability path; the build rejects invalid IDs/values, and traceability
rejects unknown consumers, unused definitions, or generated Python parity
drift.

Jinja's `render_icon()` and the frontend `createIcon()` / `setIcon()` helpers
turn records into neutral `<span data-icon>` markup. The outer `.icon` span
owns stable layout geometry, while its `.icon-glyph` child owns the rendered
font size. Application code passes semantic IDs rather than glyph names or
library classes. `icons.css` is the sole owner of `--icon-*` geometry:
semantic optical exceptions use `data-icon`, while the `icon-xs` through
`icon-2xl` modifiers provide intentional contextual scaling. Component CSS may
position, stack, color, or hide an icon, but must not replace its box, glyph
size, line height, or optical offsets. Icon-only controls consequently
shrink-wrap the icon box and add only interaction styling.

`src/style/pipeline.json` is the machine-readable contract for this path. It
names the registry and virtual module, generated Python targets, CSS entry and
output, explicit Tailwind sources, and the transforms used by each Rollup mode.
Both Rollup configurations consume the CSS output from this contract.

Leaves in `styles.yaml` are typed records rather than bare strings:

```yaml
button:
  submit:
    classes: "..."
    intent: primary form submission action
    surfaces: [server, frontend]
    hooks: []
```

An `alias` may replace `classes` when two semantic roles intentionally share a
runtime value. The build rejects untyped leaves, unknown fields, invalid
metadata, missing alias targets, and alias cycles. Normalization happens once;
the virtual JavaScript module and generated Python map receive that same
string-valued runtime tree.

### Style Traceability

Run `venv/bin/python run.py traceability --styles` when tightening shared
styles. The reporter scans source usage in `src/` and
`lagniappe/web/templates/` against `src/style/styles.yaml`; it intentionally
ignores generated static bundles and checks generated Python output only for
runtime parity.

The style graph reports:

- shared style keys that are referenced with the same extra classes in both
  Jinja and JavaScript;
- repeated single-surface style extensions;
- long or repeated raw class strings that are candidates for `styles.yaml`;
- raw class strings that already match a YAML entry and can usually be replaced
  by the shared key;
- unused YAML entries, unknown style references, and duplicate YAML values.
- authored stylesheet classifications and semantic selector ownership;
- Tailwind candidate compilation, source reachability, and Python/JavaScript
  runtime-map parity;
- icon ID/value validation, consumer coverage, and generated Python parity;
- template-contract and explicit `@style` test evidence.

Normal runs write `reports/style-traceability.md` plus the versioned
`reports/style-manifest.json`. Use `--json` for the shared traceability report
envelope, or `--no-report --no-manifest` for a console-only pass. For
candidate-review cautions, see [STYLE_CANDIDATES.md](STYLE_CANDIDATES.md).

### Biome

Biome owns formatting and linting for authored JavaScript, CSS, and JSON under
`src/script/`, `src/style/`, and `build/`. The pinned configuration excludes
generated frontend output under `lagniappe/web/static/`.

```bash
npm run check
npm run format
```

`npm run check` is non-mutating and checks formatting, lint rules, and import
organization. `npm run format` writes formatting changes only. Biome is pinned
in `package.json`; keep the lockfile in sync when upgrading it.

The CSS rules for descending specificity and `!important` are disabled
repository-wide. The authored styles intentionally use both for state,
responsive, and editor overrides, so those diagnostics do not distinguish
defects from the cascade conventions used here.

### Python lint

Ruff owns the narrow Python correctness lint in `ruff.toml`; it is not used as
a Python formatter. Run it from the project virtualenv:

```bash
venv/bin/python -m ruff check .
```

The selected rules cover import placement, invalid statement structure,
syntax-level failures, and Pyflakes findings such as unused imports and
undefined names. Python 3.12 is the lint target because it is the minimum
supported runtime. Package `__init__.py` files intentionally receive
exceptions for unused and late imports because they act as public facades or
route-registration modules. Ruff is pinned in `requirements-dev.txt`.

### `updateServiceWorker(buildId, version, mode)`

Reads `src/script/sw.template.mjs`, replaces all `__BUILD_ID__` placeholders with
the current build ID, injects the shared browser protocol plus the
Rollup-generated versioned dynamic chunk URLs into their placeholders, and
writes the result to `lagniappe/web/static/sw.js`. It also writes
`lagniappe/web/static/build.json` with the build ID, application version, and
explicit production/development mode. It runs during `writeBundle()` so the
service worker and metadata always match the current build.

### `versionChunkImports(buildId)`

Rewrites Rollup-generated static imports, re-exports, and dynamic imports so
internal chunk URLs carry `?v={buildId}`. It does not rename the emitted files.
The plugin runs before production minification so source maps include the URL
rewrite, and `updateServiceWorker()` derives its precache list from the same
build ID.

### `emitMaterialSymbols()`

Reads the vendored official registry-derived subset from
`src/fonts/material-symbols-rounded.woff2` and emits it using the first 12
hex characters of its SHA-256 digest. The source request, axes, glyph list,
upstream version, and full digest are recorded in the adjacent JSON metadata.
After Rollup writes the current asset, the plugin removes older generated
Material Symbols variants from the output font directory without touching
other fonts.

### `resolveMaterialSymbolsFont()`

Rewrites the stable authored Material Symbols URL in `fonts.css` to the
content-hashed emitted filename. This is required for a subset: adding a glyph
must not let an installation reuse an older cached font that lacks it.

## Warning Suppression

Both configs suppress two known warnings:

- **EVAL**: Suppressed for `node_modules` (Firebase SDK uses eval internally)
- **CIRCULAR_DEPENDENCY**: Suppressed for `y-prosemirror` (known circular dependency in the Yjs ProseMirror bindings)

## Settings And Build Metadata

Both configs read `config/files/lagniappe_settings.yaml` for `VERSION`; the
production config also reads optional `SENTRY_AUTH_TOKEN`. A blank or missing
token produces a normal production bundle without JavaScript source maps or
Sentry upload plugins. Each frontend build writes a fresh `BUILD_ID` to
`config/constants.py` and to `lagniappe/web/static/build.json`. The constant is
tracked with the repo so upgraded installations receive the current
cache-busting value; local app settings should not contain `BUILD_ID`.
