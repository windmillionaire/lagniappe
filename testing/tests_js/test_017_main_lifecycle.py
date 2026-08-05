"""DOM-light checks for the main frontend lifecycle coordinator."""

import textwrap


def run_main_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const fetchCalls = [];
const syncCalls = [];
const controllerMessages = [];
const serviceWorkerRegistrations = [];
const serviceWorkerListeners = new Map();
const documentListeners = new Map();
const windowListeners = new Map();
const analyticsCalls = [];
const authenticatedCalls = [];
const capturedErrors = [];
let viewElement = null;
let focused = true;
let pageMode = "production";

const connectivityState = {{
  browser: "online",
  server: "unknown",
  visibility: "visible",
  controller: "uncontrolled",
}};
const connectivity = {{
  get hidden() {{ return connectivityState.visibility === "hidden"; }},
  get online() {{
    return connectivityState.browser === "online" &&
      connectivityState.server !== "offline";
  }},
  snapshot() {{ return {{ ...connectivityState }}; }},
  transition(patch = {{}}) {{
    Object.assign(connectivityState, patch);
    return this.snapshot();
  }},
}};
const connectivityMessage = (state) => ({{
  protocol: "lagniappe-browser",
  protocol_version: 3,
  type: "connectivity-state",
  state: {{ ...state }},
}});
const parseServiceWorkerMessage = (data) => data;

const serviceWorker = {{
  controller: null,
  addEventListener(type, listener) {{
    serviceWorkerListeners.set(type, listener);
  }},
  register: async (url) => {{
    serviceWorkerRegistrations.push(url);
    return {{}};
  }},
}};

let viewLoader = async () => null;

const context = {{
  AbortController,
  analytics: {{ view() {{ analyticsCalls.push("analytics"); }} }},
  applyNotificationStateHeader() {{}},
  captureError(error) {{ capturedErrors.push(error); }},
  captureNetworkError() {{}},
  clearRecentSearchResults() {{}},
  clearTimeout,
  connectivity,
  connectivityMessage,
  configureSentry() {{}},
  CustomEvent: class {{
    constructor(type, options = {{}}) {{
      this.type = type;
      this.detail = options.detail;
    }}
  }},
  document: {{
    activeElement: null,
    body: {{}},
    hidden: false,
    readyState: "loading",
    addEventListener(type, listener) {{ documentListeners.set(type, listener); }},
    hasFocus() {{ return focused; }},
    querySelector(selector) {{
      if (selector === "[lp-view]") return viewElement;
      if (selector === "meta[name='mode']") {{
        return {{ getAttribute() {{ return pageMode; }} }};
      }}
      return null;
    }},
  }},
  fetchCalls,
  initializeLogoutForms() {{ authenticatedCalls.push("logout"); }},
  isSkippedViewTransitionError() {{ return false; }},
  isTransientNetworkError(error) {{ return error?.message === "Failed to fetch"; }},
  navigator: {{
    onLine: true,
    serviceWorker,
  }},
  parseServiceWorkerMessage,
  setTimeout,
  syncCalls,
  documentListeners,
  serviceWorkerListeners,
  serviceWorkerRegistrations,
  capturedErrors,
  updateUserData() {{ authenticatedCalls.push("user"); }},
  window: {{
    __TESTING__: true,
    addEventListener(type, listener) {{ windowListeners.set(type, listener); }},
    dispatchEvent() {{}},
  }},
  windowListeners,
}};
context.document.activeElement = context.document.body;
context.fetch = async (url, options = {{}}) => {{
  fetchCalls.push({{ url, options }});
  return new Response("pong", {{ status: 200 }});
}};
context.Response = Response;
context.globalThis = context;
context.loadView = (...args) => viewLoader(...args);
context.setView = (view) => {{ viewElement = view; }};
context.setViewLoader = (loader) => {{ viewLoader = loader; }};
context.setFocused = (value) => {{ focused = value; }};
context.setMode = (value) => {{ pageMode = value; }};
context.flushPaint = async () => {{
  await new Promise((resolve) => setTimeout(resolve, 10));
  for (let index = 0; index < 4; index += 1) await Promise.resolve();
}};

