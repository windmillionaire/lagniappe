# Frontend Build

Rollup bundles authored TypeScript and CSS from `src/` into
`lagniappe/web/static/`. The build also generates server-side style maps,
service-worker metadata, and stable cache generations.

Rollup owns the files listed in `build.json`. Edit their inputs under `src/`
or `build/`. The same static directory also contains tracked files such as
`404.html`, PWA branding and site artwork.

For styles, icons, and linting, read
[INFRA_BUILD_STYLES.md](INFRA_BUILD_STYLES.md).

## Commands

```bash
npm run dev
npm run build
npm run typecheck
```

Development output is readable and tagged with mode `development`. Production
output is minified, enforces startup budgets, records mode `production`, and
may upload hidden JavaScript source maps when `SENTRY_AUTH_TOKEN` is present.
Development builds use a fresh build ID. Distributable production builds derive their ID from the frontend source digest, including the templates scanned by Tailwind. Local Sentry source-map uploads get a fresh ID. Both write bundle analysis under `reports/`.
The application version in build metadata comes from `package.json`, even when
local generated settings still describe an earlier release. Production bundle
version replacements and Sentry releases use that same package version.

`build/rollup.shared.mjs` owns the common login, monitoring, and main bundle
construction: registry-derived inputs, output names, browser resolution,
type stripping for `.ts` and `.mts`, warning handling, chunk versioning, and
artifact recording. Run `npm run typecheck` for compile-time diagnostics.
The shared config creates fresh
plugins for each standalone entry. Standalone login and monitoring bundles inline
dynamic imports to preserve their single-file output when dependencies add lazy
modules. `rollup.dev.config.mjs` and
`rollup.config.mjs` keep their ordered mode-specific plugins and version values
explicit, including CSS transforms, minification, source maps, startup budgets,
Sentry uploads, and visualizer options. Publication still runs through
`build/run-rollup.mjs` and `build/publication.mjs`.

## Browser endpoints

Flask's registered routes supply the paths in `src/script/generated/endpoints.ts`.
The template in `build/browser-endpoints.ts.jinja` maps the existing browser
helper names and arguments to Flask endpoint names. Bind path arguments by
their Flask names. The template adds client-side query strings to those paths.
Application modules import `ENDPOINTS` from `src/script/shared/endpoints.ts`.

Regenerate the module before building the frontend after a bound route or the
template changes.

```bash
venv/bin/python -m runner.browser_endpoints
npm run build
```

The generator loads the Flask URL map with the offline test fixture. Node
builds consume the committed TypeScript output. Use
`venv/bin/python -m runner.browser_endpoints --check` to check the working
tree. `run.py release-check` checks the Flask routes and output in the Git index.

## Polling and external API schemas

Run `venv/bin/python -m runner.wire_contracts` after changing a polling model or
an external Plan contract. It writes the TypeScript types and validation fields
in `src/script/generated/poll.ts` from the server's polling contract and payload
models. It also writes `mcp/src/lagniappe_mcp/wire_schemas.json` from the Flask
OpenAPI for the actor, answer context, Plan, files, submission receipt and
lifecycle request and response schemas.
The standalone MCP package reads these schemas and selects its public fields.

Run the same command with `--check` to verify the working tree. The release
check runs both generators against the staged sources and outputs.

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
Its precache requests use normal HTTP cache semantics, allowing a fresh response
from an HTML preload to be reused. Changed builds use distinct URLs; stale HTTP
responses still follow the server's revalidation policy.
Assets already present in the worker's static cache are skipped during precache.

`build.json` is the build completion marker. It records the application
version, build ID, build mode, a digest of all declared frontend sources, and
the path, size, and digest of every published artifact. The inventory includes
nested chunks, fonts, PDF.js assets, the service worker, and the generated
Python style/icon registries. The runtime reads the build ID from this marker
for template URLs and ETags. Local application settings must not define
`BUILD_ID`.

The build wrapper generates the tracked JavaScript/Python registries before
recording the source digest, then removes the previous completion marker before
Rollup starts.
It publishes the new `build.json` after every Rollup entry,
optional Sentry upload, and output check succeeds, and only if the authored
source digest is unchanged. A failed or interrupted build therefore leaves no
apparently complete marker; the next managed build repairs it.

