"""Node-backed checks for Core background startup readiness."""

from pathlib import Path


# @pair startup:interaction-ready
# @pair startup:deferred-services
# @pair startup:single-flight
# @pair startup:destroy-safety
# @pair startup:performance-marks
# @pair forms:submit-interception
def test_shell_intercepts_interactions_before_deferred_services(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const marks = [];
const windowListeners = new Map();
const documentListeners = new Map();

const context = {
  console,
  clearTimeout,
  CustomEvent: class {
    constructor(type, options) { this.type = type; this.detail = options?.detail; }
  },
  connectivity: { online: true, hidden: false },
  document: {
    hidden: false,
    addEventListener(type, listener) { documentListeners.set(type, listener); },
    querySelector(selector) {
      if (selector === "meta[name='mode']") {
        return { getAttribute() { return "public"; } };
      }
      return null;
    },
    removeEventListener(type) { documentListeners.delete(type); },
  },
  performance: {
    getEntriesByName(name) { return marks.includes(name) ? [{}] : []; },
    mark(name) { marks.push(name); },
  },
  queueMicrotask,
  setTimeout,
  URLSearchParams,
  window: {
    addEventListener(type, listener) { windowListeners.set(type, listener); },
    location: { search: "" },
    matchMedia() {
      return {
        addEventListener() {},
        matches: false,
        removeEventListener() {},
      };
    },
    removeEventListener(type) { windowListeners.delete(type); },
  },
};
context.globalThis = context;
vm.createContext(context);

let source = fs.readFileSync("src/script/views/base/shell.mjs", "utf8");
source = source.replace(
  'import { connectivity } from "../../shared/connectivity";',
  "",
);
source = source.replaceAll("export const ", "const ");
source = source.replace("export default class ShellView", "class ShellView");
source += "\nglobalThis.ShellView = ShellView;";
vm.runInContext(source, context);

const createRoot = () => {
  const listeners = new Map();
  const attributes = new Map();
  return {
    attributes,
    dataset: { kind: "manual" },
    isConnected: true,
    listeners,
    addEventListener(type, listener) { listeners.set(type, listener); },
    dispatchEvent() {},
    removeEventListener(type) { listeners.delete(type); },
    setAttribute(name, value) { attributes.set(name, value); },
  };
};

const createSubmit = (form, submitter) => ({
  defaultPrevented: false,
  submitter,
  target: form,
  preventDefault() { this.defaultPrevented = true; },
  stopPropagation() { this.stopped = true; },
});

(async () => {
  const root = createRoot();
  const view = new context.ShellView(root);
  let clicks = 0;
  view._click = () => { clicks += 1; };
  let resolveManager;
  let managerLoads = 0;
  let submits = 0;
  const managerReady = new Promise((resolve) => { resolveManager = resolve; });
  view.ensureSubmissionManager = () => {
    managerLoads += 1;
    return managerReady;
  };

  await view.init();
  if (root.dataset.interactive !== "true") {
    throw new Error("The shell did not publish synchronous interaction readiness");
  }
  root.listeners.get("click")({});
  if (clicks !== 1 || marks.join(",") !== "lagniappe:interaction-ready") {
    throw new Error(`Click readiness or first mark was late: ${marks}`);
  }

  const form = {
    dataset: {},
    isConnected: true,
    closest(selector) { return selector === "[lp-component]" ? this : null; },
    removeAttribute() {},
    setAttribute() {},
  };
  const submitter = {
    dataset: {},
    disabled: false,
    removeAttribute(name) { if (name === "aria-busy") this.busy = false; },
    setAttribute(name) { if (name === "aria-busy") this.busy = true; },
  };
  const first = createSubmit(form, submitter);
  const second = createSubmit(form, submitter);
  root.listeners.get("submit")(first);
  root.listeners.get("submit")(second);
  if (!first.defaultPrevented || !second.defaultPrevented || !submitter.busy) {
    throw new Error("Cold submits were not synchronously intercepted");
  }
  await Promise.resolve();
  if (managerLoads !== 1) throw new Error("Cold manager loading was not single-flight");

  resolveManager({ submit() { submits += 1; } });
  await view._coldActions.get(form);
  if (submits !== 1 || submitter.busy || submitter.dataset.loading) {
    throw new Error("The intended action was not replayed with clean busy state");
  }

  view.publish();
  await Promise.resolve();
  if (root._lp_view !== view || !root.attributes.has("initialized")) {
    throw new Error("The shell published before concrete initialization");
  }
  if (marks.join(",") !== [
    "lagniappe:interaction-ready",
    "lagniappe:view-ready",
    "lagniappe:services-ready",
  ].join(",")) {
    throw new Error(`Readiness marks were out of order: ${marks}`);
  }

  const destroyedRoot = createRoot();
  const destroyed = new context.ShellView(destroyedRoot);
  let resolveDestroyedManager;
  let destroyedSubmits = 0;
  destroyed.ensureSubmissionManager = () => new Promise((resolve) => {
    resolveDestroyedManager = resolve;
  });
  await destroyed.init();
  const destroyedForm = {
    dataset: {},
    isConnected: true,
    closest() { return this; },
    removeAttribute() {},
    setAttribute() {},
  };
  destroyedRoot.listeners.get("submit")(createSubmit(destroyedForm, null));
  await Promise.resolve();
  destroyed.destroy();
  resolveDestroyedManager({ submit() { destroyedSubmits += 1; } });
  await Promise.resolve();
  await Promise.resolve();
  if (destroyedSubmits !== 0 || destroyedRoot.listeners.size !== 0) {
    throw new Error("Destroying during a cold load left active behavior");
  }

  const retryRoot = createRoot();
  const retryView = new context.ShellView(retryRoot);
  let attempts = 0;
  let retrySubmits = 0;
  retryView.reportStartupError = () => {};
  retryView.ensureSubmissionManager = async () => {
    attempts += 1;
    if (attempts === 1) throw new Error("chunk unavailable");
    return { submit() { retrySubmits += 1; } };
  };
  await retryView.init();
  const retryForm = {
    dataset: {},
    isConnected: true,
    closest() { return this; },
    removeAttribute() {},
    setAttribute() {},
  };
  const retryButton = {
    dataset: {},
    disabled: false,
    removeAttribute() {},
    setAttribute() {},
  };
  retryRoot.listeners.get("submit")(createSubmit(retryForm, retryButton));
  await retryView._coldActions.get(retryForm);
  if (retryButton.disabled || retryButton.dataset.loading) {
    throw new Error("A failed chunk left the control non-retryable");
  }
  retryRoot.listeners.get("submit")(createSubmit(retryForm, retryButton));
  await retryView._coldActions.get(retryForm);
  if (attempts !== 2 || retrySubmits !== 1) {
    throw new Error("A failed cold action did not retry successfully");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @pair startup:first-interaction
# @pair startup:single-flight
# @pair search:navbar-results
def test_lazy_search_replays_the_latest_live_input_after_loading(run_node):
    core_source = Path("src/script/views/base/core.mjs").read_text()
    assert "(box) => this._activateSearchBox(box)" in core_source
    assert "search.value" not in core_source

    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const documentListeners = new Map();
const context = {
  console,
  clearTimeout,
  connectivity: { online: true, hidden: false },
  CustomEvent: class {},
  document: {
    hidden: false,
    addEventListener(type, listener) { documentListeners.set(type, listener); },
    querySelector(selector) {
      if (selector === "meta[name='mode']") {
        return { getAttribute() { return "testing"; } };
      }
      return null;
    },
    removeEventListener(type) { documentListeners.delete(type); },
  },
  performance: { getEntriesByName() { return []; }, mark() {} },
  queueMicrotask,
  setTimeout,
  window: {
    addEventListener() {},
    matchMedia() {
      return {
        addEventListener() {},
        matches: false,
        removeEventListener() {},
      };
    },
    removeEventListener() {},
  },
};
context.globalThis = context;
vm.createContext(context);

let source = fs.readFileSync("src/script/views/base/shell.mjs", "utf8");
source = source.replace(
  'import { connectivity } from "../../shared/connectivity";',
  "",
);
source = source.replaceAll("export const ", "const ");
source = source.replace("export default class ShellView", "class ShellView");
source += "\nglobalThis.ShellView = ShellView;";
vm.runInContext(source, context);

const root = {
  dataset: { kind: "manual" },
  addEventListener() {},
  dispatchEvent() {},
  removeEventListener() {},
  setAttribute() {},
};
const search = {
  dataset: {},
  removeAttribute(name) { delete this[name]; },
  setAttribute(name, value) { this[name] = value; },
};
const input = {
  value: "first query",
  closest(selector) { return selector === "[lp-search]" ? search : null; },
};

(async () => {
  const view = new context.ShellView(root);
  view.hasDeferredServices = true;
  let loadCount = 0;
  let resolveSearch;
  const loaded = new Promise((resolve) => { resolveSearch = resolve; });
  view.ensureSearchBox = () => {
    loadCount += 1;
    return loaded;
  };
  await view.init();

  documentListeners.get("input")({ target: input });
  input.value = "latest query";
  documentListeners.get("input")({ target: input });
  await Promise.resolve();
  if (loadCount !== 1) {
    throw new Error(`Search loading was not single-flight: ${loadCount}`);
  }

  const queries = [];
  resolveSearch({
    element: input,
    _input(event) { queries.push(event.target.value); },
    showPanel() { throw new Error("A populated search opened without replaying"); },
  });
  await view._coldActions.get(search);

  if (queries.length !== 1 || queries[0] !== "latest query") {
    throw new Error(`Search replay did not use the live input: ${queries}`);
  }
  if (search["aria-busy"] || search.dataset.loading) {
    throw new Error("Search replay left stale busy state");
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
'''
    )


# @pair polling:channel
# @pair polling:entity
# @pair polling:refresh
# @pair polling:active-widget
# @pair polling:visibility
# @pair polling:subscription-lifecycle
# @pair polling:nonblocking
# @pair startup:single-flight
# @pair startup:nonblocking
def test_core_polling_subscription_lifecycle(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const context = {
  console,
  document: { querySelector() { return null; } },
  URLSearchParams,
  window: { location: { search: "" } },
};
vm.createContext(context);

let source = fs.readFileSync("src/script/views/base/core.mjs", "utf8");
source = source.replace(
  /^import [\s\S]*?(?=\/\*\*)/,
  `
const connectivity = {};
const ENDPOINTS = {};
const captureError = () => {};
const request = {};
const withTransition = async (callback) => await callback();
const ViewComponent = class {};
const collectRefreshTargets = () => [];
const reconcileChange = () => {};
const refreshCollectionComponents = () => {};
const ensureDeferredOperations = () => {};
const ensureEditWatcher = () => {};
const ensureEntityMenu = () => {};
const ensureModalClasses = () => {};
const ensureNotifications = () => {};
const ensureOfflineModal = () => {};
const ensureOfflineQueue = () => {};
const ensurePollingCoordinator = () => {};
const ensureSearchBox = () => {};
const ensureSubmissionManager = () => {};
const ensureSyncManager = () => {};
const initializeCoreServices = () => {};
const ShellView = class {};
const Task = class {};
`,
);
source = source.replace("export default class Core", "class Core");
source += "\nglobalThis.Core = Core;";
vm.runInContext(source, context);

(async () => {
  const subscriptions = [];
  const polling = {
    subscribe(descriptor, options) { subscriptions.push({ descriptor, options }); },
  };
  let refreshes = 0;
  const collection = Object.create(context.Core.prototype);
  Object.assign(collection, {
    PollingCoordinator: polling,
    elt: {
      dataset: { fingerprint: "pages-v1", index: "pages" },
      querySelector() { return null; },
    },
    kind: "page",
    key: null,
    async refresh() { refreshes += 1; },
  });
  collection._initPollingSubscription();
  const channel = subscriptions[0];
  if (
    channel.descriptor.type !== "channel" ||
    channel.descriptor.channel !== "pages" ||
    channel.descriptor.revision !== "pages-v1"
  ) {
    throw new Error("The collection polling descriptor changed");
  }
  await channel.options.onResult({ status: "changed" });
  if (refreshes !== 1) throw new Error("Collection polling did not refresh");

  const changes = [];
  const editResults = [];
  const watcher = {
    async receiveEntityResult(key, result) {
      editResults.push(`${key}:${result.status}`);
    },
  };
  const entity = Object.create(context.Core.prototype);
  Object.assign(entity, {
    PollingCoordinator: polling,
    elt: {
      dataset: { fingerprint: "entity-v1" },
      querySelector() { return {}; },
    },
    key: "entity-key",
    ensureEditWatcher: async () => watcher,
    async reconcileChange(change) { changes.push(change); },
  });
  entity._initPollingSubscription();
  const entitySubscription = subscriptions[1];
  await entitySubscription.options.onResult({ status: "changed" });
  await entitySubscription.options.onResult({ status: "unavailable" });
  if (
    changes.map(({ type }) => type).join(",") !== "entity-poll,delete" ||
    editResults.join(",") !== "entity-key:changed,entity-key:unavailable"
  ) {
    throw new Error("Entity polling reconciliation changed");
  }

  const lifecycleEvents = [];
  const lifecycle = Object.create(context.Core.prototype);
  Object.assign(lifecycle, {
    _destroyed: false,
    hidden: false,
    online: true,
    EditWatcher: {
      async reconcileSubscriptions() { lifecycleEvents.push("forms"); },
    },
    SyncManager: {
      async reconcileSubscriptions() { lifecycleEvents.push("documents"); },
    },
    components: {
      active: {
        widgets: {
          ingress: {
            async syncPollingSubscription() { lifecycleEvents.push("ingress"); },
          },
        },
      },
    },
  });
  await lifecycle.reconcilePollingSubscriptions();
  lifecycle.hidden = true;
  await lifecycle.reconcilePollingSubscriptions();
  if (lifecycleEvents.join(",") !== "forms,documents,ingress") {
    throw new Error(`Polling ownership changed: ${lifecycleEvents}`);
  }

  let resolveFirstPass;
  let passes = 0;
  let activePasses = 0;
  let maximumActivePasses = 0;
  const firstPass = new Promise((resolve) => { resolveFirstPass = resolve; });
  const scheduled = Object.create(context.Core.prototype);
  Object.assign(scheduled, {
    _destroyed: false,
    hidden: false,
    online: true,
    _pollingReconcileRequested: false,
    _pollingReconcileTask: null,
    elt: {},
    reportStartupError(error) { throw error; },
    async reconcilePollingSubscriptions() {
      passes += 1;
      activePasses += 1;
      maximumActivePasses = Math.max(maximumActivePasses, activePasses);
      if (passes === 1) await firstPass;
      activePasses -= 1;
    },
  });
  const scheduledFirst = scheduled.schedulePollingReconciliation();
  await Promise.resolve();
  await Promise.resolve();
  const scheduledSecond = scheduled.schedulePollingReconciliation();
  if (scheduledFirst !== scheduledSecond || passes !== 1) {
    throw new Error("Subscription reconciliation was not single-flight");
  }
  resolveFirstPass();
  await scheduledFirst;
  if (passes !== 2 || maximumActivePasses !== 1) {
    throw new Error(`Subscription passes overlapped or were lost: ${passes}/${maximumActivePasses}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @pair polling:blur
# @pair polling:visibility
# @pair sync:deregistration
def test_core_sync_distinguishes_visible_blur_from_hard_suspension(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const context = {
  console,
  connectivity: { online: true },
  document: { hidden: false },
  URLSearchParams,
  window: { location: { search: "" } },
};
vm.createContext(context);

let source = fs.readFileSync("src/script/views/base/core.mjs", "utf8");
source = source.replace(
  /^import [\s\S]*?(?=\/\*\*)/,
  `
const connectivity = globalThis.connectivity;
const ENDPOINTS = {};
const captureError = () => {};
const request = {};
const withTransition = async (callback) => await callback();
const ViewComponent = class {};
const collectRefreshTargets = () => [];
const reconcileChange = () => {};
const refreshCollectionComponents = () => {};
const ensureDeferredOperations = () => {};
const ensureEditWatcher = () => {};
const ensureEntityMenu = () => {};
const ensureModalClasses = () => {};
const ensureNotifications = () => {};
const ensureOfflineModal = () => {};
const ensureOfflineQueue = () => {};
const ensurePollingCoordinator = () => {};
const ensureSearchBox = () => {};
const ensureSubmissionManager = () => {};
const ensureSyncManager = () => {};
const initializeCoreServices = () => {};
const ShellView = class {};
const Task = class {};
`,
);
source = source.replace("export default class Core", "class Core");
source += "\nglobalThis.Core = Core;";
vm.runInContext(source, context);

const events = [];
const blurStarts = [];
const view = Object.create(context.Core.prototype);
Object.assign(view, {
  hidden: false,
  blurred: false,
  online: true,
  connectivityGeneration: 0,
  EditWatcher: { pause() { events.push("forms:pause"); } },
  PollingCoordinator: {
    blur(startedAt) {
      blurStarts.push(startedAt);
      events.push("polling:blur");
    },
    pause() { events.push("polling:pause"); },
  },
  SyncManager: {
    async deregister() { events.push("documents:deregister"); },
  },
});
Object.defineProperty(view, "offline", {
  configurable: true,
  writable: true,
  value: false,
});

(async () => {
  await view.sync({ hidden: true, blurred: true, blurredAt: 42 });
  const startedAt = view.blurredAt;
  if (
    events.join(",") !== "forms:pause,polling:blur,documents:deregister" ||
    view.blurred !== true ||
    blurStarts[0] !== startedAt ||
    startedAt !== 42
  ) {
    throw new Error(`Visible blur did not retain narrow polling: ${events}`);
  }

  await view.sync({ hidden: true, blurred: true, blurredAt: 99 });
  if (events.length !== 3 || view.blurredAt !== startedAt) {
    throw new Error("Duplicate visible blur restarted the lifecycle window");
  }

  await view.sync({ hidden: true, blurred: false });
  if (
    events.slice(3).join(",") !==
      "forms:pause,polling:pause,documents:deregister" ||
    view.blurred !== false ||
    view.blurredAt !== null
  ) {
    throw new Error(`Hard suspension retained visible-blur polling: ${events}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @pair startup:deferred-services
# @pair startup:component-render
# @pair startup:nonblocking
# @pair polling:subscription-lifecycle
# @pair polling:component-render
# @pair polling:nonblocking
def test_component_render_does_not_wait_for_polling_reconciliation(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const context = {
  console,
  CustomEvent: class {},
  document: { getElementById() { return null; } },
};
vm.createContext(context);

let source = fs.readFileSync("src/script/views/base/component.mjs", "utf8");
source = source.replace(
  /^import [\s\S]*?(?=\/\*\*)/,
  `
const NavElement = class {};
const showBriefly = () => {};
const withTransition = async (callback) => await callback();
const loadWidget = async () => null;
`,
);
source = source.replace("export default class ViewComponent", "class ViewComponent");
source += "\nglobalThis.ViewComponent = ViewComponent;";
vm.runInContext(source, context);

(async () => {
  let scheduled = 0;
  let reconciled = 0;
  const neverSettles = new Promise(() => {});
  const component = Object.create(context.ViewComponent.prototype);
  Object.assign(component, {
    active: null,
    _nav: null,
    elt: {
      dataset: {},
      querySelector() { return null; },
    },
    name: "info",
    view: {
      schedulePollingReconciliation() {
        scheduled += 1;
        return neverSettles;
      },
    },
    widgets: {
      info: {
        async reconcile() { reconciled += 1; },
      },
    },
    _setParentComponent() {},
  });

  const outcome = component.render(true);
  if (outcome !== undefined || reconciled !== 1 || scheduled !== 1) {
    throw new Error("Component rendering waited for background subscription work");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @pair forms:queue-independent-initial-render
def test_offline_queue_does_not_block_initial_form_render(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const context = { console };
vm.createContext(context);

let source = fs.readFileSync("src/script/elements/form.mjs", "utf8");
source = source.replace('import { withTransition } from "../shared";\n', "");
source = source.replace(
  'import { BaseForm } from "./base/baseForm";',
  "const BaseForm = class {};",
);
source = source.replace("export class FormElement", "class FormElement");
source += "\nglobalThis.FormElement = FormElement;";
vm.runInContext(source, context);

(async () => {
  let initialized = false;
  let renderCalls = 0;
  const initialReplayReady = new Promise(() => {});
  const target = {
    cloneNode() { return {}; },
    setAttribute(name) {
      if (name === "initialized") initialized = true;
    },
  };
  const form = new context.FormElement({
    target,
    view: { initialReplayReady },
    readonly: false,
  });
  form._initForm = async () => { renderCalls += 1; };
  form.commitRevisionBaseline = () => {};

  const outcome = await Promise.race([
    form.init().then(() => "rendered"),
    new Promise((resolve) => setTimeout(() => resolve("blocked"), 50)),
  ]);
  if (outcome !== "rendered" || !initialized || renderCalls !== 1) {
    throw new Error("Offline queue readiness blocked the initial form render");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


def test_page_layout_is_visible_in_server_template():
    template = Path("lagniappe/web/templates/pages/page.html").read_text()
    layout = template.split('<div id="layout"', 1)[1].split(">", 1)[0]
    info_template = Path("lagniappe/web/templates/pages/info.html").read_text()
    info_prefix, info_suffix = info_template.split('data-widget="PageInfo"', 1)
    info_form = info_prefix.rsplit("<form", 1)[1] + info_suffix.split(">", 1)[0]

    assert 'data-visible="false"' not in layout
    assert 'data-visible="false"' not in info_form


def test_initial_replay_is_scheduled_after_view_readiness():
    services = Path("src/script/views/base/services.mjs").read_text()
    core = Path("src/script/views/base/core.mjs").read_text()
    load_body = core.split("\tasync load(component, route) {", 1)[1].split(
        "\n\t/**", 1
    )[0]

    assert "const start = view._publishedReady.then(() => view)" in services
    assert "afterFirstPaint" not in services
    assert "view.initialReplayReady = view.offlineQueueReady.then" in services
    assert "inspectOfflineWork(view)" in services
    assert "view.prefetch()" in services
    assert "offlineQueueReady.then(() => view.prefetch())" not in services
    assert "offlineQueue" not in load_body
    assert "ensureOfflineQueue" not in load_body


# @pair sync:editor-readiness
# @pair sync:loader-free
# @pair sync:state-only
def test_collaborative_document_renders_before_initial_state(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

let resolveSync;
let loaderAppends = 0;
const loadedAttributes = [];
const syncReady = new Promise((resolve) => { resolveSync = resolve; });
const context = {
  console,
  document: {
    createElement() {
      return {
        dataset: {},
        className: "",
        classList: { add() {} },
        appendChild() { loaderAppends += 1; },
        setAttribute(name) { loadedAttributes.push(name); },
      };
    },
  },
};
vm.createContext(context);

let source = fs.readFileSync("src/script/elements/editor/collaborative.mjs", "utf8");
source = source.replace(
  /^import [\s\S]*?(?=\/\*\*)/,
  `
const STYLES = { editor: { container: "editor-container" } };
const Y = { Doc: class {} };
const base64ToUint8Array = () => null;
const uint8ArrayToBase64 = () => "";
const waitForAttribute = async () => {};
const collaborativeEditor = () => null;
const Toolbar = class {};
`,
);
source = source.replace(
  "export class CollaborativeDocument",
  "class CollaborativeDocument",
);
source += "\nglobalThis.CollaborativeDocument = CollaborativeDocument;";
vm.runInContext(source, context);

(async () => {
  let stateCalls = 0;
  const shellCalls = [];
  const documentWidget = Object.create(context.CollaborativeDocument.prototype);
  Object.assign(documentWidget, {
    headless: false,
    remote: null,
    syncId: "page-1:document",
    view: { syncReady },
    target: {
      replaceChildren(container) {
        shellCalls.push("container");
        this.container = container;
      },
    },
    _initEditor() { shellCalls.push("editor"); },
    _initToolbar() { shellCalls.push("toolbar"); },
  });

  const result = documentWidget.init();
  if (result !== undefined) {
    throw new Error("Document shell initialization unexpectedly became async");
  }
  if (shellCalls.join(",") !== "container,editor,toolbar") {
    throw new Error(`Document shell did not render synchronously: ${shellCalls}`);
  }
  if (loaderAppends !== 0) {
    throw new Error("Document shell rendered a visible loading placeholder");
  }

  let stateSettled = false;
  documentWidget.initialStateReady.then(() => { stateSettled = true; });
  await Promise.resolve();
  if (stateCalls !== 0 || stateSettled || loadedAttributes.includes("loaded")) {
    throw new Error("Document requested state before SyncManager was ready");
  }

  resolveSync({
    async state(widget) {
      stateCalls += 1;
      if (widget !== documentWidget) throw new Error("Wrong document widget");
      return { fingerprint: "remote-fingerprint" };
    },
  });
  await documentWidget.initialStateReady;

  if (
    stateCalls !== 1 ||
    documentWidget.remote?.fingerprint !== "remote-fingerprint" ||
    !loadedAttributes.includes("loaded")
  ) {
    throw new Error("Document did not fetch initial state from the ready manager");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features sync editor
# @dimensions initialization empty-content save-guard
# @pair sync:initialization
# @pair sync:empty-content
# @pair sync:save-guard
# @pair sync:intentional-clear
# @pair sync:checkpoint
# @pair sync:dirty-state
# @pair sync:concurrent-edit
# @pair sync:response-contract
# @pair editor:initialization
# @pair editor:empty-content
# @pair editor:save-guard
def test_collaborative_document_does_not_save_untouched_empty_state(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const context = { console };
vm.createContext(context);

let source = fs.readFileSync("src/script/elements/editor/collaborative.mjs", "utf8");
source = source.replace(
  /^import [\s\S]*?(?=\/\*\*)/,
  `
const STYLES = {};
const Y = { Doc: class {} };
const base64ToUint8Array = () => null;
const uint8ArrayToBase64 = () => "";
const waitForAttribute = async () => {};
const primitives = {};
const collaborativeEditor = () => globalThis.editorStub;
const Toolbar = class {};
`,
);
source = source.replace(
  "export class CollaborativeDocument",
  "class CollaborativeDocument",
);
source += "\nglobalThis.CollaborativeDocument = CollaborativeDocument;";

let editorHandler;
let ydocUpdateHandler;
context.editorStub = {
  on(name, handler) {
    if (name === "create") editorHandler = handler;
  },
  getHTML() { return "<p></p>"; },
};
vm.runInContext(source, context);

const documentWidget = Object.create(context.CollaborativeDocument.prototype);
Object.assign(documentWidget, {
  initialized: false,
  _dirty: false,
  _applyingRemote: false,
  updateQueue: [],
  snapshot: null,
  container: {},
  editor: null,
  target: { dataset: {} },
  ydoc: {
    on(name, handler) {
      if (name === "update") ydocUpdateHandler = handler;
    },
  },
  _packageState() { return this.currentState; },
  _packageUpdates() {
    this.updateQueue.length = 0;
    return "user-update";
  },
  currentState: "fresh-empty-state",
});

documentWidget._initEditor();
if (!editorHandler || !ydocUpdateHandler) {
  throw new Error("Collaborative editor lifecycle handlers were not installed");
}

ydocUpdateHandler("setup-update", "local");
if (documentWidget._dirty) {
  throw new Error("Editor setup transaction was classified as a user edit");
}
documentWidget._commitInitialBaseline();
documentWidget.initialized = true;

documentWidget.currentState = "current-document-state";
documentWidget.updateQueue.push("pending-user-update");
const syncPayload = documentWidget.syncData;
if (
  syncPayload?.update !== "user-update" ||
  syncPayload?.ydoc !== "current-document-state" ||
  documentWidget.updateQueue.length !== 0
) {
  throw new Error("Document sync payload did not package its delta and checkpoint");
}

if (documentWidget.saveData !== null) {
  throw new Error("Untouched fresh document produced an eager save payload");
}

documentWidget.snapshot = "existing-content-state";
documentWidget.currentState = "intentionally-cleared-state";
ydocUpdateHandler("clear-update", "local");
const clearPayload = documentWidget.saveData;
if (
  clearPayload?.html !== "" ||
  clearPayload?.ydoc !== "intentionally-cleared-state" ||
  clearPayload?.update !== "user-update"
) {
  throw new Error("Intentional clearing did not remain saveable");
}

documentWidget.commitSavedBaseline(clearPayload.ydoc);
documentWidget.currentState = "remote-only-state";
if (documentWidget._dirty || documentWidget.saveData !== null) {
  throw new Error("Persisted or remote-only state remained locally dirty");
}

ydocUpdateHandler("later-user-update", "local");
if (documentWidget.saveData === null) {
  throw new Error("A later user edit was lost after committing the save baseline");
}
'''
    )
