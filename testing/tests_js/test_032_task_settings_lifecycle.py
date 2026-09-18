"""Node-backed checks for task-settings and task-form lifecycle behavior."""


# @matrix tasks : attach-form model-task-link retained-draft manual-form-choice
def test_model_task_selection_replaces_form_and_preserves_later_manual_choice(run_node):
    run_node(r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const context = {
  FormWidget: class { constructor(attributes) { Object.assign(this, attributes); } },
};
vm.createContext(context);
const source = fs.readFileSync("src/script/widgets/taskSettings.mjs", "utf8")
  .replace(/^import .*;\n/gm, "")
  .replace(/export class /g, "class ");
vm.runInContext(source + "\nglobalThis.BaseTaskSettings = BaseTaskSettings;", context);
const widget = new context.BaseTaskSettings({component: {elt: {querySelector: () => null}}});
const selected = new Set();
const formControl = {
  details: {}, readonly: false,
  get active() { return selected.size > 0; },
  clear() { selected.clear(); this.details = {}; },
  addOption(option) { selected.add(option.id); this.details = option; },
};
widget.buttons.selectForm = formControl;
function choose(name, option) {
  widget._formUpdatedListener({detail: {name, options: option ? {[option.id]: option} : {}}});
}
const first = {id: "first-form"};
const second = {id: "second-form"};
choose("project", {id: "first-model", kind: "model", form: first});
assert.deepEqual([...selected], [first.id]);
choose("project", {id: "second-model", kind: "model", form: second});
assert.deepEqual([...selected], [second.id], "The retained form must be replaced, not added alongside the new form");
choose("project", {id: "second-model", kind: "model", form: second});
assert.deepEqual([...selected], [second.id]);

const manual = {id: "manual-form"};
formControl.clear();
formControl.addOption(manual);
choose("form", manual);
choose("project", {id: "plain-project", kind: "project"});
choose("project", {id: "formless-model", kind: "model"});
choose("project", null);
choose("category", {id: "category", form: first});
assert.deepEqual([...selected], [manual.id], "A later manual choice remains until a model with a form is selected");

formControl.readonly = true;
choose("project", {id: "first-model", kind: "model", form: first});
assert.deepEqual([...selected], [manual.id]);
delete widget.buttons.selectForm;
choose("project", {id: "first-model", kind: "model", form: first});
''')


# @matrix tasks : active-widget complete uncomplete update-state
def test_closed_task_errors_persist_while_waiting_and_retrying(run_node):
    run_node(r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const timers = new Map();
let now = 0;
let timerId = 0;
const context = {
  queueMicrotask,
  setTimeout(callback, delay) {
    timers.set(++timerId, {callback, at: now + delay});
    return timerId;
  },
  clearTimeout(id) { timers.delete(id); },
  document: {createElement: () => ({textContent: ""})},
  captureError(error) { throw error; },
  isSkippedViewTransitionError: () => false,
};
vm.createContext(context);
for (const path of [
  "src/script/shared/transitions.mjs", "src/script/shared/utilities.mjs",
  "src/script/views/base/component.mjs",
]) {
  const source = fs.readFileSync(path, "utf8")
    .replace(/^import .*;\n/gm, "")
    .replace(/export (?:default )?/g, "");
  vm.runInContext(source, context);
}
vm.runInContext("globalThis.ViewComponent = ViewComponent; globalThis.withTransition = withTransition;", context);
async function advanceClock(ms) {
  now += ms;
  for (const [id, timer] of timers) {
    if (timer.at > now) continue;
    timers.delete(id);
    timer.callback();
  }
  await context.withTransition(() => {});
}
(async () => {
  for (const cachedForm of [false, true]) {
    const error = {
      dataset: {visible: "false"}, textContent: "",
      replaceChildren(...children) { this.textContent = children.map(child => child.textContent).join(""); },
    };
    const row = {
      id: "task", dataset: {open: "false"},
      closest() { return this; }, querySelector: () => error,
    };
    const component = new context.ViewComponent(row, {});
    component._nav = {show() {}, hide() {}};
    const widgetErrors = [];
    component.active = cachedForm ? {showError: message => widgetErrors.push(message), enable() {}} : null;
    for (const message of ["Migration in progress", "Migration still in progress"]) {
      component.disable();
      component.showError(message);
      await context.withTransition(() => {});
      assert.equal(error.dataset.visible, "true");
      assert.equal(error.textContent, message);
      await advanceClock(60_000);
      assert.equal(error.dataset.visible, "true", "A rejected action must stay visible while waiting to retry");
      assert.equal(error.textContent, message);
      assert.deepEqual(widgetErrors, [], "A hidden cached form must not receive the error");
    }
    if (cachedForm) {
      row.dataset.open = "TaskForm";
      component.showError("Open form error");
      assert.deepEqual(widgetErrors, ["Open form error"]);
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
''')