## Entry points and chunks

| Entry point | Output | Responsibility |
| --- | --- | --- |
| `src/script/main.ts` | `script.js` and chunks | Private application and interactive public pages. |
| `src/script/public.ts` | `chunks/views/public.js` | Minimal native-share behavior for anonymous public documents. |
| `src/script/login.ts` | `login.js` | Identity Platform REST client and login forms. |
| `src/script/sentry.ts` | `sentry.js` | Conditional local browser monitoring SDK. |

`src/script/viewRegistry.ts` is the source of runtime view selection and
stable named entries under `chunks/views/`. Rollup derives feature chunks from
module boundaries. Editor, PDF, modal, combobox, offline, sync, notification,
and similar code stay lazy until their owning surface requests them.

Stable feature groups in `build/utility.mjs` collect modules used together;
source files and widget activation remain independent. Common code is shared,
not copied between route bundles.

| Group | Contents / loading policy |
| --- | --- |
| `foundation`, `core-foundation`, `entity-foundation`, `index-foundation` | Stable route foundations. Storage/query lifecycle helpers join the shared foundation. |
| `ui-resources`, `ui-controls` | Generated style/icon resources; shared primitives, buttons and formatting. |
| `combobox` | Search, dropdowns, entity menus and Floating UI; preloaded on layouts with navigation search. Location lookup stays separate. |
| `forms` | Common form infrastructure, simple/choice fields, picker adapters and Form creation. Search alone does not import this group. |
| `form-sections`, `form-complex`, `permissions` | Entity-form sections; table/todo/signature fields; permission controls. Loaded by their owning form. |
| `document`, `editor-dialogs` | Shared document engine/toolbar; optional dialogs including AI generation. History remains separate so its toolbar control does not pull in dialogs/uploads. |
| `uploads` | Shared upload UI, File/Ingress upload widgets and Plan creation. Low-level direct-upload transport stays independent. |
| `page-tools`, `project-tools`, `home-tools` | Their routes preload these tools. Page tools include photo/document settings; Project tools include model tasks. |
| `task-tools`, `user-tools` | Task form/history/settings/list tools on demand; User Index creation/permissions tools. Personal user settings stay separate. |
| `index-tools`, `filters` | Table display, sorting, columns and mobile controls on table-index routes; filter tools on demand. Inline editing stays separate. |
| `admin-tools`, `builder-controls` | Preloaded only on their Admin/Builder routes. Builder HTML controls remain lazy. |
| `offline-replay`, `account` | Queue/replay helpers and account utilities retain their existing lazy activation. The tiny offline-work probe, polling and sync remain independent. |

Page HTML also preloads forms and the document; Project HTML preloads the
document. User Index preloads its tools and forms when its tools are available.
Hints prepare modules without executing them or initializing hidden widgets.
PDF support and monitoring keep their separate lazy boundaries. Preloading is
not a service-worker bypass: matching build-versioned requests reuse the
browser HTTP cache or service-worker Cache Storage through the normal paths.

The production build enforces these startup limits.

| Budget key | Measured closure | Limit (KiB) |
| --- | --- | ---: |
| `main` | Main entry alone, including upstream failure recovery | 52 |
| `shell` | Main plus a shell view | 72 |
| `core` | Main plus a Core view other than Page | 148 |
| `page` | Main plus the Page view | 160 |
| `builder` | Builder view | 332 |

`build/startupBudget.mjs` measures deduplicated minified static imports and
fails when a closure exceeds its budget. These limits are reviewable guardrails:
shared-resource and choice-field consolidation justified modest increases to
the Core and Builder limits. Compare the actual route preload union as well as
the static entry closure before changing them. It also prevents heavy interactive
systems such as sync, edit reconciliation, modals, notifications, and combobox
from entering every Core view's static closure.
The edit-reconciliation guard covers the whole `forms/revisions/` directory,
including the watcher, reconciler, review modals, and preview adapter. These
modules remain available through the lazy `ensureEditWatcher()` service.

