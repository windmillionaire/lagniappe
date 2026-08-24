# Frontend Service Worker

The service worker (`src/script/sw.template.mjs`) handles offline support,
caching, and connectivity state. It is a template file -- the build process
replaces `__BUILD_ID__` placeholders with the current build cache ID before
writing it to `lagniappe/web/static/sw.js`.

## Caching Strategy

The service worker owns two Cache API stores:

| Store | Name | Purpose |
|---|---|---|
| Cache | `static-cache` | Static assets (current JS chunks, CSS, fonts, images) |
| Cache | `response-cache` | Cacheable API/page responses (HTML, JSON) |

The response itself is the single source of truth for its validator. Cached
responses retain their server-provided `ETag`, so there is no parallel
IndexedDB validator store to coordinate or invalidate.

### Request Classification

Cross-origin requests bypass the service worker so third-party scripts and
provider-owned telemetry keep their browser-defined request modes and redirect
handling. Every same-origin fetch is classified into one of three categories:

**Static** (`isStatic`) -- fonts, images, chunks, the offline page, and files
ending in `.css`, `.js`, `.map`, `.json`, `.txt`, or `.ico`:

- Strategy: **cache-first**
- On hit: return cached response immediately
- On miss: fetch from network, cache if successful, return response
- On network error: return 503
- On service-worker activation: current dynamic JS chunk URLs, including their
  build-ID query strings, are warmed into `static-cache` from the build-injected
  precache list

**Cacheable** -- all non-static GET requests:

- Strategy: **network-first with ETag validation**
- Sends `If-None-Match` with the ETag on the cached response
- On 304: return the cached response with `X-Lagniappe-Updated: false`
- On 200: cache and return the response unless the response is
  `no-store` or redirected
- On network error: return a stale cached response if available; otherwise
  return the offline document for navigation or an explicit 503 for non-navigation
  requests

When a cached response exists and connectivity is not known to be offline, all
dynamic GETs wait for conditional network validation. The cached response is
used only after a 304 or an actual network failure. This prevents slow requests
from returning stale application state based on an arbitrary deadline while
preserving ETag storage and offline reuse.
`shared/request.mjs` exposes the worker marker as `response.updated`; refresh
consumers skip DOM reconciliation when it is `false`.

`/l/token` is classified as network-only because returning a cached token would be
functionally incorrect. `/l/ping` bypasses the worker entirely. Neither caller
adds request-side `no-store` or `Cache-Control` directives: cacheability is
server-owned through `g.NO_CACHE` and the application `after_request` hook.

Conditional requests are cloned from the original `FetchEvent` request so
navigation redirect handling is preserved. Redirected and `opaqueredirect`
responses are returned to the browser but discarded from the service-worker
cache.

**Everything else** (POST, PUT, DELETE):

- Strategy: **network-only**
- Passed straight to the network
- On network error: return 503 with error context sent to Sentry

### ETag Management

ETags travel with cached responses. The flow is:

1. Look up the cached response and read its `ETag` header
2. If found, add `If-None-Match: {etag}` to the request
3. If the server returns 304, serve the cached body with the unchanged marker
4. If the server returns 200, replace the cached response
5. If 304 arrives but no cached response exists (edge case), re-fetch without the ETag

## Cache Invalidation

Two invalidation mechanisms exist:

### ETag-Based Stale Response Cleanup

When a cacheable response arrives with a changed ETag on qualifying routes (`/`, `/get*`, `/categories/*`, `*/index`, `*/rows`), the service worker deletes sibling cached responses for the same URL path (different query params). This handles cases where index pages change their query parameters (pagination, filters) and old cached versions become stale.

Cursor-bearing row requests use the same cacheable GET path as any other row
request. Datastore/API errors are handled by the normal application error path;
the service worker does not transform cursor failures into frontend reload
messages.

### Server-Triggered Full Invalidation

If a response includes the `X-Lagniappe-Invalidate-Cache` header, the response
cache is deleted. The service worker then fetches a fresh CSRF token and
validates the user session with confirmation that the response cache was
cleared. This is used for events like permission changes or site-wide updates
that require a clean slate.

The server acknowledgement is complete only when the token response is OK and
nonempty and `POST /l/validate-user` returns an OK JSON response with
`cacheCleared: true`. Failures are reported with stage/status metadata only.
The worker does not spin a private retry loop: the server retains its
invalidation flag, so a later response repeats the header and starts another
coalesced acknowledgement attempt.

## Quota Management

`maybeEvictForQuota()` runs after each new cache entry, throttled to at most once
per 60 seconds. If storage usage exceeds 90% of quota, it deletes up to 200 of
the oldest cached responses (cache keys are in insertion order). The VM harness
proves the unavailable/failing estimate paths, throttle, threshold, and bounded
oldest-first batch.

## Lifecycle Events

### Install

Calls `skipWaiting()` to activate immediately rather than waiting for all tabs
to close.

### Activate

Refreshes application-owned cache state on activation:

1. Deletes `static-cache` and `response-cache` (but not unrelated origin caches)
2. Opens the static cache and caches `/offline`
3. Claims all clients
4. Warms the current dynamic JS chunk URLs into the static cache

This ensures a clean start after a service worker update. Main app chunks use
stable filenames on disk, but Rollup-generated imports and the service-worker
precache list use build-ID query strings such as
`/chunks/shared.js?v=b824d23e`. This binds an entrypoint to the matching chunk
generation instead of letting a cache-first response mix two builds. Activation
deletes prior static-cache entries and warms only the current build. Because the
query string is part of both the Cache API and HTTP-cache key, App Engine can
serve `/chunks/*.js` with a long-lived immutable policy. The layout templates
keep owning the versioned `/script.js?v=...` entrypoint. The `controllerchange`
listener in `main.mjs` clears cached recent search results, publishes the
current connectivity state to the replacement controller, and runs
`syncView()` when the new service worker takes control.

Authenticated pages schedule registration only after the concrete view has
published and the browser reaches an idle slot (with a one-second maximum).
This keeps activation's chunk-warming request burst from competing with the
structural view and its first widget imports. Public pages do not register the
authenticated service-worker lifecycle.

`main.mjs` sends the worker a versioned `connectivity-state` message with four
independent fields: browser link state, application-server reachability,
document visibility, and controller availability. The worker validates the
protocol/version and all four field values before using browser/server state to
choose network or cached behavior. `/l/ping` remains the authority for server
reachability; `navigator.onLine` remains a scheduling hint.

### Fetch

Routes requests through the classification logic above. Extension URLs (`extension://`) are ignored entirely.
Cross-origin URLs are also ignored and proceed through the browser's normal
network path.

## Connectivity Messages

The service worker receives only the versioned `connectivity-state` message
from the active page. It uses that state to make cache/network decisions. It
does not receive push data or relay server state to tabs; application updates
are owned by the visible view's polling coordinator.

## Error Handling

The service worker has its own `captureError()` function (separate from the
app's `shared/errors.mjs`). It forwards errors to Sentry when Sentry is
available.

Navigation errors use the cached offline document when no cached response is
available. AJAX GETs and mutation failures return a JSON 503 payload
(`{"ok": false, "error": "You are offline"}`); other non-navigation requests
receive a plain-text 503. This prevents token, fragment, script, or image
requests from treating the HTML offline page as a successful response.

## Template Variables

| Variable | Replaced With | Purpose |
|---|---|---|
| `__BUILD_ID__` | Build cache string | Embedded as `SW_VERSION` constant and tracked in `config/constants.py`; ensures the SW file changes on each frontend build so the browser detects an update |
| `/* __BROWSER_PROTOCOL__ */ null` | `config/browser_protocol.json` | Gives the standalone worker the same versioned message/event and connectivity-state vocabulary as the main bundle and Python message producers |
| `/* __PRECACHE_URLS__ */ []` | JSON array of versioned Rollup output chunk URLs | Lets activation warm the current build's exact dynamic JS cache keys into `static-cache` |

The `updateServiceWorker()` Rollup plugin in `build/utility.mjs` handles the replacements and writes the output to `lagniappe/web/static/sw.js`.
