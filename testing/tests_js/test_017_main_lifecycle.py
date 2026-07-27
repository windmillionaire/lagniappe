"""DOM-light checks for the main frontend lifecycle coordinator."""

import textwrap


def run_main_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const fetchCalls = [];
const syncCalls = [];
const controllerMessages = [];
const serviceWorkerListeners = new Map();
let viewElement = null;

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
  protocol_version: 2,
  type: "connectivity-state",
  state: {{ ...state }},
}});
const parseServiceWorkerMessage = (data) => data;

const serviceWorker = {{
  controller: null,
  addEventListener(type, listener) {{
    serviceWorkerListeners.set(type, listener);
  }},
  register: async () => ({{}}),
}};

const context = {{
  AbortController,
  analytics: {{ view() {{}} }},
  captureError() {{}},
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
    addEventListener() {{}},
    querySelector(selector) {{
      return selector === "[lp-view]" ? viewElement : null;
    }},
  }},
  fetchCalls,
  initializeLogoutForms() {{}},
  isSkippedViewTransitionError() {{ return false; }},
  navigator: {{
    onLine: true,
    serviceWorker,
  }},
  parseServiceWorkerMessage,
  setTimeout,
  syncCalls,
  serviceWorkerListeners,
  updateUserData() {{}},
  window: {{
    __TESTING__: true,
    addEventListener() {{}},
    dispatchEvent() {{}},
  }},
}};
context.document.activeElement = context.document.body;
context.fetch = async (url, options = {{}}) => {{
  fetchCalls.push({{ url, options }});
  return new Response("pong", {{ status: 200 }});
}};
context.Response = Response;
context.globalThis = context;
context.setView = (view) => {{ viewElement = view; }};

let source = fs.readFileSync("src/script/main.mjs", "utf8");
source = source.replace('import "../style/main.css";', "");
source = source.replace(
  /import \\{{[\\s\\S]*?\\}} from "\\.\\/shared";/,
  "",
);

vm.createContext(context);
vm.runInContext(source, context);
const pingServer = context.pingServer;
const setView = context.setView;
const suspendCurrentView = context.suspendCurrentView;
const syncView = context.syncView;
const initialize = context.initialize;

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    run_node(script)


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

suspendCurrentView();

if (syncCalls.length !== 1 || syncCalls[0].hidden !== true) {
  throw new Error(`View was not suspended directly: ${JSON.stringify(syncCalls)}`);
}
if (fetchCalls.length !== 0) {
  throw new Error("Suspending the view performed a health check");
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
if (call.url !== "/ping" || call.options.method !== "HEAD") {
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
    message.protocol_version !== 2 ||
    message.type !== "connectivity-state" ||
    message.state.controller !== "controlled" ||
    message.state.visibility !== "visible") {
  throw new Error(`Replacement state was malformed: ${JSON.stringify(message)}`);
}
""",
    )
