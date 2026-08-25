"""Node-backed checks for ingress polling ownership and stage actions."""


# @features ingress ui-action
# @dimensions stage-action single-flight retryable-action polling-recovery
def test_ingress_stage_action_failure_restores_button_and_polling_for_retry(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const document = { activeElement: null, body: {} };
const context = {
  buttons: {
    active({ existingButton }) {
      return {
        activate(text, kind) {
          existingButton.disabled = true;
          existingButton.textContent = text;
          if (kind) existingButton.dataset.kind = kind;
        },
        deactivate(text, kind) {
          existingButton.disabled = false;
          existingButton.textContent = text;
          if (kind) existingButton.dataset.kind = kind;
        },
      };
    },
  },
  captureError() {},
  console,
  document,
  DOMParser: class {},
  FacetsBox: class {},
  Modal: class {},
  primitives: {},
  request: {},
  SelectBox: class {},
  withTransition(callback) { return callback(); },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/ingress.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class ImportData", "class ImportData");
source += "\nglobalThis.ImportData = ImportData;";
vm.runInContext(source, context);

(async () => {
const stage = {};
const progress = {};
const target = {
  dataset: { stage: "IMPORTING" },
  querySelector(selector) {
    if (selector === "[data-role='stage']") return stage;
    if (selector === "[data-role='progress']") return progress;
    return null;
  },
};
const widget = new context.ImportData({ key: "ingress-key", target });
let pollingRestarts = 0;
let operationCount = 0;
let finishRequest;
let shownError = null;
widget.importRequestStarted = true;
widget._clearError = () => { shownError = null; };
widget._showError = (message) => { shownError = message; };
widget._setImportStopped = () => { widget.importRequestStarted = false; };
widget._startImportPolling = () => {
  pollingRestarts += 1;
  widget.importRequestStarted = true;
};

const attributes = {};
const button = {
  dataset: { kind: "delete" },
  disabled: false,
  isConnected: true,
  textContent: "Stop Import",
  setAttribute(name, value) { attributes[name] = value; },
  removeAttribute(name) { delete attributes[name]; },
  focus() { document.activeElement = this; },
};
document.activeElement = button;
const options = {
  pendingText: "Stopping...",
  pendingKind: "delete",
  fallback: "Import could not be stopped. Please try again.",
  pausePolling: true,
  operation() {
    operationCount += 1;
    return new Promise((resolve) => { finishRequest = resolve; });
  },
};

const first = widget._runStageAction(button, options);
const duplicate = widget._runStageAction(button, options);
if (first !== duplicate || operationCount !== 1) {
  throw new Error("Concurrent ingress actions were not coalesced");
}
if (!button.disabled || attributes["aria-busy"] !== "true") {
  throw new Error("Ingress action did not expose its pending state");
}
finishRequest({ ok: false, error: "Stop unavailable" });
if (await first !== false) throw new Error("Failed ingress action was not reported");
if (
  button.disabled ||
  button.textContent !== "Stop Import" ||
  attributes["aria-busy"] !== undefined
) {
  throw new Error("Failed ingress action did not restore its control");
}
if (shownError !== "Stop unavailable" || pollingRestarts !== 1) {
  throw new Error("Failed stop did not preserve its error and polling lifecycle");
}

const retry = widget._runStageAction(button, options);
if (retry === first || operationCount !== 2) {
  throw new Error("Released ingress action could not be retried");
}
finishRequest({ ok: false, error: "Still unavailable" });
await retry;
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    )


# @features ingress
# @dimensions stage-update serialization next-action
def test_ingress_next_waits_for_pending_stage_update(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

let finishPatch;
let patchFinished = false;
const calls = [];
const context = {
  buttons: {},
  console,
  DOMParser: class {},
  FacetsBox: class {},
  FormData: class {
    constructor(form) { this.form = form; }
    append() {}
  },
  formatting: {},
  Modal: class {},
  primitives: {},
  request: {
    patch() {
      calls.push("patch:start");
      return new Promise((resolve) => {
        finishPatch = () => {
          patchFinished = true;
          calls.push("patch:finish");
          resolve({ ok: true });
        };
      });
    },
    async put() {
      calls.push(`next:${patchFinished}`);
      return { stage: "ASSIGN_COLUMNS" };
    },
  },
  SelectBox: class {},
  withTransition(callback) { return callback(); },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/ingress.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class ImportData", "class ImportData");
source += "\nglobalThis.ImportData = ImportData;";
vm.runInContext(source, context);

(async () => {
const form = {};
const stage = { querySelectorAll() { return []; } };
const progress = {};
const target = {
  dataset: { stage: "CHOOSE_FORM" },
  querySelector(selector) {
    if (selector === "[data-role='stage']") return stage;
    if (selector === "[data-role='progress']") return progress;
    return null;
  },
};
const widget = new context.ImportData({
  endpoints: {
    update() { return "/update"; },
    next() { return "/next"; },
  },
  key: "ingress-key",
  target,
});
widget.stageSettings = { target: form };
widget._setStage = () => true;

const change = widget._change({
  target: { closest(selector) { return selector === "form" ? form : null; } },
});
const next = widget._next();
await Promise.resolve();
if (calls.includes("next:false")) {
  throw new Error("Next raced the pending stage update");
}

finishPatch();
await Promise.all([change, next]);
if (calls.join(",") !== "patch:start,patch:finish,next:true") {
  throw new Error(`Stage actions were not serialized: ${calls.join(",")}`);
}
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @pairs ingress:active-widget ingress:visibility ingress:subscription-lifecycle ingress:catch-up
# @pairs polling:active-widget polling:visibility polling:subscription-lifecycle polling:catch-up
def test_ingress_polling_tracks_widget_visibility(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const subscriptions = new Map();
const coordinator = {
  subscribe(descriptor, hooks) {
    subscriptions.set(descriptor.id, { descriptor, hooks });
    return () => subscriptions.delete(descriptor.id);
  },
};
const context = {
  buttons: {},
  console,
  DOMParser: class {},
  FacetsBox: class {},
  formatting: {},
  Modal: class {},
  primitives: {},
  request: {},
  SelectBox: class {},
  withTransition(callback) { return callback(); },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/ingress.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class ImportData", "class ImportData");
source += "\nglobalThis.ImportData = ImportData;";
vm.runInContext(source, context);

const stage = {};
const progress = {};
const target = {
  dataset: { stage: "IMPORTING", fingerprint: "ingress-v1" },
  querySelector(selector) {
    if (selector === "[data-role='stage']") return stage;
    if (selector === "[data-role='progress']") return progress;
    return null;
  },
};
const ancestor = {
  dataset: { visible: "false" },
  parentElement: { closest() { return null; } },
};
const component = {
  active: null,
  visible: false,
  elt: {
    parentElement: {
      closest(selector) {
        return selector === "[lp-component]" ? ancestor : null;
      },
    },
  },
};
const widget = new context.ImportData({
  component,
  key: "ingress-key",
  target,
  view: { PollingCoordinator: coordinator },
  visible: false,
});

widget._startImportPolling();
if (subscriptions.size) {
  throw new Error("Hidden running import received a polling subscription");
}

component.active = widget;
component.visible = true;
widget.visible = true;
widget.syncPollingSubscription();
if (subscriptions.size) {
  throw new Error("Import inside a hidden parent received a subscription");
}

ancestor.dataset.visible = "true";
widget.syncPollingSubscription();
if (!subscriptions.has("ingress:ingress-key")) {
  throw new Error("Active import did not receive a polling subscription");
}

widget.visible = false;
widget.syncPollingSubscription();
if (subscriptions.size) {
  throw new Error("Deactivated import kept its polling subscription");
}

widget.visible = true;
widget.syncPollingSubscription();
if (!subscriptions.has("ingress:ingress-key")) {
  throw new Error("Reopened running import did not restore polling");
}

widget._setImportStopped();
if (subscriptions.size || widget.importRequestStarted) {
  throw new Error("Completed import retained polling state");
}
'''
    )
