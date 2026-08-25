"""Node-backed checks for form-builder schema defaults."""


# @features forms
# @dimensions builder-save single-flight retryable-action stale-acknowledgement
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
};
const previewToggle = { dataset: {} };
const previewPanel = { dataset: {} };
const document = {
  activeElement: button,
  body: {},
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
  captureError() {},
  clearTimeout() {},
  console,
  document,
  FormData: class { constructor(form) { this.form = form; } },
  Renderer: class {},
  request: {
    put() {
      return new Promise((resolve, reject) => requests.push({ resolve, reject }));
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
let schema = [{ id: "first", type: "text" }];
const builder = {
  get schema() { return schema; },
};
const header = new context.Header(builder);
if (
  button.attributes["aria-describedby"] !== "notification" ||
  notification.attributes.role !== "status" ||
  notification.attributes["aria-live"] !== "polite"
) {
  throw new Error("Builder save errors are not exposed as an accessible status");
}

const first = header.saveForm();
const duplicate = header.saveForm();
if (first !== duplicate || requests.length !== 1) {
  throw new Error("Concurrent saves were not coalesced");
}
if (!button.disabled || button.attributes["aria-busy"] !== "true") {
  throw new Error("Save did not expose its pending state");
}

schema = [...schema, { id: "second", type: "number" }];
requests.shift().resolve({ ok: true });
if (await first !== true) throw new Error("Successful request was not reported");
if (button.dataset.saved !== "false") {
  throw new Error("A stale save response acknowledged newer builder edits");
}
if (button.disabled || button.attributes["aria-busy"] !== undefined) {
  throw new Error("Successful stale save did not release the control");
}

const rejected = header.saveForm();
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
requests.shift().resolve({ ok: false, error: "Temporary save failure" });
if (await failed !== false) throw new Error("Failed request was not reported");
if (button.disabled || notification.dataset.visible !== "true") {
  throw new Error("Failed save did not release the control with a visible error");
}
if (notification.textContent !== "Temporary save failure") {
  throw new Error(`Unexpected save error: ${notification.textContent}`);
}

const retry = header.saveForm();
if (retry === failed || requests.length !== 1) {
  throw new Error("Released save could not be retried");
}
requests.shift().resolve({ ok: true });
if (await retry !== true || button.dataset.saved !== "true") {
  throw new Error("Retry did not acknowledge the current builder state");
}
if (notification.dataset.visible !== "false" || notification.textContent !== "") {
  throw new Error("Successful retry did not clear the prior error");
}

const late = header.saveForm();
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


# @features forms ui-action
# @dimensions schema-generation single-flight retryable-action persistent-error
def test_builder_generation_failure_stays_visible_and_releases_submitter(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

let finishRequest;
let requestCount = 0;
const context = {
  BaseForm: class {},
  captureError() {},
  console,
  ENDPOINTS: { createSchema: "/forms/create-schema" },
  FacetsBox: class {},
  FormData: class {
    get(name) { return name === "description" ? "Create a form" : null; }
    append() {}
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
source = source.replace(/^import .*$/gm, "");
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


# @features forms form-table
# @dimensions builder-defaults unsaved-preview empty-columns
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


# @pairs forms:builder-lifecycle offline:builder-lifecycle
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
const saveButton = { dataset: {} };
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
  saveButton.dataset.visible !== "false"
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
  saveButton.dataset.visible !== "true"
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


# @pairs forms:builder-list-actions forms:action-button-centering
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
source = source.replace(/^import .*$/gm, "");
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
