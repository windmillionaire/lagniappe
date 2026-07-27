"""Node-backed checks for the frontend SyncManager request contract."""

import textwrap

def run_sync_manager_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const requestCalls = [];
let activeRequests = 0;
let maxActiveRequests = 0;
let blockFirstSync = false;
let releaseFirstSync = null;
const windowListeners = new Map();

const ENDPOINTS = {{
  register: "/register",
  deregister: "/deregister",
  sync: "/sync",
  state: "/state",
}};

const offline = {{
  deleteSyncRecord: async () => undefined,
  deleteSyncRecords: async () => undefined,
  getAllOfflineRecords: async () => ({{ sync: [] }}),
  getSyncRecord: async () => null,
  updateSyncRecord: async () => undefined,
}};

const request = {{
  post: async (url, body, options = {{}}) => {{
    activeRequests += 1;
    maxActiveRequests = Math.max(maxActiveRequests, activeRequests);
    requestCalls.push({{ url, body, options }});
    const syncCallCount = requestCalls.filter((call) => call.url === "/sync").length;
    try {{
      if (blockFirstSync && url === "/sync" && syncCallCount === 1) {{
        await new Promise((resolve) => {{
          releaseFirstSync = resolve;
        }});
      }}
      return {{ ok: true, modified: [] }};
    }} finally {{
      activeRequests -= 1;
    }}
  }},
}};

const context = {{
  clearTimeout,
  console,
  ENDPOINTS,
  EVENTS: {{ SYNC_UPDATE: "sync-update" }},
  loadHeadlessWidget: async () => null,
  offline,
  request,
  setTimeout,
  waitForAttribute: async () => undefined,
  window: {{
    addEventListener(type, listener) {{
      windowListeners.set(type, listener);
    }},
    removeEventListener(type, listener) {{
      if (windowListeners.get(type) === listener) windowListeners.delete(type);
    }},
  }},
}};

vm.createContext(context);
let source = fs.readFileSync("src/script/shared/sync.mjs", "utf8");
source = source.replace(
  'import {{ loadHeadlessWidget }} from "../widgets/loader";',
  "const loadHeadlessWidget = globalThis.loadHeadlessWidget;",
);
source = source.replace(
  'import {{ ENDPOINTS }} from "./endpoints";',
  "const ENDPOINTS = globalThis.ENDPOINTS;",
);
source = source.replace(
  'import {{ EVENTS }} from "./protocol";',
  "const EVENTS = globalThis.EVENTS;",
);
source = source.replace(
  `import {{
\tdeleteSyncRecord,
\tdeleteSyncRecords,
\tgetAllOfflineRecords,
\tgetSyncRecord,
\tupdateSyncRecord,
}} from "./offline";`,
  `const {{
\tdeleteSyncRecord,
\tdeleteSyncRecords,
\tgetAllOfflineRecords,
\tgetSyncRecord,
\tupdateSyncRecord,
}} = globalThis.offline;`,
);
source = source.replace(
  'import {{ request }} from "./request";',
  "const request = globalThis.request;",
);
source = source.replace(
  'import {{ waitForAttribute }} from "./utilities";',
  "const waitForAttribute = globalThis.waitForAttribute;",
);
source = source.replace("export class SyncManager", "class SyncManager");
source += "\\nglobalThis.SyncManager = SyncManager;";
vm.runInContext(source, context);
const SyncManager = context.SyncManager;

function nextTurn() {{
  return new Promise((resolve) => setTimeout(resolve, 0));
}}

function makeWidget({{
  syncId = "entity:document",
  syncPayloads = [],
  savePayloads = [],
}} = {{}}) {{
  return {{
    component: {{ key: "entity-key" }},
    fingerprint: "fp0",
    initialized: true,
    syncId,
    get syncData() {{
      return syncPayloads.shift() ?? null;
    }},
    get saveData() {{
      return savePayloads.shift() ?? null;
    }},
  }};
}}

function makeManager(widget, fcmToken = "token-1") {{
  const widgetList = Array.isArray(widget) ? widget : [widget];
  const widgets = Object.fromEntries(
    widgetList.map((item, index) => [item.syncId || `widget-${{index}}`, item]),
  );
  const view = {{
    components: {{ document: {{ widgets }} }},
    fcmToken,
    online: true,
  }};
  return new SyncManager(view);
}}

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""

    run_node(script)


# @features sync
# @dimensions request-queue keepalive
def test_send_updates_queues_save_behind_in_flight_sync_without_keepalive(run_node):
    run_sync_manager_check(
        run_node,
        """
const widget = makeWidget({
  syncPayloads: [{ update: "delta-1", ydoc: "ydoc-1" }],
  savePayloads: [{ update: null, ydoc: "ydoc-save", html: "<p>Save</p>" }],
});
const manager = makeManager(widget);

blockFirstSync = true;
const first = manager.sendUpdates(false);
await nextTurn();

if (requestCalls.length !== 1) {
  throw new Error(`Expected first sync request, got ${requestCalls.length}`);
}
if (requestCalls[0].options.keepalive) {
  throw new Error("Normal sync unexpectedly used keepalive");
}

const second = manager.sendUpdates(true);
await nextTurn();

if (requestCalls.length !== 1) {
  throw new Error("Queued save started before the first sync settled");
}

releaseFirstSync();
await Promise.all([first, second]);

const syncCalls = requestCalls.filter((call) => call.url === "/sync");
if (syncCalls.length !== 2) {
  throw new Error(`Expected two serialized sync calls, got ${syncCalls.length}`);
}
if (maxActiveRequests !== 1) {
  throw new Error(`Expected no overlapping sync requests, saw ${maxActiveRequests}`);
}
if (syncCalls[1].body.updates[0].save !== true) {
  throw new Error("Queued save did not run after the in-flight sync");
}
if (syncCalls.some((call) => call.options.keepalive)) {
  throw new Error("Normal queued sync unexpectedly used keepalive");
}
""",
    )


# @features sync
# @dimensions state-only
def test_state_without_token_fetches_without_registering(run_node):
    run_sync_manager_check(
        run_node,
        """
const widget = makeWidget();
const manager = makeManager(widget, null);

const remote = await manager.state(widget);

const stateCall = requestCalls.find((call) => call.url === "/state");
if (!stateCall) {
  throw new Error("State-only manager did not fetch /state");
}
if ("token" in stateCall.body) {
  throw new Error("Tokenless state request unexpectedly included a token");
}
if ("version" in stateCall.body) {
  throw new Error("Document state request included the removed form version field");
}
if (manager._registeredIds.size !== 0) {
  throw new Error("Tokenless state request registered a widget");
}
if (remote?.ok !== true) {
  throw new Error("State-only manager did not return remote state");
}
""",
    )


# @features sync
# @dimensions hidden-view
def test_hidden_view_does_not_register(run_node):
    run_sync_manager_check(
        run_node,
        """
const manager = makeManager(makeWidget());
manager.view.hidden = true;

await manager.register();

if (requestCalls.some((call) => call.url === "/register")) {
  throw new Error("Hidden view registered document presence");
}
if (manager._registered) {
  throw new Error("Hidden view entered registered state");
}
""",
    )


# @features sync
# @dimensions lifecycle-listeners
def test_destroy_removes_sync_listeners(run_node):
    run_sync_manager_check(
        run_node,
        """
const manager = makeManager(makeWidget(), null);

manager.init();
if (!windowListeners.has("sync-update") || !windowListeners.has("sync-save")) {
  throw new Error("SyncManager did not install its lifecycle listeners");
}

manager.destroy();
if (windowListeners.size !== 0) {
  throw new Error("SyncManager left lifecycle listeners installed after destroy");
}
""",
    )


# @features sync
# @dimensions tokenless-save document registration-exclusion
def test_tokenless_document_save_posts_without_registering(run_node):
    run_sync_manager_check(
        run_node,
        """
const widget = makeWidget({
  savePayloads: [{ update: "delta-save", ydoc: "ydoc-save", html: "<p>Save</p>" }],
});
const manager = makeManager(widget, null);

const response = await manager.sendUpdates(true);

const syncCall = requestCalls.find((call) => call.url === "/sync");
if (!syncCall) {
  throw new Error("Tokenless document save did not post /sync");
}
if ("token" in syncCall.body) {
  throw new Error("Tokenless document save unexpectedly included a token");
}
if (syncCall.body.updates.length !== 1) {
  throw new Error(`Expected one tokenless save update, got ${syncCall.body.updates.length}`);
}
if (syncCall.body.updates[0].sync_id !== "entity:document") {
  throw new Error("Tokenless save sent the wrong sync_id");
}
if (syncCall.body.updates[0].html !== "<p>Save</p>") {
  throw new Error("Tokenless save did not include document HTML");
}
if (manager._registeredIds.size !== 0) {
  throw new Error("Tokenless document save registered a widget");
}
if (response?.ok !== true) {
  throw new Error("Tokenless document save did not return the sync response");
}
""",
    )


# @features sync
# @dimensions deregistration keepalive
def test_deregister_keeps_unload_sync_and_cleanup_keepalive(run_node):
    run_sync_manager_check(
        run_node,
        """
const widget = makeWidget({
  savePayloads: [{ update: null, ydoc: "ydoc-save", html: "<p>Save</p>" }],
});
const manager = makeManager(widget);
manager._registeredIds.add(widget.syncId);

await manager.deregister();

const syncCall = requestCalls.find((call) => call.url === "/sync");
if (!syncCall?.options.keepalive) {
  throw new Error("Deregister save did not use keepalive");
}

const deregisterCall = requestCalls.find((call) => call.url === "/deregister");
if (!deregisterCall?.options.keepalive) {
  throw new Error("Deregister cleanup did not use keepalive");
}
""",
    )