let source = fs.readFileSync("src/script/main.mjs", "utf8");
source = source.replace(
  /^import[\\s\\S]*?(?=\\/\\*\\*)/,
  "",
);
source = source.replaceAll(
  'import("./shared/analytics")',
  "Promise.resolve({{ analytics: globalThis.analytics }})",
);
source = source.replaceAll(
  'import("./shared/logout")',
  "Promise.resolve({{ initializeLogoutForms: globalThis.initializeLogoutForms }})",
);
source = source.replaceAll(
  'import("./shared/user")',
  "Promise.resolve({{ updateUserData: globalThis.updateUserData }})",
);
source = source.replaceAll(
  'import("./shared/utilities")',
  "Promise.resolve({{ clearRecentSearchResults: globalThis.clearRecentSearchResults }})",
);
source = source.replaceAll(
  'import("./shared/errors")',
  `Promise.resolve({{
    captureError: globalThis.captureError,
    captureNetworkError: globalThis.captureNetworkError,
    isSkippedViewTransitionError: globalThis.isSkippedViewTransitionError,
    isTransientNetworkError: globalThis.isTransientNetworkError,
  }})`,
);

vm.createContext(context);
vm.runInContext(source, context);
const pingServer = context.pingServer;
const setView = context.setView;
const suspendCurrentView = context.suspendCurrentView;
const syncView = context.syncView;
const initialize = context.initialize;
const flushPaint = context.flushPaint;

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    run_node(script)


# @features startup
# @dimensions navigation transient-network error-reporting
def test_navigation_fetch_abort_is_not_reported_as_application_error(run_node):
    run_main_check(
        run_node,
        """
initialize();
const handler = windowListeners.get("unhandledrejection");
if (!handler) throw new Error("Global rejection handler was not installed");

const transient = {
  type: "unhandledrejection",
  reason: new TypeError("Failed to fetch"),
  prevented: false,
  preventDefault() { this.prevented = true; },
};
await handler(transient);
if (!transient.prevented || capturedErrors.length !== 0) {
  throw new Error("A navigation fetch abort was reported as an application error");
}

const genuine = {
  type: "unhandledrejection",
  reason: new Error("broken startup"),
  preventDefault() {},
};
await handler(genuine);
if (capturedErrors.length !== 1 || capturedErrors[0].message !== "broken startup") {
  throw new Error("A genuine startup error was suppressed");
}
""",
    )


# @features offline sync
# @dimensions pagehide visibility deregistration
def test_suspend_current_view_deregisters_without_health_check(run_node):
    run_main_check(
        run_node,
        """
setView({
  _lp_view: {
    sync(options) {
      syncCalls.push(options);
    },
  },
});

await suspendCurrentView();

if (syncCalls.length !== 1 || syncCalls[0].hidden !== true) {
  throw new Error(`View was not suspended: ${JSON.stringify(syncCalls)}`);
}
if (fetchCalls.length !== 0) {
  throw new Error("Suspending the view performed a health check");
}
""",
    )


# @pair polling:blur
# @pair polling:focus
# @pair polling:visibility
# @pair polling:catch-up
def test_window_blur_suspends_polling_until_focus_catchup(run_node):
    run_main_check(
        run_node,
        """
setView({
  _lp_view: {
    async sync(options) {
      syncCalls.push(options);
    },
  },
});
initialize();
await flushPaint();
await syncView();
fetchCalls.splice(0);
syncCalls.splice(0);

context.setFocused(false);
await windowListeners.get("blur")();
if (
  fetchCalls.length !== 0 ||
  syncCalls.length !== 1 ||
  syncCalls[0].hidden !== true
) {
  throw new Error(
    `Blur did not suspend without a health request: ${JSON.stringify({ fetchCalls, syncCalls })}`,
  );
}

fetchCalls.splice(0);
syncCalls.splice(0);
context.setFocused(true);
await windowListeners.get("focus")();
if (
  fetchCalls.length !== 1 ||
  syncCalls.length !== 1 ||
  syncCalls[0].hidden !== false
) {
  throw new Error(
    `Focus did not run one catch-up cycle: ${JSON.stringify({ fetchCalls, syncCalls })}`,
  );
}
""",
    )


# @features offline
# @dimensions server-health cache-policy
def test_ping_uses_server_owned_cache_policy(run_node):
    run_main_check(
        run_node,
        """
const online = await pingServer();
if (!online || fetchCalls.length !== 1) {
  throw new Error("Ping did not complete successfully");
}
const call = fetchCalls[0];
if (call.url !== "/l/ping" || call.options.method !== "HEAD") {
  throw new Error(`Unexpected ping request: ${JSON.stringify(call)}`);
}
if ("cache" in call.options || new Headers(call.options.headers).has("Cache-Control")) {
  throw new Error("Ping overrode the server-owned cache policy");
}
""",
    )


