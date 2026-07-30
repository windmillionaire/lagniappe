"""Node-backed checks for Core background startup readiness."""


# @pair startup:queue-hydration
# @pair startup:polling
# @pair offline:background-replay
# @pair polling:channel
# @pair polling:entity
# @pair polling:refresh
# @pair polling:startup
# @pair polling:active-widget
# @pair polling:visibility
# @pair polling:subscription-lifecycle
# @pair sync:editor-readiness
def test_core_init_starts_polling_without_waiting_for_initial_replay(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const events = [];
let resolveQueueInit;
let resolveReplay;
const queueInit = new Promise((resolve) => { resolveQueueInit = resolve; });
const replay = new Promise((resolve) => { resolveReplay = resolve; });

const context = {
  console,
  CustomEvent: class {
    constructor(type, options) { this.type = type; this.detail = options?.detail; }
  },
  document: {
    hidden: false,
    querySelector() { return null; },
  },
  events,
  queueInit,
  replay,
  URLSearchParams,
  window: {
    __TESTING__: false,
    addEventListener() {},
    location: { search: "" },
    matchMedia() {
      return { addEventListener() {}, matches: false };
    },
    removeEventListener() {},
  },
};
vm.createContext(context);

let source = fs.readFileSync("src/script/views/base/core.mjs", "utf8");
source = source.replace(
  /^import [\s\S]*?(?=const COLLECTION_ONLY_CHANGE_TYPES)/,
  `
const SearchBox = class {};
const EntityMenu = class { destroy() {} };
const Notifications = class { init() {} };
const captureError = (error) => events.push(["error", error.message]);
const clearRecentSearchResults = () => {};
const connectivity = { online: true, hidden: false };
const DeferredOperationManager = class {
  init() { return this; }
  destroy() {}
};
const DeleteModal = class {};
const EditWatcher = class {
  init() {}
  destroy() {}
};
const ENDPOINTS = {};
const HelpModal = class {};
const OfflineQueue = class {
  async init() {
    events.push("queue-init");
    await queueInit;
    events.push("queue-ready");
  }
  async replay() {
    events.push("replay-started");
    return await replay;
  }
};
const OfflineModal = class { enable() {} };
const PollingCoordinator = class {
  constructor() { events.push("polling-created"); }
  init() { events.push("polling-init"); return this; }
  subscribe(descriptor, options) {
    events.push(["subscription", descriptor, options]);
  }
  destroy() {}
};
const request = {};
const SyncManager = class {
  init() { events.push("sync-init"); }
  destroy() {}
};
const withTransition = async (callback) => await callback();
const ViewComponent = class {};
const SubmissionManager = class {
  constructor() { this.submit = () => {}; }
  destroy() {}
};
const Task = class {};
`,
);
source = source.replace("export default class Core", "class Core");
source += "\nglobalThis.Core = Core;";
vm.runInContext(source, context);

const attributes = new Set();
const root = {
  dataset: { fingerprint: "pages-v1", index: "pages", kind: "page" },
  addEventListener() {},
  dispatchEvent() {},
  querySelector() { return {}; },
  querySelectorAll() { return []; },
  removeEventListener() {},
  setAttribute(name) { attributes.add(name); },
};

(async () => {
  const view = new context.Core(root);
  view.refresh = async () => { events.push("refresh"); };
  let replayReadyAtPrefetch = null;
  view.prefetch = () => {
    replayReadyAtPrefetch = view.initialReplayReady;
  };
  let initialized = false;
  const initPromise = view.init().then(() => { initialized = true; });

  await Promise.resolve();
  if (initialized || !events.includes("queue-init")) {
    throw new Error("Core did not wait only for offline queue hydration");
  }

  resolveQueueInit();
  await initPromise;
  await Promise.resolve();

  if (!attributes.has("initialized") || root._lp_view !== view) {
    throw new Error("Core did not publish itself after queue hydration");
  }
  if (!view.SyncManager || !events.includes("sync-init")) {
    throw new Error("Core did not initialize sync during startup");
  }
  if (!view.PollingCoordinator || !events.includes("polling-init")) {
    throw new Error("Core did not initialize the polling coordinator");
  }
  if (!events.includes("replay-started")) {
    throw new Error("Initial replay was not scheduled in the background");
  }
  if (replayReadyAtPrefetch !== view.initialReplayReady) {
    throw new Error("Prefetch started before replay readiness was installed");
  }

  const manager = await view.syncReady;
  if (manager !== view.SyncManager) {
    throw new Error("Sync readiness did not resolve to the initialized manager");
  }

  resolveReplay(1);
  await view._initialReplayTask;
  if (events.filter((event) => event === "refresh").length !== 1) {
    throw new Error("Successful background replay did not refresh once");
  }

  const channelSubscription = events.find(
    (event) => Array.isArray(event) && event[0] === "subscription"
      && event[1]?.type === "channel",
  );
  if (
    channelSubscription?.[1]?.channel !== "pages"
    || channelSubscription[1].revision !== "pages-v1"
  ) {
    throw new Error("Core did not install its collection polling subscription");
  }
  await channelSubscription[2].onResult({ status: "changed" });
  if (events.filter((event) => event === "refresh").length !== 2) {
    throw new Error("Changed collection polling result did not refresh the view");
  }

  const reconciled = [];
  const editResults = [];
  const entityView = Object.create(context.Core.prototype);
  Object.assign(entityView, {
    PollingCoordinator: view.PollingCoordinator,
    EditWatcher: {
      async receiveEntityResult(key, result) {
        editResults.push([key, result.status]);
      },
    },
    elt: { dataset: { fingerprint: "entity-v1" } },
    key: "entity-key",
    async reconcileChange(change) { reconciled.push(change); },
  });
  entityView._initPollingSubscription();
  const entitySubscription = events.find(
    (event) => Array.isArray(event) && event[0] === "subscription"
      && event[1]?.type === "entity",
  );
  if (
    entitySubscription?.[1]?.key !== "entity-key"
    || entitySubscription[1].revision !== "entity-v1"
  ) {
    throw new Error("Core did not install its entity polling subscription");
  }
  await entitySubscription[2].onResult({
    status: "changed",
    payload: { fingerprint: "entity-v2" },
  });
  await entitySubscription[2].onResult({ status: "unavailable" });
  if (
    reconciled.length !== 2
    || reconciled[0].type !== "entity-poll"
    || reconciled[1].type !== "delete"
    || editResults.map((entry) => entry.join(":")).join(",") !==
      "entity-key:changed,entity-key:unavailable"
  ) {
    throw new Error("Entity polling results were not reconciled");
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
  if (lifecycleEvents.join(",") !== "forms,documents,ingress") {
    throw new Error(
      `Widget polling ownership was not reconciled: ${lifecycleEvents}`,
    );
  }
  lifecycle.hidden = true;
  await lifecycle.reconcilePollingSubscriptions();
  if (lifecycleEvents.length !== 3) {
    throw new Error("Inactive view reconciled widget subscriptions");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @pair offline:background-replay
# @pair forms:queued-restore
def test_offline_form_restore_waits_for_initial_replay(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

let resolveReplay;
const initialReplayReady = new Promise((resolve) => { resolveReplay = resolve; });
const context = { console };
vm.createContext(context);

let source = fs.readFileSync("src/script/elements/form.mjs", "utf8");
source = source.replace(
  'import { BaseForm } from "./base/baseForm";',
  "const BaseForm = class {};",
);
source = source.replace("export class FormElement", "class FormElement");
source += "\nglobalThis.FormElement = FormElement;";
vm.runInContext(source, context);

(async () => {
  const target = {
    cloneNode() { return {}; },
    hasAttribute(name) { return name === "lp-offline"; },
  };
  const form = new context.FormElement({
    target,
    view: { initialReplayReady },
    readonly: false,
  });
  let queueReads = 0;
  form._queuedMutation = () => {
    queueReads += 1;
    return null;
  };

  const restoring = form._restoreQueuedForm();
  await Promise.resolve();
  if (queueReads !== 0) {
    throw new Error("Form inspected queued state before initial replay settled");
  }

  resolveReplay(0);
  const restored = await restoring;
  if (restored !== false || queueReads !== 1) {
    throw new Error("Form did not inspect the settled queue exactly once");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @pair sync:editor-readiness
# @pair sync:state-only
def test_collaborative_document_waits_for_sync_manager_before_state(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

let resolveSync;
const syncReady = new Promise((resolve) => { resolveSync = resolve; });
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
  const documentWidget = Object.create(context.CollaborativeDocument.prototype);
  Object.assign(documentWidget, {
    headless: false,
    remote: null,
    syncId: "page-1:document",
    view: { syncReady },
    _initContainer() {
      this.container = { setAttribute() {} };
    },
    _initEditor() {},
    _initToolbar() {},
  });

  const initializing = documentWidget.init();
  await Promise.resolve();
  if (stateCalls !== 0) {
    throw new Error("Document requested state before SyncManager was ready");
  }

  resolveSync({
    async state(widget) {
      stateCalls += 1;
      if (widget !== documentWidget) throw new Error("Wrong document widget");
      return { fingerprint: "remote-fingerprint" };
    },
  });
  await initializing;

  if (stateCalls !== 1 || documentWidget.remote?.fingerprint !== "remote-fingerprint") {
    throw new Error("Document did not fetch initial state from the ready manager");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )
