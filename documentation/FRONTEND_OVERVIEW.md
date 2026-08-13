# Frontend Overview

The frontend lives in `src/` and is split into two concerns: JavaScript application code (`src/script/`) and styles (`src/style/`). Rollup bundles everything into chunks that are served from `lagniappe/web/static/`.

## Entry Points

### `main.mjs` (app and public pages)

The primary entry point for logged-in users, and for public pages that need
shared infrastructure such as analytics. On DOM ready it:

1. Sets test mode when the page is served in the testing environment.
2. Sends a fire-and-forget analytics view event when analytics metadata enables it.
3. Runs `syncView()` to initialize the current view and server-health state.
4. Registers global `error` and `unhandledrejection` listeners that route to Sentry via `captureError`.
5. Registers `visibilitychange`, `focus`, `pagehide`/`pageshow`, and `online`/`offline` listeners for server health, view sync, and sync deregistration/registration. `ConnectivityState` retains separate browser, server, visibility, and service-worker-controller signals. Hiding a view suspends it directly without an unnecessary `/l/ping`; foreground transitions perform one health check and one polling catch-up.
6. Registers the service worker (`sw.js`) and publishes versioned connectivity state to its cache policy. The worker does not carry application update events.
7. Calls `updateUserData()` to sync the user's timezone and location to the server, except when `<meta name="mode" content="public">` marks a public page.

`getView()` finds the `[lp-view]` element, reads its `data-kind` attribute,
dynamically imports the matching view module from the `VIEWS` registry,
instantiates it, and calls `init()`. Search initialization happens during
`Core.init()`.

Re-initialization is handled on `pageshow` (bfcache) events, which re-check server
health and force view sync. `Core.sync()` schedules offline replay, re-registers
document/widget polling ownership, and runs one shared catch-up. Only changed
entity/collection results invoke their focused probe or refresh route.

### `login.mjs` (unauthenticated)

A separate bundle for the login page. It initializes the focused Identity
Platform REST client, selects the server-rendered login form, and coordinates
form transitions through `login:show-*` events without loading a provider-owned
Auth SDK. The client/server trust boundary, Google button iframe and CSP,
verification delivery, account states, and recovery behavior are documented in
[AUTHENTICATION.md](AUTHENTICATION.md).

### `sentry.mjs` (conditional production monitoring)

A separate local bundle for `@sentry/browser`. Production templates load it
only when error reporting is enabled. It initializes from the rendered
installation `SENTRY_JS_DSN`, explicitly disables default PII, and applies the
shared browser event sanitizer. Browser events can therefore use a separate
Sentry project from backend events.

## View Registry (`main.mjs`)

`main.mjs` contains the `VIEWS` registry that maps `data-kind` values to lazy-loaded view modules:

```
project  → views/project    (extends Entity)
page     → views/page       (extends Entity)
home     → views/home       (extends Core)
manual   → views/manual     (extends Core)
results  → views/results    (extends Core)
builder  → views/builder    (extends Core)
user     → views/user       (extends EntityIndex)
form     → views/base/index (EntityIndex)
category → views/base/index (EntityIndex)
task     → views/base/index (EntityIndex)
file     → views/file       (extends Entity)
analytics → views/analytics (lazy dashboard accordion loader)
```

When `getView()` runs, it reads `data-kind` from the `[lp-view]` element,
dynamically imports the matching module, instantiates it with the DOM node, and
calls `init()`. The active view is stored for access by the health check and
sync systems.

The manual view delegates section navigation and command-copy actions from its
stable root. Command blocks rendered by `manual/macros.html::code` therefore
keep working after AJAX section replacement. Copy uses the browser Clipboard
API first, falls back to a temporary selected textarea for older browsers, and
briefly reports `Copied!` or `Copy failed` on the originating button.

## Shared Utilities (`shared/`)

Public shared APIs are re-exported from `shared/index.mjs` as a single import
point; internal implementation modules are noted below. Modules:

