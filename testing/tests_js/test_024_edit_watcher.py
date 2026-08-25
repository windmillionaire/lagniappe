"""Node-backed checks for generic form state and committed edit watching."""


# @matrix forms unsaved-state : change input non-sync reset success
def test_base_form_tracks_unsaved_state_without_sync(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const listeners = new Map();
const target = {
  addEventListener(type, listener) { listeners.set(type, listener); },
  removeEventListener(type) { listeners.delete(type); },
  hasAttribute(name) { return false; },
  querySelector() { return null; },
};
const submitButton = { disabled: false };
const widget = {
  target,
  submitButton,
  readonly: false,
  schema: [],
  submission: {},
  messages: { submit: "Save", submitting: "Saving", submitted: "Saved" },
  unsavedState: false,
};

const context = {
  console,
  queueMicrotask,
  showBriefly() {},
  withTransition(callback) { return callback(); },
  primitives: { error() { return {}; } },
  Renderer: class {},
  ICONS: { builder: { unsaved: "unsaved" } },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/base/baseForm.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class BaseForm", "class BaseForm");
source += "\nglobalThis.BaseForm = BaseForm;";
vm.runInContext(source, context);

const form = new context.BaseForm(widget);
form.setSubmitButton = (state) => { form.lastState = state; };
form.hideError = () => {};
form._initUnsavedState();

if (!listeners.has("input") || !listeners.has("change")) {
  throw new Error("Unsynced form did not receive dirty listeners");
}
listeners.get("input")({
  target: { disabled: false, matches() { return true; } },
});
if (!widget.unsavedState || form.lastState.icon !== "builder.unsaved") {
  throw new Error("Input did not expose generic unsaved state");
}

form.success();
if (widget.unsavedState) throw new Error("Successful submit kept dirty state");

listeners.get("change")({
  target: { disabled: false, matches() { return true; } },
});
listeners.get("reset")();
queueMicrotask(() => {
  if (widget.unsavedState) throw new Error("Reset kept dirty state");
});
'''
    )


# @matrix edited-entity-notice forms : canonicalization formdata repeated-values revision-only-state
def test_form_revision_snapshot_is_canonical_and_memory_only(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class FakeFormData {
  constructor(entries = []) { this.values = entries; }
  entries() { return this.values[Symbol.iterator](); }
}
const target = {
  cloneNode() { return this; },
  getAttribute() { return null; },
  setAttribute() {},
};
const context = {
  areEqual(left, right) { return JSON.stringify(left) === JSON.stringify(right); },
  BaseForm: class {},
  console,
  File: class {},
  FormData: FakeFormData,
  HTMLFormElement: class {},
  primitives: {},
};
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/form.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class FormElement", "class FormElement");
source += "\nglobalThis.FormElement = FormElement;";
vm.runInContext(source, context);

const widget = new context.FormElement({ target });
Object.defineProperty(widget, "formData", {
	configurable: true,
  get() {
    return new FakeFormData([
      ["category", "second"],
      ["name", "Example"],
      ["category", "first"],
    ]);
  },
});
Object.defineProperty(widget, "revisionEntries", {
  get() { return [["__revision-owner", "true"]]; },
});
const first = widget.revisionSnapshot();

Object.defineProperty(widget, "formData", {
  configurable: true,
  get() {
    return new FakeFormData([
      ["category", "first"],
      ["category", "second"],
      ["name", "Example"],
    ]);
  },
});
const second = widget.revisionSnapshot();
if (first !== second) {
  throw new Error(`Repeated values were order-sensitive: ${first} !== ${second}`);
}
widget.commitRevisionBaseline();
if (widget.revisionBaseline !== second) {
  throw new Error("Committed revision baseline did not use the form snapshot");
}
if (target.dataset?.revisionFingerprint) {
  throw new Error("Revision comparison persisted a content fingerprint");
}
'''
    )


# @matrix edited-entity-notice : acknowledgement acknowledgement-no-probe active-state batching clean-state comparison entity-ancestor focused-state overlap-follow-up per-form reload-fallback subscription-lifecycle targeted-reset transition visibility
def test_edit_watcher_compares_and_resets_each_form_independently(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const events = [];
const focusedElement = {};
const anchor = {
  dataset: {
    key: "entity-key",
    fingerprint: "old",
    modified: "2026-07-22T10:00:00+00:00",
  },
};
const makeMarker = (route, widget) => {
  const button = { disabled: false, textContent: "Reset form" };
  const message = { textContent: "This form changed elsewhere." };
  const form = {
    dataset: { widget: widget.name },
    _lp_widget: widget,
  };
  const marker = {
    dataset: { visible: "false", editedRoute: route },
    querySelector(selector) {
      return selector === "[data-role='edited-message']" ? message : button;
    },
    closest(selector) {
      if (selector === "[lp-entity]") return anchor;
      if (selector === "form[data-widget]") return form;
      return null;
    },
  };
  button.closest = (selector) => selector === "[lp-edited-marker]" ? marker : null;
  widget.target = {
    querySelector() { return marker; },
    contains(element) { return widget.focused === true && element === focusedElement; },
  };
  return { marker, button, message };
};
const widgetA = {
  name: "FormA",
  revisionBaseline: "same",
  revisionSnapshot() { return "local-dirty"; },
  revisionCanReset() { return true; },
  buildLocalRevision(response) { return { response: { ...response, remote: "local-a" } }; },
  commitRevisionBaseline() { events.push({ type: "commit-a" }); },
  async applyRevision(response) { events.push({ type: "apply-a", response }); },
};
const widgetB = {
  name: "FormB",
  unsavedState: true,
  revisionBaseline: "old",
  revisionSnapshot() { return "old"; },
  revisionCanReset() { return true; },
  buildLocalRevision(response) { return { response: { ...response, remote: "old" } }; },
  commitRevisionBaseline() { events.push({ type: "commit-b" }); },
  async applyRevision(response) { events.push({ type: "apply-b", response }); },
};
const widgetC = {
  name: "FormC",
  focused: true,
  revisionBaseline: "old",
  revisionSnapshot() { return "old"; },
  revisionCanReset() { return true; },
  buildLocalRevision(response) { return { response: { ...response, remote: "old" } }; },
  commitRevisionBaseline() { events.push({ type: "commit-c" }); },
  async applyRevision(response) { events.push({ type: "apply-c", response }); },
};
widgetA.component = { active: null, visible: false };
widgetA.visible = false;
widgetB.component = { active: widgetB, visible: true };
widgetB.visible = true;
widgetC.component = { active: widgetC, visible: true };
widgetC.visible = true;
const { marker: markerA } = makeMarker("/form-a", widgetA);
const { marker: markerB, button: buttonB } = makeMarker("/form-b", widgetB);
const { marker: markerC } = makeMarker("/form-c", widgetC);
const viewListeners = new Map();
const windowListeners = new Map();
const pollSubscriptions = new Map();
const pollTriggers = [];
const view = {
  key: "root-key",
  online: true,
  hidden: false,
  elt: {
    dataset: anchor.dataset,
    addEventListener(type, listener) { viewListeners.set(type, listener); },
    removeEventListener(type) { viewListeners.delete(type); },
    querySelectorAll(selector) {
      return selector === "[lp-edited-marker]" ? [markerA, markerB, markerC] : [];
    },
  },
  addFlash(marker) { events.push({ type: "flash", marker }); },
  PollingCoordinator: {
    subscribe(descriptor, hooks) {
      pollSubscriptions.set(descriptor.id, { descriptor, hooks });
      return () => pollSubscriptions.delete(descriptor.id);
    },
    acknowledge(id, revision) {
      const subscription = pollSubscriptions.get(id);
      if (subscription) subscription.descriptor.revision = revision;
    },
    async trigger(ids) {
      pollTriggers.push(ids);
      for (const id of ids) {
        const subscription = pollSubscriptions.get(id);
        if (!subscription) continue;
        if (subscription.descriptor.type === "entity") {
          await subscription.hooks.onResult({
            status: "changed",
            revision: "new",
            payload: {
              fingerprint: "new",
              modified: "2026-07-22T11:00:00+00:00",
            },
          });
        } else {
          await subscription.hooks.onResult({
            status: "unchanged",
            revision: "unlocked",
          });
        }
      }
      return [];
    },
  },
};
const context = {
  areEqual(left, right) { return JSON.stringify(left) === JSON.stringify(right); },
  clearTimeout() {},
  console,
  document: { activeElement: focusedElement },
  captureError(error) { throw error; },
  Modal: class {},
  STYLES: {},
  withTransition(callback) {
    events.push({ type: "transition" });
    return callback();
  },
  loadRevisionPreview(widget, response) {
    return {
      name: widget.name,
      syncId: "",
      schema: null,
      revisionSnapshot() { return response.remote; },
      destroy() {},
    };
  },
  request: {
    async get(url, params, options) {
      events.push({ type: "form-request", url, options });
      return { ok: true, remote: url === "/form-a" ? "same" : "new" };
    },
  },
  setTimeout(callback, delay) {
    events.push({ type: "timer", callback, delay });
    return events.length;
  },
  window: {
    addEventListener(type, listener) { windowListeners.set(type, listener); },
    removeEventListener(type) { windowListeners.delete(type); },
    location: { reload() { events.push({ type: "reload" }); } },
  },
};
vm.createContext(context);
let reconcilerSource = fs.readFileSync("src/script/shared/editReconciler.mjs", "utf8");
reconcilerSource = reconcilerSource.replace(/^import .*$/gm, "");
reconcilerSource = reconcilerSource.replace(
  "export class EditReconciler",
  "class EditReconciler",
);
reconcilerSource += "\nglobalThis.EditReconciler = EditReconciler;";
vm.runInContext(reconcilerSource, context);
let source = fs.readFileSync("src/script/shared/editWatcher.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class EditWatcher", "class EditWatcher");
source += "\nglobalThis.EditWatcher = EditWatcher;";
vm.runInContext(source, context);

(async () => {
  const watcher = new context.EditWatcher(view);
  await watcher.check();
  if (pollSubscriptions.size !== 2 || pollTriggers[0].length !== 2) {
    throw new Error("Duplicate markers were not deduplicated by entity key");
  }
  if (markerA.dataset.visible !== "false" || events.some(({ type }) => type === "apply-a")) {
	throw new Error("Inactive form performed hidden reconciliation work");
  }
  if (markerB.dataset.visible !== "true") {
    throw new Error("Changed form did not display its notice");
  }
  if (markerC.dataset.visible !== "true" || events.some(({ type }) => type === "apply-c")) {
    throw new Error("Focused form was replaced instead of displaying its notice");
  }
  if (anchor.dataset.fingerprint !== "new") {
    throw new Error("Form probes did not advance the checked fingerprint");
  }
  const probes = events.filter((event) => event.type === "form-request");
  if (
    probes.length !== 2 ||
    probes.some((event) => event.url === "/form-a") ||
    probes.some((event) => event.options.acknowledgeEntities !== false)
  ) {
    throw new Error("Only active forms should be probed without acknowledgement");
  }
  if (events.some((event) => event.type === "reload")) {
    throw new Error("Fingerprint mismatch reloaded without user action");
  }

  widgetA.component.active = widgetA;
  widgetA.component.visible = true;
  widgetA.visible = true;
  await watcher.reconcileSubscriptions();
  const catchupProbes = events.filter(
    (event) => event.type === "form-request" && event.url === "/form-a",
  );
  if (catchupProbes.length !== 1 || markerA.dataset.visible !== "true") {
    throw new Error("Newly active form did not catch up from its retained revision");
  }

  const timersBeforeAcknowledgement = events.filter(
    (event) => event.type === "timer",
  ).length;
  watcher.acknowledge({ key: "entity-key", fingerprint: "new" });
  if (
    events.filter((event) => event.type === "timer").length !==
    timersBeforeAcknowledgement
  ) {
    throw new Error("Unchanged local acknowledgement scheduled revalidation");
  }

  const probesBeforeAcknowledgement = events.filter(
    (event) => event.type === "form-request",
  ).length;
  watcher.acknowledge({ key: "entity-key", fingerprint: "acknowledged" });
  if (anchor.dataset.fingerprint !== "acknowledged") {
    throw new Error("Local acknowledgement did not refresh entity baseline");
  }
  if (markerB.dataset.visible !== "true") {
    throw new Error("Local acknowledgement cleared a form notice before revalidation");
  }
  if (
    events.filter((event) => event.type === "form-request").length !==
    probesBeforeAcknowledgement
  ) {
    throw new Error("Local acknowledgement probed an already reconciled form");
  }

  view.elt.querySelectorAll = () => [];
  watcher.acknowledge({ key: "root-key", fingerprint: "newer" });
  if (view.elt.dataset.fingerprint !== "newer") {
    throw new Error("Marker-free view root did not accept its local revision");
  }

  watcher._reconciler._state(markerB).mode = "reset";
  await watcher._click({ target: { closest() { return buttonB; } } });
	if (!events.some((event) => event.type === "apply-b")) {
    throw new Error("Reset action did not apply the staged form response");
  }
  if (events.some((event) => event.type === "reload")) {
    throw new Error("Form reset reloaded the page");
  }

  watcher._reconciler._state(markerB).mode = "reload";
  await watcher._click({ target: { closest() { return buttonB; } } });
  if (events.filter((event) => event.type === "reload").length !== 1) {
    throw new Error("Explicit fallback action did not reload");
  }

  const triggersBefore = pollTriggers.length;
  await watcher.check();
  if (pollTriggers.length !== triggersBefore + 1) {
    throw new Error("Explicit recheck did not delegate to the coordinator");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @matrix edited-entity-notice : clean-state coalescing overlap-follow-up
def test_edit_watcher_coalesces_overlapping_revision_probes(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const requests = [];
const applications = [];
const anchor = {
  dataset: {
    key: "entity-key",
    fingerprint: "old",
    modified: "2026-07-22T10:00:00+00:00",
  },
};
const button = { textContent: "", disabled: false };
const message = { textContent: "" };
const widget = {
  name: "FormA",
  visible: false,
  unsavedState: false,
  form: { _queued: false },
  revisionBaseline: "old",
  revisionCanReset() { return true; },
  revisionSnapshot() { return "old"; },
  buildLocalRevision(response) {
    return { response: { ...response, snapshot: "old" } };
  },
  commitRevisionBaseline() {},
  async applyRevision(response) { applications.push(response); },
};
widget.component = { active: null };
const form = { dataset: { widget: "FormA" }, _lp_widget: widget };
const marker = {
  isConnected: true,
  dataset: { visible: "false", editedRoute: "/form-a" },
  querySelector(selector) {
    return selector === "[data-role='edited-message']" ? message : button;
  },
  closest(selector) {
    if (selector === "[lp-entity]") return anchor;
    if (selector === "form[data-widget]") return form;
    return null;
  },
};
widget.target = {
  querySelector() { return marker; },
  contains() { return false; },
};

const context = {
  areEqual(left, right) { return JSON.stringify(left) === JSON.stringify(right); },
  captureError(error) { throw error; },
  console,
  document: { activeElement: null },
  loadRevisionPreview(_widget, response) {
    return {
      revisionSnapshot() { return response.snapshot; },
      destroy() {},
    };
  },
  Modal: class {},
  request: {
    get(url, _params, options) {
      return new Promise((resolve) => {
        requests.push({ url, options, resolve });
      });
    },
  },
  setImmediate,
  STYLES: {},
  withTransition(callback) { return callback(); },
  window: { addEventListener() {}, removeEventListener() {} },
};
vm.createContext(context);
let reconcilerSource = fs.readFileSync("src/script/shared/editReconciler.mjs", "utf8");
reconcilerSource = reconcilerSource.replace(/^import .*$/gm, "");
reconcilerSource = reconcilerSource.replace(
  "export class EditReconciler",
  "class EditReconciler",
);
reconcilerSource += "\nglobalThis.EditReconciler = EditReconciler;";
vm.runInContext(reconcilerSource, context);
let source = fs.readFileSync("src/script/shared/editWatcher.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class EditWatcher", "class EditWatcher");
source += "\nglobalThis.EditWatcher = EditWatcher;";
vm.runInContext(source, context);

(async () => {
  const watcher = new context.EditWatcher({
    addFlash() {},
    components: {},
    elt: { addEventListener() {}, querySelectorAll() { return []; } },
  });

  const first = watcher._reconciler.probe(
    marker,
    "fingerprint-one",
    "2026-07-22T11:00:00+00:00",
  );
  const duplicate = watcher._reconciler.probe(
    marker,
    "fingerprint-one",
    "2026-07-22T11:00:00+00:00",
  );
  const followup = watcher._reconciler.probe(
    marker,
    "fingerprint-two",
    "2026-07-22T12:00:00+00:00",
  );
  if (requests.length !== 1) {
    throw new Error(`Overlapping probes were not coalesced: ${requests.length}`);
  }

  requests[0].resolve({ ok: true, snapshot: "saved-one" });
  while (requests.length < 2) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  requests[1].resolve({ ok: true, unchanged: true });
  await Promise.all([first, duplicate, followup]);

  if (requests.length !== 2) {
    throw new Error(`Expected one newer follow-up probe, received ${requests.length}`);
  }
  if (
    requests.some(({ options }) => options.acknowledgeEntities !== false) ||
    applications.length !== 1 ||
    applications[0].snapshot !== "saved-one"
  ) {
    throw new Error(
      `A later unchanged response displaced the authoritative response: ${JSON.stringify(applications)}`,
    );
  }
  const revision = watcher._markerRevisions.get(marker);
  if (revision?.fingerprint !== "fingerprint-two") {
    throw new Error(`The newest probe revision was not retained: ${JSON.stringify(revision)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )
