"""Node-backed checks for the browser event and connectivity contracts."""

import json
import textwrap


def run_shared_module_check(run_node, module_path: str, exports: list[str], assertion: str):
    export_list = ", ".join(exports)
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const browserProtocol = JSON.parse(
  fs.readFileSync("config/browser_protocol.json", "utf8"),
);
const context = {{
  console,
  document: {{ hidden: false }},
  navigator: {{ onLine: true, serviceWorker: {{ controller: null }} }},
}};
context.globalThis = context;
let source = fs.readFileSync({json.dumps(module_path)}, "utf8");
source = source.replace(
  /^import BROWSER_PROTOCOL from .*;$/m,
  `const BROWSER_PROTOCOL = ${{JSON.stringify(browserProtocol)}};`,
);
source = source.replace(/\\bexport\\s+/g, "");
source += `\nObject.assign(globalThis, {{ {export_list} }});`;

vm.createContext(context);
vm.runInContext(source, context);

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    run_node(script)


PROTOCOL_EXPORTS = [
    "BROWSER_PROTOCOL_ID",
    "BROWSER_PROTOCOL_VERSION",
    "EVENTS",
    "WORKER_MESSAGES",
    "connectivityMessage",
    "parseServiceWorkerMessage",
    "validateConnectivityState",
    "validatePublicEvent",
]


# @pair browser-protocol:notification
# @pair browser-protocol:server-change
# @pair browser-protocol:sync-update
# @pair browser-protocol:import-progress
# @pair browser-protocol:validation
# @pair browser-protocol:version
# @pair browser-protocol:envelope
def test_public_event_contract_accepts_current_messages(run_node):
    run_shared_module_check(
        run_node,
        "src/script/shared/protocol.mjs",
        PROTOCOL_EXPORTS,
        """
const messages = [
  {
    protocol: "lagniappe-browser",
    protocol_version: "2",
    type: "notification",
    html: '<li data-key="notice-1">Ready</li>',
  },
  {
    protocol: "lagniappe-browser",
    protocol_version: "2",
    type: "server-change",
    message: JSON.stringify({
      type: "deferred-complete",
      source_widget: "CreateToolReport",
      destination: "tools:ToolReportList",
    }),
  },
  {
    protocol: "lagniappe-browser",
    protocol_version: "2",
    type: "sync-update",
    message: JSON.stringify({ update: { sync_id: "page-1:document" } }),
  },
  {
    protocol: "lagniappe-browser",
    protocol_version: "2",
    type: "sync-update",
    message: JSON.stringify({
      update: { fetch: true, sync_id: "page-1:document" },
    }),
  },
  {
    protocol: "lagniappe-browser",
    protocol_version: "2",
    type: "import-result",
    key: "file-1",
    count: "3",
  },
  ...["import-complete", "import-stopped", "import-error"].map((type) => ({
    protocol: "lagniappe-browser",
    protocol_version: "2",
    type,
    key: "file-1",
  })),
];

for (const data of messages) {
  const parsed = context.parseServiceWorkerMessage(data);
  if (!parsed || parsed.type !== data.type || parsed.version !== 2) {
    throw new Error(`Current message was rejected: ${JSON.stringify(data)}`);
  }
}
""",
    )


# @features browser-protocol
# @dimensions identifiers malformed-payload unknown-event incompatible-version strict-version
def test_public_event_contract_rejects_unknown_or_malformed_messages(run_node):
    run_shared_module_check(
        run_node,
        "src/script/shared/protocol.mjs",
        PROTOCOL_EXPORTS,
        """
const current = (data) => ({
  protocol: "lagniappe-browser",
  protocol_version: "2",
  ...data,
});
const invalid = [
  null,
  { type: "notification", html: "<li>Unversioned</li>" },
  current({ type: "unknown-event", key: "entity-1" }),
  current({ type: "notification", html: "" }),
  current({
    type: "activity",
    message: JSON.stringify({ type: "delete", key: "entity-1" }),
  }),
  current({
    type: "server-change",
    message: JSON.stringify({ type: "delete" }),
  }),
  current({
    type: "server-change",
    message: JSON.stringify({
      type: "deferred-complete",
      source_widget: "CreateToolReport",
    }),
  }),
  current({ type: "server-change", message: "plain text" }),
  current({ type: "sync-update", message: JSON.stringify({ update: {} }) }),
  current({ type: "import-result", key: "file-1", count: "many" }),
  current({ type: "import-complete" }),
  {
    protocol: "lagniappe-browser",
    protocol_version: "1",
    type: "notification",
    html: "<li>Old message</li>",
  },
  {
    protocol: "lagniappe-browser",
    protocol_version: "3",
    type: "notification",
    html: "<li>Future message</li>",
  },
];

for (const data of invalid) {
  if (context.parseServiceWorkerMessage(data) !== null) {
    throw new Error(`Malformed message was accepted: ${JSON.stringify(data)}`);
  }
}
""",
    )


# @features connectivity
# @dimensions worker-message state-validation version producer
def test_connectivity_messages_are_versioned_and_validated(run_node):
    run_shared_module_check(
        run_node,
        "src/script/shared/protocol.mjs",
        PROTOCOL_EXPORTS,
        """
const state = {
  browser: "online",
  server: "offline",
  visibility: "hidden",
  controller: "controlled",
};
if (!context.validateConnectivityState(state)) {
  throw new Error("Explicit connectivity state was rejected");
}
const message = context.connectivityMessage(state);
if (message.protocol !== "lagniappe-browser" ||
    message.protocol_version !== 2 ||
    message.type !== "connectivity-state" ||
    message.state === state) {
  throw new Error(`Connectivity message was not versioned: ${JSON.stringify(message)}`);
}

for (const invalid of [
  null,
  { ...state, server: "maybe" },
  { browser: "online", server: "online" },
]) {
  if (context.validateConnectivityState(invalid)) {
    throw new Error(`Invalid connectivity state was accepted: ${JSON.stringify(invalid)}`);
  }
}
let threw = false;
try {
  context.connectivityMessage({ ...state, controller: "replacing" });
} catch (error) {
  threw = error?.name === "TypeError";
}
if (!threw) throw new Error("Invalid connectivity producer state was not rejected");
""",
    )


# @features connectivity
# @dimensions startup browser-state server-health polling-recovery visibility controller
def test_connectivity_state_table_covers_lifecycle_transitions(run_node):
    run_shared_module_check(
        run_node,
        "src/script/shared/connectivity.mjs",
        ["ConnectivityState", "connectivity"],
        """
const state = new context.ConnectivityState();
const cases = [
  {
    name: "startup",
    patch: {},
    expected: {
      browser: "online",
      server: "unknown",
      visibility: "visible",
      controller: "uncontrolled",
      online: true,
    },
  },
  {
    name: "offline browser",
    patch: { browser: "offline" },
    expected: { browser: "offline", online: false },
  },
  {
    name: "failed ping while browser online",
    patch: { browser: "online", server: "offline" },
    expected: { browser: "online", server: "offline", online: false },
  },
  {
    name: "polling recovery",
    patch: { server: "online" },
    expected: { server: "online", online: true },
  },
  {
    name: "hidden",
    patch: { visibility: "hidden" },
    expected: { visibility: "hidden", hidden: true },
  },
  {
    name: "visible with controller replacement",
    patch: { visibility: "visible", controller: "controlled" },
    expected: {
      visibility: "visible",
      controller: "controlled",
      hidden: false,
    },
  },
];

for (const testCase of cases) {
  const snapshot = state.transition(testCase.patch);
  for (const [field, expected] of Object.entries(testCase.expected)) {
    const actual = field === "online"
      ? state.online
      : field === "hidden"
        ? state.hidden
        : snapshot[field];
    if (actual !== expected) {
      throw new Error(`${testCase.name}: expected ${field}=${expected}, got ${actual}`);
    }
  }
}

let threw = false;
try {
  state.transition({ server: "sometimes" });
} catch (error) {
  threw = error?.name === "TypeError";
}
if (!threw) throw new Error("Invalid state transition was accepted");
""",
    )
