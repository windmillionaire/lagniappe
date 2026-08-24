# Frontend Build

Rollup bundles authored JavaScript and CSS from `src/` into
`lagniappe/web/static/`. The build also generates server-side style maps,
service-worker metadata, and stable cache generations.

`lagniappe/web/static/` is disposable generated output. Change `src/`,
`build/`, or the style registries and run the appropriate build; do not edit
generated bundles. The authored runtime-free `404.html` is the sole exception.

For styles, icons, and linting, read
[INFRA_BUILD_STYLES.md](INFRA_BUILD_STYLES.md).

## Commands

```bash
npm run dev
npm run build
```

Development output is readable and tagged with mode `development`. Production
output is minified, enforces startup budgets, records mode `production`, and
may upload hidden JavaScript source maps when `SENTRY_AUTH_TOKEN` is present.
Both modes emit a fresh build ID and bundle analysis under `reports/`.

## Output

```text
lagniappe/web/static/
├── 404.html
├── script.js
├── login.js
├── sentry.js
├── style.css
├── sw.js
├── build.json
├── fonts/
└── chunks/
    ├── shared.js
    ├── views/
    └── <feature>.js
```

Chunk filenames are stable. Generated imports carry `?v=<build-id>`, so an
entry point and all of its static and dynamic imports use one cache generation.
The service worker warms those exact URLs after an update.

`build.json` records the application version, build ID, and build mode.
`config/constants.py` receives the same build ID for template URLs and ETags.
Local application settings must not define `BUILD_ID`.

## Entry points and chunks

| Entry point | Output | Responsibility |
| --- | --- | --- |
| `src/script/main.mjs` | `script.js` and chunks | Private application and interactive public pages. |
| `src/script/login.mjs` | `login.js` | Identity Platform REST client and login forms. |
| `src/script/sentry.mjs` | `sentry.js` | Conditional local browser monitoring SDK. |

`src/script/viewRegistry.mjs` is the source of runtime view selection and
stable named entries under `chunks/views/`. Rollup derives feature chunks from
module boundaries. Editor, PDF, modal, combobox, offline, sync, notification,
and similar code stay lazy until their owning surface requests them.

The main startup path has four measured closures:

| Budget key | Measured closure | Limit (KiB) |
| --- | --- | ---: |
| `main` | Main entry alone | 32 |
| `shell` | Main plus a shell view | 64 |
| `core` | Main plus a Core view | 120 |
| `builder` | Builder view | 200 |

`build/startupBudget.mjs` measures deduplicated minified static imports and
fails when a closure exceeds its budget. It also prevents heavy interactive
systems such as sync, edit reconciliation, modals, notifications, and combobox
from entering every Core view's static closure.

## Production behavior

`build/rollup.config.mjs` adds:

- esbuild minification with legal comments removed;
- Tailwind processing and cssnano;
- production build metadata and the startup budget;
- a Rollup visualizer at `reports/bundle-stats.html`;
- the content-addressed Material Symbols subset;
- versioned chunk imports and service-worker precache entries; and
- optional hidden Sentry source maps.

When `SENTRY_AUTH_TOKEN` is configured, Rollup uploads hidden JavaScript source
maps and removes them from static output. Without a token, source-map creation
and upload plugins are disabled. CSS source maps are not emitted.

## Development behavior

`build/rollup.dev.config.mjs` keeps JavaScript readable, omits cssnano and
Sentry upload, and writes `reports/bundle-stats-dev.html`. Its timestamp version
is a frontend constant only; the configured application version is unchanged.

Managed test startup hashes authored inputs and generated output. It runs the
development build only when the bundle is incomplete or stale, records the
state in `reports/test-frontend-bundle.json`, and preserves a complete
production build. The same interprocess lock guards build preflight and browser
test sessions.

## Build plugins

The custom plugins in `build/utility.mjs` enforce one artifact contract:

- `versionChunkImports(buildId)` adds the build query to generated imports
  without renaming files.
- `updateServiceWorker(buildId, version, mode)` injects the browser protocol,
  dynamic precache URLs, and build constants into `sw.template.mjs`, then
  writes `sw.js` and `build.json`.
- `emitMaterialSymbols()` emits the vendored glyph subset under a filename
  derived from its digest.
- `resolveMaterialSymbolsFont()` rewrites the stable authored font URL to that
  generated asset.
- `buildStyles()` validates the semantic style and icon registries and emits
  their JavaScript and Python representations. See
  [INFRA_BUILD_STYLES.md](INFRA_BUILD_STYLES.md).

Both Rollup configurations suppress dependency warnings for `eval` inside
packages and the known `y-prosemirror` circular dependency. New warnings from
application modules should remain visible.

## Release boundary

Development occurs on `next/<version>` or `hotfix/<version>` branches. At
release freeze, run one canonical dependency install and production build:

```bash
npm ci
npm run build
venv/bin/python run.py release-check --base origin/main
```

Commit the generated output and test the complete candidate before merging its
release pull request. The release gate requires committed production metadata;
a development build cannot pass.

Hosted E2E exports an exact clean commit with production output, deploys that
commit without rebuilding, and imports evidence for the same source tree. See
[TESTING_HOSTED_E2E.md](TESTING_HOSTED_E2E.md) and
[INFRA_DEPLOYMENT.md](INFRA_DEPLOYMENT.md).
