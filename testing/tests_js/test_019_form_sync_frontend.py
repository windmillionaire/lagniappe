"""Node-backed checks for form rendering and administrative widgets."""


# @features admin
# @dimensions site-settings composite-widgets sections persistence
def test_site_settings_coordinates_section_widgets(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

class FakeToggle {
  constructor() {
    this.dataset = {};
    this.attributes = {};
    this.title = "";
  }
  setAttribute(name, value) { this.attributes[name] = value; }
}

class FakeSection {
  constructor(name) {
    this.dataset = { section: name, open: "false" };
    this.body = { dataset: { visible: "false" } };
    this.toggle = new FakeToggle();
  }
  querySelector(selector) {
    if (selector === "[data-role='section-body']") return this.body;
    if (selector === "[data-role='expand']") return this.toggle;
    return null;
  }
}

const names = [
  "maintenance",
  "administrators",
  "deployment",
  "ai-models",
  "service-providers",
  "site-image",
];
const sections = names.map((name) => new FakeSection(name));
const target = {
  attributes: {},
  listeners: {},
  querySelectorAll: () => sections,
  addEventListener(type, listener) { this.listeners[type] = listener; },
  removeEventListener(type, listener) {
    if (this.listeners[type] === listener) delete this.listeners[type];
  },
  setAttribute(name, value) { this.attributes[name] = value; },
};

const loaded = [];
const widgets = new Map();
const component = {
  async loadWidget(name) {
    loaded.push(name);
    const widget = {
      modified: false,
      responses: [],
      openedCount: 0,
      updated(response) { this.responses.push(response); },
      async opened() { this.openedCount += 1; },
    };
    widgets.set(name, widget);
    return widget;
  },
};

const storage = new Map([["lagniappe:site-settings-section", "missing"]]);
const context = {
  console,
  localStorage: {
    getItem: (key) => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: (key) => storage.delete(key),
  },
  withTransition: async (callback) => await callback(),
};

vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/siteSettings.mjs", "utf8");
source = source.replace(/import[\s\S]*?from ".*?";\n/g, "");
source = source.replace("export class SiteSettings", "class SiteSettings");
source += "\nglobalThis.SiteSettings = SiteSettings;";
vm.runInContext(source, context);

(async () => {
  const settings = new context.SiteSettings({ component, target });
  await settings.init();

  const expectedWidgets = [
    "SiteMaintenance",
    "SiteAdministrators",
    "SiteDeployment",
    "SiteAiModels",
    "SiteServiceProviders",
    "SiteImage",
  ];
  if (JSON.stringify(loaded.sort()) !== JSON.stringify(expectedWidgets.sort())) {
    throw new Error(`Unexpected child widgets: ${JSON.stringify(loaded)}`);
  }
  if (target.attributes.initialized !== "") {
    throw new Error("Coordinator was published before initialization completed");
  }
  if (sections[0].dataset.open !== "true" || sections[0].body.dataset.visible !== "true") {
    throw new Error("Invalid saved state did not fall back to Maintenance");
  }

  const response = { deployment: { DEPLOY_SCALING_TYPE: "basic" } };
  settings.updated(response);
  for (const widget of widgets.values()) {
    if (widget.responses[0] !== response || widget.modified !== true) {
      throw new Error("Aggregate response was not forwarded for reconciliation");
    }
  }

  await settings._toggleSection("site-image");
  const image = widgets.get("SiteImage");
  if (image.openedCount !== 1 || storage.get("lagniappe:site-settings-section") !== "site-image") {
    throw new Error("Opening Site Image did not persist state or invoke its lifecycle hook");
  }
  if (sections.at(-1).dataset.open !== "true" || sections[0].dataset.open !== "false") {
    throw new Error("Opening one section did not close the prior section");
  }

  await settings._toggleSection("site-image");
  if (storage.has("lagniappe:site-settings-section") || sections.some((section) => section.dataset.open === "true")) {
    throw new Error("Collapsing the active section did not clear persisted state");
  }

  settings.destroy();
  if (target.listeners.click) throw new Error("Coordinator click listener was not removed");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""
    )


# @features admin
# @dimensions ai-settings model-options saved-values
def test_site_settings_initializes_ai_selects_before_syncing_saved_values(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const context = {
  SiteSetting: class {},
  SelectBox: class {},
  buttons: {},
  console,
  request: {},
};

vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/siteSettings/aiModels.mjs", "utf8");
source = source.replace(/import[\s\S]*?from ".*?";\n/g, "");
source = source.replace("export class SiteAiModels", "class SiteAiModels");
source += "\nglobalThis.SiteAiModels = SiteAiModels;";
vm.runInContext(source, context);

const calls = [];
const settings = Object.create(context.SiteAiModels.prototype);
settings.aiForm = { querySelector: () => null };
settings._initAiSelectBoxes = () => calls.push("init");
settings._populateAiModelSelect = (name) => calls.push(`populate:${name}`);
settings._setAiField = (name, value) => calls.push(`set:${name}:${value}`);
settings.updateSummary = () => calls.push("summary");

settings._renderAiSettings(
  {
    AI_MODEL: "saved-primary",
    AI_UTILITY_MODEL: "saved-utility",
    AI_IMAGE_MODEL: "saved-image",
    AI_LOCATION: "global",
  },
  { text: [], image: [] },
);

if (calls[0] !== "init") {
  throw new Error(`AI selects initialized too late: ${JSON.stringify(calls)}`);
}
const firstSet = calls.findIndex((call) => call.startsWith("set:"));
const lastPopulate = calls.reduce(
  (index, call, current) => call.startsWith("populate:") ? current : index,
  -1,
);
if (firstSet <= lastPopulate) {
  throw new Error(`Saved values synced before options: ${JSON.stringify(calls)}`);
}
if (!calls.includes("set:AI_MODEL:saved-primary") ||
    !calls.includes("set:AI_UTILITY_MODEL:saved-utility")) {
  throw new Error(`Saved model values were not synchronized: ${JSON.stringify(calls)}`);
}
"""
    )


# @features admin
# @dimensions ai-settings model-selection submission
def test_site_settings_ai_submission_uses_visible_combobox_values(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

class FormData {
  constructor(form) {
    this.data = new Map(form.initialData);
  }
  get(name) {
    return this.data.get(name);
  }
  set(name, value) {
    this.data.set(name, value);
  }
}

const context = {
  SiteSetting: class {},
  SelectBox: class {},
  buttons: {},
  console,
  FormData,
  request: {},
};

vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/siteSettings/aiModels.mjs", "utf8");
source = source.replace(/import[\s\S]*?from ".*?";\n/g, "");
source = source.replace("export class SiteAiModels", "class SiteAiModels");
source += "\nglobalThis.SiteAiModels = SiteAiModels;";
vm.runInContext(source, context);

const primary = {
  name: "AI_MODEL",
  value: "stale-native-primary",
  closest: () => ({
    _lp_combobox: { values: new Set(["visible-primary"]) },
  }),
};
const utility = {
  name: "AI_UTILITY_MODEL",
  value: "native-utility",
  closest: () => ({
    _lp_combobox: { values: new Set() },
  }),
};
const form = {
  initialData: [
    ["AI_MODEL", "stale-form-primary"],
    ["AI_UTILITY_MODEL", "stale-form-utility"],
    ["AI_IMAGE_MODEL", "saved-image"],
    ["AI_LOCATION", "global"],
  ],
  querySelectorAll: () => [primary, utility],
};
const settings = Object.create(context.SiteAiModels.prototype);
settings.aiForm = form;

const data = settings._aiSettingsFormData();
if (data.get("AI_MODEL") !== "visible-primary") {
  throw new Error(`Visible primary selection was not submitted: ${data.get("AI_MODEL")}`);
}
if (data.get("AI_UTILITY_MODEL") !== "native-utility") {
  throw new Error(`Native fallback was not submitted: ${data.get("AI_UTILITY_MODEL")}`);
}
if (data.get("AI_IMAGE_MODEL") !== "saved-image" || data.get("AI_LOCATION") !== "global") {
  throw new Error("Non-combobox AI fields changed while constructing the submission");
}
"""
    )


# @features forms form-schema
# @dimensions visibility canonical-list legacy-object-rejected
def test_renderer_visibility_requires_canonical_condition_lists(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const context = {
  areEqual: () => true,
  captureError(error) { throw error; },
  console,
  generateElementId: () => "renderer-test",
  getFormElement: async () => null,
  withTransition: async (callback) => await callback(),
};

vm.createContext(context);
let source = fs.readFileSync("src/script/elements/renderer.mjs", "utf8");
source = source.replace(
  'import { getFormElement } from "../elements/loader";',
  "const getFormElement = globalThis.getFormElement;",
);
source = source.replace(
  /import \{[\s\S]*?\} from "\.\.\/shared";/,
  "const { areEqual, captureError, generateElementId, withTransition } = globalThis;",
);
source = source.replace("export class Renderer", "class Renderer");
source += "\nglobalThis.Renderer = Renderer;";
vm.runInContext(source, context);

const triggerNode = {};
const targetNode = { dataset: {} };
const trigger = {
  id: "trigger-renderer-test",
  schema: { id: "trigger", type: "checkbox" },
  elt: triggerNode,
  active: (value) => value === true,
};
const target = {
  id: "conditional-renderer-test",
  schema: {
    id: "conditional",
    type: "input",
    visibility: [{ id: "trigger", value: true }],
  },
  elt: targetNode,
};
const form = {
  target: { dataset: {} },
  readonly: false,
};
const renderer = new context.Renderer(form);
renderer.elements.set(trigger.id, trigger);
renderer.elements.set(target.id, target);

(async () => {
  await renderer._initVisibilityTriggers();
  renderer._updateDerivedState();
  if (targetNode.dataset.visible !== "true") {
    throw new Error(`Expected canonical visibility to match, got ${targetNode.dataset.visible}`);
  }
  if (!renderer.visibilityTriggers.get(trigger)?.has(target)) {
    throw new Error("Canonical visibility trigger ownership was not registered");
  }

  target.schema.visibility = { id: "trigger", value: true };
  let rejected = false;
  try {
    await renderer._initVisibilityTriggers();
  } catch (error) {
    rejected = /filter/.test(error.message);
  }
  if (!rejected) {
    throw new Error("Legacy object-shaped visibility was still accepted");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


# @features forms form-schema
# @dimensions builder presentation-defaults immutable-schema
def test_builder_model_defaults_are_presentation_only(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

class Node {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.classList = { add() {} };
  }
  appendChild(child) { this.children.push(child); return child; }
}
const calls = [];
const primitive = (kind) => (attributes) => {
  calls.push({ kind, attributes });
  return new Node();
};
const context = {
  CONFIG: {
    PRESENTATION_DEFAULTS: {
      input: { title: "Input", input: "text" },
      link: { title: "Link", location: "out" },
    },
  },
  console,
  document: { createElement: () => new Node(), getElementById: () => new Node() },
  primitives: {
    badge: primitive("badge"),
    checkbox: primitive("checkbox"),
    input: primitive("input"),
    label: primitive("label"),
    radio: primitive("radio"),
    select: primitive("select"),
    textarea: primitive("textarea"),
  },
  Sortable: { create() { return { destroy() {} }; } },
  STYLES: {
    badge: { builder: "" },
    builder: { model: "" },
    radio: { fieldset: { column: "" }, label: "" },
  },
};

vm.createContext(context);
let source = fs.readFileSync("src/script/views/builder/panels/model.mjs", "utf8");
source = source.replace('import Sortable from "sortablejs";', "const Sortable = globalThis.Sortable;");
source = source.replace('import { STYLES } from "styles";', "const STYLES = globalThis.STYLES;");
source = source.replace('import { CONFIG } from "../../../config/builder";', "const CONFIG = globalThis.CONFIG;");
source = source.replace('import { primitives } from "../../../elements/primitives";', "const primitives = globalThis.primitives;");
source = source.replace("export class ModelPanel", "class ModelPanel");
source = source.replace("export const ModelElement", "const ModelElement");
source += "\nglobalThis.ModelElement = ModelElement;";
vm.runInContext(source, context);

const inputSchema = { id: "field", type: "input" };
const linkSchema = { id: "link", type: "link" };
const before = JSON.stringify([inputSchema, linkSchema]);
context.ModelElement.input(inputSchema);
context.ModelElement.link(linkSchema);

if (JSON.stringify([inputSchema, linkSchema]) !== before) {
  throw new Error("Rendering builder models mutated the durable schema draft");
}
const inputCall = calls.find((call) => call.kind === "input");
const linkCall = calls.find((call) => call.kind === "label");
if (inputCall?.attributes?.label !== "Input" || inputCall?.attributes?.type !== "text") {
  throw new Error("Input presentation defaults were not applied");
}
if (linkCall?.attributes?.label !== "Link" || linkCall?.attributes?.icon !== "out") {
  throw new Error("Link presentation defaults were not applied");
}
"""
    )


# @features admin database-migrations
# @dimensions current pending running failed audit-error version-history repairs actionable-links cache-gate
# @template home/site_settings.html::site_settings
def test_site_settings_migration_status_uses_generic_release_states(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

class FakeNode {
  constructor() {
    this.textContent = "";
    this.dataset = {};
    this.children = [];
    this.nodes = {};
    this.disabled = false;
    this.open = false;
  }
  querySelector(selector) { return this.nodes[selector] || null; }
  replaceChildren() { this.children = []; }
  appendChild(child) { this.children.push(child); }
  get childElementCount() { return this.children.length; }
}

const title = new FakeNode();
const summary = new FakeNode();
const results = new FakeNode();
const repairs = new FakeNode();
const errors = new FakeNode();
const updateButton = new FakeNode();
const cacheButton = new FakeNode();
const panel = new FakeNode();
panel.nodes = {
  "[data-role='migration-status-title']": title,
  "[data-role='migration-status-summary']": summary,
  "[data-role='migration-status-results']": results,
  "[data-role='migration-status-repairs']": repairs,
  "[data-role='migration-status-errors']": errors,
};
const target = new FakeNode();
target.nodes = {
  "[data-role='migration-status']": panel,
  "[data-role='site-update']": updateButton,
  "[data-role='rebuild-cache']": cacheButton,
};

const context = {
  SiteSetting: class {},
  STYLES: {
    link: { emphasized: "link-emphasized" },
    siteSettings: {
      migration: {
        releaseSummary: "release-summary",
        migrationList: "migration-list",
        completion: "completion",
        attemptList: "attempt-list",
      },
    },
  },
  Modal: class {},
  buttons: {},
  clearRecentSearchResults() {},
  console,
  document: { createElement: () => new FakeNode() },
  request: {},
};

vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/siteSettings/maintenance.mjs", "utf8");
source = source.replace(/import[\s\S]*?from ".*?";\n/g, "");
source = source.replace("export class SiteMaintenance", "class SiteMaintenance");
source += "\nglobalThis.SiteMaintenance = SiteMaintenance;";
vm.runInContext(source, context);

const settings = Object.create(context.SiteMaintenance.prototype);
settings.target = target;

const completed = {
  id: "FSM-001",
  sequence: 1,
  introduced_in: "0.1",
  label: "Canonical form schemas",
  state: "complete",
  completed_at: "2026-07-14T00:00:00+00:00",
  completed_version: "0.1",
  completed_build_id: "old-build",
  attempts: [
    {
      status: "failed",
      totals: { changed: 0, repaired: 0, failed: 1 },
      repairs: [],
      errors: [
        {
          key: "stale-error-key",
          message: "A failure resolved by the later attempt",
          url: "/forms/already-repaired-form",
          link_label: "Open form",
        },
      ],
    },
    {
      status: "complete",
      totals: { changed: 1, repaired: 1, failed: 0 },
      repairs: [
        {
          key: "long-repair-key",
          message: "Removed invalid schema data",
          url: "/forms/repairable-form",
          link_label: "Open form",
        },
      ],
      errors: [],
    },
  ],
};

settings._renderMigrationStatus({
  status: "current",
  current_version: "0.3",
  cache_refresh_allowed: true,
  counts: { complete: 1, total: 1 },
  migrations: [completed],
});
if (title.textContent !== "Site updates are current") {
  throw new Error(`Unexpected current title: ${title.textContent}`);
}
if (!updateButton.disabled || cacheButton.disabled) {
  throw new Error("Current state did not gate maintenance buttons correctly");
}
const completedRelease = results.children[0].children[0];
if (completedRelease.open || completedRelease.children[0].textContent !== "Version 0.1 — 1/1 completed") {
  throw new Error("Completed release history was not rendered collapsed");
}
const completion = completedRelease.children[1].children[0].children[0];
if (!completion.textContent.includes("version 0.1, build old-build")) {
  throw new Error(`Completion build was not retained: ${completion.textContent}`);
}
const repairLink = repairs.children[0].children[0];
if (repairLink?.href !== "/forms/repairable-form" || repairLink?.textContent !== "Open form") {
  throw new Error("Repair detail did not link to the affected form");
}
if (repairs.children[0].textContent.includes("long-repair-key")) {
  throw new Error("Linked repair detail exposed the raw Datastore key");
}
if (errors.childElementCount) {
  throw new Error("Resolved errors from an older attempt remained actionable");
}

const pending = {
  id: "NEXT-001",
  sequence: 2,
  introduced_in: "0.3",
  label: "Next durable update",
  state: "pending",
  attempts: [],
};
settings._renderMigrationStatus({
  status: "pending",
  current_version: "0.3",
  cache_refresh_allowed: false,
  counts: { complete: 1, pending: 1, failed: 0, interrupted: 0, blocked: 0 },
  migrations: [completed, pending],
});
if (title.textContent !== "Site updates are ready" || summary.textContent !== "Version 0.3. 1 pending, 1 previously completed.") {
  throw new Error(`Unexpected pending state: ${title.textContent} / ${summary.textContent}`);
}
if (updateButton.disabled || !cacheButton.disabled || results.childElementCount !== 2) {
  throw new Error("Pending state did not expose ordered releases or gate cache refresh");
}
if (!results.children[1].children[0].open) {
  throw new Error("Pending release group was not expanded");
}

const failed = {
  ...pending,
  state: "failed",
  attempts: [
    {
      status: "failed",
      totals: { changed: 0, repaired: 0, failed: 1 },
      repairs: [],
      errors: [
        {
          key: "long-error-key",
          message: "schema is not valid JSON",
          url: "/forms/unreadable-form",
          link_label: "Open form",
        },
      ],
    },
  ],
};
settings._renderMigrationStatus({
  status: "failed",
  current_version: "0.3",
  cache_refresh_allowed: false,
  counts: { complete: 1, failed: 1, interrupted: 0, blocked: 1, pending: 0 },
  migrations: [completed, failed, { ...pending, id: "LAST-001", sequence: 3, state: "blocked" }],
});
if (title.textContent !== "Site updates need attention" || updateButton.disabled || !cacheButton.disabled) {
  throw new Error("Failed state was not retryable while cache remained gated");
}
const errorLink = errors.children[0].children[0];
if (errorLink?.href !== "/forms/unreadable-form" || errorLink?.textContent !== "Open form") {
  throw new Error("Failure detail did not link to the affected form");
}

settings._renderMigrationStatus({
  status: "running",
  current_version: "0.3",
  cache_refresh_allowed: false,
  counts: { running: 1 },
  migrations: [{ ...pending, state: "running" }],
});
if (title.textContent !== "Site updates are running" || !updateButton.disabled) {
  throw new Error("Running state did not prevent a concurrent update");
}

settings._renderMigrationStatus({
  status: "audit-error",
  current_version: "0.3",
  cache_refresh_allowed: false,
  counts: { audit_error: 1 },
  migrations: [{ ...pending, state: "audit-error", audit_error: "Stored sequence does not match" }],
});
if (title.textContent !== "Site update history needs repair" || !updateButton.disabled || errors.childElementCount !== 1) {
  throw new Error("Audit error state was not rendered as a blocking repair");
}
"""
    )
