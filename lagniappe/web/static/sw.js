var define_BROWSER_PROTOCOL_default = { id: "lagniappe-browser", version: 4, messages: { CONNECTIVITY: "connectivity-state", UPSTREAM_UNAVAILABLE: "upstream-unavailable" }, events: {}, connectivity: { browser: ["online", "offline"], server: ["unknown", "online", "offline"], visibility: ["visible", "hidden"], controller: ["controlled", "uncontrolled"] } };
var define_PRECACHE_URLS_default = ["/chunks/account.js?v=b1f93f0c", "/chunks/admin-tools.js?v=b1f93f0c", "/chunks/analytics.js?v=b1f93f0c", "/chunks/baseList.js?v=b1f93f0c", "/chunks/baseTable.js?v=b1f93f0c", "/chunks/builder-controls.js?v=b1f93f0c", "/chunks/builder.js?v=b1f93f0c", "/chunks/category.js?v=b1f93f0c", "/chunks/combobox.js?v=b1f93f0c", "/chunks/connectivity.js?v=b1f93f0c", "/chunks/core-foundation.js?v=b1f93f0c", "/chunks/deferredOperations.js?v=b1f93f0c", "/chunks/directUpload.js?v=b1f93f0c", "/chunks/document.js?v=b1f93f0c", "/chunks/documentHistory.js?v=b1f93f0c", "/chunks/editor-dialogs.js?v=b1f93f0c", "/chunks/editor.js?v=b1f93f0c", "/chunks/entity-foundation.js?v=b1f93f0c", "/chunks/fileInfo.js?v=b1f93f0c", "/chunks/filePdfPreview.js?v=b1f93f0c", "/chunks/filters.js?v=b1f93f0c", "/chunks/form-complex.js?v=b1f93f0c", "/chunks/form-sections.js?v=b1f93f0c", "/chunks/forms.js?v=b1f93f0c", "/chunks/foundation.js?v=b1f93f0c", "/chunks/home-tools.js?v=b1f93f0c", "/chunks/html.js?v=b1f93f0c", "/chunks/index-foundation.js?v=b1f93f0c", "/chunks/index-tools.js?v=b1f93f0c", "/chunks/ingress.js?v=b1f93f0c", "/chunks/location.js?v=b1f93f0c", "/chunks/messageComposer.js?v=b1f93f0c", "/chunks/modal.js?v=b1f93f0c", "/chunks/notifications.js?v=b1f93f0c", "/chunks/offline-replay.js?v=b1f93f0c", "/chunks/offline.js?v=b1f93f0c", "/chunks/offlineWork.js?v=b1f93f0c", "/chunks/page-tools.js?v=b1f93f0c", "/chunks/permissions.js?v=b1f93f0c", "/chunks/polling.js?v=b1f93f0c", "/chunks/project-tools.js?v=b1f93f0c", "/chunks/submission.js?v=b1f93f0c", "/chunks/sync.js?v=b1f93f0c", "/chunks/task-tools.js?v=b1f93f0c", "/chunks/ui-controls.js?v=b1f93f0c", "/chunks/ui-resources.js?v=b1f93f0c", "/chunks/uploads.js?v=b1f93f0c", "/chunks/upstreamUnavailable.js?v=b1f93f0c", "/chunks/user-tools.js?v=b1f93f0c", "/chunks/userSettings.js?v=b1f93f0c", "/chunks/views/admin.js?v=b1f93f0c", "/chunks/views/analytics.js?v=b1f93f0c", "/chunks/views/builder.js?v=b1f93f0c", "/chunks/views/file.js?v=b1f93f0c", "/chunks/views/help.js?v=b1f93f0c", "/chunks/views/home.js?v=b1f93f0c", "/chunks/views/index.js?v=b1f93f0c", "/chunks/views/manual.js?v=b1f93f0c", "/chunks/views/messages.js?v=b1f93f0c", "/chunks/views/page.js?v=b1f93f0c", "/chunks/views/project.js?v=b1f93f0c", "/chunks/views/public.js?v=b1f93f0c", "/chunks/views/report.js?v=b1f93f0c", "/chunks/views/results.js?v=b1f93f0c", "/chunks/views/user.js?v=b1f93f0c", "/chunks/watcher.js?v=b1f93f0c"];
const SW_VERSION = "b1f93f0c";
const CACHE = `static-cache`;
const RESPONSE_CACHE = `response-cache`;
const PRECACHE_URLS = define_PRECACHE_URLS_default;
const UPDATED_HEADER = "X-Lagniappe-Updated";
const UPSTREAM_UNAVAILABLE_HEADER = "X-Lagniappe-Upstream-Unavailable";
const UPSTREAM_STATUS_HEADER = "X-Lagniappe-Upstream-Status";
const STALE_CACHE_HEADER = "X-Lagniappe-Stale-Cache";
const UPSTREAM_STATUSES = /* @__PURE__ */ new Set([500, 502, 503, 504]);
const STATIC_RETRY_DELAYS_MS = [250, 750];
const BROWSER_PROTOCOL = define_BROWSER_PROTOCOL_default;
const TOKEN_REQUEST = {
  credentials: "include",
  headers: { "X-Lagniappe-Request": "true" }
};
function captureError(error, context = {}) {
  if (typeof self.Sentry !== "undefined" && self.Sentry) {
    if (error instanceof Error) {
      self.Sentry.captureException(error, context);
    } else {
      self.Sentry.captureMessage(error, context);
    }
  }
}
async function updateCaches() {
  await Promise.all([caches.delete(CACHE), caches.delete(RESPONSE_CACHE)]);
  const cache = await caches.open(CACHE);
  await cache.add("/offline");
}
async function precacheStaticAssets() {
  const cache = await caches.open(CACHE);
  await Promise.allSettled(
    PRECACHE_URLS.map(async (url) => {
      const request = new Request(new URL(url, self.location.origin).href);
      const cached = await cache.match(request, { ignoreVary: true });
      if (cached && !responsePreventsStorage(cached)) return;
      const response = await fetchStaticAsset(request);
      if (response.ok && !responsePreventsStorage(response)) {
        await cache.put(request, response.clone());
      }
    })
  );
}
async function fetchStaticAsset(request) {
  let currentRequest = request;
  for (let attempt = 0; ; attempt += 1) {
    let response;
    try {
      response = await fetch(currentRequest);
    } catch (error) {
      if (request.method !== "GET" || request.signal.aborted || error != null && (typeof error === "object" || typeof error === "function") && "name" in error && error.name === "AbortError" || attempt === STATIC_RETRY_DELAYS_MS.length) {
        throw error;
      }
    }
    if (response && (request.method !== "GET" || request.signal.aborted || !UPSTREAM_STATUSES.has(response.status) || response.headers.has("X-Lagniappe-Error") || attempt === STATIC_RETRY_DELAYS_MS.length)) {
      return response;
    }
    await response?.body?.cancel().catch(() => {
    });
    await new Promise(
      (resolve) => setTimeout(resolve, STATIC_RETRY_DELAYS_MS[attempt])
    );
    if (request.signal.aborted) throw request.signal.reason;
    currentRequest = networkRequest(request, { cache: "reload" });
  }
}
const _validateUser = async (cacheConfirmation = {}) => {
  const failed = (stage, status = null) => {
    captureError(new Error("User validation acknowledgement failed."), {
      context: "validate_user",
      stage,
      ...Number.isInteger(status) ? { status } : {}
    });
    return false;
  };
  let tokenResponse;
  try {
    tokenResponse = await fetch("/l/token", TOKEN_REQUEST);
  } catch {
    return failed("token-request");
  }
  if (!tokenResponse?.ok)
    return failed("token-response", tokenResponse?.status);
  let newToken;
  try {
    newToken = (await tokenResponse.text()).trim();
  } catch {
    return failed("token-body", tokenResponse.status);
  }
  if (!newToken) return failed("token-empty", tokenResponse.status);
  let validationResponse;
  try {
    validationResponse = await fetch("/l/validate-user", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": newToken,
        "X-Lagniappe-Request": "true"
      },
      credentials: "include",
      body: JSON.stringify({
        cacheCleared: cacheConfirmation.cacheCleared === true,
        responseCacheCleared: cacheConfirmation.responseCacheCleared === true,
        cacheGeneration: cacheConfirmation.cacheGeneration,
        cacheRevision: cacheConfirmation.cacheRevision
      })
    });
  } catch {
    return failed("validation-request");
  }
  if (!validationResponse?.ok) {
    return failed("validation-response", validationResponse?.status);
  }
  let acknowledgement;
  try {
    acknowledgement = await validationResponse.json();
  } catch {
    return failed("validation-body", validationResponse.status);
  }
  if (!isRecord(acknowledgement) || acknowledgement.cacheCleared !== true) {
    if (isRecord(acknowledgement) && acknowledgement.retry === true)
      return false;
    return failed("validation-acknowledgement", validationResponse.status);
  }
  return true;
};
let _cacheGeneration = 0;
const _cacheInvalidations = /* @__PURE__ */ new Map();
const _validateUserRequests = /* @__PURE__ */ new Map();
function responseInvalidatesCache(response) {
  return response.headers.get("X-Lagniappe-Invalidate-Cache");
}
async function clearClientCache(cacheRevision = null) {
  const current = _cacheInvalidations.get(cacheRevision);
  if (current) return current;
  const cacheGeneration = _cacheGeneration + 1;
  _cacheGeneration = cacheGeneration;
  const pending = (async () => {
    await caches.delete(RESPONSE_CACHE);
    const responseCacheCleared = typeof caches.has === "function" ? !await caches.has(RESPONSE_CACHE) : true;
    return {
      cacheCleared: responseCacheCleared,
      responseCacheCleared,
      cacheGeneration
    };
  })().finally(() => {
    _cacheInvalidations.delete(cacheRevision);
  });
  _cacheInvalidations.set(cacheRevision, pending);
  return pending;
}
function validateUserOnce(cacheConfirmation) {
  if (!cacheConfirmation.cacheCleared) return null;
  const revision = cacheConfirmation.cacheRevision;
  const current = _validateUserRequests.get(revision);
  if (current) return current;
  const pending = _validateUser(cacheConfirmation).finally(() => {
    _validateUserRequests.delete(revision);
  });
  _validateUserRequests.set(revision, pending);
  return pending;
}
async function checkForCacheInvalidation(response, options = {}) {
  if (!responseInvalidatesCache(response)) return { invalidated: false };
  const cacheRevision = response.headers.get("X-Lagniappe-Cache-Revision");
  const confirmation = {
    ...await clearClientCache(cacheRevision),
    cacheRevision
  };
  const acknowledged = options.validate !== false ? await validateUserOnce(confirmation) : null;
  return {
    invalidated: true,
    ...confirmation,
    ...acknowledged === null ? {} : { acknowledged }
  };
}
async function clearSiblingCacheEntries(newETag, storedETag, url, pathname) {
  if (storedETag && newETag && storedETag === newETag) return;
  const shouldClear = pathname === "/" || pathname.startsWith("/l/get") || pathname.startsWith("/categories") || pathname.includes("/index") || pathname.includes("/rows");
  if (!shouldClear) return;
  const cache = await caches.open(RESPONSE_CACHE);
  const siblingReqs = await cache.keys(new Request(url), {
    ignoreSearch: true
  });
  const staleReqs = siblingReqs.filter((req) => req.url !== url);
  if (staleReqs.length > 0) {
    await Promise.all(staleReqs.map((req) => cache.delete(req)));
  }
}
function responsePreventsStorage(response) {
  if (responseInvalidatesCache(response)) return true;
  if (response.redirected || response.type === "opaqueredirect") return true;
  return response.headers.get("Cache-Control")?.split(",").some((directive) => directive.trim().toLowerCase() === "no-store") ?? false;
}
async function discardCachedResponse(cache, request) {
  await cache.delete(request, { ignoreVary: true });
}
async function handleUncacheableResponse(event, cache, request, response, options = {}) {
  if (!responsePreventsStorage(response)) return false;
  const discard = discardCachedResponse(cache, request);
  if (options.awaitDiscard) {
    await discard;
  } else {
    event.waitUntil(discard);
  }
  await checkForCacheInvalidation(response);
  return true;
}
let _lastEvictionCheck = 0;
const EVICTION_THROTTLE_MS = 6e4;
async function maybeEvictForQuota() {
  const now = Date.now();
  if (now - _lastEvictionCheck < EVICTION_THROTTLE_MS) return;
  _lastEvictionCheck = now;
  const storage = self.navigator?.storage;
  if (!storage?.estimate) return;
  try {
    const { usage, quota } = await storage.estimate();
    if (!usage || !quota) return;
    const THRESHOLD = 0.9;
    const BATCH_SIZE = 200;
    if (usage / quota < THRESHOLD) return;
    const cache = await caches.open(RESPONSE_CACHE);
    const keys = await cache.keys();
    if (keys.length === 0) return;
    const toDelete = keys.slice(0, Math.min(BATCH_SIZE, keys.length));
    await Promise.all(toDelete.map((req) => cache.delete(req)));
  } catch (e) {
    console.warn("Quota-based eviction failed:", e);
  }
}
let _connectivity = {
  browser: navigator.onLine === false ? "offline" : "online",
  server: "unknown",
  visibility: "visible",
  controller: "uncontrolled"
};
function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function isConnectivitySnapshot(state) {
  return Object.entries(BROWSER_PROTOCOL.connectivity).every(
    ([field, values]) => {
      const value = state[field];
      return typeof value === "string" && values.includes(value);
    }
  );
}
function receiveConnectivityMessage(data) {
  if (!isRecord(data) || data.protocol !== BROWSER_PROTOCOL.id || Number(data.protocol_version) !== BROWSER_PROTOCOL.version || data.type !== BROWSER_PROTOCOL.messages.CONNECTIVITY) {
    return false;
  }
  const state = data.state;
  if (!isRecord(state) || !isConnectivitySnapshot(state)) return false;
  _connectivity = { ...state };
  return true;
}
function isUpstreamUnavailableResponse(response) {
  return Boolean(
    response && UPSTREAM_STATUSES.has(response.status) && response.headers.get("content-type")?.includes("text/html") && !response.headers.get("X-Lagniappe-Error")
  );
}
function upstreamRouteClass(pathname) {
  if (pathname === "/") return "root";
  const segment = pathname.split("/").filter(Boolean)[0] || "root";
  if (segment === "l") return "internal";
  const allowed = /* @__PURE__ */ new Set([
    "admin",
    "analytics",
    "categories",
    "files",
    "filters",
    "forms",
    "home",
    "manual",
    "messages",
    "pages",
    "process",
    "projects",
    "public",
    "reports",
    "tasks",
    "testing",
    "users"
  ]);
  return allowed.has(segment) ? segment : "other";
}
function boundedServer(response) {
  return String(response.headers.get("Server") || "").replace(/[^\x20-\x7E]/g, "").slice(0, 128);
}
async function notifyUpstreamUnavailable(request, response, { stale = false } = {}) {
  const pathname = new URL(request.url).pathname;
  const method = String(request.method || "GET").toUpperCase();
  const message = {
    protocol: BROWSER_PROTOCOL.id,
    protocol_version: BROWSER_PROTOCOL.version,
    type: BROWSER_PROTOCOL.messages.UPSTREAM_UNAVAILABLE,
    state: {
      status: response.status,
      method,
      route_class: upstreamRouteClass(pathname),
      server: boundedServer(response),
      trace_header_present: Boolean(
        response.headers.get("X-Cloud-Trace-Context") || response.headers.get("Traceparent")
      ),
      timestamp: (/* @__PURE__ */ new Date()).toISOString(),
      online: _connectivity.browser !== "offline",
      service_worker: "controlled",
      stale: Boolean(stale),
      outcome_uncertain: method !== "GET",
      retry_outcome: "service_worker"
    }
  };
  const clients = await self.clients.matchAll({
    type: "window",
    includeUncontrolled: false
  });
  for (const client of clients) client.postMessage?.(message);
}
function upstreamHeaders(response, { stale = false, originalResponse = response } = {}) {
  const headers = new Headers(response?.headers || {});
  headers.set(UPSTREAM_UNAVAILABLE_HEADER, "true");
  headers.set(
    UPSTREAM_STATUS_HEADER,
    String(originalResponse?.status || response?.status || 503)
  );
  const server = boundedServer(originalResponse);
  if (server) headers.set("Server", server);
  headers.set(STALE_CACHE_HEADER, stale ? "true" : "false");
  headers.set("Cache-Control", "no-store");
  headers.set("Retry-After", "5");
  return headers;
}
function markedStaleResponse(cached, upstream) {
  return new Response(cached.body, {
    status: cached.status,
    statusText: cached.statusText,
    headers: upstreamHeaders(cached, {
      stale: true,
      originalResponse: upstream
    })
  });
}
function brandedUpstreamResponse(request, upstream) {
  const headers = upstreamHeaders(upstream);
  if (request.mode === "navigate") {
    headers.set("Content-Type", "text/html; charset=utf-8");
    return new Response(
      `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Lagniappe temporarily unavailable</title><body style="font:16px system-ui,sans-serif;margin:0;background:#f8fafc;color:#0f172a"><main style="max-width:42rem;margin:12vh auto;padding:2rem"><section style="background:white;border:1px solid #cbd5e1;border-radius:.75rem;padding:2rem;box-shadow:0 8px 24px #0f172a14"><h1>Lagniappe is temporarily unavailable</h1><p>The application server could not complete this request. Your saved work remains safe. Wait a moment, then try again.</p><a href="" style="display:inline-block;margin-top:1rem;padding:.65rem 1rem;border-radius:.4rem;background:#334155;color:white;text-decoration:none;font-weight:650">Try again</a></section></main></body></html>`,
      { status: 503, statusText: "Service Unavailable", headers }
    );
  }
  const applicationRequest = request.headers.get("X-Lagniappe-Request") === "true" || request.method !== "GET";
  if (applicationRequest) {
    headers.set("Content-Type", "application/json");
    return new Response(
      JSON.stringify({
        ok: false,
        error: "The application server is temporarily unavailable.",
        code: "upstream_instance_unavailable",
        upstreamUnavailable: true,
        stale: false,
        retryable: request.method === "GET",
        outcomeUncertain: request.method !== "GET"
      }),
      { status: 503, statusText: "Service Unavailable", headers }
    );
  }
  headers.set("Content-Type", "text/plain; charset=utf-8");
  return new Response(
    "Lagniappe is temporarily unavailable. Try again shortly.",
    {
      status: 503,
      statusText: "Service Unavailable",
      headers
    }
  );
}
function handleUpstreamUnavailable(event, request, response, cached) {
  event.waitUntil(
    notifyUpstreamUnavailable(request, response, { stale: Boolean(cached) })
  );
  return cached ? markedStaleResponse(cached, response) : brandedUpstreamResponse(request, response);
}
self.addEventListener("message", (event) => {
  receiveConnectivityMessage(event.data);
});
self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});
self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      await updateCaches();
      await self.clients.claim();
      await precacheStaticAssets();
    })()
  );
});
function isStatic(pathname) {
  return pathname.startsWith("/fonts/") || pathname.startsWith("/images/") || pathname.startsWith("/chunks/") || pathname.startsWith("/offline") || /\.(css|js|mjs|map|json|txt|ico)(\?|$)/.test(pathname);
}
self.addEventListener("fetch", (event) => {
  const requestUrl = event.request.url;
  const url = new URL(requestUrl);
  const pathname = url.pathname;
  if (requestUrl.includes("extension://")) return;
  if (url.origin !== self.location.origin) return;
  if (pathname === "/l/ping") return;
  if (pathname === "/l/token" && event.request.method === "GET") {
    event.respondWith(handleNetworkOnlyGet(event));
    return;
  }
  if (isStatic(pathname)) {
    event.respondWith(handleStatic(event));
    return;
  } else if (event.request.method === "GET") {
    event.respondWith(handleCacheable(event, pathname));
    return;
  }
  event.respondWith(handleRequest(event, pathname));
});
async function handleStatic(event) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(event.request, { ignoreVary: true });
  if (cached) {
    if (!responsePreventsStorage(cached)) return cached;
    await cache.delete(event.request, { ignoreVary: true });
  }
  try {
    const response = await fetchStaticAsset(event.request);
    if (isUpstreamUnavailableResponse(response)) {
      return handleUpstreamUnavailable(event, event.request, response);
    }
    if (responsePreventsStorage(response)) {
      event.waitUntil(cache.delete(event.request, { ignoreVary: true }));
    } else if (response.ok) {
      event.waitUntil(cache.put(event.request, response.clone()));
    }
    return response;
  } catch (error) {
    captureError(error, {
      url: event.request.url,
      context: "fetch_static_asset_failed"
    });
    return unavailableResponse(event.request);
  }
}
async function offlineFallback() {
  const cache = await caches.open(CACHE);
  const fallback = await cache.match("/offline");
  if (fallback) return fallback;
  return new Response("Offline", { status: 503, statusText: "Offline" });
}
async function unavailableResponse(request) {
  if (request.mode === "navigate") return offlineFallback();
  if (request.headers.get("X-Lagniappe-Request") === "true") {
    return new Response(
      JSON.stringify({
        ok: false,
        error: "You are offline",
        retryable: false,
        outcomeUncertain: true
      }),
      {
        status: 503,
        headers: { "Content-Type": "application/json" }
      }
    );
  }
  return new Response("Offline", {
    status: 503,
    statusText: "Offline",
    headers: { "Content-Type": "text/plain" }
  });
}
function networkRequest(request, { etag, cache } = {}) {
  const headers = new Headers(request.headers);
  if (cache === "reload") {
    headers.delete("If-None-Match");
    headers.delete("If-Modified-Since");
  }
  if (etag) {
    headers.set("If-None-Match", etag);
    headers.delete("If-Modified-Since");
  }
  const options = { headers };
  if (cache) options.cache = cache;
  return new Request(request, options);
}
function markResponseNotUpdated(response) {
  const headers = new Headers(response.headers);
  headers.set(UPDATED_HEADER, "false");
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}
async function handleNetworkOnlyGet(event) {
  const { request } = event;
  const cache = await caches.open(RESPONSE_CACHE);
  try {
    const response = await fetch(request);
    if (isUpstreamUnavailableResponse(response)) {
      return handleUpstreamUnavailable(event, request, response);
    }
    await discardCachedResponse(cache, request);
    event.waitUntil(checkForCacheInvalidation(response));
    return response;
  } catch (error) {
    captureError(error, {
      context: "fetch_network_only_failed",
      url: request.url
    });
    return unavailableResponse(request);
  }
}
async function handleCacheable(event, pathname) {
  const { request } = event;
  const url = request.url;
  const requestCacheGeneration = _cacheGeneration;
  const cache = await caches.open(RESPONSE_CACHE);
  let cachedResponse = await cache.match(request, {
    ignoreVary: true
  });
  const storedInvalidation = cachedResponse && responseInvalidatesCache(cachedResponse);
  if (cachedResponse && responsePreventsStorage(cachedResponse)) {
    await discardCachedResponse(cache, request);
    cachedResponse = null;
  }
  const online = _connectivity.browser !== "offline" && _connectivity.server !== "offline";
  if (!online && cachedResponse) return cachedResponse;
  const storedETag = cachedResponse?.headers.get("ETag");
  const fetchRequest = networkRequest(request, {
    etag: storedETag,
    ...storedInvalidation ? { cache: "reload" } : {}
  });
  const networkPromise = (async () => {
    try {
      let response = await fetch(fetchRequest);
      if (isUpstreamUnavailableResponse(response)) {
        return handleUpstreamUnavailable(
          event,
          request,
          response,
          cachedResponse
        );
      }
      let invalidationResult = { invalidated: false };
      let uncacheableResponse = await handleUncacheableResponse(
        event,
        cache,
        request,
        response,
        { awaitDiscard: response.status === 304 }
      );
      if (response.status === 304) {
        let shouldFetchFresh = false;
        if (uncacheableResponse) {
          shouldFetchFresh = true;
        } else if (responseInvalidatesCache(response)) {
          invalidationResult = await checkForCacheInvalidation(response) || {
            invalidated: true
          };
          cachedResponse = null;
          shouldFetchFresh = true;
        } else if (cachedResponse) {
          return markResponseNotUpdated(cachedResponse);
        }
        if (!shouldFetchFresh) {
          console.warn("304 but no cached response, fetching fresh:", url);
          shouldFetchFresh = true;
        }
        if (shouldFetchFresh) {
          response = await fetch(networkRequest(request, { cache: "reload" }));
          if (isUpstreamUnavailableResponse(response)) {
            return handleUpstreamUnavailable(
              event,
              request,
              response,
              cachedResponse
            );
          }
          uncacheableResponse = await handleUncacheableResponse(
            event,
            cache,
            request,
            response,
            { awaitDiscard: response.status === 304 }
          );
        }
      } else if (!uncacheableResponse && responseInvalidatesCache(response)) {
        invalidationResult = await checkForCacheInvalidation(response) || {
          invalidated: true
        };
        cachedResponse = null;
      }
      if (response.ok) {
        if (uncacheableResponse) return response;
        if (invalidationResult.invalidated || requestCacheGeneration !== _cacheGeneration) {
          return response;
        }
        const newETag = response.headers.get("ETag");
        event.waitUntil(cache.put(request, response.clone()));
        event.waitUntil(maybeEvictForQuota());
        event.waitUntil(
          clearSiblingCacheEntries(newETag, storedETag, url, pathname)
        );
        event.waitUntil(checkForCacheInvalidation(response));
      }
      return response;
    } catch {
      return null;
    }
  })();
  if (cachedResponse) {
    const result2 = await networkPromise;
    return result2 || cachedResponse;
  }
  const result = await networkPromise;
  if (result) return result;
  return unavailableResponse(request);
}
async function handleRequest(event, pathname) {
  const request = event.request;
  try {
    const response = await fetch(request);
    if (isUpstreamUnavailableResponse(response)) {
      return handleUpstreamUnavailable(event, request, response);
    }
    if (pathname !== "/l/validate-user" && responseInvalidatesCache(response)) {
      event.waitUntil(checkForCacheInvalidation(response));
    }
    return response;
  } catch (error) {
    captureError(error, {
      context: "request_fetch_failed",
      url: request.url,
      method: request.method
    });
    return new Response(
      JSON.stringify({ ok: false, error: "You are offline" }),
      {
        status: 503,
        headers: { "Content-Type": "application/json" }
      }
    );
  }
}
