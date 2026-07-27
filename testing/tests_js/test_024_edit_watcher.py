"""Node-backed checks for generic form state and committed edit watching."""


# @features forms unsaved-state
# @dimensions non-sync input change success reset
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


# @features edited-entity-notice forms
# @dimensions formdata canonicalization repeated-values revision-only-state
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


# @features edited-entity-notice
# @dimensions entity-ancestor batching per-form comparison acknowledgement targeted-reset reload-fallback overlap-follow-up acknowledgement-no-probe clean-state focused-state transition
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
const { marker: markerA } = makeMarker("/form-a", widgetA);
const { marker: markerB, button: buttonB } = makeMarker("/form-b", widgetB);
const { marker: markerC } = makeMarker("/form-c", widgetC);
const viewListeners = new Map();
const windowListeners = new Map();
const view = {
  key: "entity-key",
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
};
const context = {
  areEqual(left, right) { return JSON.stringify(left) === JSON.stringify(right); },
  clearTimeout() {},
  console,
  document: { activeElement: focusedElement },
  ENDPOINTS: { edited: "/edited" },
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
    async post(url, payload) {
      events.push({ type: "edited-request", url, payload });
      return {
        ok: true,
        edited: [{
          key: "entity-key",
          fingerprint: "new",
          modified: "2026-07-22T11:00:00+00:00",
        }],
      };
    },
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
let source = fs.readFileSync("src/script/shared/editWatcher.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class EditWatcher", "class EditWatcher");
source += "\nglobalThis.EditWatcher = EditWatcher;";
vm.runInContext(source, context);

(async () => {
  const watcher = new context.EditWatcher(view);
  await watcher.check();
  const requestEvent = events.find((event) => event.type === "edited-request");
  if (requestEvent.payload.entities.length !== 1) {
    throw new Error("Duplicate markers were not deduplicated by entity key");
  }
  if (markerA.dataset.visible !== "false" || !events.some(({ type }) => type === "apply-a")) {
	throw new Error("Inactive clean form change did not remount without a notice");
  }
  const cleanTransition = events.find((event) => event.type === "transition");
  if (!cleanTransition) {
    throw new Error("Clean form replacement did not use a view transition");
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
  if (probes.length !== 3 || probes.some((event) => event.options.acknowledgeEntities !== false)) {
    throw new Error("Forms were not probed independently without acknowledgement");
  }
  if (events.some((event) => event.type === "reload")) {
    throw new Error("Fingerprint mismatch reloaded without user action");
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
  watcher.acknowledge({ key: "entity-key", fingerprint: "newer" });
  if (view.elt.dataset.fingerprint !== "newer") {
    throw new Error("Marker-free view root did not accept its local revision");
  }

  watcher._state(markerB).mode = "reset";
  await watcher._click({ target: { closest() { return buttonB; } } });
	if (!events.some((event) => event.type === "apply-b")) {
    throw new Error("Reset action did not apply the staged form response");
  }
  if (events.some((event) => event.type === "reload")) {
    throw new Error("Form reset reloaded the page");
  }

  watcher._state(markerB).mode = "reload";
  await watcher._click({ target: { closest() { return buttonB; } } });
  if (events.filter((event) => event.type === "reload").length !== 1) {
    throw new Error("Explicit fallback action did not reload");
  }

  let releaseFirstCheck;
  let firstCheckStarted;
  const started = new Promise((resolve) => { firstCheckStarted = resolve; });
  let checkRuns = 0;
  watcher._checkNow = async () => {
    checkRuns += 1;
    if (checkRuns === 1) {
      firstCheckStarted();
      await new Promise((resolve) => { releaseFirstCheck = resolve; });
    }
  };
  const firstCheck = watcher.check();
  await started;
  const overlappingCheck = watcher.check();
  if (firstCheck !== overlappingCheck) {
    throw new Error("Overlapping checks did not share one completion promise");
  }
  releaseFirstCheck();
  await overlappingCheck;
  if (checkRuns !== 2) {
    throw new Error(`Overlapping check did not queue one follow-up: ${checkRuns}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )
