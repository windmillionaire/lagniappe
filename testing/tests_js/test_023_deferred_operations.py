"""Node-backed checks for deferred-operation browser reconciliation."""


# @features deferred-jobs
# @dimensions status batch request-limit revision polling progress timing etag backoff teardown push-acceleration decoration-opt-out
def test_deferred_operation_manager_batches_orders_and_renders_status(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const requests = [];
const activities = [];
const timers = [];
const responses = [
  {
    ok: true,
    etag: '"status-one"',
    operations: [
      {
        key: "operation-a",
        status: "running",
        phase: "generating",
        phase_label: "Generating",
        elapsed_seconds: 75,
        revision: 3,
        terminal: false,
        recovering: false,
      },
      {
        key: "operation-b",
        status: "succeeded",
        phase: "complete",
        phase_label: "Complete",
        elapsed_seconds: 12,
        revision: 2,
        terminal: true,
        recovering: false,
        source_widget: "CreateToolReport",
        destination: "tools:ToolReportList",
        entity_key: "report-b",
      },
    ],
  },
  {
    ok: true,
    etag: '"status-two"',
    operations: [
      {
        key: "operation-a",
        status: "running",
        phase: "generating",
        phase_label: "Generating",
        elapsed_seconds: 80,
        revision: 3,
        terminal: false,
        recovering: false,
      },
    ],
  },
  { ok: true, unchanged: true, etag: '"status-two"' },
];

function operationNode(key) {
  const phase = { textContent: "Waiting to start" };
  const elapsed = { textContent: "just now" };
  return {
    dataset: { operation: key, operationRevision: "0" },
    phase,
    elapsed,
    querySelector(selector) {
      if (selector === "[data-role='deferred-phase']") return phase;
      if (selector === "[data-role='deferred-elapsed']") return elapsed;
      return null;
    },
  };
}

const nodes = [operationNode("operation-a"), operationNode("operation-b")];
const context = {
  console,
  CustomEvent: class {
    constructor(type, options) { this.type = type; this.detail = options.detail; }
  },
  document: {
    hidden: false,
    createElement(tagName) {
      return {
        tagName,
        dataset: {},
        children: [],
        append(...children) { this.children.push(...children); },
        setAttribute(name, value) { this[name] = value; },
      };
    },
    querySelectorAll(selector) {
      return selector === "[data-operation]" ? nodes : [];
    },
  },
  ENDPOINTS: { deferredOperations: "/tools/operations/status" },
  createIcon(name, classes = "") {
    return {
      tagName: "span",
      className: `icon icon-spin ${classes}`.trim(),
      dataset: { icon: name },
      textContent: "progress_activity",
      setAttribute(name, value) { this[name] = value; },
    };
  },
  Math,
  request: {
    async post(url, body, options) {
      requests.push({ url, body, options });
      return responses.shift();
    },
  },
  window: {
    clearTimeout() {},
    dispatchEvent() {},
    setTimeout(callback, delay) {
      timers.push({ callback, delay });
      return timers.length;
    },
  },
};
vm.createContext(context);
let source = fs.readFileSync(
  "src/script/shared/deferredOperations.mjs",
  "utf8",
);
source = source.replace(/^import .*;\n/gm, "");
source = source.replace(
  "export class DeferredOperationManager",
  "class DeferredOperationManager",
);
source += "\nglobalThis.DeferredOperationManager = DeferredOperationManager;";
vm.runInContext(source, context);

(async () => {
  const view = {
    online: true,
	async reconcileChange(message) { activities.push(message); },
  };
  const manager = new context.DeferredOperationManager(view);
  manager.scan();
  manager.timer = null;
  await manager.poll();

  if (requests.length !== 1) throw new Error("Expected one batched request");
  if (requests[0].body.operations.join(",") !== "operation-a,operation-b") {
    throw new Error(`Operations were not batched: ${JSON.stringify(requests)}`);
  }
  if (nodes[0].phase.textContent !== "Generating") {
    throw new Error(`Phase was not rendered: ${nodes[0].phase.textContent}`);
  }
  if (nodes[0].elapsed.textContent !== "1 min") {
    throw new Error(`Elapsed time was not rendered: ${nodes[0].elapsed.textContent}`);
  }
  if (manager.operations.has("operation-b")) {
    throw new Error("Terminal operation was not removed");
  }
  if (activities.length !== 1 || activities[0].key !== "report-b") {
    throw new Error(`Terminal destination was not refreshed: ${JSON.stringify(activities)}`);
  }
  if (manager.nudge("operation-b", 2) !== false) {
    throw new Error("A completed operation should reject a stale push");
  }

  manager.timer = null;
  await manager.poll();
  if (Object.keys(requests[1].options.headers).length !== 0) {
    throw new Error("A changed operation set reused an invalid ETag");
  }
  manager.timer = null;
  await manager.poll();
  if (requests[2].options.headers["If-None-Match"] !== '"status-two"') {
    throw new Error(`Conditional status header missing: ${JSON.stringify(requests[1])}`);
  }
  if (manager.pollInterval <= 4000) {
    throw new Error("Unchanged status did not back off");
  }

  manager.receive({
    key: "operation-a",
    status: "running",
    phase: "queued",
    phase_label: "Waiting to start",
    elapsed_seconds: 1,
    revision: 2,
    terminal: false,
  });
  if (nodes[0].phase.textContent !== "Generating") {
    throw new Error("Out-of-order status replaced a newer phase");
  }
  if (manager.nudge("operation-a", 2) !== false) {
    throw new Error("An out-of-order push should be rejected before refresh");
  }

  context.document.hidden = true;
  manager.timer = null;
  await manager.poll();
  if (requests.length !== 3) throw new Error("Hidden documents must pause polling");

  manager.destroy();
  if (manager.operations.size || manager.ignored.size) {
    throw new Error("Destroy did not clear operation state");
  }

  context.document.hidden = false;
  const large = new context.DeferredOperationManager(view);
  for (let index = 0; index < 51; index += 1) {
    large.operations.set(`large-operation-${index}`, { revision: 0 });
  }
  responses.push(
    { ok: true, operations: [] },
    { ok: true, operations: [] },
  );
  const requestCount = requests.length;
  await large.poll();
  const bounded = requests.slice(requestCount);
  if (bounded.length !== 2) {
    throw new Error(`Expected two bounded status requests: ${bounded.length}`);
  }
  if (
    bounded.some((entry) => entry.body.operations.length > 50) ||
    bounded.reduce((total, entry) => total + entry.body.operations.length, 0) !== 51
  ) {
    throw new Error(`Status request bound was not enforced: ${JSON.stringify(bounded)}`);
  }
  large.destroy();

  const undecoratedForm = {
    dataset: { deferredStatus: "false" },
    querySelector() { return null; },
    append() { throw new Error("Opted-out form received operation progress"); },
  };
  const formManager = new context.DeferredOperationManager(view);
  if (!formManager.track("create-form-operation", { node: undecoratedForm })) {
    throw new Error("Opted-out form operation was not tracked");
  }
  if (undecoratedForm.dataset.operation) {
    throw new Error("Opted-out form received an operation decoration");
  }
  formManager.destroy();

  const controls = [{ disabled: false }, { disabled: false }];
  const submitGroup = {
    replacement: null,
    replaceWith(node) { this.replacement = node; },
  };
  const autofill = {
    removed: false,
    remove() { this.removed = true; },
  };
  const lockedForm = {
    dataset: { deferredLock: "form", operation: "autofill-operation" },
    setAttribute(name, value) { this[name] = value; },
    matches(selector) { return selector === "[data-operation]"; },
    querySelector(selector) {
      if (selector === "[data-role='autofill']") return autofill;
      if (selector === "[data-role='submit-group']") return submitGroup;
      return null;
    },
    querySelectorAll(selector) {
      return selector === "[data-operation]" ? [] : controls;
    },
    append() {},
  };
  const actionManager = new context.DeferredOperationManager(view);
  actionManager.scan(lockedForm);
  if (
    !submitGroup.replacement ||
    submitGroup.replacement.dataset.role !== "deferred-progress" ||
    !autofill.removed
  ) {
    throw new Error("Autofill progress did not replace the complete action area");
  }
  if (controls.some((control) => !control.disabled) || lockedForm["aria-busy"] !== "true") {
    throw new Error("Autofill lock did not disable the full form");
  }
  actionManager.destroy();

  const retryActivities = [];
  const retryManager = new context.DeferredOperationManager({
    online: true,
	async reconcileChange(message) {
		retryActivities.push(message);
		if (retryActivities.length === 1) throw new Error("retry");
	},
  });
  retryManager.operations.set("operation-retry", { revision: 0 });
  const terminal = {
    key: "operation-retry",
    status: "succeeded",
    phase: "complete",
    phase_label: "Complete",
    elapsed_seconds: 5,
    revision: 1,
    terminal: true,
    source_widget: "PageInfo",
    destination: "page:PageInfo",
    entity_key: "page-key",
  };
  if (await retryManager.receive(terminal)) {
    throw new Error("A failed destination refresh was reported as reconciled");
  }
  if (!retryManager.operations.has("operation-retry")) {
    throw new Error("Terminal operation was dropped before its destination refreshed");
  }
  if (!(await retryManager.receive(terminal))) {
    throw new Error("A successful destination refresh was not reconciled");
  }
  if (retryManager.operations.has("operation-retry") || retryActivities.length !== 2) {
    throw new Error("Terminal destination refresh was not retried exactly once");
  }
  retryManager.destroy();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


# @pair deferred-jobs:operation-order
# @pair deferred-jobs:stale-event
# @pair messaging:push-acceleration
# @pair messaging:stale-event
def test_server_change_defers_completion_to_authoritative_status(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const nudged = [];
const reconciled = [];
const context = {
  console,
  document: { hidden: false, querySelector() { return null; } },
  URLSearchParams,
  window: {
	location: { search: "" },
	matchMedia() { return { matches: false, addEventListener() {} }; },
  },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/views/base/core.mjs", "utf8");
source = source.replace(
  /^import [\s\S]*?(?=const MESSAGING_FEATURE_SELECTOR)/,
  `
const SearchBox = class {};
const EntityMenu = class {};
const Notifications = class {};
const OfflineQueue = class {};
const captureError = () => {};
const clearRecentSearchResults = () => {};
const connectivity = { online: true, hidden: false };
const DeferredOperationManager = class {};
const DeleteModal = class {};
const EditWatcher = class {};
const ENDPOINTS = {};
const EVENTS = { SERVER_CHANGE: "server-change" };
const HelpModal = class {};
const initializeMessaging = async () => null;
const Modal = class {};
const OfflineModal = class {};
const request = {};
const SyncManager = class {};
const SubmissionManager = class {
  constructor() { this.submit = () => {}; }
};
const withTransition = async (callback) => callback();
const ViewComponent = class {};
const Task = class {};
`,
);
source = source.replace("export default class Core", "class Core");
source += "\nglobalThis.Core = Core;";
vm.runInContext(source, context);

(async () => {
  const view = Object.create(context.Core.prototype);
  view.DeferredOperations = {
	nudge(operation, revision) { nudged.push([operation, revision]); },
  };
  view.reconcileChange = async (change) => { reconciled.push(change); };

  view._receiveServerChange({ detail: {
	type: "deferred-complete",
	operation: "operation-a",
	revision: 3,
	source_widget: "CreateToolReport",
	destination: "tools:ToolReportList",
  }});
  if (nudged.length !== 1 || reconciled.length) {
	throw new Error("Completion push reconciled before authoritative status confirmation");
  }

  view._receiveServerChange({ detail: { type: "delete", key: "entity-a" } });
  await Promise.resolve();
  if (reconciled.length !== 1 || reconciled[0].key !== "entity-a") {
	throw new Error("Committed server change was not routed to reconciliation");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


# @pair messaging:unavailable-token
# @pair messaging:editability
# @pair deferred-jobs:polling
# @pair sync:state-only
def test_core_keeps_non_push_controls_editable_without_fcm_token(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const context = {
  console,
  document: {
    hidden: false,
    querySelector() { return null; },
  },
  globalThis: null,
  Notification: { permission: "granted" },
  syncInit: 0,
  URLSearchParams,
  window: {
    __TESTING__: false,
    location: { search: "" },
    matchMedia() { return { matches: false, addEventListener() {} }; },
  },
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/views/base/core.mjs", "utf8");
source = source.replace(
  /^import [\s\S]*?(?=const MESSAGING_FEATURE_SELECTOR)/,
  `
const SearchBox = class {};
const EntityMenu = class {};
const Notifications = class {};
const OfflineQueue = class {};
const captureError = () => {};
const clearRecentSearchResults = () => {};
const connectivity = { online: true, hidden: false };
const DeferredOperationManager = class {};
const DeleteModal = class {};
const EditWatcher = class {};
const ENDPOINTS = {};
const EVENTS = { SERVER_CHANGE: "server-change" };
const HelpModal = class {};
const initializeMessaging = async () => null;
const Modal = class {};
const OfflineModal = class {};
const request = {};
const SyncManager = class {
  constructor(view) { this.view = view; }
  init() { syncInit += 1; }
};
const SubmissionManager = class {
  constructor() { this.submit = () => {}; }
};
const withTransition = async (callback) => callback();
const ViewComponent = class {};
const Task = class {};
`,
);
source = source.replace("export default class Core", "class Core");
source += "\nglobalThis.Core = Core;";
vm.runInContext(source, context);

(async () => {
  const root = {
    dataset: { kind: "home", readonly: "false" },
    querySelector() { return {}; },
  };
  const view = new context.Core(root);
  await view._initSync();
  if (view.readonly || root.dataset.readonly === "true") {
    throw new Error("Missing FCM token made unrelated controls read-only");
  }
  if (context.syncInit !== 1 || !view.SyncManager) {
    throw new Error("State-only SyncManager was not initialized");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )
