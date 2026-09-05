"""Node-backed checks for service-worker cache behavior."""

import textwrap

def run_service_worker_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

class CacheMock {{
  constructor() {{
    this.deletes = [];
    this.entries = new Map();
    this.puts = 0;
  }}

  async delete(request) {{
    const url = requestUrl(request);
    this.deletes.push(url);
    return this.entries.delete(url);
  }}

  async add(request) {{
    this.entries.set(requestUrl(request), new Response("offline"));
  }}

  async keys(request = null, options = {{}}) {{
    const keys = [...this.entries.keys()];
    if (!request) return keys.map((url) => new Request(url));

    const target = new URL(requestUrl(request));
    return keys
      .filter((url) => {{
        const candidate = new URL(url);
        if (options.ignoreSearch) {{
          return candidate.origin === target.origin &&
            candidate.pathname === target.pathname;
        }}
        return candidate.href === target.href;
      }})
      .map((url) => new Request(url));
  }}

  async match(request) {{
    return this.entries.get(requestUrl(request));
  }}

  async put(request, response) {{
    this.puts += 1;
    this.entries.set(requestUrl(request), response.clone());
  }}
}}

function requestUrl(request) {{
  return typeof request === "string" ? request : request.url;
}}

const responseCache = new CacheMock();
const staticCache = new CacheMock();
const fetchCalls = [];
const clientMessages = [];
const deletedCaches = [];
const listeners = new Map();
const cacheNames = new Set(["static-cache", "response-cache", "third-party-cache"]);

const context = {{
  clearTimeout,
  console,
  deletedCaches,
  fetchCalls,
  clientMessages,
  Headers,
  navigator: {{ onLine: true }},
  Request,
  Response,
  listeners,
  self: {{
    addEventListener(type, listener) {{ listeners.set(type, listener); }},
    clients: {{
      matchAll: async () => [{{
        postMessage(message) {{ clientMessages.push(message); }},
      }}],
    }},
    location: new URL("https://example.test/"),
    navigator: {{}},
    Sentry: null,
    skipWaiting: async () => {{}},
  }},
  setTimeout,
  URL,
}};

context.caches = {{
  async delete(name) {{
    deletedCaches.push(name);
    return cacheNames.delete(name);
  }},
  async keys() {{
    return [...cacheNames];
  }},
  async has(name) {{
    return cacheNames.has(name);
  }},
  async open(name) {{
    cacheNames.add(name);
    return name === "response-cache" ? responseCache : staticCache;
  }},
}};

vm.createContext(context);
const browserProtocol = JSON.parse(
  fs.readFileSync("config/browser_protocol.json", "utf8"),
);
let workerSource = fs.readFileSync("src/script/sw.template.mjs", "utf8");
workerSource = workerSource.replace(
  "/* __BROWSER_PROTOCOL__ */ null",
  JSON.stringify(browserProtocol),
);
vm.runInContext(workerSource, context);
vm.runInContext(`
realCheckForCacheInvalidation = checkForCacheInvalidation;
checkForCacheInvalidation = async () => {{}};
`, context);

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    run_node(script)


# @matrix cache : no-store service-worker
def test_no_store_304_discards_cached_response(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async (request) => {
  fetchCalls.push(request);
  if (request.headers.has("X-Lagniappe-If-None-Match")) {
    throw new Error("SW used the removed custom ETag header");
  }
  if (request.headers.get("If-None-Match") === '"cached-etag"') {
    return new Response(null, {
      status: 304,
      headers: { "Cache-Control": "private, no-store" },
    });
  }

  return new Response("fresh", {
    status: 200,
    headers: { "Cache-Control": "NO-STORE" },
  });
};
const request = new Request("https://example.test/l/token", {
  credentials: "include",
});
responseCache.entries.set(request.url, new Response("cached", {
  headers: { ETag: '"cached-etag"' },
}));

const waitUntil = [];
const response = await context.handleCacheable({
  request,
  waitUntil: (promise) => waitUntil.push(Promise.resolve(promise)),
}, "/l/token");
await Promise.all(waitUntil);

const body = await response.text();
if (body !== "fresh") {
  throw new Error(`Expected fresh response body, got ${body}`);
}
if (responseCache.entries.has(request.url)) {
  throw new Error("no-store response remained in the response cache");
}
if (responseCache.puts !== 0) {
  throw new Error("no-store response was written to the response cache");
}
if (fetchCalls.length !== 2) {
  throw new Error(`Expected conditional fetch plus fresh fetch, got ${fetchCalls.length}`);
}
if (fetchCalls[0].headers.get("If-None-Match") !== '"cached-etag"') {
  throw new Error("first request was not conditional");
}
""",
    )


# @matrix cache csrf : network-only service-worker token
def test_token_request_is_network_only_without_client_cache_directives(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async (request) => {
  fetchCalls.push(request);
  if (request.cache === "no-store") {
    throw new Error("frontend forced token cache policy");
  }
  if (request.headers.has("Cache-Control")) {
    throw new Error("frontend sent a token cache-control header");
  }
  return new Response("fresh-token", {
    headers: { "Cache-Control": "no-store" },
  });
};
const request = new Request("https://example.test/l/token", {
  credentials: "include",
  headers: { "X-Lagniappe-Request": "true" },
});
responseCache.entries.set(request.url, new Response("stale-token"));

const waitUntil = [];
const response = await context.handleNetworkOnlyGet({
  request,
  waitUntil: (promise) => waitUntil.push(Promise.resolve(promise)),
});
await Promise.all(waitUntil);

const body = await response.text();
if (body !== "fresh-token") {
  throw new Error(`Expected fresh token body, got ${body}`);
}
if (fetchCalls.length !== 1) {
  throw new Error(`Expected one network token fetch, got ${fetchCalls.length}`);
}
if (responseCache.entries.has(request.url)) {
  throw new Error("stale token response remained in the response cache");
}
if (responseCache.puts !== 0) {
  throw new Error("no-store token response was written to the response cache");
}
""",
    )


# @matrix cache request : conditional-response dom-refresh service-worker
def test_cached_304_marks_response_not_updated(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async (request) => {
  fetchCalls.push(request);
  return new Response(null, { status: 304 });
};

const request = new Request("https://example.test/pages/example/tasks", {
  headers: { "X-Lagniappe-Request": "true" },
});
responseCache.entries.set(request.url, new Response("unchanged tasks", {
  headers: { ETag: '"tasks-etag"' },
}));

const waitUntil = [];
const response = await context.handleCacheable({
  request,
  waitUntil: (promise) => waitUntil.push(Promise.resolve(promise)),
}, "/pages/example/tasks");
await Promise.all(waitUntil);

if (await response.text() !== "unchanged tasks") {
  throw new Error("304 did not reuse the cached response body");
}
if (response.headers.get("X-Lagniappe-Updated") !== "false") {
  throw new Error("304 cache reuse did not expose the unchanged marker");
}
if (fetchCalls[0].headers.get("If-None-Match") !== '"tasks-etag"') {
  throw new Error("cached response ETag was not used for validation");
}
""",
    )


# @matrix cache offline : ajax response-shape service-worker
def test_application_get_failure_returns_503_instead_of_offline_html(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async () => {
  throw new Error("offline");
};
staticCache.entries.set("/offline", new Response("offline document"));

const request = new Request("https://example.test/pages/example/tasks", {
  headers: { "X-Lagniappe-Request": "true" },
});
const response = await context.handleCacheable({
  request,
  waitUntil() {},
}, "/pages/example/tasks");

if (response.status !== 503) {
  throw new Error(`Expected an explicit 503, got ${response.status}`);
}
if (!response.headers.get("Content-Type").includes("application/json")) {
  throw new Error("AJAX failure did not return JSON");
}
const body = await response.json();
if (body.ok !== false || body.error !== "You are offline" ||
    body.retryable !== false || body.outcomeUncertain !== true) {
  throw new Error(`Unexpected offline response: ${JSON.stringify(body)}`);
}
""",
    )


# @matrix cache offline : navigation response-shape service-worker
def test_navigation_failure_uses_offline_document(run_node):
    run_service_worker_check(
        run_node,
        """
staticCache.entries.set("/offline", new Response("offline document"));

const request = {
  mode: "navigate",
  headers: new Headers(),
};
const response = await context.unavailableResponse(request);

if (response.status !== 200 || await response.text() !== "offline document") {
  throw new Error("Navigation failure did not return the offline document");
}
""",
    )


# @matrix cache : activation ownership service-worker
def test_activation_clears_only_application_owned_caches(run_node):
    run_service_worker_check(
        run_node,
        """
await context.updateCaches();

const deleted = new Set(context.deletedCaches);
if (!deleted.has("static-cache") || !deleted.has("response-cache")) {
  throw new Error(`Application caches were not reset: ${context.deletedCaches}`);
}
if (deleted.has("third-party-cache")) {
  throw new Error("Activation deleted a cache it does not own");
}
""",
    )


