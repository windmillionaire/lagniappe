/*! Third-party licenses: /third-party-licenses.txt */
import { B as BROWSER_PROTOCOL } from './connectivity.js?v=b74a2211';

const BROWSER_PROTOCOL_ID = BROWSER_PROTOCOL.id;
const BROWSER_PROTOCOL_VERSION = BROWSER_PROTOCOL.version;
const WORKER_MESSAGES = Object.freeze({ ...BROWSER_PROTOCOL.messages });
function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
function isMember(choices, value) {
  return typeof value === "string" && choices.some((choice) => choice === value);
}
function validateConnectivityState(state) {
  if (!isRecord(state)) return false;
  return isMember(["online", "offline"], state.browser) && isMember(["unknown", "online", "offline"], state.server) && isMember(["visible", "hidden"], state.visibility) && isMember(["controlled", "uncontrolled"], state.controller);
}
function connectivityMessage(state) {
  if (!validateConnectivityState(state)) {
    throw new TypeError("Invalid connectivity state");
  }
  return {
    protocol: BROWSER_PROTOCOL_ID,
    protocol_version: BROWSER_PROTOCOL_VERSION,
    type: WORKER_MESSAGES.CONNECTIVITY,
    state: { ...state }
  };
}
const UPSTREAM_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];
const UPSTREAM_STATUSES$1 = /* @__PURE__ */ new Set([500, 502, 503, 504]);
const UPSTREAM_RETRY_OUTCOMES = [
  "not_attempted",
  "failed",
  "recovered",
  "service_worker"
];
function validateUpstreamUnavailableState(state) {
  if (!isRecord(state)) return false;
  return UPSTREAM_STATUSES$1.has(Number(state.status)) && isMember(UPSTREAM_METHODS, state.method) && typeof state.route_class === "string" && /^[a-z-]{1,32}$/.test(state.route_class) && typeof state.server === "string" && state.server.length <= 128 && typeof state.trace_header_present === "boolean" && typeof state.timestamp === "string" && typeof state.online === "boolean" && isMember(["controlled", "uncontrolled"], state.service_worker) && typeof state.stale === "boolean" && typeof state.outcome_uncertain === "boolean" && isMember(UPSTREAM_RETRY_OUTCOMES, state.retry_outcome);
}

