"""Node-backed checks for deferred-operation poll subscriptions."""


# @matrix deferred-jobs : backoff decoration-opt-out lazy-watcher polling progress rendered-visibility revision status teardown terminal-ownership timing visible-blur
def test_deferred_operation_manager_batches_orders_and_renders_status(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

function operationNode(key, visible = true) {
	const phase = { textContent: "Waiting to start" };
	const elapsed = { textContent: "just now" };
	return {
		dataset: { operation: key, operationRevision: "0" },
		isConnected: true,
		visible,
		phase,
		elapsed,
		closest() { return this.visible ? null : {}; },
		getClientRects() { return this.visible ? [{}] : []; },
    querySelector(selector) {
      if (selector === "[data-role='deferred-phase']") return phase;
      if (selector === "[data-role='deferred-elapsed']") return elapsed;
      return null;
    },
    querySelectorAll() { return []; },
  };
}

const nodes = [operationNode("operation-a"), operationNode("operation-b", false)];
const subscriptions = new Map();
const descriptors = new Map();
const schedules = new Map();
const triggers = [];
const reconciled = [];
const expectedCompletions = [];
let ensureEditWatcherCalls = 0;
let reschedules = 0;
const blurStarts = [];
const coordinator = {
  subscribe(descriptor, hooks) {
    descriptors.set(descriptor.id, descriptor);
    schedules.set(descriptor.id, {
      mode: hooks.mode,
      initial: hooks.initial,
    });
    subscriptions.set(descriptor.id, hooks);
    return () => subscriptions.delete(descriptor.id);
  },
	async trigger(ids) { triggers.push(ids); return []; },
	blur(startedAt) { blurStarts.push(startedAt); },
	reschedule() { reschedules += 1; },
};
const context = {
  console,
  CustomEvent: class {
    constructor(type, options) { this.type = type; this.detail = options.detail; }
  },
  createIcon() { return { setAttribute() {} }; },
  withTransition(callback) { return callback(); },
  document: {
    createElement() {
      return { dataset: {}, children: [], setAttribute() {},
        append(...children) { this.children.push(...children); } };
    },
    querySelectorAll(selector) {
      return selector === "[data-operation]" ? nodes : [];
    },
  },
  window: { dispatchEvent() {} },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/deferredOperations.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replace(
  "export class DeferredOperationManager",
  "class DeferredOperationManager",
);
source += "\nglobalThis.DeferredOperationManager = DeferredOperationManager;";
vm.runInContext(source, context);

const editWatcher = {
  expectDeferredCompletion(key, operation) {
    expectedCompletions.push({ key, operation });
  },
};
const view = {
  PollingCoordinator: coordinator,
  EditWatcher: null,
  async ensureEditWatcher() {
    ensureEditWatcherCalls += 1;
    this.EditWatcher = editWatcher;
    return editWatcher;
  },
  async reconcileChange(change) { reconciled.push(change); },
};
const manager = new context.DeferredOperationManager(view).init();

(async () => {
  if (subscriptions.size !== 2) {
    throw new Error("Visible operations did not create polling subscriptions");
  }
	if (triggers.length !== 0 ||
			descriptors.get("operation:operation-a")?.revision !== 0 ||
			schedules.get("operation:operation-a")?.initial !== "scheduled") {
		throw new Error("Server-rendered operation did not seed a delayed revision cursor");
	}
	if (
		subscriptions.get("operation:operation-a").whileBlurred() !== true ||
		subscriptions.get("operation:operation-b").whileBlurred() !== false
	) {
		throw new Error("Blurred polling did not follow rendered operation visibility");
	}
	manager.track("operation-local", { revision: 2 });
	if (triggers.length !== 1 || triggers[0] !== "operation:operation-local") {
		throw new Error("Locally started operation did not request an immediate poll");
	}
	if (subscriptions.get("operation:operation-local").whileBlurred() !== false) {
		throw new Error("A background-only operation qualified for visible blur polling");
	}
	view.hidden = true;
	view.blurred = true;
	view.blurredAt = 42;
	manager.track("operation-a", { node: nodes[0], immediate: false });
	view.hidden = false;
	view.blurred = false;
	if (reschedules !== 1 || blurStarts.join(",") !== "42") {
		throw new Error("Existing operation visibility did not refresh scheduling");
	}
  await manager.poll();
  if (triggers.length !== 2 || triggers[1].length !== 3) {
    throw new Error("Operation poll did not delegate a batch to the coordinator");
  }

  await subscriptions.get("operation:operation-a").onResult({
    status: "changed",
    payload: {
      key: "operation-a",
      status: "running",
      phase: "generating",
      phase_label: "Generating",
      elapsed_seconds: 75,
      revision: 3,
      terminal: false,
    },
  });
  if (nodes[0].phase.textContent !== "Generating" ||
      nodes[0].elapsed.textContent !== "1 min") {
    throw new Error("Active operation status was not rendered");
  }

  await subscriptions.get("operation:operation-b").onResult({
    status: "changed",
    payload: {
      key: "operation-b",
      status: "succeeded",
      phase: "complete",
      phase_label: "Complete",
      elapsed_seconds: 12,
      revision: 2,
      terminal: true,
      entity_key: "report-b",
      source_widget: "CreateToolReport",
      destination: "tools:ToolReportList",
    },
  });
  if (manager.operations.has("operation-b") ||
      reconciled[0]?.key !== "report-b") {
    throw new Error("Terminal operation was not reconciled and retired");
  }
  if (
    ensureEditWatcherCalls !== 1 ||
    expectedCompletions[0]?.key !== "report-b" ||
    expectedCompletions[0]?.operation !== "operation-b"
  ) {
    throw new Error("Terminal operation did not await ownership reconciliation");
  }
  if (manager.nudge("operation-a", 2) !== false) {
    throw new Error("An out-of-order operation revision was accepted");
  }

  const newer = operationNode("operation-a");
  Object.assign(newer.dataset, {
    operationRevision: "5", operationStatus: "retry_wait",
    operationPhase: "using_tools", operationPhaseLabel: "Checking context",
    operationRecovering: "true", operationElapsed: "80",
  });
  const older = operationNode("operation-a");
  Object.assign(older.dataset, {
    operationRevision: "2", operationStatus: "running",
    operationPhase: "generating", operationPhaseLabel: "Generating",
  });
  nodes.push(newer, older);
  manager.scan();
  for (const node of [nodes[0], newer, older]) {
    if (node.phase.textContent !== "Checking context. Automatic recovery is active." ||
        node.dataset.operationRevision !== "5") {
      throw new Error("An older sibling snapshot replaced the shared latest status");
    }
  }
  manager.scan();
  await subscriptions.get("operation:operation-a").onResult({ status: "unchanged" });
  if (older.phase.textContent !== newer.phase.textContent ||
      manager.operations.get("operation-a").status.phase_label !== "Checking context") {
    throw new Error("Rescanning rendered progress lost the cached phase metadata");
  }
  manager.nudge("operation-a");
  if (manager.operations.get("operation-a").revision !== 5) {
    throw new Error("A cursorless nudge erased the shared operation revision");
  }
  manager.track("operation-replacement", { node: newer, immediate: false });
  if (!subscriptions.has("operation:operation-a") || older.dataset.operation !== "operation-a") {
    throw new Error("Reusing one target retired a job still owned by another target");
  }

  const owner = operationNode("operation-owned");
  owner.querySelector = (selector) => owner.progress?.children.find(
    (child) => selector === "[data-role='deferred-phase']" && child.dataset?.role === "deferred-phase",
  );
  owner.append = (progress) => { owner.progress = progress; };
  nodes.push(owner);
  manager.track("operation-owned", { node: owner, immediate: false });
  if (!owner.progress || owner.progress.dataset.operation) {
    throw new Error("Generated progress became a second operation owner");
  }
  manager.track("operation-next", { node: owner, immediate: false });
  if (subscriptions.has("operation:operation-owned") || owner.dataset.operation !== "operation-next") {
    throw new Error("Generated progress kept a replaced operation subscribed");
  }

  manager.destroy();
  if (manager.operations.size || subscriptions.size) {
    throw new Error("Destroy did not clear operation state");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


# @matrix deferred-jobs : terminal-ownership revision
def test_deferred_operation_manager_reconciles_server_rendered_terminal_status(
    run_node,
):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const phase = { textContent: "Complete" };
const elapsed = { textContent: "just now" };
const node = {
  dataset: {
    key: "report-ready",
    operation: "operation-complete",
    operationRevision: "7",
    operationStatus: "succeeded",
    operationPhase: "complete",
    operationPhaseLabel: "Complete",
    operationElapsed: "3",
    operationRecovering: "false",
    operationTerminal: "true",
  },
  isConnected: true,
  closest() { return null; },
  getClientRects() { return [{}]; },
  querySelector(selector) {
    if (selector === "[data-role='deferred-phase']") return phase;
    if (selector === "[data-role='deferred-elapsed']") return elapsed;
    return null;
  },
  querySelectorAll() { return []; },
};
const subscriptions = new Map();
const triggers = [];
const events = [];
const reconciled = [];
const expectedCompletions = [];
const context = {
  console,
  setTimeout,
  CustomEvent: class {
    constructor(type, options) { this.type = type; this.detail = options.detail; }
  },
  createIcon() { return {}; },
  withTransition(callback) { return callback(); },
  document: {
    querySelectorAll(selector) {
      return selector === "[data-operation]" ? [node] : [];
    },
  },
  window: { dispatchEvent(event) { events.push(event); } },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/deferredOperations.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replace(
  "export class DeferredOperationManager",
  "class DeferredOperationManager",
);
source += "\nglobalThis.DeferredOperationManager = DeferredOperationManager;";
vm.runInContext(source, context);

const view = {
  PollingCoordinator: {
    subscribe(descriptor, hooks) {
      subscriptions.set(descriptor.id, { descriptor, ...hooks });
      return () => subscriptions.delete(descriptor.id);
    },
    trigger(ids) { triggers.push(ids); },
    reschedule() {},
  },
  EditWatcher: {
    expectDeferredCompletion(key, operation) {
      expectedCompletions.push({ key, operation });
    },
  },
  async reconcileChange(change) {
    reconciled.push(change);
    if (reconciled.length === 1) throw new Error("Replacement temporarily unavailable");
  },
};

(async () => {
  const manager = new context.DeferredOperationManager(view).init();
  manager.scan();
  const subscription = subscriptions.get("operation:operation-complete");
  if (events.length || reconciled.length || subscriptions.size !== 1 ||
      subscription.descriptor.revision >= 7 || triggers.length !== 2) {
    throw new Error("Terminal HTML bypassed the authoritative operation poll");
  }
  const result = {
    status: "changed",
    payload: {
      key: "operation-complete", revision: 7, status: "succeeded",
      phase: "complete", phase_label: "Complete", terminal: true,
      entity_key: "authoritative-report", source_widget: "CreateToolReport",
      destination: "tools:ToolReportList",
    },
  };
  if (await subscription.onResult(result) !== false || subscriptions.size !== 1) {
    throw new Error("Failed terminal replacement was acknowledged instead of retried");
  }
  if (await subscription.onResult(result) !== true) {
    throw new Error("Terminal replacement could not recover at the same revision");
  }

  if (
    events.length !== 2 ||
    events[0].type !== "deferred-operation" ||
    events[0].detail.key !== "operation-complete" ||
    events[0].detail.entity_key !== "authoritative-report"
  ) {
    throw new Error("Server-rendered terminal status was not published to its view owner");
  }
  if (
    reconciled.length !== 2 ||
    reconciled[0].type !== "deferred-complete" ||
    reconciled[0].key !== "authoritative-report" ||
    reconciled[0].destination !== "tools:ToolReportList" ||
    reconciled[0].source_widget !== "CreateToolReport" ||
    expectedCompletions[0]?.operation !== "operation-complete"
  ) {
    throw new Error("Server-rendered terminal status was not reconciled");
  }
  if (manager.operations.size || subscriptions.size) {
    throw new Error("Reconciled terminal seed remained subscribed");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )
