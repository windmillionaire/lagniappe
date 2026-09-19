"""Node-backed checks for form-builder schema defaults."""


# @matrix forms : builder-save retryable-action single-flight stale-acknowledgement
def test_builder_save_releases_for_retry_and_only_acknowledges_submitted_state(
    run_node,
):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const requests = [];
const classes = new Set();
const button = {
  classList: {
    add(name) { classes.add(name); },
    remove(name) { classes.delete(name); },
  },
  dataset: { saved: "false", kind: "unsaved" },
  disabled: false,
  isConnected: true,
  attributes: {},
  setAttribute(name, value) { this.attributes[name] = value; },
  removeAttribute(name) { delete this.attributes[name]; },
  focus() { document.activeElement = this; },
};
const nameDisplay = { dataset: {}, textContent: "Retryable Form" };
const nameInput = {
  dataset: {},
  value: "Retryable Form",
  addEventListener() {},
  removeEventListener() {},
};
const nameHidden = { value: "Retryable Form" };
const schemaForm = { dataset: { route: "/forms/retry/update" } };
const notification = {
  attributes: {},
  dataset: { visible: "false" },
  textContent: "",
  setAttribute(name, value) { this.attributes[name] = value; },
  append(link) { this.link = link; },
};
const previewToggle = { dataset: {} };
const previewPanel = { dataset: {} };
const document = {
  activeElement: button,
  body: {},
  createElement() { return { dataset: {} }; },
  getElementById(id) {
    return {
      "form-name-display": nameDisplay,
      "form-name-input": nameInput,
      "form-name-hidden": nameHidden,
      "schema-form": schemaForm,
      notification,
      "preview-toggle": previewToggle,
      "preview-panel": previewPanel,
    }[id] || null;
  },
  querySelector(selector) {
    return selector === "[data-saved]" ? button : null;
  },
};
const context = {
  areEqual(a, b) { return JSON.stringify(a) === JSON.stringify(b); },
  crypto: require("node:crypto").webcrypto,
  structuredClone,
  captureError() {},
  clearTimeout() {},
  console,
  document,
  FormData: class { constructor(form) { this.form = form; } },
  FormRenderer: class {},
  request: {
    put(...args) {
      return new Promise((resolve, reject) => requests.push({ resolve, reject, args }));
    },
  },
  setTimeout() { throw new Error("Persistent save errors must not schedule hiding"); },
  withTransition(callback) { return callback(); },
};
vm.createContext(context);
let source = fs.readFileSync(
  "src/script/views/builder/panels/header.mjs",
  "utf8",
);
source = source.replace(/^import(?:[\s\S]*?)from .*;\n/gm, "");
source = source.replace("export class Header", "class Header");
source += "\nglobalThis.Header = Header;";
vm.runInContext(source, context);