const UPSTREAM_STATUSES = /* @__PURE__ */ new Set([500, 502, 503, 504]);
const UPSTREAM_ERROR_HEADER = "X-Lagniappe-Error";
const UPSTREAM_UNAVAILABLE_HEADER = "X-Lagniappe-Upstream-Unavailable";
const UPSTREAM_STATUS_HEADER = "X-Lagniappe-Upstream-Status";
const STALE_CACHE_HEADER = "X-Lagniappe-Stale-Cache";
const UPSTREAM_RETRY_DELAY_MS = 500;
const REPORT_COOLDOWN_MS = 5 * 60 * 1e3;
const MAX_SERVER_LENGTH = 128;
const ROUTE_CLASSES = /* @__PURE__ */ new Set([
  "admin",
  "analytics",
  "categories",
  "files",
  "filters",
  "forms",
  "home",
  "internal",
  "manual",
  "messages",
  "pages",
  "process",
  "projects",
  "public",
  "reports",
  "root",
  "tasks",
  "testing",
  "users"
]);
const _reported = /* @__PURE__ */ new Map();
let _retry = null;
let _retrying = false;
let _clientInstalled = false;
function _sameOrigin(url) {
  try {
    const base = window.location.href || `${window.location.origin}/`;
    return new URL(url, base).origin === window.location.origin;
  } catch {
    return false;
  }
}
function upstreamRouteClass(url) {
  try {
    const base = window.location.href || `${window.location.origin}/`;
    const pathname = new URL(url, base).pathname;
    if (pathname === "/") return "root";
    const segment = pathname.split("/").filter(Boolean)[0] || "root";
    if (segment === "l") return "internal";
    return ROUTE_CLASSES.has(segment) ? segment : "other";
  } catch {
    return "other";
  }
}
function isUpstreamUnavailableResponse(response, url) {
  if (response?.headers?.get(UPSTREAM_UNAVAILABLE_HEADER) === "true") {
    return true;
  }
  return Boolean(
    response && _sameOrigin(url) && UPSTREAM_STATUSES.has(response.status) && response.headers.get("content-type")?.includes("text/html") && !response.headers.get(UPSTREAM_ERROR_HEADER)
  );
}
async function handleUpstreamResponse(response, {
  method,
  url,
  retryUpstream = true,
  fetchResponse,
  retryCurrent,
  retryOriginal
}) {
  let upstreamFailure = isUpstreamUnavailableResponse(response, url) ? response : null;
  let retryOutcome = "not_attempted";
  if (!upstreamFailure) {
    if (response.ok || response.status === 304) noteFreshApplicationResponse();
    return { response };
  }
  if (method === "GET" && retryUpstream) {
    await new Promise(
      (resolve) => setTimeout(resolve, UPSTREAM_RETRY_DELAY_MS)
    );
    response = await fetchResponse();
    retryOutcome = isUpstreamUnavailableResponse(response, url) ? "failed" : "recovered";
    if (retryOutcome === "recovered") {
      reportUpstreamUnavailable(
        upstreamUnavailableDetails(upstreamFailure, {
          method,
          url,
          retryOutcome
        })
      );
      if (response.ok || response.status === 304)
        noteFreshApplicationResponse();
      return { response };
    }
    upstreamFailure = response;
  }
  const details = upstreamUnavailableDetails(upstreamFailure, {
    method,
    url,
    retryOutcome
  });
  const outcomeUncertain = method !== "GET";
  reportUpstreamUnavailable(details);
  showUpstreamUnavailable(
    { stale: details.stale, outcomeUncertain },
    outcomeUncertain ? retryCurrent : retryOriginal
  );
  return {
    result: {
      ok: false,
      error: "The application server is temporarily unavailable.",
      code: "upstream_instance_unavailable",
      status: details.status,
      upstreamUnavailable: true,
      stale: details.stale,
      retryable: method === "GET",
      outcomeUncertain,
      retryOutcome
    }
  };
}
function _boundedServer(value) {
  return String(value || "").replace(/[^\x20-\x7E]/g, "").slice(0, MAX_SERVER_LENGTH);
}
function _releaseMetadata() {
  const banner = document.querySelector(
    "[data-role='upstream-unavailable']"
  );
  return {
    build: String(banner?.dataset.build || "").slice(0, 64),
    release: String(banner?.dataset.release || "").slice(0, 64)
  };
}
function upstreamUnavailableDetails(response, {
  method = "GET",
  url = "/",
  stale = null,
  retryOutcome = "not_attempted"
} = {}) {
  const originalStatus = Number(
    response.headers.get(UPSTREAM_STATUS_HEADER) || response.status
  );
  return {
    status: UPSTREAM_STATUSES.has(originalStatus) ? originalStatus : response.status,
    method: String(method).toUpperCase(),
    route_class: upstreamRouteClass(url),
    server: _boundedServer(response.headers.get("Server")),
    trace_header_present: Boolean(
      response.headers.get("X-Cloud-Trace-Context") || response.headers.get("Traceparent")
    ),
    timestamp: (/* @__PURE__ */ new Date()).toISOString(),
    online: navigator.onLine !== false,
    service_worker: navigator.serviceWorker?.controller ? "controlled" : "uncontrolled",
    stale: stale === null ? response.headers.get(STALE_CACHE_HEADER) === "true" : Boolean(stale),
    retry_outcome: retryOutcome,
    ..._releaseMetadata()
  };
}
function reportUpstreamUnavailable(details) {
  const diagnostic = {
    status: UPSTREAM_STATUSES.has(Number(details.status)) ? Number(details.status) : 503,
    method: ["GET", "POST", "PUT", "PATCH", "DELETE"].includes(
      String(details.method).toUpperCase()
    ) ? String(details.method).toUpperCase() : "GET",
    route_class: ROUTE_CLASSES.has(details.route_class) ? details.route_class : "other",
    server: _boundedServer(details.server),
    trace_header_present: details.trace_header_present === true,
    timestamp: String(details.timestamp || (/* @__PURE__ */ new Date()).toISOString()).slice(
      0,
      40
    ),
    online: details.online !== false,
    service_worker: details.service_worker === "controlled" ? "controlled" : "uncontrolled",
    build: String(details.build || "").slice(0, 64),
    release: String(details.release || "").slice(0, 64),
    stale: details.stale === true,
    retry_outcome: [
      "not_attempted",
      "failed",
      "recovered",
      "service_worker"
    ].includes(details.retry_outcome) ? details.retry_outcome : "not_attempted"
  };
  const key = `${diagnostic.method}:${diagnostic.route_class}`;
  const now = Date.now();
  if (now - (_reported.get(key) || 0) < REPORT_COOLDOWN_MS) return false;
  _reported.set(key, now);
  window.Sentry?.captureMessage?.(
    "Application server temporarily unavailable",
    {
      level: "warning",
      fingerprint: ["upstream_instance_unavailable"],
      tags: {
        failure_code: "upstream_instance_unavailable",
        method: diagnostic.method,
        route_class: diagnostic.route_class
      },
      contexts: { upstream_instance_unavailable: diagnostic }
    }
  );
  return true;
}
function _renderBanner(details) {
  const banner = document.querySelector(
    "[data-role='upstream-unavailable']"
  );
  if (!banner) return;
  const message = banner.querySelector(
    "[data-role='upstream-unavailable-message']"
  );
  const uncertain = details.outcomeUncertain === true;
  const stale = details.stale === true;
  if (message) {
    message.textContent = uncertain ? "The server is temporarily unavailable. We could not confirm whether your change was saved. Check the current state before trying it again." : stale ? "The server is temporarily unavailable. You are viewing saved content; your current work is still here." : "The server is temporarily unavailable. Your current page and unsaved work are unchanged.";
  }
  banner.dataset.visible = "true";
  banner.dataset.stale = stale ? "true" : "false";
  banner.dataset.outcomeUncertain = uncertain ? "true" : "false";
  banner.setAttribute("aria-hidden", "false");
}
function showUpstreamUnavailable(details, retry = null) {
  _retry = typeof retry === "function" ? retry : null;
  _renderBanner(details);
}
function noteFreshApplicationResponse() {
  const banner = document.querySelector(
    "[data-role='upstream-unavailable']"
  );
  if (!banner) return;
  _retry = null;
  banner.dataset.visible = "false";
  banner.dataset.stale = "false";
  banner.dataset.outcomeUncertain = "false";
  banner.setAttribute("aria-hidden", "true");
}
function receiveUpstreamUnavailable(details, retry = null) {
  if (!validateUpstreamUnavailableState(details)) return false;
  reportUpstreamUnavailable({ ...details, ..._releaseMetadata() });
  showUpstreamUnavailable(
    {
      stale: details.stale,
      outcomeUncertain: details.outcome_uncertain
    },
    retry
  );
  return true;
}
function receiveUpstreamUnavailableMessage(message) {
  if (!message || typeof message !== "object" || !("state" in message))
    return false;
  return receiveUpstreamUnavailable(message.state, async () => {
    const { request } = await import('./foundation.js?v=b74a2211').then(function (n) { return n.p; });
    return request.get(window.location.pathname, null, {
      replaceErrorPage: false,
      retryUpstream: false
    });
  });
}
function installUpstreamUnavailableBanner() {
  if (!_clientInstalled) {
    _clientInstalled = true;
    navigator.serviceWorker?.addEventListener?.("message", (event) => {
      const data = event.data;
      if (data && typeof data === "object" && "protocol" in data && data.protocol === BROWSER_PROTOCOL_ID && "protocol_version" in data && Number(data.protocol_version) === BROWSER_PROTOCOL_VERSION && "type" in data && data.type === WORKER_MESSAGES.UPSTREAM_UNAVAILABLE) {
        receiveUpstreamUnavailableMessage(data);
      }
    });
    if (window.__TESTING__) {
      window.__TEST_UPSTREAM_UNAVAILABLE__ = async () => {
        const { request } = await import('./foundation.js?v=b74a2211').then(function (n) { return n.p; });
        return request.get("/testing/upstream-unavailable");
      };
    }
  }
  const button = document.querySelector(
    "[data-role='upstream-unavailable-retry']"
  );
  if (!button || button.dataset.initialized === "true") return;
  button.dataset.initialized = "true";
  button.addEventListener("click", async () => {
    if (_retrying || !_retry) return;
    _retrying = true;
    button.disabled = true;
    button.textContent = "Trying\u2026";
    try {
      await _retry();
    } finally {
      _retrying = false;
      button.disabled = false;
      button.textContent = "Try again";
    }
  });
}

export { connectivityMessage as c, handleUpstreamResponse as h, installUpstreamUnavailableBanner as i };
