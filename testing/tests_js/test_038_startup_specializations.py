"""Node-backed checks for startup-sensitive view specialization."""


# @pair startup:mobile-only-dropdown
# @pair manual:responsive-navigation
def test_manual_dropdown_loads_only_in_mobile_mode(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const windowListeners = new Map();
const context = {
  clearTimeout,
  console,
  ENDPOINTS: { manual: {} },
  mobileMode: false,
  request: {},
  setTimeout,
  window: {
    addEventListener(type, listener) { windowListeners.set(type, listener); },
    removeEventListener(type) { windowListeners.delete(type); },
  },
};
context.globalThis = context;
vm.createContext(context);

let source = fs.readFileSync("src/script/views/manual.mjs", "utf8");
source = source.replace(
  /^import [\s\S]*?(?=\/\*\*)/,
  `
const ShellView = class {
  constructor(elt) {
    this.elt = elt;
    this.mobile = globalThis.mobileMode;
    this._destroyed = false;
  }
  async init() {}
  destroy() { this._destroyed = true; }
};
`,
);
source = source.replace("export default class Manual", "class Manual");
source += "\nglobalThis.Manual = Manual;";
vm.runInContext(source, context);

const createRoot = () => {
  const listeners = new Map();
  return {
    listeners,
    addEventListener(type, listener) { listeners.set(type, listener); },
    querySelector() { return null; },
    removeEventListener(type) { listeners.delete(type); },
  };
};

(async () => {
  const desktopRoot = createRoot();
  const desktop = new context.Manual(desktopRoot);
  let desktopLoads = 0;
  desktop._ensureMobileDropdown = async () => { desktopLoads += 1; };
  await desktop.init();
  if (desktopLoads !== 0) throw new Error("Desktop Manual loaded Dropdown");
  desktop.mobile = true;
  desktopRoot.listeners.get("mobile-resize")();
  if (desktopLoads !== 1) throw new Error("Manual did not load after mobile resize");
  desktop.destroy();

  context.mobileMode = true;
  const mobile = new context.Manual(createRoot());
  let mobileLoads = 0;
  mobile._ensureMobileDropdown = async () => { mobileLoads += 1; };
  await mobile.init();
  if (mobileLoads !== 1) throw new Error("Mobile Manual did not load Dropdown");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @pair table-controls:eager-column-state
# @pair table-controls:lazy-checkbox-panel
# @pair table-controls:persistence
def test_column_visibility_state_applies_before_lazy_panel(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const storage = new Map([["columns-tasks", "[2]"]]);
let toggleListener = null;
const styles = [];
const context = {
  console,
  document: {
    createElement() {
      return {
        remove() { this.removed = true; },
        textContent: "",
      };
    },
    head: { appendChild(style) { styles.push(style); } },
  },
  localStorage: {
    getItem(key) { return storage.get(key) || null; },
    setItem(key, value) { storage.set(key, value); },
  },
};
vm.createContext(context);

let source = fs.readFileSync(
  "src/script/widgets/tableVisibilityState.mjs",
  "utf8",
);
source = source.replace(
  "export class TableVisibilityState",
  "class TableVisibilityState",
);
source += "\nglobalThis.TableVisibilityState = TableVisibilityState;";
vm.runInContext(source, context);

const headers = ["name", "status", "owner"].map((column) => ({
  dataset: { column },
}));
const component = {
  elt: {
    id: "table",
    querySelectorAll() { return headers; },
  },
  widgets: {},
};
const view = {
  hash: "tasks",
  elt: {
    addEventListener(_type, listener) { toggleListener = listener; },
    removeEventListener() { toggleListener = null; },
  },
};
const state = new context.TableVisibilityState({
  component,
  view,
  selected: [],
  columns: headers.map(({ dataset }) => ({
    field: dataset.column,
    selected: true,
  })),
}).init();

if (!styles[0].textContent.includes("nth-child(2)")) {
  throw new Error("Saved visibility was not applied eagerly");
}
if (state.visibleColumns.join(",") !== "name,owner") {
  throw new Error(`Saved visible columns changed: ${state.visibleColumns}`);
}
toggleListener({ detail: { active: true, column: "status" } });
if (styles[0].textContent || storage.get("columns-tasks") !== "[]") {
  throw new Error("The lazy controller event did not update eager state");
}
state.destroy();
if (!styles[0].removed || toggleListener) {
  throw new Error("Column state did not remove its lifecycle resources");
}
'''
    )


# @pair pages:photo-lazy-activation
# @pair pages:photo-visible-startup
def test_page_photo_initializes_only_when_selected_or_visible(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const storage = new Map();
const context = {
  console,
  localStorage: {
    getItem(key) { return storage.get(key) || null; },
    setItem(key, value) { storage.set(key, value); },
  },
  URLSearchParams,
  window: { location: { pathname: "/pages/page-1", search: "" } },
};
vm.createContext(context);

let source = fs.readFileSync("src/script/views/page.mjs", "utf8");
source = source.replace(
  'import Entity from "./base/entity";',
  `
const Entity = class {
  constructor(elt) { this.elt = elt; this.hash = "page"; this.key = "page-1"; }
  async init() {}
  getComponent() { return this.component; }
  isSecondaryCardVisible() { return this.photoVisible; }
};
`,
);
source = source.replace("export default class Page", "class Page");
source += "\nglobalThis.Page = Page;";
vm.runInContext(source, context);

const photo = {};
const createPage = ({ active = null, visible = false } = {}) => {
  const page = new context.Page({
    dataset: {},
    querySelector(selector) { return selector === "#photo" ? photo : null; },
  });
  let activations = 0;
  page.component = {
    active,
    async activate(name) {
      if (name !== "PagePhoto") throw new Error("Wrong photo widget");
      activations += 1;
    },
  };
  page.photoVisible = visible;
  return { page, activations: () => activations };
};

(async () => {
  const hidden = createPage();
  await hidden.page.init();
  if (hidden.activations()) throw new Error("Hidden photo initialized eagerly");

  const visible = createPage({ visible: true });
  await visible.page.init();
  if (visible.activations() !== 1) throw new Error("Visible photo was not initialized");

  const selected = createPage({ active: { name: "PagePhoto" } });
  await selected.page.init();
  if (selected.activations()) throw new Error("Selected photo initialized twice");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @pair ai-report:lazy-form-runtime
# @pair ai-report:concurrent-form-init
def test_report_loads_base_form_only_for_present_forms_and_in_parallel(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const events = [];
const pending = new Map();
let formLoads = 0;
class FakeBaseForm {
  constructor({ target }) { this.target = target; }
  init() {
    events.push(`start:${this.target.dataset.role}`);
    return new Promise((resolve) => pending.set(this.target.dataset.role, resolve));
  }
}
const context = {
  console,
  createIcon() {},
  FakeBaseForm,
  request: {},
  setIcon() {},
  window: { addEventListener() {} },
};
context.globalThis = context;
context.loadBaseForm = async () => {
  formLoads += 1;
  return { BaseForm: context.FakeBaseForm };
};
vm.createContext(context);

let source = fs.readFileSync("src/script/views/report.mjs", "utf8");
source = source.replace(
  /^import [\s\S]*?(?=\/\*\*)/,
  `
const Core = class {
  constructor(elt) { this.elt = elt; }
  async init() {}
};
const REPORT_FORM_SELECTOR =
  "[data-role='run-report-form'], [data-role='retry-report-form'], [data-role='undo-report-form'], [data-role='revise-report-form']";
`,
);
source = source.replace(
  'import("../elements/base/baseForm")',
  "globalThis.loadBaseForm()",
);
source = source.replace("export default class Report", "class Report");
source += "\nglobalThis.Report = Report;";
vm.runInContext(source, context);

const createTarget = (role) => ({
  dataset: { role },
  addEventListener() {},
});
const targets = {
  run: createTarget("run-report-form"),
  undo: createTarget("undo-report-form"),
  revise: createTarget("revise-report-form"),
};
const formsRoot = {
  querySelector(selector) {
    if (selector.includes(",")) return targets.run;
    if (selector.includes("run-report-form")) return targets.run;
    if (selector.includes("undo-report-form")) return targets.undo;
    if (selector.includes("revise-report-form")) return targets.revise;
    return null;
  },
};

(async () => {
  const empty = new context.Report({ querySelector() { return null; } });
  await empty.init();
  if (formLoads !== 0) throw new Error("Formless report loaded BaseForm");

  const report = new context.Report(formsRoot);
  const initializing = report.init();
  for (let index = 0; index < 4; index += 1) await Promise.resolve();
  if (formLoads !== 1 || events.length !== 3) {
    throw new Error(`Report forms did not start concurrently: ${events}`);
  }
  for (const resolve of pending.values()) resolve();
  await initializing;
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )
