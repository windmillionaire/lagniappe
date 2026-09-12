"""Schema-only migration planning never needs target submission queries."""

import pytest


# @matrix form-migration : modify-panel draft-undo
def test_delete_element_commits_panel_and_model_changes_in_one_transition(run_node):
    run_node(r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const nodes = [];
const commits = [];
const changes = [];
let committing = false;
function node() {
  const result = {
    dataset: {}, children: [], listeners: {},
    appendChild(child) { this.children.push(child); return child; },
    append(child) { this.children.push(child); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(type, handler) { this.listeners[type] = handler; },
    setAttribute() {}, querySelector() { return node(); },
  };
  nodes.push(result);
  return result;
}
const context = {
  Condition: class {}, STYLES: {button: {submit: "button"}},
  document: {createElement: node}, fieldKind: field => field.type,
  withTransition(commit) { if (committing) commit(); else commits.push(commit); },
};
vm.createContext(context);
const source = fs.readFileSync("src/script/views/builder/conditions/modify.mjs", "utf8")
  .replace(/^import .*;\n/gm, "")
  .replace("export default class Modify", "class Modify");
vm.runInContext(source + "\nglobalThis.Modify = Modify;", context);
const change = name => {
  assert.equal(committing, true, `${name} changed the UI before the transition`);
  changes.push(name);
};
const element = {schema: {id: "notes", type: "textarea"}};
const builder = {
  selectedElement: element,
  savedField: () => element.schema,
  conversionCatalog: {types: []},
  conditions: {close() { context.withTransition(() => change("close-options")); }},
  removeElement() { change("remove-element"); this.selectedElement = null; },
  settings: {deselectItem() { change("deselect-settings"); }},
  formSettings: {set visible(value) { assert.equal(value, true); change("show-form-settings"); }},
};
const modify = Object.assign(Object.create(context.Modify.prototype), {
  builder, element, header: node(), target: node(), destroy() {}, setTitle() {},
});
modify.init();
const remove = nodes.find(node => node.textContent === "Delete");
remove.listeners.click();
assert.deepEqual(changes, [], "All visible changes must wait for one commit");
assert.equal(commits.length, 1);
committing = true;
commits.shift()();
assert.deepEqual(changes, ["close-options", "remove-element", "deselect-settings", "show-form-settings"]);
''')


# @matrix form-migration : progress recovery
@pytest.mark.parametrize("suspension", ["focused", "visible-blur", "focus", "offline", "background-load"])
def test_builder_resumes_migration_polling_and_clears_completed_status(
    run_node, suspension
):
    run_node(
        r"""
(async () => {
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const suspension = SUSPENSION;
let now = 1000;
let timerId = 0;
const timers = new Map();
const clock = {
  setTimeout(callback, delay) {
    timers.set(++timerId, { callback, at: now + delay });
    return timerId;
  },
  clearTimeout(id) { timers.delete(id); },
};
const element = () => ({
  dataset: {}, children: [],
  setAttribute(name, value) { this[name] = value; },
  isConnected: true,
  checkVisibility() { return !this.hidden; },
  append(...children) { this.children.push(...children); },
  replaceChildren(...children) { this.children = children; },
  get textContent() { return this.text || this.children.map(child => child.textContent).join(""); },
  set textContent(text) { this.text = text; this.children = []; },
});
let running = { operation: "job-1", status: "running" };
const saved = { schema: [{ id: "quantity", type: "input", input: "text" }] };
const finished = { ok: true, draft: saved, baseline: "generation-2" };
let response = { ok: true, pending_change: running };
let heldRefresh = null;
let polls = 0;
let refreshes = 0;
let restored = 0;
const context = {
  ...clock,
  window: clock,
  Date: { now: () => now },
  Math, queueMicrotask,
  crypto: { randomUUID: () => "client-1" },
  sessionStorage: { getItem() { return "client-1"; } },
  ENDPOINTS: { poll: "/l/poll" },
  captureError(error) { throw error; },
  connectivity: { online: true },
  document: { createElement: element, querySelector() { return null; } },
  request: {
    async post(url, body) {
      assert.equal(url, "/l/poll");
      assert.equal(body.subscriptions.length, 1);
      assert.equal(body.subscriptions[0].key, running.operation);
      polls += 1;
      const revision = response.pending_change ? 1 : 2;
      return { ok: true, version: 1, results: body.subscriptions.map(item => ({
        id: item.id, type: "operation", revision, poll_after_ms: 4000,
        status: item.revision === revision ? "unchanged" : "changed",
        ...(item.revision === revision ? {} : {
          payload: { key: item.key, revision, terminal: !response.pending_change },
        }),
      })) };
    },
    async get(url) {
      assert.equal(url, "/forms/form-1/change");
      refreshes += 1;
      return heldRefresh ? await heldRefresh : response;
    },
  },
};
vm.createContext(context);
for (const [file, name] of [
  ["shared/polling", "PollingCoordinator"],
  ["views/builder/panels/header", "Header"],
  ["views/builder/changeStatus", "FormChangeStatus"],
  ["views/builder/builder", "FormBuilder"],
]) {
  let source = fs.readFileSync(`src/script/${file}.mjs`, "utf8")
    .replace(/^import[\s\S]*?from ["'][^"']+["'];\n/gm, "")
    .replace(`export class ${name}`, `class ${name}`)
    .replace("export default FormBuilder;", "");
  vm.runInContext(source + `\nglobalThis.${name} = ${name};`, context);
}
const builder = Object.assign(Object.create(context.FormBuilder.prototype), {
  key: "form-1", online: true, hidden: suspension === "background-load",
  _independentDocuments: new Set(),
  draft: {
    dirty: false, saved,
    acknowledge(submitted, result) {
      assert.equal(submitted, saved);
      assert.equal(result, finished);
      this.baseline = result.baseline;
    },
  },
  async restoreDraft() { restored += 1; this.header.saved(); },
});
for (const name of ["settings", "conditions", "components", "model", "formSettings"])
  builder[name] = { panel: element() };
builder.header = Object.assign(Object.create(context.Header.prototype), {
  builder, saveButton: element(), notification: element(),
});
builder.setPendingChange(running);
const polling = builder.changeStatus.polling;
const nextTimer = async () => {
  assert.ok(timers.size, "Pending migration must schedule its next status check");
  const [id, timer] = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
  timers.delete(id);
  now = timer.at;
  timer.callback();
  await polling.activePoll;
};
if (suspension !== "background-load") {
  await nextTimer();
  assert.equal(refreshes, 1);
  assert.equal(builder.pendingChange, running);
  assert.equal(timers.size, 1, "Running migration keeps polling on a timer");
  if (["focused", "visible-blur"].includes(suspension)) {
    if (suspension === "visible-blur")
      await builder.sync({hidden: true, blurred: true, blurredAt: now});
    await nextTimer();
    assert.equal(refreshes, 2, "Unchanged operation status keeps the visible builder polling");
    response = finished;
    await nextTimer();
  } else {
    if (suspension === "offline") context.connectivity.online = false;
    await builder.sync({ hidden: suspension === "focus" });
    // Let any previously scheduled timer expire while the builder is inactive.
    if (timers.size) await nextTimer();
    assert.equal(refreshes, 1, "Inactive builder must not refresh its schema");
  }
}
if (!["focused", "visible-blur"].includes(suspension)) {
  assert.equal(timers.size, 0);
  assert.equal(builder.header.saveButton["aria-disabled"], "true");
  // The server finishes while inactive; returning catches up without a reload.
  response = finished;
  context.connectivity.online = true;
  await builder.sync({ hidden: false });
}
assert.equal(builder.pendingChange, null, "Completed migration stayed locked on return");
assert.equal(refreshes, ["focused", "visible-blur"].includes(suspension) ? 3 : suspension === "background-load" ? 1 : 2);
assert.equal(builder.draft.baseline, "generation-2");
assert.equal(restored, 1);
assert.equal(builder.header.notification.textContent, "Form update finished.");
assert.equal(polling.subscriptions.size, 0);
for (const name of ["settings", "conditions", "components", "model", "formSettings"])
  assert.equal(builder[name].panel.inert, false);
builder.draft.dirty = true;
builder.header.unsaved();
assert.equal(builder.header.saveButton["aria-disabled"], "false");
await nextTimer();
assert.equal(builder.header.notification.dataset.visible, "false");
assert.equal(timers.size, 0, "Completed migration stopped polling");
await builder.sync({hidden: false});

// The same builder saves another conversion without reloading.
running = { operation: "job-2", status: "queued" };
response = { ok: true, pending_change: running };
builder.setPendingChange(running);
assert.equal(builder.header.saveButton["aria-disabled"], "true");
let releaseRefresh;
heldRefresh = new Promise(resolve => { releaseRefresh = resolve; });
const previousRefreshes = refreshes;
const oldCycle = nextTimer();
for (let turns = 0; refreshes === previousRefreshes && turns < 20; turns += 1)
  await Promise.resolve();
assert.equal(refreshes, previousRefreshes + 1);
const staleResponse = response;
await builder.sync({ hidden: true });
response = finished;
const returning = builder.sync({ hidden: false });
heldRefresh = null;
releaseRefresh(staleResponse);
await returning;
await oldCycle;
assert.equal(builder.pendingChange, null, "Second migration stayed locked on return");
assert.equal(restored, 2);
assert.equal(polling.subscriptions.size, 0);
})().catch(error => { console.error(error); process.exit(1); });
""".replace("SUSPENSION", repr(suspension))
    )


# @matrix form-migration : saved-job progress reload recovery
def test_migration_status_uses_notification_and_keeps_save_disabled(run_node):
    run_node(r"""
(async () => {
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const element = () => ({
  dataset: {}, children: [],
  setAttribute(name, value) { this[name] = value; },
  append(...children) { this.children.push(...children); },
  appendChild(child) { this.children.push(child); return child; },
  replaceChildren(...children) { this.children = children; },
  get textContent() { return this.text || this.children.map(child => child.textContent).join(""); },
  set textContent(text) { this.text = text; this.children = []; },
  addEventListener() {}, remove() {},
});
const context = {
  document: { createElement: element },
  clearTimeout() {},
  setTimeout() { throw new Error("Migration notification must stay visible"); },
  PollingCoordinator: class {
    init() { return this; }
    subscribe() { return () => {}; }
    destroy() {}
  },
};
vm.createContext(context);
for (const [file, name] of [["panels/header", "Header"], ["changeStatus", "FormChangeStatus"]]) {
  const source = fs.readFileSync(`src/script/views/builder/${file}.mjs`, "utf8")
    .replace(/^import[\s\S]*?from ["'][^"']+["'];\n/gm, "")
    .replace(`export class ${name}`, `globalThis.${name} = class ${name}`);
  vm.runInContext(source, context);
}
const builder = { draft: { dirty: true } };
for (const name of ["settings", "conditions", "components", "model", "formSettings"]) {
  builder[name] = { panel: element() };
}
builder.header = Object.assign(Object.create(context.Header.prototype), {
  builder, saveButton: element(), notification: element(),
});
const header = builder.header;
const status = new context.FormChangeStatus(builder);
const running = { operation: "job-1", status: "running", can_cancel: true };
status.show(running);
assert.equal(header.notification.children[0], status.node);
assert.equal(header.notification.textContent, "Schema migration in progress, Save temporarily disabled");
assert.equal(header.notification.dataset.visible, "true");
assert.equal(header.saveButton["aria-disabled"], "true");
// Both Save acknowledgement and reload refresh the header's saved/dirty state.
header.saved();
header.unsaved();
assert.equal(header.notification.children[0], status.node);
assert.equal(header.notification.dataset.visible, "true");
assert.equal(header.saveButton["aria-disabled"], "true");
assert.equal(await header.saveForm(), false);
status.show({ ...running, status: "failed", error: "Try again" });
assert.equal(status.node.children.length, 2);
assert.equal(status.node.children[1].textContent, "Retry");
assert.ok(!header.notification.textContent.includes("Cancel"));
status.show(null);
header.unsaved();
assert.equal(header.notification.dataset.visible, "false");
assert.equal(header.saveButton["aria-disabled"], "false");
status.destroy();
})().catch(error => { console.error(error); process.exit(1); });
""")


# @matrix form-migration : schema-only stable-identity conditions
def test_schema_changes_and_condition_repairs_are_local(run_node):
    run_node(r"""
const assert = await import("node:assert/strict").then(module => module.default);
const { needsMigration, repairConditions } = await import(process.cwd() + "/src/script/views/builder/migrations.mjs");
const before = [{id:"a", type:"input", input:"text", title:"Old"}];
assert.equal(needsMigration(before, [{...before[0], title:"New"}]), false);
assert.equal(needsMigration(before, [{...before[0], input:"number"}]), true);
assert.equal(needsMigration(before, []), true);
assert.equal(needsMigration([], before), false);
const schema = [{id:"choice",type:"select",options:[{value:"yes",label:"Yes"}]},
 {id:"note",type:"textarea",visibility:[{id:"choice",type:"radio",value:"yes"},{id:"gone",value:"missing"}]}];
assert.equal(repairConditions(schema), 1);
assert.deepEqual(schema[1].visibility, [{id:"choice",type:"select",value:"yes"}]);
""")


# @matrix form-migration : stale-input representation-aware
def test_incompatible_local_values_require_review(run_node):
    run_node(r"""
const assert = await import("node:assert/strict").then(module => module.default);
const { compatibleField, incompatibleSchema } = await import(process.cwd() + "/src/script/shared/formRepresentation.mjs");
const text = {id:"quantity",type:"input",input:"text"};
assert.equal(compatibleField(text, {...text,title:"New label"}), true);
assert.equal(compatibleField(text, {...text,input:"number"}), false);
assert.equal(incompatibleSchema([text], []), true);
assert.equal(incompatibleSchema([text], [text,{id:"extra",type:"textarea"}]), false);
const table = {id:"items",type:"table",columns:[text]};
assert.equal(compatibleField(table,{...table,columns:[{...text,input:"number"}]}), false);
""")


# @matrix form-migration : stale-input queued-conflict explicit-review
@pytest.mark.parametrize("mode", ["dirty", "queued", "clean"])
@pytest.mark.parametrize("change", ["convert", "remove"])
def test_projected_matching_values_do_not_discard_incompatible_drafts(run_node, mode, change):
    run_node(r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const mode = MODE;
const change = CHANGE;
const context = {
  BaseForm: class {}, structuredClone, console,
  areEqual: (left, right) => JSON.stringify(left) === JSON.stringify(right),
  captureError(error) { throw error; },
  withTransition: commit => commit(),
  loadRevisionPreview: async (_widget, response) => ({
    revisionSnapshot: () => JSON.stringify(response.submission), destroy() {},
  }),
};
vm.createContext(context);
for (const [path, name] of [
  ["src/script/shared/formRepresentation.mjs", null],
  ["src/script/elements/form.mjs", "FormElement"],
  ["src/script/shared/editReconciler.mjs", "EditReconciler"],
]) {
  const source = fs.readFileSync(path, "utf8")
    .replace(/^import .*$/gm, "").replaceAll("export ", "");
  vm.runInContext(source + (name ? `\nglobalThis.${name} = ${name};` : ""), context);
}
const before = [
  {id: "quantity", type: "input", input: "text"},
  {id: "note", type: "textarea"},
];
const after = change === "remove" ? [before[1]] : [
  {...before[0], input: "number"}, before[1],
];
const saved = change === "remove" ? {note: "Keep"} : {quantity: 9, note: "Keep"};
const local = {quantity: mode === "clean" ? "009" : "unfinished", note: "Keep"};
let applied = 0;
const cancelled = [];
const button = {textContent: ""};
const message = {textContent: ""};
const widget = new context.FormElement({
  name: "TaskForm", schema: before, submission: {quantity: "009", note: "Keep"},
  target: {cloneNode() { return {}; }},
});
const marker = {
  dataset: {visible: "false"},
  querySelector: selector => selector.includes("edited-message") ? message : button,
  closest: selector => selector === "form[data-widget]" ? {_lp_widget: widget} :
    {dataset: {fingerprint: "before", modified: "old"}},
};
widget.target.querySelector = () => marker;
widget.form = {renderer: {}, _queued: mode === "queued"};
widget.unsavedState = mode === "dirty";
widget.visible = true;
widget.component = {active: widget};
widget._revisionBaseline = "baseline";
widget.revisionSnapshot = () => JSON.stringify(local);
widget.revisionCanReset = () => true;
widget.captureFormState = () => ({renderer_submission: local});
widget._applyQueuedFields = () => {};
widget.prepareRevision = async response => () => {
  applied++;
  widget.schema = response.schema;
};
const reconciler = new context.EditReconciler({
  offlineQueue: {cancel: async id => cancelled.push(id)},
});
const response = {ok: true, schema: after, submission: saved};
// The actual projection omits incompatible local values and matches the server.
assert.deepEqual(widget.buildLocalRevision(response).response.submission, saved);
(async () => {
  const record = mode === "queued" ? {id: "queued-answer"} : null;
  await reconciler._stageRevision(marker, widget, response, {
    fingerprint: "after", modified: "new", record,
  });
  if (mode === "clean") {
    assert.equal(applied, 1);
    assert.equal(marker.dataset.visible, "false");
    return;
  }
  assert.equal(applied, 0, "An incompatible draft was discarded before review");
  assert.deepEqual(cancelled, [], "A queued value was cancelled before review");
  assert.equal(marker.dataset.visible, "true");
  assert.equal(button.textContent, "Review values");
  assert.equal(widget.captureFormState().renderer_submission.quantity, "unfinished");
  assert.equal(widget.schema, before);
  await reconciler.resolveRevision(marker, "server");
  assert.equal(applied, 1);
  assert.deepEqual(cancelled, mode === "queued" ? [record.id] : []);
  assert.equal(marker.dataset.visible, "false");
})().catch(error => { console.error(error); process.exit(1); });
'''.replace("MODE", repr(mode)).replace("CHANGE", repr(change)))