## Production behavior

`build/rollup.config.mjs` adds:

- esbuild minification with legal comments removed;
- Tailwind processing and cssnano;
- production build metadata and the startup budget;
- a Rollup visualizer at `reports/bundle-stats.html`;
- content-addressed text webfonts and the Material Symbols subset;
- versioned chunk imports and service-worker precache entries; and
- optional hidden Sentry source maps.

When `SENTRY_AUTH_TOKEN` is configured, Rollup uploads hidden JavaScript source
maps and removes them from static output. Without a token, source-map creation
and upload plugins are disabled. Sentry names the uploaded release from the
`package.json` version, independent of the version currently deployed from the
checkout's application settings. CSS source maps are not emitted.

## Development behavior

`build/rollup.dev.config.mjs` keeps JavaScript readable, omits cssnano and
Sentry upload, and writes `reports/bundle-stats-dev.html`. Its timestamp version
is a frontend constant only; the configured application version is unchanged.

Managed test startup validates the shared source/artifact manifest and records
the accepted development state in `reports/test-frontend-bundle.json`. It
preserves a coherent, current production build. Missing, corrupt, or stale
output—including an old production build after source changes—is replaced by a
development build. The source contract includes fonts and third-party license
inputs as well as scripts, styles, and build configuration. The same
interprocess lock guards build preflight and browser test sessions.

## Build plugins

The custom plugins in `build/utility.mjs` enforce one artifact contract:

- `versionChunkImports(buildId)` adds the build query to generated imports
  without renaming files.
- `updateServiceWorker(buildId)` compiles `sw.template.ts` with the browser
  protocol, dynamic precache URLs, and build ID, then writes `sw.js` atomically.
- `recordBuildArtifacts(...)` collects every Rollup output across all entry
  configurations. The build wrapper validates that inventory and publishes the
  completion marker last.
- `emitFonts()` emits vendored text and icon WOFF2 files under filenames
  derived from their digests and removes obsolete published fonts.
- `resolveFonts()` rewrites stable authored font URLs to those generated
  assets. Registry generation emits their matching Jinja preload URL map.
- `generateStyleModules()` validates and writes matching JavaScript and Python
  registries. `buildStyles()` invokes the same idempotent step for direct Rollup
  callers. See
  [INFRA_BUILD_STYLES.md](INFRA_BUILD_STYLES.md).

Both Rollup configurations suppress dependency warnings for `eval` inside
packages and the known `y-prosemirror` circular dependency. New warnings from
application modules should remain visible.

## Release boundary

The **Frontend bundle** workflow builds a production ZIP when frontend inputs
change on `next/*` or `hotfix/*`. It publishes the ZIP as an asset on the
`frontend-<full source SHA-256>` GitHub prerelease. The build ID, archive
members and timestamps are deterministic, so a retry can verify the existing
asset. Pull requests run the build and retain a downloadable Actions artifact.

A clean owner installation retrieves the ZIP using Python. The installer checks
its SHA-256, source identity, version and every file in `build.json` before
installing the static files. Saved copies live in `reports/frontend-bundles/`.
The PWA manifest and site artwork are installation-owned. Python style bindings
are included in the ZIP and checked against their tracked copies.

At release freeze, record the published archive digest and check the staged tree.

```bash
venv/bin/python -m runner.frontend_bundle pin
git add config/frontend-release.json
venv/bin/python run.py release-check --base origin/main
```

A backend-only change can reuse the same pin. Hosted E2E installs the pinned
archive in its exported Git tree before building either hosted artifact. The
approved release publisher attaches that same ZIP to the versioned release.

For a local rehearsal, `npm run build` followed by
`venv/bin/python -m runner.frontend_bundle pack` prints the ZIP path.
`pin --archive PATH` can bootstrap the first pin before branch publication.
Copy a pinned ZIP into a fresh checkout's `reports/frontend-bundles/` and run
`venv/bin/python -m runner.frontend_bundle sync` to verify and install it offline.

[Hosted E2E](TESTING_HOSTED_E2E.md) · [Deployment](INFRA_DEPLOYMENT.md)
