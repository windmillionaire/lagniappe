"""Node-backed checks for task-settings and task-form lifecycle behavior."""


# @matrix tasks : history-fill latest-submission incompatible-value stale-response
def test_task_history_fill_reports_incompatible_values_and_ignores_stale_responses(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const pending = [];
const notices = [];
const controls = [];
const target = {
  dataset: {history: "history"},
  querySelector: () => notices[0] || null,
  append(notice) { notices.push(notice); },
};
const context = {
  FormElement: class { constructor(attributes) { Object.assign(this, attributes); } },
  sections: {},
  captureError: () => { throw new Error("unexpected request error"); },
  request: { get: () => new Promise(resolve => pending.push(resolve)) },
  document: { createElement: () => ({
    dataset: {}, setAttribute() {},
    remove() { notices.splice(notices.indexOf(this), 1); },
  }) },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/taskForm.mjs", "utf8");
source = source.replace(/import .*?;\n/g, "");
source = source.replaceAll("export class ", "class ");
vm.runInContext(source + "\nglobalThis.TaskForm = TaskForm;", context);

(async () => {
  const form = {renderer: {addHistoryFillButtons: values => controls.push(values)}};
  const widget = new context.TaskForm({target, form, endpoints: {latestHistorySubmission: "/history"}});
  const unavailable = widget.loadHistoryFill();
  pending.shift()({latest_submission: {note: "Do not reuse"}, history_error: "Original <img> choices are unavailable."});
  await unavailable;
  assert.equal(notices[0].dataset.role, "history-fill-error");
  assert.equal(notices[0].textContent, "Original <img> choices are unavailable.");
  assert.equal(notices[0].innerHTML, undefined);
  assert.equal(controls.length, 0);

  widget._resetHistoryFillCache();
  const old = widget.loadHistoryFill();
  const oldResponse = pending.shift();
  widget._resetHistoryFillCache();
  const current = widget.loadHistoryFill();
  pending.shift()({latest_submission: {note: "Reusable"}});
  await current;
  assert.equal(notices.length, 0);
  assert.equal(controls.length, 1);
  assert.equal(controls[0].note, "Reusable");
  oldResponse({latest_submission: {}, history_error: "Stale failure"});
  await old;
  assert.equal(notices.length, 0);
  assert.equal(controls.length, 1);

  widget._resetHistoryFillCache();
  const destroyed = widget.loadHistoryFill();
  widget.form = null;
  pending.shift()({history_error: "Late failure"});
  await destroyed;
  assert.equal(notices.length, 0);
  assert.equal(controls.length, 1);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    )


# @matrix tasks : action-control-lifecycle teardown
def test_task_settings_awaits_action_controls_and_cleans_up(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const events = [];
let resolveUpload;
const uploadReady = new Promise((resolve) => { resolveUpload = resolve; });

class FormElement {
  constructor(attributes) {
    Object.assign(this, attributes);
    this.destroyables = [];
  }

  async _initForm() {
    events.push("form:init");
  }

  destroy() {
    events.push("form:destroy");
    for (const destroyable of this.destroyables) destroyable.destroy?.();
    this.destroyables = [];
  }
}

const controls = {};
function createControl(kind) {
  const control = {
    kind,
    async init() {
      events.push(`${kind}:init`);
      if (kind === "upload") await uploadReady;
      events.push(`${kind}:ready`);
    },
    destroy() {
      events.push(`${kind}:destroy`);
    },
  };
  controls[kind] = control;
  return control;
}

const SectionToggle = {
  facet: () => createControl("facet"),
  date: () => createControl("date"),
  upload: () => createControl("upload"),
};

let updatedListener = null;
const actionButtons = {
  querySelectorAll(selector) {
    if (selector !== "button[data-action]") {
      throw new Error(`Unexpected action selector: ${selector}`);
    }
    return [
      { dataset: { action: "uploadFile" } },
      { dataset: { action: "selectProject" } },
    ];
  },
  addEventListener(name, listener) {
    events.push(`listener:add:${name}`);
    updatedListener = listener;
  },
  removeEventListener(name, listener) {
    if (name === "updated" && listener === updatedListener) {
      events.push(`listener:remove:${name}`);
      updatedListener = null;
    }
  },
};
const target = {
  querySelector(selector) {
    if (selector === "[data-role='action-buttons']") return actionButtons;
    return null;
  },
};

const context = {
  FormElement,
  InputElement: class {},
  SectionToggle,
  TextareaElement: class {},
  console,
};
vm.createContext(context);

let source = fs.readFileSync("src/script/widgets/taskSettings.mjs", "utf8");
source = source.replace(/import .*?;\n/g, "");
source = source.replaceAll("export class ", "class ");
source += "\nglobalThis.BaseTaskSettings = BaseTaskSettings;";
vm.runInContext(source, context);

(async () => {
  const widget = new context.BaseTaskSettings({ target });

  if (widget.actions !== actionButtons || events.length !== 0) {
    throw new Error("Reading actions should not initialize controls");
  }

  let settled = false;
  const initializing = widget._initForm().then(() => { settled = true; });
  await new Promise((resolve) => setImmediate(resolve));

  const pendingEvents = JSON.stringify(events);
  if (settled ||
      pendingEvents !== JSON.stringify(["form:init", "upload:init"])) {
    throw new Error(`Task settings did not await upload readiness: ${pendingEvents}`);
  }
  if (updatedListener || Object.keys(widget.buttons).length !== 0 ||
      widget.destroyables.length !== 0) {
    throw new Error("Pending controls were exposed before becoming ready");
  }

  resolveUpload();
  await initializing;

  const readyEvents = JSON.stringify(events);
  const expectedReady = JSON.stringify([
    "form:init",
    "upload:init",
    "upload:ready",
    "facet:init",
    "facet:ready",
    "listener:add:updated",
  ]);
  if (readyEvents !== expectedReady) {
    throw new Error(`Action controls initialized out of order: ${readyEvents}`);
  }
  if (widget.buttons.uploadFile !== controls.upload ||
      widget.buttons.selectProject !== controls.facet ||
      widget.destroyables.length !== 2 ||
      !updatedListener) {
    throw new Error("Ready action controls were not registered");
  }

  widget.destroy();
  const destroyedEvents = JSON.stringify(events.slice(-4));
  const expectedDestroyed = JSON.stringify([
    "listener:remove:updated",
    "form:destroy",
    "upload:destroy",
    "facet:destroy",
  ]);
  if (destroyedEvents !== expectedDestroyed ||
      Object.keys(widget.buttons).length !== 0 ||
      widget.destroyables.length !== 0 ||
      updatedListener) {
    throw new Error(`Task settings cleanup was incomplete: ${JSON.stringify(events)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


# @matrix forms : schema-ownership sibling-widgets
def test_form_response_metadata_stays_with_renderer_widget(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

class BaseForm {}

function target({ renderer = false } = {}) {
  return {
    dataset: {},
    cloneNode() { return target({ renderer }); },
    hasAttribute(name) {
      return renderer && ["data-schema", "data-submission"].includes(name);
    },
  };
}

const context = { BaseForm, console };
vm.createContext(context);

let source = fs.readFileSync("src/script/elements/form.mjs", "utf8");
source = source.replace(/import .*?;\n/g, "");
source = source.replace("export class FormElement", "class FormElement");
source += "\nglobalThis.FormElement = FormElement;";
vm.runInContext(source, context);

const responseState = {
  schema: [{ id: "task-form-field" }],
  submission: { "task-form-field": "saved value" },
};

const settingsReplacement = target();
const settings = new context.FormElement({
  name: "TaskSettings",
  target: target(),
});
settings.updated({
  ...responseState,
  html: {
    querySelector(selector) {
      if (selector !== "[data-widget='TaskSettings']") {
        throw new Error(`Unexpected selector: ${selector}`);
      }
      return settingsReplacement;
    },
  },
});

if (settings.schema !== null || settings.submission !== null) {
  throw new Error("TaskSettings adopted a sibling TaskForm schema/submission");
}
if (settings.initialTarget !== settingsReplacement || !settings._updated) {
  throw new Error("TaskSettings did not retain its normal HTML reconciliation");
}

const renderer = new context.FormElement({
  name: "TaskForm",
  target: target({ renderer: true }),
});
renderer.updated({
  ...responseState,
  html: {
    querySelector() { return target({ renderer: true }); },
  },
});
if (renderer.schema !== responseState.schema ||
    renderer.submission !== responseState.submission) {
  throw new Error("TaskForm did not adopt its owned response state");
}

const revision = new context.FormElement({
  name: "TaskForm",
  target: target({ renderer: true }),
});
revision.updated(responseState);
if (revision.schema !== responseState.schema ||
    revision.submission !== responseState.submission) {
  throw new Error("Metadata-only form revision stopped updating renderer state");
}
"""
    )