(async () => {
const { BuilderDraft } = await import(process.cwd() + "/src/script/views/builder/draft.mjs");
let schema = [{ id: "first", type: "text" }];
let restores = 0;
let settingRefreshes = 0;
let conditionRefreshes = 0;
let controlRefreshes = 0;
const restoredOptions = [];
const builder = {
  get schema() { return schema; },
  captureDraft() { return { schema: structuredClone(schema), name: nameHidden.value, form_type: "task", html_fields: {} }; },
  updateSchema() { this.draft.record(this.captureDraft()); this.draft.dirty ? header.unsaved() : header.saved(); },
  async draftPayload(state) { return structuredClone(state); },
  settings: { refreshSavedState() { settingRefreshes++; } },
  conditions: { condition: { refreshSavedState() { conditionRefreshes++; } } },
  refreshDraftControls() { controlRefreshes++; this.draft.dirty ? header.unsaved() : header.saved(); },
  restoreDraft(options) { restores++; restoredOptions.push(options); schema = structuredClone(this.draft.state.schema); this.draft.dirty ? header.unsaved() : header.saved(); },
};
builder.draft = new BuilderDraft(builder.captureDraft(), "initial");
const header = new context.Header(builder);
if (
  button.attributes["aria-describedby"] !== "notification" ||
  notification.attributes.role !== "status" ||
  notification.attributes["aria-live"] !== "polite"
) {
  throw new Error("Builder save errors are not exposed as an accessible status");
}

schema = [{ ...schema[0], title: "Edited notes" }];
builder.updateSchema();
if (!builder.draft.dirty || button.disabled || button.attributes["aria-disabled"] !== "false") {
  throw new Error("Editing a saved form did not enable Save");
}
builder.online = false;
header.unsaved();
if (button.attributes["aria-disabled"] !== "true" || await header.saveForm() !== false || requests.length) {
  throw new Error("Offline Save started publication or advertised availability");
}
builder.online = true;
header.unsaved();
const first = header.saveForm();
const duplicate = header.saveForm();
await new Promise(setImmediate);
if (first !== duplicate || requests.length !== 1) {
  throw new Error("Concurrent saves were not coalesced");
}
if (button.disabled || button.attributes["aria-disabled"] !== "true" || button.attributes["aria-busy"] !== "true") {
  throw new Error("Save did not stay focusable while exposing its pending state");
}
if (classes.has("opacity-50")) {
  throw new Error("Saving dimmed the Save control");
}
if (requests[0].args[2]?.replaceErrorPage !== false) {
  throw new Error("Builder save did not preserve its retryable page on HTTP errors");
}

schema = [...schema, { id: "second", type: "number" }];
builder.updateSchema();
const firstRequest = requests.shift();
firstRequest.resolve({ ok: true, draft: firstRequest.args[1], baseline: "saved-1" });
if (await first !== true) throw new Error("Successful request was not reported");
if (button.dataset.saved !== "false") {
  throw new Error("A stale save response acknowledged newer builder edits");
}
if (button.disabled || button.attributes["aria-busy"] !== undefined) {
  throw new Error("Successful stale save did not release the control");
}
if (restores || settingRefreshes !== 1 || conditionRefreshes !== 1 || controlRefreshes !== 1) {
  throw new Error("A save receipt rebuilt newer edits instead of refreshing the saved restrictions and controls");
}
if (schema.length !== 2 || builder.draft.state.schema.length !== 2 || builder.draft.saved.schema.length !== 1) {
  throw new Error("A save receipt discarded newer edits or included them in the saved baseline");
}

const rejected = header.saveForm();
await new Promise(setImmediate);
button.dataset.visible = "false";
requests.shift().reject(new Error("transport failed"));
if (await rejected !== false || button.disabled) {
  throw new Error("Rejected save did not release the control");
}
if (button.dataset.visible !== "false") {
  throw new Error("Save settlement overwrote connectivity-owned visibility");
}
button.dataset.visible = "true";

const failed = header.saveForm();
await new Promise(setImmediate);
requests.shift().resolve({ ok: false, error: "Temporary save failure" });
if (await failed !== false) throw new Error("Failed request was not reported");
if (button.disabled || notification.dataset.visible !== "true") {
  throw new Error("Failed save did not release the control with a visible error");
}
if (notification.textContent !== "Temporary save failure") {
  throw new Error(`Unexpected save error: ${notification.textContent}`);
}

const conflicted = header.saveForm();
await new Promise(setImmediate);
requests.shift().resolve({ ok: false, code: "stale_form_draft", error: "Changed elsewhere", saved_url: "/forms/current" });
if (await conflicted !== false || notification.link?.href !== "/forms/current" || notification.link.target !== "_blank") {
  throw new Error("Stale Save did not preserve the draft with a separate saved-form link");
}
if (builder.draft.state.schema.length !== 2 || !builder.draft.dirty) {
  throw new Error("Stale Save discarded the current local draft");
}

const retry = header.saveForm();
await new Promise(setImmediate);
if (retry === failed || requests.length !== 1) {
  throw new Error("Released save could not be retried");
}
const retriedRequest = requests.shift();
retriedRequest.resolve({ ok: true, draft: retriedRequest.args[1], baseline: "saved-2" });
if (await retry !== true || button.dataset.saved !== "true") {
  throw new Error("Retry did not acknowledge the current builder state");
}
if (notification.dataset.visible !== "false" || notification.textContent !== "") {
  throw new Error("Successful retry did not clear the prior error");
}
if (button.disabled || button.attributes["aria-disabled"] !== "true") {
  throw new Error("Saved status did not remain focusable and aria-disabled");
}
if (restores || settingRefreshes !== 2 || conditionRefreshes !== 2 || controlRefreshes !== 2) {
  throw new Error("An ordinary Save rebuilt the panel instead of refreshing its saved restrictions and controls");
}
if (classes.has("opacity-50")) {
  throw new Error("The saved control remained dimmed");
}

const savedRestores = restores;
const savedRevision = builder.draft.revision;
if (await header.saveForm() !== true) {
  throw new Error("Saving an unchanged form was not treated as already saved");
}
if (requests.length || restores !== savedRestores || builder.draft.revision !== savedRevision) {
  throw new Error("Saving an unchanged form submitted or rebuilt the saved draft");
}
if (button.disabled || button.dataset.saved !== "true" || button.attributes["aria-disabled"] !== "true") {
  throw new Error("An unchanged Save disturbed the saved control state");
}

schema = schema.map((field) => field.id === "first" ? { ...field, title: "   Normalized notes   " } : field);
builder.updateSchema();
const normalized = header.saveForm();
await new Promise(setImmediate);
const normalizationRequest = requests.shift();
const accepted = structuredClone(normalizationRequest.args[1]);
accepted.schema[0].title = "Normalized notes";
normalizationRequest.resolve({ ok: true, draft: accepted, baseline: "saved-3" });
if (await normalized !== true || restores !== 1 || restoredOptions[0]?.preserveFocus !== true) {
  throw new Error("A server-normalized schema did not reconcile the visible form while preserving its panel");
}
if (schema[0].title !== "Normalized notes" || builder.draft.dirty || button.dataset.saved !== "true") {
  throw new Error("The server-normalized saved form was not reflected in the builder");
}
if (settingRefreshes !== 2 || conditionRefreshes !== 2 || controlRefreshes !== 2) {
  throw new Error("Normalization incorrectly used the unchanged-panel path");
}

schema = schema.map((field) => field.id === "first" ? { ...field, title: "Edited after saving" } : field);
builder.updateSchema();
if (button.disabled || button.attributes["aria-disabled"] !== "false") {
  throw new Error("A new edit did not reenable Save after a successful retry");
}
const late = header.saveForm();
await new Promise(setImmediate);
header.destroy();
requests.shift().resolve({ ok: true });
if (await late !== false) {
  throw new Error("Destroyed header published a late save acknowledgement");
}
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    )


# @matrix forms ui-action : persistent-error retryable-action schema-generation single-flight
def test_builder_generation_failure_stays_visible_and_releases_submitter(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

let finishRequest;
let requestCount = 0;
const context = {
  FormController: class {},
  crypto: require("node:crypto").webcrypto,
  captureError() {},
  console,
  ENDPOINTS: { createSchema: "/forms/create-schema" },
  FacetsBox: class {},
  FormData: class {
    get(name) { return name === "description" ? "Create a form" : null; }
    append() {}
    set() {}
  },
  Modal: class {},
  request: {
    post() {
      requestCount += 1;
      return new Promise((resolve) => { finishRequest = resolve; });
    },
  },
};
vm.createContext(context);
let source = fs.readFileSync(
  "src/script/views/builder/panels/formSettings.mjs",
  "utf8",
);
source = source.replace(/^import[\s\S]*?;\n/gm, "");
source = source.replace("export class FormSettings", "class FormSettings");
source += "\nglobalThis.FormSettings = FormSettings;";
vm.runInContext(source, context);

(async () => {
const attributes = {};
const submitter = {
  dataset: {},
  disabled: false,
  isConnected: true,
  setAttribute(name, value) { attributes[name] = value; },
  removeAttribute(name) { delete attributes[name]; },
};
let error = null;
let resets = 0;
const settings = {
  _destroyed: false,
  _generationPromise: null,
  builder: {
    updateSchema() {},
    draft: { revision: 0, baseline: "source" },
    captureDraft() { return { schema: [], html_fields: {} }; },
    header: {
      saveButton: { dataset: { saved: "true" } },
      persistenceState: { name: "Generated Form", schema: [] },
    },
  },
  generateForm: {
    target: { dataset: { visible: "true" } },
    submitButton: submitter,
    showError(message) { error = message; submitter.disabled = false; },
    resetSubmitButton() { resets += 1; error = null; },
  },
  _updateSchema: context.FormSettings.prototype._updateSchema,
};
const event = {
  submitter,
  preventDefault() {},
  stopPropagation() {},
};

const first = context.FormSettings.prototype._generateSchema.call(settings, event);
const duplicate = context.FormSettings.prototype._generateSchema.call(settings, event);
if (first !== duplicate || requestCount !== 1) {
  throw new Error("Concurrent schema generations were not coalesced");
}
if (!submitter.disabled || attributes["aria-busy"] !== "true") {
  throw new Error("Schema generation did not expose its pending state");
}

finishRequest({ ok: false, error: "Generation unavailable" });
if (await first !== false) throw new Error("Failed generation was not reported");
if (error !== "Generation unavailable" || resets !== 0) {
  throw new Error("Generation failure was cleared by submit-button reset");
}
if (submitter.disabled || attributes["aria-busy"] !== undefined) {
  throw new Error("Failed generation did not release its submitter");
}
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    )


# @matrix form-table forms : builder-defaults empty-columns unsaved-preview
def test_table_creation_defaults_columns_for_unsaved_preview(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const context = {
  generateElementId(type) {
    return `${type}-1`;
  },
  ModelElement: {
    table(schema) {
      return { id: schema.id };
    },
  },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/views/builder/builder.mjs", "utf8");
source = source.replace(/^import(?:[\s\S]*?)from .*;\n/gm, "");
source = source.replace(
  "export default FormBuilder;",
  "globalThis.FormBuilder = FormBuilder;",
);
vm.runInContext(source, context);

const builder = {
  elements: new Map(),
  settings: {
    create() {
      return {};
    },
  },
};
const schema = { type: "table" };
const element = context.FormBuilder.prototype.createElement.call(builder, schema);

if (schema.id !== "table-1") {
  throw new Error(`Unexpected table ID: ${schema.id}`);
}
if (!Array.isArray(schema.columns) || schema.columns.length !== 0) {
  throw new Error("New table schema did not default columns to an empty list");
}
if (builder.elements.get(schema.id)?.schema !== schema) {
  throw new Error("Builder did not retain the normalized table schema");
}
if (element.id !== schema.id) {
  throw new Error("Builder model did not receive the normalized table schema");
}
'''
    )


# @matrix forms offline : builder-lifecycle
def test_builder_sync_uses_shared_connectivity_without_orphaned_global_state(
    run_node,
):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

(async () => {
const search = { dataset: {} };
const indicator = {
  dataset: {},
  setAttribute(name, value) { this[name] = value; },
};
const saveButton = {
  dataset: {},
  getAttribute(name) { return this[name] ?? null; },
  setAttribute(name, value) { this[name] = value; },
};
const context = {
  connectivity: {
    hidden: false,
    online: true,
  },
  document: {
    hidden: false,
    querySelector(selector) {
      return selector === "[lp-search]" ? search : null;
    },
  },
  window: {},
};
vm.createContext(context);
let source = fs.readFileSync("src/script/views/builder/builder.mjs", "utf8");
source = source.replace(/^import(?:[\s\S]*?)from .*;\n/gm, "");
source = source.replace(
  "export default FormBuilder;",
  "globalThis.FormBuilder = FormBuilder;",
);
vm.runInContext(source, context);

const builder = {
  _independentDocuments: new Set(),
  flushIndependentDocuments:
    context.FormBuilder.prototype.flushIndependentDocuments,
  header: { saveButton },
  hidden: false,
  offline: context.FormBuilder.prototype.offline,
  offlineIndicator: indicator,
  online: true,
};

context.connectivity.online = false;
await context.FormBuilder.prototype.sync.call(builder, { hidden: true });
if (builder.online !== false || builder.hidden !== true) {
  throw new Error("Builder did not adopt the shared offline/hidden state");
}
if (
  indicator.dataset.visible !== "true" ||
  search.dataset.visible !== "false" ||
  saveButton.dataset.visible !== "true" ||
  saveButton["aria-disabled"] !== "true"
) {
  throw new Error("Builder controls did not enter their offline state");
}

context.connectivity.online = true;
await context.FormBuilder.prototype.sync.call(builder, { hidden: false });
if (builder.online !== true || builder.hidden !== false) {
  throw new Error("Builder did not adopt the shared online/visible state");
}
if (
  indicator.dataset.visible !== "false" ||
  search.dataset.visible !== "true" ||
  saveButton.dataset.visible !== "true" ||
  saveButton["aria-disabled"] !== "false"
) {
  throw new Error("Builder controls did not recover their online state");
}
if (Object.hasOwn(context.window, "__LP_OFFLINE__")) {
  throw new Error("Builder still published orphaned global offline state");
}
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
''',
    )


# @matrix forms : action-button-centering builder-list-actions
def test_builder_schema_lists_use_button_surfaces_and_centered_actions(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class Node {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.className = "";
    this.classList = {
      add: (...classes) => {
        this.className = `${this.className} ${classes.join(" ")}`.trim();
      },
    };
  }
  appendChild(child) { this.children.push(child); return child; }
  append(...children) { this.children.push(...children); }
}

const styles = {
  builder: {
    settings: {
      item: "builder-setting-item",
      open: "builder-setting-open",
      toggle: {
        container: "action-icon-button size-5",
        icon: "icon-xs",
      },
    },
  },
};
const context = {
  CONFIG: {},
  STYLES: styles,
  document: {
    createElement: (tagName) => new Node(tagName),
    getElementById: () => new Node("div"),
  },
  primitives: {
    toggle({ styles: toggleStyles, data }) {
      const button = new Node("button");
      button.className = toggleStyles.container;
      Object.assign(button.dataset, data);
      return button;
    },
    label({ tag = "label", role = "label", styles: labelStyles = {} }) {
      const outer = new Node(tag);
      outer.className = labelStyles.label || "";
      const inner = outer.appendChild(new Node("div"));
      inner.dataset.role = role;
      inner.className = labelStyles.container || "";
      return outer;
    },
  },
  withTransition(callback) { return callback(); },
};
vm.createContext(context);
let source = fs.readFileSync(
  "src/script/views/builder/panels/elementSettings.mjs",
  "utf8",
);
source = source.replace(/^import[\s\S]*?;\n/gm, "");
source = source.replace("export class ElementSettings", "class ElementSettings");
source += `
globalThis.settingFactories = { _condition, _option, _column, _toggle };
`;
vm.runInContext(source, context);

const { _condition, _option, _column, _toggle } = context.settingFactories;
const condition = _condition({ name: "Approved", checked: true }, 0);
const option = _option({ label: "First" }, 0, 2);
const column = _column({ name: "Amount", input: "number" }, 0, 2);

for (const [name, row] of [["condition", condition], ["option", option], ["column", column]]) {
  const open = row.children[0];
  if (open.tagName !== "BUTTON" || open.type !== "button") {
    throw new Error(`${name} editor is not exposed as a button`);
  }
  if (open.className !== styles.builder.settings.open) {
    throw new Error(`${name} editor lost the shared button surface`);
  }
}
if (column.tagName !== "LI") {
  throw new Error("Table columns are not represented as semantic list items");
}

const actions = [
  _toggle("add", "add"),
  condition.children[1],
  ...option.children[1].children,
  ...column.children[1].children,
];
for (const action of actions) {
  if (action.type !== "button") {
    throw new Error(`Builder ${action.dataset.role} action can submit its containing form`);
  }
  const classes = action.className.split(/\s+/);
  if (!classes.includes("action-icon-button") || !classes.includes("size-5")) {
    throw new Error(`Builder ${action.dataset.role} action bypassed centered icon geometry`);
  }
}
'''
    )


# @matrix forms : access-restrictions explicit-submit retryable-action single-flight
def test_restriction_save_submits_snapshot_and_releases_failed_submitter(run_node):
    run_node(r'''
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const requests = [];
let settle;
const context = {
  captureError() {},
  FormData: class {
    constructor(form) { this.groups = [...form.groups]; }
    *[Symbol.iterator]() { for (const group of this.groups) yield ["group-key", group]; }
  },
  request: { put(route, data) {
    requests.push({route, data});
    return new Promise(resolve => { settle = resolve; });
  } },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/views/builder/panels/formSettings.mjs", "utf8")
  .replace(/^import[\s\S]*?;\n/gm, "")
  .replace("export class FormSettings", "class FormSettings");
vm.runInContext(source + "\nglobalThis.FormSettings = FormSettings;", context);
(async () => {
  const messages = [];
  const button = {disabled: false};
  const settings = {
    _destroyed: false, _restrictionPromise: null,
    restrictions: {dataset: {route: "/forms/example/restrictions"}, groups: ["group-one"]},
    restrictionForm: {
      submitButton: button,
      submitting() { messages.push("spinner"); },
      success() { messages.push("saved"); },
      resetSubmitButton() { messages.push("reset"); },
      markUnsavedState() { messages.push("unsaved"); },
      showError(error) { messages.push(error); },
    },
  };
  const event = {preventDefault() {}, stopPropagation() {}};
  const save = () => context.FormSettings.prototype._saveRestrictions.call(settings, event);
  const first = save();
  assert.equal(save(), first);
  assert.equal(requests.length, 1);
  assert.equal(button.disabled, true);
  assert.equal(messages[0], "spinner");
  settings.restrictions.groups.push("group-two");
  assert.equal(requests[0].data.groups.length, 1);
  settle({ok: false, error: "Queue unavailable"});
  await first;
  assert.equal(button.disabled, false);
  assert.equal(messages.at(-1), "Queue unavailable");
  const retry = save();
  assert.equal(requests.length, 2);
  assert.equal(requests[1].data.groups.length, 2);
  settle({ok: true});
  await retry;
  assert.equal(button.disabled, false);
  assert.equal(messages.at(-1), "saved");
  const pending = save();
  settings.restrictions.groups.push("group-three");
  settle({ok: true});
  await pending;
  assert.equal(messages.at(-1), "unsaved");
  assert.equal(button.disabled, false);
})().catch(error => { console.error(error); process.exitCode = 1; });
''')
