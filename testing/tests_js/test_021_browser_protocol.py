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
    "WORKER_MESSAGES",
    "connectivityMessage",
    "validateConnectivityState",
]


# @matrix browser-protocol : connectivity-only envelope version
def test_browser_protocol_contains_only_connectivity_messages(run_node):
    run_shared_module_check(
        run_node,
        "src/script/shared/protocol.mjs",
        PROTOCOL_EXPORTS,
        """
if (Object.keys(context.WORKER_MESSAGES).length !== 1 ||
    context.WORKER_MESSAGES.CONNECTIVITY !== "connectivity-state") {
  throw new Error("The worker protocol contains a non-connectivity message");
}
""",
    )


# @matrix browser-protocol : connectivity producer validation version
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
    message.protocol_version !== 3 ||
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


# @matrix connectivity : browser-state controller polling-recovery server-health startup visibility
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
