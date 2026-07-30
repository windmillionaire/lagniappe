"""Node-backed checks for deferred-operation poll subscriptions."""


# @features deferred-jobs
# @dimensions status revision polling progress timing backoff teardown decoration-opt-out
def test_deferred_operation_manager_batches_orders_and_renders_status(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

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
    querySelectorAll() { return []; },
  };
}

const nodes = [operationNode("operation-a"), operationNode("operation-b")];
const subscriptions = new Map();
const triggers = [];
const reconciled = [];
const expectedCompletions = [];
const coordinator = {
  subscribe(descriptor, hooks) {
    subscriptions.set(descriptor.id, hooks);
    return () => subscriptions.delete(descriptor.id);
  },
  async trigger(ids) { triggers.push(ids); return []; },
};
const context = {
  console,
  CustomEvent: class {
    constructor(type, options) { this.type = type; this.detail = options.detail; }
  },
  createIcon() { return {}; },
  document: {
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

const view = {
  PollingCoordinator: coordinator,
  EditWatcher: {
    expectDeferredCompletion(key, operation) {
      expectedCompletions.push({ key, operation });
    },
  },
  async reconcileChange(change) { reconciled.push(change); },
};
const manager = new context.DeferredOperationManager(view).init();

(async () => {
  if (subscriptions.size !== 2) {
    throw new Error("Visible operations did not create polling subscriptions");
  }
  await manager.poll();
  if (triggers.length !== 1 || triggers[0].length !== 2) {
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
    expectedCompletions[0]?.key !== "report-b" ||
    expectedCompletions[0]?.operation !== "operation-b"
  ) {
    throw new Error("Terminal operation ownership was not forwarded to form reconciliation");
  }
  if (manager.nudge("operation-a", 2) !== false) {
    throw new Error("An out-of-order operation revision was accepted");
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