# @pair offline:rapid-transitions
# @pair offline:coalescing
# @pair offline:server-health
# @pair offline:transitions
def test_rapid_sync_requests_coalesce_and_retain_forced_transition(run_node):
    run_main_check(
        run_node,
        """
setView({
  _lp_view: {
    async sync(options) {
      syncCalls.push(options);
    },
  },
});
const first = syncView();
const second = syncView({ force: true });
const third = syncView({ hidden: false });
await Promise.all([first, second, third]);

if (syncCalls.length !== 2) {
  throw new Error(`Rapid transitions were not coalesced: ${JSON.stringify(syncCalls)}`);
}
if (syncCalls[1].force !== true || syncCalls[1].hidden !== false) {
  throw new Error(`Pending transition options were lost: ${JSON.stringify(syncCalls[1])}`);
}
if (fetchCalls.length !== 2) {
  throw new Error(`Expected two coalesced health checks, got ${fetchCalls.length}`);
}
""",
    )


# @pair connectivity:controller-replacement
# @pair connectivity:state-publication
# @pair connectivity:version
# @pair service-worker:controller-replacement
# @pair service-worker:state-publication
# @pair service-worker:version
def test_controller_replacement_receives_current_versioned_connectivity_state(run_node):
    run_main_check(
        run_node,
        """
const firstController = {
  postMessage(message) { controllerMessages.push({ owner: "first", message }); },
};
const secondController = {
  postMessage(message) { controllerMessages.push({ owner: "second", message }); },
};
context.navigator.serviceWorker.controller = firstController;
initialize();
await flushPaint();
await syncView();

context.navigator.serviceWorker.controller = secondController;
const replace = serviceWorkerListeners.get("controllerchange");
if (!replace) throw new Error("Controller replacement listener was not registered");
replace();
await syncView();

const replacement = controllerMessages.find(({ owner }) => owner === "second");
if (!replacement) throw new Error("Replacement controller did not receive state");
const { message } = replacement;
if (message.protocol !== "lagniappe-browser" ||
    message.protocol_version !== 3 ||
    message.type !== "connectivity-state" ||
    message.state.controller !== "controlled" ||
    message.state.visibility !== "visible") {
  throw new Error(`Replacement state was malformed: ${JSON.stringify(message)}`);
}
""",
    )


# @pair startup:interaction-ready
# @pair service-worker:registration
def test_service_worker_registration_starts_immediately(run_node):
    run_main_check(
        run_node,
        """
let resolveView;
const viewReady = new Promise((resolve) => { resolveView = resolve; });
const root = {
  dataset: { kind: "page" },
  isConnected: true,
  setAttribute() {},
};
context.setView(root);
context.setViewLoader(async () => ({
  default: class {
    constructor(element) { this.elt = element; }
    async init() { await viewReady; }
    publish() { this.elt._lp_view = this; }
  },
}));

initialize();
if (serviceWorkerRegistrations.join(",") !== "/sw.js") {
  throw new Error(`Service-worker registration did not start immediately: ${serviceWorkerRegistrations}`);
}

resolveView();
await flushPaint();
if (serviceWorkerRegistrations.length !== 1) {
  throw new Error(`Service-worker registration was repeated: ${serviceWorkerRegistrations}`);
}
""",
    )


# @pair startup:public-boundary
# @pair startup:deferred-lifecycle
# @pair startup:analytics
# @pair service-worker:registration
def test_public_page_skips_authenticated_lifecycle(run_node):
    run_main_check(
        run_node,
        """
context.setMode("public");
setView({
  _lp_view: {
    sync() { syncCalls.push("private-sync"); },
  },
});
initialize();
await flushPaint();
if (analyticsCalls.length !== 1) {
  throw new Error("Public analytics did not start");
}
if (
  authenticatedCalls.length ||
  fetchCalls.length ||
  syncCalls.length
) {
  throw new Error("Public startup registered authenticated lifecycle work");
}
if (
  serviceWorkerRegistrations.join(",") !== "/sw.js" ||
  [...serviceWorkerListeners.keys()].join(",") !== "controllerchange"
) {
  throw new Error("Public startup did not install foundational service-worker infrastructure");
}
if ([...windowListeners.keys()].sort().join(",") !== "error,unhandledrejection") {
  throw new Error(`Public startup registered the wrong listeners: ${[
    ...windowListeners.keys()
  ]}`);
}
""",
    )
