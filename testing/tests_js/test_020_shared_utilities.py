"""Node-backed checks for DOM-free shared frontend utilities."""

import textwrap


def run_utility_check(run_node, assertion: str):
    script = f"""
const fs = require("node:fs");
const vm = require("node:vm");

const observers = [];
const context = {{
  clearTimeout,
  console,
  crypto,
  document: {{}},
  MutationObserver: class {{
    constructor(callback) {{
      this.callback = callback;
      this.disconnected = false;
      observers.push(this);
    }}
    disconnect() {{ this.disconnected = true; }}
    observe() {{}}
  }},
  observers,
  setTimeout,
}};

vm.createContext(context);
let source = fs.readFileSync("src/script/shared/utilities.mjs", "utf8");
source = source.replace(
  'import {{ captureError, isSkippedViewTransitionError }} from "./errors";',
  "const captureError = () => undefined; const isSkippedViewTransitionError = () => false;",
);
source = source.replaceAll("export const ", "const ");
source = source.replaceAll("export function ", "function ");
source += "\\nglobalThis.waitForAttribute = waitForAttribute; globalThis.areEqual = areEqual;";
vm.runInContext(source, context);

(async () => {{
{textwrap.indent(assertion, "  ")}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    run_node(script)


# @pairs frontend-utilities:mutation-observer frontend-utilities:cleanup
def test_wait_for_attribute_resolves_and_cleans_up_observers(run_node):
    run_utility_check(
        run_node,
        """
const attributes = new Map();
const element = {
  hasAttribute: (name) => attributes.has(name),
  getAttribute: (name) => attributes.get(name),
};
const pending = context.waitForAttribute(element, "data-ready", 50);
if (observers.length !== 1) throw new Error("observer was not created");
attributes.set("data-ready", "yes");
observers[0].callback();
if (await pending !== "yes") throw new Error("attribute value was not returned");
if (!observers[0].disconnected) throw new Error("observer was not disconnected");

const timeoutElement = { hasAttribute: () => false, getAttribute: () => null };
let timedOut = false;
try {
  await context.waitForAttribute(timeoutElement, "data-never", 1);
} catch (error) {
  timedOut = error.message.includes("data-never");
}
if (!timedOut) throw new Error("missing attribute did not time out");
if (!observers[1].disconnected) throw new Error("timed-out observer leaked");
""",
    )


# @pairs frontend-utilities:deep-equality frontend-utilities:array-order
def test_are_equal_normalizes_object_keys_but_preserves_array_order(run_node):
    run_utility_check(
        run_node,
        """
if (!context.areEqual({ b: 2, nested: { y: 2, x: 1 } }, { nested: { x: 1, y: 2 }, b: 2 })) {
  throw new Error("equivalent object key orders compared unequal");
}
if (context.areEqual({ values: [1, 2] }, { values: [2, 1] })) {
  throw new Error("array order was incorrectly normalized");
}
""",
    )


# @pairs location:geolocation location:distance-threshold location:session-update
def test_user_location_updates_only_for_initial_or_distant_positions(run_node):
    script = """
const fs = require("node:fs");
const vm = require("node:vm");

const values = new Map();
const posts = [];
let coords = { latitude: 37.7749, longitude: -122.4194 };
const storage = {
  getItem: (key) => values.get(key) ?? null,
  setItem: (key, value) => values.set(key, value),
  removeItem: (key) => values.delete(key),
};
const context = {
  console,
  localStorage: storage,
  navigator: {
    geolocation: {
      getCurrentPosition: (success) => success({ coords }),
    },
  },
  request: {
    post: async (...args) => posts.push(args),
  },
  sessionStorage: storage,
};

vm.createContext(context);
let source = fs.readFileSync("src/script/shared/user.mjs", "utf8");
source = source.replace(
  'import { request } from "./request";',
  "const request = globalThis.request;",
);
source = source.replaceAll("export async function ", "async function ");
source += "\\nglobalThis.updateUserLocation = updateUserLocation;";
vm.runInContext(source, context);

(async () => {
  await context.updateUserLocation();
  if (posts.length !== 1) throw new Error("initial location was not posted");

  coords = { latitude: 37.78, longitude: -122.42 };
  await context.updateUserLocation();
  if (posts.length !== 1) throw new Error("nearby location triggered a post");

  coords = { latitude: 34.0522, longitude: -118.2437 };
  await context.updateUserLocation();
  if (posts.length !== 2) throw new Error("distant location was not posted");
  const body = posts[1][1];
  if (body.location.latitude !== coords.latitude) {
    throw new Error("posted location did not match geolocation");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    run_node(script)
