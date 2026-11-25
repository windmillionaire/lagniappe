/*! Third-party licenses: /third-party-licenses.txt */
import { c as connectivity } from './chunks/connectivity.js?v=b74a2211';
import { n as applyNotificationStateHeader } from './chunks/foundation.js?v=b74a2211';
import { i as installUpstreamUnavailableBanner, c as connectivityMessage } from './chunks/upstreamUnavailable.js?v=b74a2211';

const BUILD_ID = "b74a2211";
const VIEW_REGISTRY = Object.freeze({
  project: { entry: "project", source: "./views/project.ts" },
  page: { entry: "page", source: "./views/page.ts" },
  home: { entry: "home", source: "./views/home.ts" },
  manual: { entry: "manual", source: "./views/manual.ts" },
  help: { entry: "help", source: "./views/base/shell.ts" },
  user: { entry: "user", source: "./views/user.ts" },
  form: { entry: "index", source: "./views/base/index.ts" },
  category: { entry: "index", source: "./views/base/index.ts" },
  task: { entry: "index", source: "./views/base/index.ts" },
  builder: { entry: "builder", source: "./views/builder/builder.ts" },
  results: { entry: "results", source: "./views/results.ts" },
  file: { entry: "file", source: "./views/file.ts" },
  report: { entry: "report", source: "./views/report.ts" },
  analytics: { entry: "analytics", source: "./views/analytics.ts" },
  admin: { entry: "admin", source: "./views/admin.ts" },
  messages: { entry: "messages", source: "./views/messages.ts" }
});
Object.freeze(
  Object.fromEntries(
    Object.values(VIEW_REGISTRY).map(({ entry, source }) => [entry, source])
  )
);
const viewEntryUrl = (kind) => {
  if (!kind || !Object.hasOwn(VIEW_REGISTRY, kind)) return null;
  const entry = VIEW_REGISTRY[kind].entry;
  return entry ? `./chunks/views/${entry}.js?v=${BUILD_ID}` : null;
};
const loadView = (kind) => {
  const url = viewEntryUrl(kind);
  if (!url) return null;
  return import(url);
};

async function onError(event) {
  const {
    captureError,
    isSkippedViewTransitionError,
    isTransientNetworkError
  } = await import('./chunks/foundation.js?v=b74a2211').then(function (n) { return n.o; });
  const eventError = "error" in event ? event.error : void 0;
  const rejection = "reason" in event ? event.reason : void 0;
  const message = "message" in event ? event.message : void 0;
  const error = eventError || rejection || message || "Unknown error";
  if (isSkippedViewTransitionError(error) || isTransientNetworkError(error)) {
    event.preventDefault();
    return;
  }
  const context = event.type === "unhandledrejection" ? { event: { type: "unhandledrejection" } } : {};
  const element = document.activeElement !== document.body ? document.activeElement : null;
  captureError(error, element, context);
}
window.__CONNECTIVITY__ = connectivity.snapshot();
window.__CONNECTIVITY_READY__ = Promise.resolve();
function publishNavigationTransitionReadiness() {
  if (window.__NAVIGATION_TRANSITION_READY__) return;
  window.__NAVIGATION_TRANSITION_SETTLED__ = false;
  window.__NAVIGATION_TRANSITION_READY__ = new Promise((resolve) => {
    const publishWhenInactive = () => {
      const transition = document.activeViewTransition;
      if (transition) {
        Promise.resolve(transition.finished).catch(() => void 0).then(() => requestAnimationFrame(publishWhenInactive));
        return;
      }
      window.__NAVIGATION_TRANSITION_SETTLED__ = true;
      resolve();
    };
    if (document.activeViewTransition) {
      publishWhenInactive();
      return;
    }
    requestAnimationFrame(() => requestAnimationFrame(publishWhenInactive));
  });
}
publishNavigationTransitionReadiness();
let __activeView = null;
const getView = async () => {
  const viewElt = document.querySelector("[lp-view]");
  if (!viewElt) return null;
  if (viewElt._lp_view) return viewElt._lp_view;
  if (__activeView) return await __activeView;
  const disconnected = () => viewElt.isConnected === false;
  __activeView = (async () => {
    const viewModule = await loadView(viewElt.dataset.kind);
    if (!viewModule) {
      const { captureError } = await import('./chunks/foundation.js?v=b74a2211').then(function (n) { return n.o; });
      captureError(
        new Error(`Unknown view kind: ${viewElt.dataset.kind || "missing"}`),
        viewElt,
        { view_kind: viewElt.dataset.kind || "" }
      );
      return null;
    }
    if (disconnected()) return null;
    const view = new viewModule.default(viewElt);
    await view.init();
    if (view._destroyed || disconnected()) return null;
    view.publish?.();
    return view;
  })();
  return await __activeView;
};
let _ping = null;
const SERVER_HEALTH_TIMEOUT_MS = 5e3;
async function pingServer() {
  if (_ping) return _ping;
  _ping = (async () => {
    const controller = new AbortController();
    const timeoutId = setTimeout(
      () => controller.abort(),
      SERVER_HEALTH_TIMEOUT_MS
    );
    try {
      const response = await fetch("/l/ping", {
        method: "HEAD",
        signal: controller.signal
      });
      applyNotificationStateHeader(response.headers);
      return response.ok;
    } catch {
      return false;
    } finally {
      clearTimeout(timeoutId);
      _ping = null;
    }
  })();
  const pending = _ping;
  window.__PING_PENDING__ = pending;
  void pending.finally(() => {
    if (window.__PING_PENDING__ === pending) window.__PING_PENDING__ = null;
  });
  return pending;
}
let _pollTimeout = null;
const KEEP_AWAKE_MS = 10 * 60 * 1e3;
const POLL_MS = 2 * 1e3;
const OFFLINE_POLL_MS = 5 * 1e3;
function stopPolling() {
  if (!_pollTimeout) return;
  clearTimeout(_pollTimeout);
  _pollTimeout = null;
}
function pollServer(online) {
  stopPolling();
  if (window.__TESTING__ && online) return;
  const browserOnline = connectivity.snapshot().browser === "online";
  const delay = online ? KEEP_AWAKE_MS : browserOnline ? POLL_MS : OFFLINE_POLL_MS;
  _pollTimeout = setTimeout(syncView, delay);
}
let _sync = null;
let _syncPending = null;
function documentInactive() {
  return document.hidden || document.hasFocus?.() === false;
}
function updateConnectivity(patch) {
  const state = connectivity.transition(patch);
  window.__CONNECTIVITY__ = state;
  navigator.serviceWorker?.controller?.postMessage(connectivityMessage(state));
  return state;
}
function queueSync({
  hidden,
  blurred,
  blurredAt,
  force = false,
  browser
} = {}) {
  const pendingHidden = hidden === void 0 ? _syncPending?.hidden : Boolean(hidden);
  const pendingBlurred = blurred === void 0 ? _syncPending?.blurred : Boolean(blurred);
  const pendingBlurredAt = blurredAt === void 0 ? _syncPending?.blurredAt : blurredAt;
  const pendingBrowser = browser === void 0 ? _syncPending?.browser : browser;
  _syncPending = {
    force: Boolean(_syncPending?.force || force)
  };
  if (pendingHidden !== void 0) _syncPending.hidden = pendingHidden;
  if (pendingBlurred !== void 0) _syncPending.blurred = pendingBlurred;
  if (pendingBlurredAt !== void 0) _syncPending.blurredAt = pendingBlurredAt;
  if (pendingBrowser !== void 0) _syncPending.browser = pendingBrowser;
}
async function syncViewOnce({
  hidden = documentInactive(),
  blurred = hidden && !document.hidden && document.hasFocus?.() === false,
  blurredAt = blurred ? Date.now() : null,
  force = false,
  browser = navigator.onLine === false ? "offline" : "online"
} = {}) {
  const controller = navigator.serviceWorker?.controller ? "controlled" : "uncontrolled";
  updateConnectivity({
    browser,
    controller,
    visibility: hidden ? "hidden" : "visible"
  });
  const viewPromise = getView();
  if (hidden) {
    stopPolling();
    const view2 = await viewPromise;
    if (view2?.sync) {
      await view2.sync({ hidden: true, blurred, blurredAt, force });
    }
    return;
  }
  const online = await pingServer();
  updateConnectivity({ server: online ? "online" : "offline" });
  pollServer(online);
  const view = await viewPromise;
  if (view?.sync) {
    await view.sync({ hidden, blurred: false, blurredAt: null, force });
  }
}
async function syncView(options = {}) {
  queueSync(options);
  if (_sync) return _sync;
  _sync = (async () => {
    let firstError = null;
    while (_syncPending) {
      const nextSync = _syncPending;
      _syncPending = null;
      try {
        await syncViewOnce(nextSync);
      } catch (error) {
        firstError ||= error;
      }
    }
    if (firstError) throw firstError;
  })().finally(() => {
    _sync = null;
  });
  window.__CONNECTIVITY_READY__ = _sync;
  return _sync;
}
function browserConnectivityChanged(browser) {
  updateConnectivity({ browser });
  return syncView({ browser });
}
function suspendCurrentView({
  blurred = false,
  blurredAt = blurred ? Date.now() : null
} = {}) {
  updateConnectivity({
    browser: navigator.onLine === false ? "offline" : "online",
    controller: navigator.serviceWorker?.controller ? "controlled" : "uncontrolled",
    visibility: "hidden"
  });
  return syncView({ hidden: true, blurred, blurredAt });
}
function setTestMode() {
  const mode = document?.querySelector("meta[name='mode']")?.getAttribute("content");
  if (mode === "testing") {
    window.__TESTING__ = true;
  }
}
function pageMode() {
  return document?.querySelector("meta[name='mode']")?.getAttribute("content");
}
async function startAnalytics() {
  const { analytics } = await import('./chunks/analytics.js?v=b74a2211');
  analytics.view();
}
function startErrorHandling() {
  window.addEventListener("unhandledrejection", onError);
  window.addEventListener("error", onError);
}
function startServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register("/sw.js").catch(async (error) => {
    const { captureNetworkError } = await import('./chunks/foundation.js?v=b74a2211').then(function (n) { return n.o; });
    captureNetworkError(error, "/sw.js", { context: "service_worker" });
  });
  navigator.serviceWorker.addEventListener("controllerchange", async () => {
    updateConnectivity({
      controller: navigator.serviceWorker?.controller ? "controlled" : "uncontrolled"
    });
    const { clearRecentSearchResults } = await import('./chunks/foundation.js?v=b74a2211').then(function (n) { return n.q; });
    clearRecentSearchResults();
    syncView();
  });
}
async function startAuthenticatedLifecycle() {
  startErrorHandling();
  const [{ initializeLogoutForms }, { updateUserData }] = await Promise.all([
    import('./chunks/account.js?v=b74a2211').then(function (n) { return n.l; }),
    import('./chunks/account.js?v=b74a2211').then(function (n) { return n.a; })
  ]);
  initializeLogoutForms();
  void startAnalytics();
  void syncView();
  document.addEventListener("visibilitychange", () => {
    document.hidden ? suspendCurrentView() : syncView();
  });
  window.addEventListener(
    "offline",
    () => browserConnectivityChanged("offline")
  );
  window.addEventListener("online", () => browserConnectivityChanged("online"));
  window.addEventListener(
    "blur",
    () => suspendCurrentView({ blurred: !document.hidden })
  );
  window.addEventListener(
    "focus",
    () => syncView({ hidden: false, blurred: false, blurredAt: null })
  );
  window.addEventListener("pagehide", () => suspendCurrentView());
  window.addEventListener("pageshow", (event) => {
    syncView({ force: event.persisted });
  });
  updateUserData();
}
function initialize() {
  if (window.__INITIALIZED__) return;
  window.__INITIALIZED__ = true;
  setTestMode();
  installUpstreamUnavailableBanner();
  const mode = pageMode();
  startServiceWorker();
  if (mode === "public") {
    void getView();
    startErrorHandling();
    void startAnalytics();
    return;
  }
  void startAuthenticatedLifecycle();
}
document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", initialize, { once: true }) : initialize();

export { initialize, pingServer, suspendCurrentView, syncView };
