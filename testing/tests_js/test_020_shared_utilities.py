"""Node-backed checks for DOM-free shared frontend utilities."""

import textwrap


USER_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

function makeStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
    values,
  };
}

const geolocationCalls = [];
const posts = [];
const localStorage = makeStorage();
const sessionStorage = makeStorage();
let coords = { latitude: 37.7749, longitude: -122.4194 };
let geolocationImplementation = (success) => success({ coords });
let postImplementation = async () => ({ ok: true, userHash: "user-hash" });
const context = {
  console,
  geolocationCalls,
  Intl: {
    DateTimeFormat() {
      return { resolvedOptions: () => ({ timeZone: "America/Los_Angeles" }) };
    },
  },
  localStorage,
  navigator: {
    geolocation: {
      getCurrentPosition(success, error, options) {
        geolocationCalls.push(options);
        geolocationImplementation(success, error);
      },
    },
  },
  posts,
  request: {
    async post(...args) {
      posts.push(args);
      return postImplementation(...args);
    },
  },
  sessionStorage,
  setGeolocationImplementation(value) { geolocationImplementation = value; },
  setPostImplementation(value) { postImplementation = value; },
};

vm.createContext(context);
let source = fs.readFileSync("src/script/shared/user.mjs", "utf8");
source = source.replace(
  'import { request } from "./request";',
  "const request = globalThis.request;",
);
source = source.replaceAll("export async function ", "async function ");
source = source.replaceAll("export function ", "function ");
source += "\nglobalThis.updateUserData = updateUserData; globalThis.updateUserLocation = updateUserLocation;";
vm.runInContext(source, context);

(async () => {
__ASSERTION__
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""


def run_user_check(run_node, assertion: str):
    script = USER_HARNESS.replace(
        "__ASSERTION__", textwrap.indent(assertion.strip(), "  ")
    )
    run_node(script)


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
if (!context.areEqual(
  { values: [{ b: 2, a: 1 }, { nested: { y: 2, x: 1 } }] },
  { values: [{ a: 1, b: 2 }, { nested: { x: 1, y: 2 } }] },
)) {
  throw new Error("equivalent objects nested in arrays compared unequal");
}
if (context.areEqual({ values: [1, 2] }, { values: [2, 1] })) {
  throw new Error("array order was incorrectly normalized");
}
""",
    )


# @pairs browser-storage:availability browser-storage:json
def test_safe_storage_adapters_handle_browser_failures_and_json(run_node):
    run_node(
        """
import assert from "node:assert/strict";
import { localStore, sessionStore } from "./src/script/shared/storage.mjs";

Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  get() { throw new Error("blocked"); },
});
assert.equal(localStore.get("missing", "fallback"), "fallback");
assert.equal(localStore.set("key", "value"), false);
assert.equal(localStore.remove("key"), false);

const values = new Map();
const storage = {
  getItem(key) { return values.get(key) ?? null; },
  setItem(key, value) { values.set(key, String(value)); },
  removeItem(key) { values.delete(key); },
};
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  value: storage,
});
Object.defineProperty(globalThis, "sessionStorage", {
  configurable: true,
  value: storage,
});

assert.equal(localStore.set("plain", "value"), true);
assert.equal(localStore.get("plain", "fallback"), "value");
assert.equal(localStore.remove("plain"), true);
assert.equal(localStore.get("plain", "fallback"), "fallback");

values.set("broken", "{not-json");
assert.deepEqual(localStore.getJSON("broken", []), []);
assert.equal(values.has("broken"), false);
assert.equal(sessionStore.setJSON("state", { active: true }), true);
assert.deepEqual(sessionStore.getJSON("state"), { active: true });

const circular = {};
circular.self = circular;
assert.equal(localStore.setJSON("circular", circular), false);
storage.setItem = () => { throw new Error("quota"); };
assert.equal(sessionStore.setJSON("quota", { active: true }), false);
""",
        module=True,
    )


# @pair location:permission-deferral
# @pairs timezone:page-load timezone:session-update
def test_user_data_sync_posts_timezone_without_requesting_location(run_node):
    run_user_check(
        run_node,
        """
const startup = context.updateUserData();
if ((await startup) !== true) {
  throw new Error("Successful timezone update was not reported");
}
if (geolocationCalls.length !== 0 || posts.length !== 1) {
  throw new Error(`Startup requested location: ${geolocationCalls.length}/${posts.length}`);
}

const [url, body, options] = posts[0];
if (
  url !== "/l/update-session" ||
  body.timezone !== "America/Los_Angeles" ||
  "location" in body ||
  options.keepalive !== true
) {
  throw new Error(`Unexpected user-data update: ${JSON.stringify(posts[0])}`);
}
if (
  sessionStorage.getItem("timezone_sent") !== "America/Los_Angeles" ||
  sessionStorage.getItem("userHash") !== "user-hash"
) {
  throw new Error("Successful timezone update was not cached for the session");
}
""",
    )


# @pairs location:geolocation location:on-demand location:session-update
# @pairs location:deduplication timezone:serialized-update
def test_user_location_sync_starts_on_demand_and_deduplicates(run_node):
    run_user_check(
        run_node,
        """
const startup = context.updateUserData();
const firstLocation = context.updateUserLocation();
const secondLocation = context.updateUserLocation();
if (firstLocation !== secondLocation || firstLocation === startup) {
  throw new Error("On-demand location update was not independently deduplicated");
}
if ((await firstLocation) !== true) {
  throw new Error("Successful on-demand location update was not reported");
}
if (geolocationCalls.length !== 1 || posts.length !== 2) {
  throw new Error(`Unexpected on-demand updates: ${geolocationCalls.length}/${posts.length}`);
}

const timezoneBody = posts[0][1];
const locationBody = posts[1][1];
if (
  timezoneBody.timezone !== "America/Los_Angeles" ||
  "location" in timezoneBody ||
  "timezone" in locationBody ||
  locationBody.location.latitude !== 37.7749 ||
  locationBody.location.longitude !== -122.4194
) {
  throw new Error(`Unexpected serialized updates: ${JSON.stringify(posts)}`);
}
""",
    )


# @pairs location:session-update location:retry
def test_user_location_sync_retries_failed_session_update(run_node):
    run_user_check(
        run_node,
        """
await context.updateUserData();
posts.length = 0;
let attempts = 0;
context.setPostImplementation(async () => ({
  ok: ++attempts > 1,
  userHash: "retry-user",
}));

if ((await context.updateUserLocation()) !== false) {
  throw new Error("Failed location update was reported as successful");
}
if ((await context.updateUserLocation()) !== true) {
  throw new Error("Location update did not retry successfully");
}
if (geolocationCalls.length !== 2 || posts.length !== 2) {
  throw new Error(`Failed update was not retried: ${geolocationCalls.length}/${posts.length}`);
}
""",
    )


# @pairs location:unavailable timezone:session-update
def test_unavailable_user_location_does_not_affect_timezone_sync(run_node):
    run_user_check(
        run_node,
        """
context.setGeolocationImplementation((success, error) => error({ code: 1 }));

if ((await context.updateUserData()) !== true) {
  throw new Error("Timezone update was not reported as synchronized");
}
if (geolocationCalls.length !== 0 || posts.length !== 1) {
  throw new Error("Timezone synchronization requested browser location");
}
const body = posts[0][1];
if (body.timezone !== "America/Los_Angeles" || "location" in body) {
  throw new Error(`Location state corrupted timezone update: ${JSON.stringify(body)}`);
}
if (sessionStorage.getItem("timezone_sent") !== "America/Los_Angeles") {
  throw new Error("Timezone was not cached after success");
}
if ((await context.updateUserLocation()) !== false) {
  throw new Error("Unavailable location was reported as synchronized");
}
await context.updateUserLocation();
if (geolocationCalls.length !== 1 || posts.length !== 1) {
  throw new Error("Unavailable geolocation was retried repeatedly on one page");
}
""",
    )
