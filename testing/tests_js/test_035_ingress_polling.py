"""Node-backed checks for ingress polling ownership."""


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