# @matrix tasks : history-fill latest-submission incompatible-value stale-response
def test_task_history_fill_reports_incompatible_values_and_ignores_stale_responses(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const pending = [];
const errors = [];
const controls = [];
const target = {
  dataset: {history: "history"},
};
const context = {
  FormWidget: class { constructor(attributes) { Object.assign(this, attributes); } },
  sections: {},
  captureError: () => { throw new Error("unexpected request error"); },
  request: { get: () => new Promise(resolve => pending.push(resolve)) },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/taskForm.mjs", "utf8");
source = source.replace(/import .*?;\n/g, "");
source = source.replaceAll("export class ", "class ");
vm.runInContext(source + "\nglobalThis.TaskForm = TaskForm;", context);

(async () => {
  const form = {
    renderer: {addHistoryFillButtons: values => controls.push(values)},
    showError(error) { errors.push(error); },
    hideError() { errors.length = 0; },
  };
  const widget = new context.TaskForm({target, form, endpoints: {latestHistorySubmission: "/history"}});
  const unavailable = widget.loadHistoryFill();
  pending.shift()({history_fields: ["note", "invalid"]});
  await unavailable;
  assert.equal(errors.length, 0);
  assert.equal(controls.length, 1);
  assert.equal(typeof controls[0].invalid, "function", "Invalid values retain a history button");
  const rejected = controls[0].invalid();
  pending.shift()({ok: false, status: 422, error: "This saved value cannot be converted."});
  assert.equal(await rejected, null);
  assert.deepEqual(errors, ["This saved value cannot be converted."]);
  const converted = controls[0].note();
  pending.shift()({ok: true, latest_submission: {note: "7"}});
  assert.equal(await converted, "7");
  assert.equal(errors.length, 0);

  widget._resetHistoryFillCache();
  const old = widget.loadHistoryFill();
  const oldResponse = pending.shift();
  widget._resetHistoryFillCache();
  const current = widget.loadHistoryFill();
  pending.shift()({history_fields: ["current"]});
  await current;
  assert.equal(controls.length, 2);
  assert.equal(typeof controls[1].current, "function");
  oldResponse({history_fields: ["stale"]});
  await old;
  assert.equal(controls.length, 2);

  widget._resetHistoryFillCache();
  const destroyed = widget.historyValue("note");
  widget.form = null;
  pending.shift()({ok: false, status: 422, error: "Late failure"});
  await destroyed;
  assert.equal(errors.length, 0);
  assert.equal(controls.length, 2);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    )


# @matrix tasks : history-fill stale-response
def test_history_fill_waits_without_overwriting_new_input(run_node):
    run_node(r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const context = {
  STYLES: {form: {icon: "icon"}}, setIcon() {},
  document: {createElement: () => ({
    dataset: {}, isConnected: true,
    appendChild(child) { return child; },
    addEventListener(_type, callback) { this.click = callback; },
  })},
};
vm.createContext(context);
const source = fs.readFileSync("src/script/elements/base/baseElement.mjs", "utf8")
  .replace(/^import .*;\n/gm, "")
  .replace("export class BaseElement", "class BaseElement");
vm.runInContext(source + "\nglobalThis.BaseElement = BaseElement;", context);
(async () => {
  const filled = [];
  const element = Object.assign(Object.create(context.BaseElement.prototype), {
    renderer: {historyFillEnabled: true}, schema: {id: "quantity", type: "input"},
    value: "", fillFromHistory(value) { if (value != null) filled.push(value); },
  });
  let release;
  const button = element.historyFillButton(() => new Promise(resolve => { release = resolve; }));
  const event = {preventDefault() {}, stopPropagation() {}};
  const first = button.click(event);
  assert.equal(button.disabled, true);
  element.value = "Typed while waiting";
  release("Historical value");
  await first;
  assert.deepEqual(filled, []);
  assert.equal(button.disabled, false);
  element.value = "";
  const second = button.click(event);
  release("7");
  await second;
  assert.deepEqual(filled, ["7"]);
  const detached = button.click(event);
  button.isConnected = false;
  release("Old form response");
  await detached;
  assert.deepEqual(filled, ["7"]);
})().catch(error => { console.error(error); process.exit(1); });
''')


# @matrix tasks : active-widget complete history-refresh uncomplete
def test_task_completion_replaces_closed_row_in_one_transition(run_node):
    run_node(
        r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const transitions = [];
let committing = false;
let beforeCommit;
const context = {
  console, BaseList: class {},
  withTransition: async (commit, options) => {
    transitions.push(options.label);
    await beforeCommit();
    committing = true;
    try { commit(); } finally { committing = false; }
  },
};
vm.createContext(context);
const component = fs.readFileSync("src/script/views/base/component.mjs", "utf8")
  .replace(/^import .*$/gm, "")
  .replace("export default class ViewComponent", "class ViewComponent");
const taskSource = fs.readFileSync("src/script/views/base/task.mjs", "utf8")
  .replace(/^import .*$/gm, "")
  .replace("export class Task", "class Task");
const listSource = fs.readFileSync("src/script/widgets/pageTaskList.mjs", "utf8")
  .replace(/^import .*$/gm, "")
  .replace("export class PageTaskList", "class PageTaskList");
vm.runInContext(`${component}\n${taskSource}\n${listSource}\nglobalThis.Task = Task; globalThis.PageTaskList = PageTaskList;`, context);

async function updateTask({ completed, nextCompleted, cancel = false, active = "TaskHistory" }) {
  transitions.length = 0;
  const renders = [];
  const destroyed = [];
  const flashes = [];
  const lists = [[], []];
  const row = (completed, connected) => ({
    id: "task-row",
    dataset: { key: "task-key", completed: String(completed), open: connected ? active : "false" },
    isConnected: connected,
    closest() { return this; },
    append(...items) { assert.equal(items.length, 0); },
  });
  const currentRow = row(completed, true);
  const nextRow = row(nextCompleted, false);
  lists[Number(completed)].push(currentRow);
  const view = { components: {}, addFlash(elt) { flashes.push(elt); } };
  const list = Object.create(context.PageTaskList.prototype);
  list.view = view;
  list.target = { querySelectorAll: () => lists.flat() };
  Object.defineProperties(list, Object.fromEntries(["activeTasks", "completedTasks"].map((name, i) => [name, {value: {
    contains: elt => lists[i].includes(elt),
    prepend(elt) {
      assert.equal(committing, true);
      assert.equal(elt.dataset.open, "false", "No open task may appear in its destination list");
      for (const rows of lists) {
        const index = rows.indexOf(elt);
        if (index !== -1) rows.splice(index, 1);
      }
      lists[i].unshift(elt);
    },
  }}])));
  const current = new context.Task(currentRow, view);
  current.widgets.TaskHistory = {name: "TaskHistory", destroy() { destroyed.push("history"); }};
  current.widgets.TaskForm = {name: "TaskForm", destroy() { destroyed.push("form"); }};
  current.active = current.widgets[active] || null;
  current._replaceNav = () => {};
  current._removeMissingWidgets = () => {};
  current.prepareRender = async () => {
    assert.equal(currentRow.dataset.open, active, "Ordinary updates retain the open header during preparation");
  };
  current.render = () => {
    assert.equal(committing, true);
    renders.push(active);
  };
  view.components[current.name] = current;
  let replacement;
  view.getComponent = elt => {
    assert.equal(committing, true);
    assert.equal(elt, nextRow);
    replacement = new context.Task(elt, view);
    view.components[replacement.name] = replacement;
    replacement.activate = () => { throw new Error("Completion must not activate or fetch a widget"); };
    replacement.render = visible => {
      assert.equal(committing, true);
      assert.equal(visible, false);
      assert.equal(replacement.active, null);
      assert.equal(nextRow.isConnected, true);
      assert.equal(currentRow.isConnected, false);
      assert.equal(view.components[current.name], replacement);
      assert.equal(Object.keys(replacement.widgets).length, 0);
      list._moveTaskIfNecessary(elt);
      renders.push("closed");
    };
    return replacement;
  };
  currentRow.replaceWith = elt => {
    assert.equal(committing, true);
    assert.equal(elt, nextRow);
    assert.equal(currentRow.dataset.completed, String(completed));
    assert.equal(currentRow.dataset.open, active, "Old form stays unchanged until replacement");
    const rows = lists[Number(completed)];
    rows[rows.indexOf(currentRow)] = nextRow;
    currentRow.isConnected = false;
    nextRow.isConnected = true;
  };
  beforeCommit = async () => {
    assert.equal(currentRow.isConnected, true);
    assert.equal(currentRow.dataset.completed, String(completed));
    assert.equal(currentRow.dataset.open, active);
    assert.equal(view.components[current.name], current);
    assert.equal(replacement, undefined);
    if (cancel) current.destroy();
  };
  await current.updated({ html: {querySelector: () => nextRow, querySelectorAll: () => []} });
  if (completed === nextCompleted) {
    assert.equal(replacement, undefined, "Ordinary updates retain their component and open widget");
    assert.deepEqual(renders, [active]);
    assert.deepEqual(destroyed, []);
  } else if (cancel) {
    assert.equal(replacement, undefined, "Destroyed views must not insert a replacement");
    assert.equal(nextRow.isConnected, false);
    assert.deepEqual(renders, []);
  } else {
    assert.deepEqual(renders, ["closed"]);
    assert.deepEqual(destroyed, ["history", "form"]);
    assert.equal(lists[Number(nextCompleted)][0], nextRow);
    assert.equal(lists[Number(completed)].length, 0);
    assert.deepEqual(flashes, [], "Moving between lists must not start a second animation");
  }
  assert.equal(transitions.length, 1);
}
(async () => {
  for (const active of ["TaskHistory", "TaskForm", "false"]) {
    await updateTask({completed: false, nextCompleted: true, active});
    await updateTask({completed: true, nextCompleted: false, active});
  }
  await updateTask({completed: false, nextCompleted: false, active: "TaskForm"});
  await updateTask({completed: true, nextCompleted: true});
  await updateTask({completed: true, nextCompleted: false, cancel: true});
})().catch(error => { console.error(error); process.exit(1); });
'''
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

class FormWidget {
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
  FormWidget,
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

class FormController {}

function target({ renderer = false } = {}) {
  return {
    dataset: {},
    cloneNode() { return target({ renderer }); },
    hasAttribute(name) {
      return renderer && ["data-schema", "data-submission"].includes(name);
    },
  };
}

const context = { FormController, console };
vm.createContext(context);

let source = fs.readFileSync("src/script/widgets/base/formWidget.mjs", "utf8");
source = source.replace(/import .*?;\n/g, "");
source = source.replace("export class FormWidget", "class FormWidget");
source += "\nglobalThis.FormWidget = FormWidget;";
vm.runInContext(source, context);

const responseState = {
  schema: [{ id: "task-form-field" }],
  submission: { "task-form-field": "saved value" },
  generation: 3,
  migration_notice: [],
};

const settingsReplacement = target();
const settings = new context.FormWidget({
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

const renderer = new context.FormWidget({
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
if (renderer.initialTarget.dataset.formGeneration !== "3" ||
    renderer.initialTarget.dataset.migrationNotice !== "[]") {
  throw new Error("TaskForm did not adopt its generation and cleared notice");
}
if (settingsReplacement.dataset.formGeneration !== undefined ||
    settingsReplacement.dataset.migrationNotice !== undefined) {
  throw new Error("TaskSettings adopted a sibling TaskForm migration state");
}

const revision = new context.FormWidget({
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