# @matrix cache : invalidation service-worker
def test_304_response_with_invalidation_header_fetches_fresh_response(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async (request) => {
  fetchCalls.push(request);
  if (request.headers.has("X-Lagniappe-If-None-Match")) {
    throw new Error("SW used the removed custom ETag header");
  }
  if (request.headers.get("If-None-Match") === '"cached-etag"') {
    return new Response(null, {
      status: 304,
      headers: { "X-Lagniappe-Invalidate-Cache": "true" },
    });
  }
  if (request.cache !== "reload") {
    throw new Error(`Expected reload fetch after invalidation, got ${request.cache}`);
  }
  return new Response("fresh page");
};
vm.runInContext(`
invalidationChecks = 0;
checkForCacheInvalidation = async (response) => {
  if (response.headers.get("X-Lagniappe-Invalidate-Cache")) {
    invalidationChecks += 1;
  }
  return { invalidated: true };
};
`, context);

const request = new Request("https://example.test/pages/example/tasks", {
  credentials: "include",
});
responseCache.entries.set(request.url, new Response("cached page", {
  headers: { ETag: '"cached-etag"' },
}));

const waitUntil = [];
const response = await context.handleCacheable({
  request,
  waitUntil: (promise) => waitUntil.push(Promise.resolve(promise)),
}, "/pages/example/tasks");
await Promise.all(waitUntil);

const body = await response.text();
if (body !== "fresh page") {
  throw new Error(`Expected fresh response body, got ${body}`);
}
if (context.invalidationChecks !== 1) {
  throw new Error(`Expected one invalidation check, got ${context.invalidationChecks}`);
}
if (fetchCalls.length !== 2) {
  throw new Error(`Expected conditional fetch plus reload fetch, got ${fetchCalls.length}`);
}
if (fetchCalls[0].headers.get("If-None-Match") !== '"cached-etag"') {
  throw new Error("request was not conditional");
}
if (fetchCalls[1].headers.has("If-None-Match")) {
  throw new Error("reload request kept the stale conditional ETag");
}
""",
    )


# @matrix cache : browser-validators service-worker
def test_dynamic_fetch_preserves_browser_validators_without_stored_etag(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async (request) => {
  fetchCalls.push(request);
  if (request.headers.get("If-None-Match") !== '"browser-cache-etag"') {
    throw new Error("dynamic fetch did not preserve browser-supplied If-None-Match");
  }
  if (request.headers.get("If-Modified-Since") !== "Sun, 28 Jun 2026 17:18:51 GMT") {
    throw new Error("dynamic fetch did not preserve browser-supplied If-Modified-Since");
  }
  if (request.headers.has("X-Lagniappe-If-None-Match")) {
    throw new Error("dynamic fetch used the removed custom ETag header");
  }
  return new Response("fresh page");
};

const request = new Request("https://example.test/categories/category-key", {
  headers: {
    "If-None-Match": '"browser-cache-etag"',
    "If-Modified-Since": "Sun, 28 Jun 2026 17:18:51 GMT",
  },
});
const waitUntil = [];
const response = await context.handleCacheable({
  request,
  waitUntil: (promise) => waitUntil.push(Promise.resolve(promise)),
}, "/categories/category-key");
await Promise.all(waitUntil);

const body = await response.text();
if (body !== "fresh page") {
  throw new Error(`Expected fresh response body, got ${body}`);
}
if (fetchCalls.length !== 1) {
  throw new Error(`Expected one network fetch, got ${fetchCalls.length}`);
}
""",
    )


# @matrix cache : cached-response network-validation service-worker
def test_cached_dynamic_get_waits_for_network_validation_before_using_cached_response(
    run_node,
):
    run_service_worker_check(
        run_node,
        """
let releaseNetwork;
context.fetch = async (request) => {
  fetchCalls.push(request);
  return await new Promise((resolve) => {
    releaseNetwork = resolve;
  });
};

const request = new Request("https://example.test/filters/saved-filter", {
  credentials: "include",
});
responseCache.entries.set(request.url, new Response("stale filter page"));

const waitUntil = [];
let settled = false;
const pending = context.handleCacheable({
  request,
  waitUntil: (promise) => waitUntil.push(Promise.resolve(promise)),
}, "/filters/saved-filter").then((response) => {
  settled = true;
  return response;
});

await new Promise((resolve) => setTimeout(resolve, 850));
if (settled) {
  throw new Error("Cached GET returned before network validation completed");
}

releaseNetwork(new Response("fresh filter page", {
  headers: { ETag: '"fresh-etag"' },
}));
const response = await pending;
await Promise.all(waitUntil);

const body = await response.text();
if (body !== "fresh filter page") {
  throw new Error(`Expected validated filter page, got ${body}`);
}
if (fetchCalls.length !== 1) {
  throw new Error(`Expected one validating fetch, got ${fetchCalls.length}`);
}
""",
    )


# @matrix cache : invalidation service-worker
def test_redirect_response_with_invalidation_header_clears_cache(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async (request) => {
  fetchCalls.push(request);
  return new Response("", {
    status: 302,
    headers: {
      "Location": "/",
      "X-Lagniappe-Invalidate-Cache": "true",
    },
  });
};
vm.runInContext(`
invalidationChecks = 0;
checkForCacheInvalidation = async (response) => {
  if (response.headers.get("X-Lagniappe-Invalidate-Cache")) {
    invalidationChecks += 1;
  }
  return { invalidated: true };
};
`, context);

const request = new Request("https://example.test/users/login?test_user=a@example.test", {
  credentials: "include",
});

const waitUntil = [];
const response = await context.handleCacheable({
  request,
  waitUntil: (promise) => waitUntil.push(Promise.resolve(promise)),
}, "/users/login");
await Promise.all(waitUntil);

if (response.status !== 302) {
  throw new Error(`Expected redirect response, got ${response.status}`);
}
if (context.invalidationChecks !== 1) {
  throw new Error(`Expected redirect invalidation check, got ${context.invalidationChecks}`);
}
if (responseCache.puts !== 0) {
  throw new Error("redirect response was written to the response cache");
}
""",
    )


# @matrix cache : invalidation service-worker
def test_cache_invalidation_confirmation_posts_after_local_clear(run_node):
    run_service_worker_check(
        run_node,
        """
const validateCalls = [];
context.fetch = async (url, options = {}) => {
  if (url === "/l/token") {
    if (options.credentials !== "include") {
      throw new Error(`Expected token credentials include, got ${options.credentials}`);
    }
    if (options.cache !== undefined || options.headers["Cache-Control"] !== undefined) {
      throw new Error("Worker overrode server-owned token cache policy");
    }
    return new Response("csrf-token");
  }
  if (url === "/l/validate-user") {
    validateCalls.push(options);
    return new Response(JSON.stringify({ cacheCleared: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }
  throw new Error(`Unexpected fetch ${url}`);
};
vm.runInContext(`
checkForCacheInvalidation = realCheckForCacheInvalidation;
`, context);

const result = await context.checkForCacheInvalidation(
  new Response("", {
    headers: { "X-Lagniappe-Invalidate-Cache": "true" },
  }),
);

if (!result.invalidated || !result.cacheCleared || !result.acknowledged) {
  throw new Error("cache invalidation did not report a confirmed clear");
}
if (validateCalls.length !== 1) {
  throw new Error(`Expected one validate-user call, got ${validateCalls.length}`);
}
const body = JSON.parse(validateCalls[0].body);
if (!body.cacheCleared || !body.responseCacheCleared || "etagStoreCleared" in body) {
  throw new Error(`validate-user payload did not confirm cache clearing: ${validateCalls[0].body}`);
}
if (validateCalls[0].headers["X-CSRFToken"] !== "csrf-token") {
  throw new Error("validate-user did not include refreshed CSRF token");
}
""",
    )


# @matrix cache : acknowledgement failure invalidation retry service-worker
def test_cache_invalidation_requires_explicit_server_acknowledgement(run_node):
    run_service_worker_check(
        run_node,
        """
const captures = [];
context.self.Sentry = {
  captureException(error, options) {
    captures.push({ message: error.message, ...options });
  },
};

const scenarios = [
  {
    stage: "token-response",
    fetch: async (url) => new Response("", { status: url === "/l/token" ? 500 : 200 }),
    validateCalls: 0,
  },
  {
    stage: "token-empty",
    fetch: async (url) => new Response(url === "/l/token" ? "   " : "", { status: 200 }),
    validateCalls: 0,
  },
  {
    stage: "validation-response",
    fetch: async (url) => url === "/l/token"
      ? new Response("csrf-token")
      : new Response("", { status: 503 }),
    validateCalls: 1,
  },
  {
    stage: "validation-body",
    fetch: async (url) => url === "/l/token"
      ? new Response("csrf-token")
      : new Response("not-json", { status: 200 }),
    validateCalls: 1,
  },
  {
    stage: "validation-acknowledgement",
    fetch: async (url) => url === "/l/token"
      ? new Response("csrf-token")
      : new Response(JSON.stringify({ cacheCleared: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    validateCalls: 1,
  },
];

vm.runInContext(`checkForCacheInvalidation = realCheckForCacheInvalidation;`, context);
for (const scenario of scenarios) {
  let validateCalls = 0;
  context.fetch = async (url, options = {}) => {
    if (url === "/l/validate-user") validateCalls += 1;
    return scenario.fetch(url, options);
  };
  const before = captures.length;
  const result = await context.checkForCacheInvalidation(
    new Response("", {
      headers: { "X-Lagniappe-Invalidate-Cache": "true" },
    }),
  );
  if (result.acknowledged !== false) {
    throw new Error(`Expected failed acknowledgement for ${scenario.stage}`);
  }
  if (validateCalls !== scenario.validateCalls) {
    throw new Error(`Unexpected validate calls for ${scenario.stage}: ${validateCalls}`);
  }
  if (captures.length !== before + 1 || captures.at(-1).stage !== scenario.stage) {
    throw new Error(`Expected one ${scenario.stage} capture: ${JSON.stringify(captures)}`);
  }
  if (captures.at(-1).message.includes("csrf-token") || "body" in captures.at(-1)) {
    throw new Error("Validation diagnostics included sensitive response data");
  }
}

let validationAttempts = 0;
context.fetch = async (url) => {
  if (url === "/l/token") return new Response("csrf-token");
  validationAttempts += 1;
  return new Response(JSON.stringify({ cacheCleared: validationAttempts > 1 }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};
const invalidation = new Response("", {
  headers: { "X-Lagniappe-Invalidate-Cache": "true" },
});
const first = await context.checkForCacheInvalidation(invalidation.clone());
const second = await context.checkForCacheInvalidation(invalidation.clone());
if (first.acknowledged !== false || second.acknowledged !== true || validationAttempts !== 2) {
  throw new Error("A failed acknowledgement did not reset for the next invalidation header");
}
""",
    )


# @matrix cache : etag redirect-mode service-worker
def test_conditional_fetch_preserves_original_request_redirect_mode(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async (request) => {
  fetchCalls.push(request);
  if (request.redirect !== "manual") {
    throw new Error(`Expected redirect mode manual, got ${request.redirect}`);
  }
  if (request.credentials !== "include") {
    throw new Error(`Expected credentials include, got ${request.credentials}`);
  }
  if (request.headers.get("X-Original") !== "yes") {
    throw new Error("conditional fetch dropped original headers");
  }
  if (request.headers.has("X-Lagniappe-If-None-Match")) {
    throw new Error("conditional fetch used the removed custom ETag header");
  }
  if (request.headers.get("If-None-Match") !== '"cached-etag"') {
    throw new Error("conditional fetch did not attach the stored ETag");
  }
  return new Response("fresh");
};
const request = new Request("https://example.test/users/login", {
  credentials: "include",
  headers: { "X-Original": "yes" },
  redirect: "manual",
});
responseCache.entries.set(request.url, new Response("cached", {
  headers: { ETag: '"cached-etag"' },
}));
const waitUntil = [];
const response = await context.handleCacheable({
  request,
  waitUntil: (promise) => waitUntil.push(Promise.resolve(promise)),
}, "/users/login");
await Promise.all(waitUntil);

const body = await response.text();
if (body !== "fresh") {
  throw new Error(`Expected fresh response body, got ${body}`);
}
if (fetchCalls.length !== 1) {
  throw new Error(`Expected one fetch, got ${fetchCalls.length}`);
}
    """,
    )


# @matrix cache : redirected-response service-worker
def test_redirected_responses_are_discarded_and_not_cached(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async (request) => {
  fetchCalls.push(request);
  const response = new Response("followed home");
  Object.defineProperty(response, "redirected", { value: true });
  return response;
};

const request = new Request("https://example.test/users/login");
const cached = new Response("stale login redirect");
Object.defineProperty(cached, "redirected", { value: true });
responseCache.entries.set(request.url, cached);

const waitUntil = [];
const response = await context.handleCacheable({
  request,
  waitUntil: (promise) => waitUntil.push(Promise.resolve(promise)),
}, "/users/login");
await Promise.all(waitUntil);

if (!response.redirected) {
  throw new Error("redirected network response was not returned");
}
if (responseCache.entries.has(request.url)) {
  throw new Error("redirected response remained in the response cache");
}
if (responseCache.puts !== 0) {
  throw new Error("redirected response was written to the response cache");
}
if (!responseCache.deletes.includes(request.url)) {
  throw new Error("redirected cached response was not deleted");
}
    """,
    )


# @matrix cache : no-store service-worker static-assets
def test_no_store_static_response_is_not_cached(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async (request) => {
  fetchCalls.push(request);
  return new Response("asset", {
    status: 200,
    headers: { "Cache-Control": "no-cache, no-store" },
  });
};

const request = new Request("https://example.test/chunks/app.js");
staticCache.entries.set(request.url, new Response("stale", {
  headers: { "Cache-Control": "no-store" },
}));
const waitUntil = [];
const response = await context.handleStatic({
  request,
  waitUntil: (promise) => waitUntil.push(Promise.resolve(promise)),
});
await Promise.all(waitUntil);

const body = await response.text();
if (body !== "asset") {
  throw new Error(`Expected static response body, got ${body}`);
}
if (fetchCalls.length !== 1) {
  throw new Error("no-store static cache hit was served instead of refetched");
}
if (staticCache.entries.has(request.url)) {
  throw new Error("no-store static response remained in the static cache");
}
if (staticCache.puts !== 0) {
  throw new Error("no-store static response was written to the static cache");
}
if (!staticCache.deletes.includes(request.url)) {
  throw new Error("no-store static response did not clear its cache key");
}
""",
    )


# @matrix cache : precache service-worker static-assets
def test_precache_static_assets_warms_configured_urls_and_ignores_failures(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async (request) => {
  fetchCalls.push(request);
  const pathname = new URL(request.url).pathname;
  if (pathname.endsWith("/missing.js")) {
    throw new Error("simulated chunk miss");
  }
  if (pathname.endsWith("/no-store.js")) {
    return new Response("do not cache", {
      headers: { "Cache-Control": "no-store" },
    });
  }
  return new Response(pathname, {
    headers: { "Cache-Control": "no-cache" },
  });
};

vm.runInContext(`
PRECACHE_URLS.push(
  "/chunks/addLink.js?v=btest123",
  "/chunks/no-store.js?v=btest123",
  "/chunks/missing.js?v=btest123"
);
`, context);

await context.precacheStaticAssets();

const chunkUrl = "https://example.test/chunks/addLink.js?v=btest123";
const noStoreUrl = "https://example.test/chunks/no-store.js?v=btest123";
const missingUrl = "https://example.test/chunks/missing.js?v=btest123";

if (!staticCache.entries.has(chunkUrl)) {
  throw new Error("chunk bundle was not precached");
}
if (staticCache.entries.has(noStoreUrl)) {
  throw new Error("no-store chunk was precached");
}
if (staticCache.entries.has(missingUrl)) {
  throw new Error("failed chunk was precached");
}
if (fetchCalls.length !== 3) {
  throw new Error(`Expected three warmup fetches, got ${fetchCalls.length}`);
}
if (!fetchCalls.every((request) => request.cache === "reload")) {
  throw new Error("precache fetches did not bypass the HTTP cache");
}
if (!fetchCalls.every((request) => request.url.includes("?v=btest123"))) {
  throw new Error("precache fetches dropped the build version");
}
""",
    )


# @matrix cache : etag query route-class service-worker sibling-invalidation
def test_changed_validators_clear_only_same_path_query_siblings_for_configured_routes(
    run_node,
):
    run_service_worker_check(
        run_node,
        """
const qualifyingPaths = [
  "/",
  "/l/get/pages",
  "/categories/example",
  "/pages/index",
  "/pages/rows",
];

for (const pathname of qualifyingPaths) {
  responseCache.entries.clear();
  responseCache.deletes.length = 0;
  const current = `https://example.test${pathname}?page=2`;
  const sibling = `https://example.test${pathname}?page=1`;
  const otherPath = `https://example.test/other?page=1`;
  responseCache.entries.set(current, new Response("current"));
  responseCache.entries.set(sibling, new Response("sibling"));
  responseCache.entries.set(otherPath, new Response("other"));

  await context.clearSiblingCacheEntries('"new"', '"old"', current, pathname);

  if (!responseCache.entries.has(current)) {
    throw new Error(`${pathname} removed the current cache key`);
  }
  if (responseCache.entries.has(sibling)) {
    throw new Error(`${pathname} retained a stale query sibling`);
  }
  if (!responseCache.entries.has(otherPath)) {
    throw new Error(`${pathname} removed a different path`);
  }
}

responseCache.entries.clear();
const ordinary = "https://example.test/pages/example?page=2";
const ordinarySibling = "https://example.test/pages/example?page=1";
responseCache.entries.set(ordinary, new Response("current"));
responseCache.entries.set(ordinarySibling, new Response("sibling"));
await context.clearSiblingCacheEntries('"new"', '"old"', ordinary, "/pages/example");
if (!responseCache.entries.has(ordinarySibling)) {
  throw new Error("An unconfigured route cleared a query sibling");
}

await context.clearSiblingCacheEntries('"same"', '"same"', ordinary, "/pages/index");
if (!responseCache.entries.has(ordinarySibling)) {
  throw new Error("An unchanged validator cleared a query sibling");
}
""",
    )


# @matrix cache : batch eviction quota service-worker throttle
def test_quota_eviction_is_throttled_and_bounded_to_oldest_entries(run_node):
    run_service_worker_check(
        run_node,
        """
let estimateCalls = 0;
context.self.navigator.storage = {
  async estimate() {
    estimateCalls += 1;
    return { usage: 91, quota: 100 };
  },
};
for (let index = 0; index < 250; index += 1) {
  const url = `https://example.test/cached/${String(index).padStart(3, "0")}`;
  responseCache.entries.set(url, new Response(String(index)));
}

vm.runInContext(`
_lastEvictionCheck = 0;
Date.now = () => 120000;
`, context);
await context.maybeEvictForQuota();

if (estimateCalls !== 1) {
  throw new Error(`Expected one storage estimate, got ${estimateCalls}`);
}
if (responseCache.deletes.length !== 200 || responseCache.entries.size !== 50) {
  throw new Error(`Eviction was not bounded to 200: ${responseCache.deletes.length}`);
}
if (!responseCache.deletes[0].endsWith("/000") ||
    !responseCache.deletes[199].endsWith("/199")) {
  throw new Error("Eviction did not remove the oldest insertion-ordered entries");
}

vm.runInContext("Date.now = () => 120001;", context);
await context.maybeEvictForQuota();
if (estimateCalls !== 1 || responseCache.deletes.length !== 200) {
  throw new Error("Quota work was not throttled within sixty seconds");
}
""",
    )


# @matrix cache : eviction failure quota service-worker unavailable
def test_quota_eviction_tolerates_unavailable_and_failed_estimates(run_node):
    run_service_worker_check(
        run_node,
        """
vm.runInContext(`
_lastEvictionCheck = 0;
Date.now = () => 120000;
`, context);
delete context.self.navigator.storage;
await context.maybeEvictForQuota();

context.self.navigator.storage = {
  async estimate() { throw new Error("estimate unavailable"); },
};
vm.runInContext("Date.now = () => 180000;", context);
await context.maybeEvictForQuota();

context.self.navigator.storage = {
  async estimate() { return { usage: 50, quota: 100 }; },
};
vm.runInContext("Date.now = () => 240000;", context);
await context.maybeEvictForQuota();
if (responseCache.deletes.length !== 0) {
  throw new Error("Unavailable or below-threshold estimates evicted entries");
}
""",
    )


# @matrix cache offline : cache-miss fallback navigation service-worker
def test_navigation_failure_without_cached_offline_document_returns_503(run_node):
    run_service_worker_check(
        run_node,
        """
const response = await context.offlineFallback();
if (response.status !== 503 || await response.text() !== "Offline") {
  throw new Error("Missing offline document did not produce the navigation 503");
}
if (response.headers.get("Content-Type")?.includes("application/json")) {
  throw new Error("Navigation fallback unexpectedly returned JSON");
}
""",
    )


# @matrix offline request : mutation response-shape service-worker
def test_mutation_failure_returns_json_503(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async () => { throw new Error("offline mutation"); };
const request = new Request("https://example.test/pages/example", {
  method: "PATCH",
  body: JSON.stringify({ name: "Updated" }),
  headers: { "Content-Type": "application/json" },
});
const response = await context.handleRequest({ request, waitUntil() {} }, "/pages/example");
if (response.status !== 503 ||
    !response.headers.get("Content-Type").includes("application/json")) {
  throw new Error("Mutation failure did not return a JSON 503");
}
const body = await response.json();
if (body.ok !== false || body.error !== "You are offline") {
  throw new Error(`Unexpected mutation fallback: ${JSON.stringify(body)}`);
}
""",
    )


# @matrix browser-protocol connectivity : controller service-worker validation version
def test_worker_accepts_only_versioned_valid_connectivity_messages(run_node):
    run_service_worker_check(
        run_node,
        """
const valid = {
  protocol: "lagniappe-browser",
  protocol_version: 4,
  type: "connectivity-state",
  state: {
    browser: "online",
    server: "offline",
    visibility: "hidden",
    controller: "controlled",
  },
};
if (!context.receiveConnectivityMessage(valid)) {
  throw new Error("Valid connectivity message was rejected");
}
const accepted = vm.runInContext("_connectivity", context);
if (accepted.server !== "offline" || accepted.visibility !== "hidden") {
  throw new Error(`Connectivity state was not applied: ${JSON.stringify(accepted)}`);
}

for (const invalid of [
	{ ...valid, protocol_version: 3 },
  { ...valid, type: "server-status" },
  { ...valid, state: { ...valid.state, server: "maybe" } },
]) {
  if (context.receiveConnectivityMessage(invalid)) {
    throw new Error(`Invalid connectivity message was accepted: ${JSON.stringify(invalid)}`);
  }
}
const retained = vm.runInContext("_connectivity", context);
if (retained.server !== "offline") {
  throw new Error("Invalid message changed the retained connectivity state");
}
""",
    )


# @matrix request-errors service-worker : application-error-marker classification upstream-unavailable
def test_worker_classifies_only_unmarked_upstream_html_failures(run_node):
    run_service_worker_check(
        run_node,
        """
for (const status of [500, 502, 503, 504]) {
  const raw = new Response("<html>upstream</html>", {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
  if (!context.isUpstreamUnavailableResponse(raw)) {
    throw new Error(`Unmarked upstream HTML ${status} was not classified`);
  }
  const marked = new Response("<html>application error</html>", {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "X-Lagniappe-Error": "true",
    },
  });
  if (context.isUpstreamUnavailableResponse(marked)) {
    throw new Error(`Application-marked HTML ${status} was misclassified`);
  }
}
if (context.isUpstreamUnavailableResponse(new Response("json", {
  status: 503,
  headers: { "Content-Type": "application/json" },
}))) {
  throw new Error("Non-HTML application response was misclassified");
}
""",
    )


# @matrix browser-protocol request-errors service-worker : client-message privacy upstream-unavailable
def test_upstream_failure_notifies_controlled_clients_with_bounded_state(run_node):
    run_service_worker_check(
        run_node,
        """
const request = new Request(
  "https://example.test/pages/secret-entity-id?private=yes",
  { method: "GET" },
);
const upstream = new Response("<html>failure contains private data</html>", {
  status: 504,
  headers: {
    "Content-Type": "text/html",
    "Server": "x".repeat(200),
    "X-Cloud-Trace-Context": "trace-value",
  },
});
await context.notifyUpstreamUnavailable(request, upstream, { stale: true });
if (clientMessages.length !== 1) {
  throw new Error(`Expected one client message, got ${clientMessages.length}`);
}
const message = clientMessages[0];
if (message.protocol_version !== 4 ||
    message.type !== "upstream-unavailable" ||
    message.state.route_class !== "pages" ||
    message.state.server.length !== 128 ||
    !message.state.trace_header_present ||
    !message.state.stale) {
  throw new Error(`Unexpected client diagnostic: ${JSON.stringify(message)}`);
}
const serialized = JSON.stringify(message);
for (const secret of ["secret-entity-id", "private=yes", "failure contains private data", "trace-value"]) {
  if (serialized.includes(secret)) {
    throw new Error(`Client diagnostic exposed ${secret}`);
  }
}
""",
    )


# @matrix cache request-errors service-worker : stale-cache upstream-unavailable
def test_upstream_failure_uses_marked_stale_cache_without_caching_5xx(run_node):
    run_service_worker_check(
        run_node,
        """
const request = new Request("https://example.test/pages/example", {
  credentials: "include",
});
responseCache.entries.set(request.url, new Response("current application page", {
  status: 200,
  headers: { "Content-Type": "text/html", ETag: '"safe"' },
}));
context.fetch = async (networkRequest) => {
  fetchCalls.push(networkRequest);
  return new Response("<html>upstream failure</html>", {
    status: 503,
    headers: {
      "Content-Type": "text/html",
      "Server": "Google Frontend",
    },
  });
};
const waitUntil = [];
const response = await context.handleCacheable({
  request,
  waitUntil(promise) { waitUntil.push(Promise.resolve(promise)); },
}, "/pages/example");
await Promise.all(waitUntil);
if (response.status !== 200 || await response.text() !== "current application page" ||
    response.headers.get("X-Lagniappe-Upstream-Unavailable") !== "true" ||
    response.headers.get("X-Lagniappe-Stale-Cache") !== "true" ||
    response.headers.get("X-Lagniappe-Upstream-Status") !== "503") {
  throw new Error("Upstream failure did not return an explicitly marked stale response");
}
if (responseCache.puts !== 0 || clientMessages[0]?.state?.stale !== true) {
  throw new Error("Upstream failure was cached or did not notify stale state");
}
""",
    )


# @matrix request-errors service-worker : branded-response retry upstream-unavailable
def test_upstream_failure_without_cache_returns_branded_retryable_503(run_node):
    run_service_worker_check(
        run_node,
        """
const request = { mode: "navigate", method: "GET", headers: new Headers() };
const upstream = new Response("<html>raw host error</html>", {
  status: 502,
  headers: { "Content-Type": "text/html", Server: "Google Frontend" },
});
const response = context.brandedUpstreamResponse(request, upstream);
const body = await response.text();
if (response.status !== 503 ||
    response.headers.get("Retry-After") !== "5" ||
    response.headers.get("X-Lagniappe-Upstream-Status") !== "502" ||
    !body.includes("Lagniappe is temporarily unavailable") ||
    !body.includes("Try again") ||
    body.includes("raw host error")) {
  throw new Error("Navigation did not receive the branded retryable 503");
}
""",
    )


# @matrix request-errors service-worker : branded-response mutation no-replay upstream-unavailable
def test_mutation_upstream_failure_returns_uncertain_json_without_replay(run_node):
    run_service_worker_check(
        run_node,
        """
context.fetch = async (request) => {
  fetchCalls.push(request);
  return new Response("<html>raw host error</html>", {
    status: 500,
    headers: { "Content-Type": "text/html" },
  });
};
const request = new Request("https://example.test/pages/example", {
  method: "PATCH",
  body: JSON.stringify({ name: "private form value" }),
  headers: { "Content-Type": "application/json" },
});
const waitUntil = [];
const response = await context.handleRequest({
  request,
  waitUntil(promise) { waitUntil.push(Promise.resolve(promise)); },
}, "/pages/example");
await Promise.all(waitUntil);
const body = await response.json();
if (fetchCalls.length !== 1 || response.status !== 503 ||
    body.code !== "upstream_instance_unavailable" ||
    body.retryable !== false || body.outcomeUncertain !== true ||
    clientMessages[0]?.state?.outcome_uncertain !== true) {
  throw new Error(`Mutation failure was not safely translated: ${JSON.stringify(body)}`);
}
""",
    )