| Module | Purpose |
|---|---|
| `analytics.mjs` | `analytics.tag()` and `analytics.view()` -- fire-and-forget page-load, login, and public-view tracking using metadata from the current page. |
| `connectivity.mjs` | `ConnectivityState` and the shared `connectivity` instance -- explicit browser-link, server-reachability, visibility, and service-worker-controller state. |
| `endpoints.mjs` | API route definitions, organized by widget name. Widget-specific endpoints are functions keyed by widget name (e.g. `ENDPOINTS.Filters(settings)`); global endpoints are static properties. |
| `polling.mjs` | `PollingCoordinator` -- one adaptive, visibility-aware scheduler with periodic/foreground and immediate/scheduled subscription modes for entity, channel, document, operation, form-lock, and ingress state. Notification state piggybacks on any poll and uses one personal-state-only request after a cold `/l/ping` miss. |
| `notificationState.mjs` | Parses `X-Lagniappe-Notification-State`, stores the latest generation/revision/count before the lazy menu loads, updates the badge, and publishes state changes to menu/coordinator consumers. |
| `editWatcher.mjs` | `EditWatcher` -- fingerprint-based entity discovery, polling subscriptions, form-lock restoration, and the stable watched-form service facade. |
| `editReconciler.mjs` | `EditReconciler` -- per-form authoritative replacement probes, draft and queued-mutation comparison, and revision resolution. Internal to `EditWatcher`. |
| `editRevisionModal.mjs` | Field-by-field and whole-form revision review modals. Internal to `EditReconciler`. |
| `deferredOperations.mjs` | `DeferredOperationManager` -- owner-authorized operation subscriptions and revision-aware terminal destination reconciliation. |
| `errors.mjs` | `captureError()`, `captureNetworkError()`, and `configureSentry()` -- collect DOM context from the nearest widget/component/view elements and forward to the configured local Sentry bundle + console. The client initializes only when an installation DSN is rendered. Its event processor removes SDK request payloads and identity context, applies the exact diagnostic-header allowlist, recursively redacts recognized credentials/payloads, and bounds nested context. |
| `request.mjs` | `request.get/post/put/patch/delete` -- wraps `fetch` with CSRF token injection, targeted retry for responses explicitly identified as CSRF failures, 422 validation error handling, redirect following, and JSON/HTML content-type detection. A service-worker `X-Lagniappe-Updated: false` marker is exposed as `response.updated === false` so refresh consumers can skip unchanged DOM work. |
| `sync.mjs` | `SyncManager` -- revisioned collaborative-document synchronization through `/l/sync` and shared document polling, including offline document-delta replay. See [SYNC_ARCHITECTURE.md](SYNC_ARCHITECTURE.md). |
| `modal.mjs` | Modal system: `Modal` (base), `DeleteModal`, `HelpModal`, and `OfflineModal`. Handles Escape/click-outside dismissal, load-from-server, and nested view transitions. |
| `offline.mjs` | IndexedDB primitives for document sync records and explicit offline mutation records. |
| `offlineQueue.mjs` | `OfflineQueue` -- serializes explicit `lp-offline` mutation commands, restores optimistic overlays, replays commands, and hands conflicts to `EditWatcher`. |
| `protocol.mjs` | Connectivity worker-message validation and construction. Server state does not cross the service-worker boundary. |
| `user.mjs` | `updateUserData()` and `updateUserLocation()` -- sync browser timezone/geolocation to the server session, with caching and distance-threshold checks. |
| `utilities.mjs` | `withTransition()` (View Transitions API wrapper with debug mode), `debounce()`, `waitForAttribute()` (MutationObserver-based attribute wait), `simpleHash()`, `generateElementId()`, `areEqual()` (deep JSON comparison), `base64ToUint8Array()`, `uint8ArrayToBase64()`. |

## Style System

Styles are defined in two places:

### CSS files (`src/style/`)

| File | Purpose |
|---|---|
| `icons.css` | Sole owner of icon geometry: the outer `.icon` box, independently sized Material `.icon-glyph`, contextual scale modifiers, semantic optical exceptions, and the CSS-drawn loading spinner. |
| `main.css` | Tailwind base + imports |
| `base.css`, `media.css`, `motion.css`, `state.css` | Global structure, media behavior, transitions, and state visibility |
| `navigation.css`, `tables.css`, `forms.css` | Semantic layout and control rules |
| `attributes.css`, `buttons.css`, `links.css`, `content.css` | Focused component rules with semantic owners |
| `interaction.css` | Cross-component interactive behavior |
| `editor.css` | TipTap rich text editor styles |
| `fonts.css` | Font-face declarations |
| `kinds.css` | Entity kind color theming (CSS custom properties) |

### YAML definitions (`src/style/`)

| File | Purpose |
|---|---|
| `styles.yaml` | Validated semantic style records keyed by component path (e.g. `button.submit`, `badge.default`, `builder.view`). Records normalize to the string-valued `STYLES` constant used throughout JS and Python. |
| `icons.yaml` | Material Symbols Rounded records keyed by lower-camel semantic IDs (e.g. `star.active`, `alignLeft`, `removeDueDate`). Each leaf owns `glyph` and `fill`, with optional `weight` or `spin`. |
| `icons.schema.json` | Shared semantic-ID and Material record contract used by Rollup and traceability. |
| `pipeline.json` | Machine-readable registry, CSS entry/output, Tailwind source, transform, and generated-map contract shared by Rollup and traceability. |

### Build Pipeline

The `buildStyles()` Rollup plugin in `build/utility.mjs` reads the pipeline
contract and both YAML files, validates/normalizes the style and icon records,
and:

1. **For JavaScript**: creates a virtual `"styles"` module that exports `ICONS` and `STYLES` as JSON objects. Shared `createIcon()` / `setIcon()` helpers resolve the structured icon records.
2. **For Python**: writes `lagniappe/web/start/styles/icons.py` and `styles.py` as auto-generated Python files containing the same dictionaries. Jinja's `render_icon()` helper resolves them server-side.

This means a single YAML source of truth drives both client and server rendering.
Use `venv/bin/python run.py traceability --styles` to check style and icon
consumers, CSS ownership, build reachability, and generated-map parity.
Review-level findings are prompts for semantic extraction, not a mandate to
deduplicate every equal class string. Equal values with distinct roles are
recorded as YAML exceptions; local responsive, spacing, state, and kind
variants remain inline until they represent a reusable concept. The Home toggle
label is a shared semantic record because the same wrapping contract appears
throughout that view.

## Directory Structure

```
src/
├── script/
│   ├── main.mjs              # App entry point
│   ├── login.mjs             # Login entry point
│   ├── sentry.mjs            # Conditional local browser monitoring
│   ├── sw.template.mjs        # Service worker template
│   ├── config/                # Editor configuration
│   ├── elements/              # Form elements (see FRONTEND_ELEMENTS.md)
│   ├── login/                 # Login form classes
│   ├── shared/                # Shared utilities (above)
│   ├── views/                 # View classes (see FRONTEND_VIEWS.md)
│   └── widgets/               # Widget classes (see FRONTEND_VIEWS.md)
└── style/
    ├── main.css               # CSS entry point
    ├── base.css, interaction.css, media.css, motion.css, state.css
    ├── navigation.css, tables.css, forms.css
    ├── attributes.css, buttons.css, links.css, content.css
    ├── editor.css, fonts.css, kinds.css
    ├── styles.yaml            # Tailwind class definitions
    ├── icons.schema.json      # Material icon record contract
    └── icons.yaml             # Semantic glyph/fill definitions
```
