"""Node-backed checks for form-builder schema defaults."""


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
