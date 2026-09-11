"""Node-backed checks for batched Core refresh orchestration."""


# @matrix polling tasks : channel refresh
def test_page_task_collection_watches_task_form_changes(run_node):
    run_node(r'''
const fs = require("node:fs");
const vm = require("node:vm");
const context = { console };
vm.createContext(context);
let source = fs.readFileSync("src/script/views/page.mjs", "utf8");
source = source.replace(/^import [\s\S]*?(?=\/\*\*)/, "class Entity { async reconcilePollingSubscriptions() {} }\n");
source = source.replace("export default class Page", "class Page");
source += "\nglobalThis.Page = Page;";
vm.runInContext(source, context);
(async () => {
  const page = new context.Page();
  const list = { name: "PageTaskList", loaded: false };
  const component = { widgets: { list } };
  let subscription, subscriptions = 0, refreshes = 0, unsubscriptions = 0;
  Object.assign(page, {
    key: "page-key", elt: { dataset: { collectionRevision: "known-tasks" } },
    components: { tasks: component },
    PollingCoordinator: { subscribe(descriptor, options) {
      subscriptions += 1;
      subscription = { descriptor, options };
      return () => { unsubscriptions += 1; };
    } },
    async _refreshCollectionComponents(components) {
      if (components.length !== 1 || components[0] !== component) throw new Error("Refreshed unrelated collections");
      refreshes += 1;
    },
  });
  await page.reconcilePollingSubscriptions();
  if (subscriptions) throw new Error("Unloaded task list subscribed");
  list.loaded = true;
  await page.reconcilePollingSubscriptions();
  await page.reconcilePollingSubscriptions();
  if (subscriptions !== 1 || subscription.descriptor.channel !== "tasks" ||
      subscription.descriptor.revision !== "known-tasks" || subscription.options.mode !== "periodic") {
    throw new Error("Loaded task list did not own one periodic Tasks subscription");
  }
  await subscription.options.onResult({status: "unchanged"});
  await subscription.options.onResult({status: "changed"});
  if (refreshes !== 1) throw new Error("Task form invalidation did not refresh exactly once");
  list.loaded = false;
  await page.reconcilePollingSubscriptions();
  if (unsubscriptions !== 1) throw new Error("Removed task list retained its subscription");
})().catch(error => { console.error(error); process.exit(1); });
''')


# @matrix reconnect-refresh : manifest
# @source src/script/widgets/tables.mjs::IndexTable.refreshDescriptor
def test_collection_manifests_include_hash_and_fingerprint(run_node):
    run_node(r'''
const fs = require("node:fs");
const vm = require("node:vm");
const context = { console, document: {} };
vm.createContext(context);
for (const [path, base, exported] of [
  ["src/script/widgets/tables.mjs", "class BaseTable {} class EmbeddedTable {}", "IndexTable"],
  ["src/script/widgets/pageTaskList.mjs", "class BaseList {}", "PageTaskList"],
]) {
  let source = fs.readFileSync(path, "utf8").replace(/^import [\s\S]*?(?=\/\*\*)/, base + "\n");
  source = source.replaceAll("export class ", "class ");
  source += `\nglobalThis.${exported} = ${exported};`;
  vm.runInContext(source, context);
  const widget = Object.create(context[exported].prototype);
  Object.assign(widget, {
    component: {name: exported === "IndexTable" ? "table" : "tasks"}, view: {key: "page", elt: {dataset: {}}},
    target: {hasAttribute: () => true, querySelectorAll: () => [{dataset: {
      key: "entity", hash: "hash", fingerprint: "revision", modified: "timestamp"
    }}]},
  });
  const rows = widget.refreshDescriptor().rows;
  if (JSON.stringify(rows) !== '[{"key":"entity","hash":"hash","fingerprint":"revision"}]') {
    throw new Error(`${exported} sent an invalid manifest: ${JSON.stringify(rows)}`);
  }
}
''')


# @matrix form-index : created-row delete-target destination-refresh sorting
def test_index_table_row_updates_rebuild_active_sort(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const context = { console, document: {} };
vm.createContext(context);

let source = fs.readFileSync("src/script/widgets/tables.mjs", "utf8");
source = source.replace(
  'import { BaseTable, EmbeddedTable } from "../elements/base/baseTable";',
  "class BaseTable {} class EmbeddedTable {}",
);
source = source.replaceAll("export class ", "class ");
source += "\nglobalThis.IndexTable = IndexTable;";
vm.runInContext(source, context);

const makeTarget = (rows) => {
  const target = {
    rows,
    hasAttribute(name) {
      return name === "loaded";
    },
    querySelector(selector) {
      if (selector === "tr[data-role='empty']") return null;
      if (selector === "tr[lp-entity]") return this.rows[0] || null;
      const match = selector.match(/^tr\[data-key="([^"]+)"\]$/);
      return match ? this.rows.find((row) => row.dataset.key === match[1]) : null;
    },
    querySelectorAll(selector) {
      return selector === "tr[lp-entity]" ? [...this.rows] : [];
    },
    append(...newRows) {
      for (const row of newRows) {
        this.rows = this.rows.filter((current) => current !== row);
        this.rows.push(row);
      }
    },
    prepend(...newRows) {
      this.rows.unshift(...newRows);
      newRows.forEach((newRow) => attachRow(newRow, this));
    },
  };
  for (const row of rows) attachRow(row, target);
  return target;
};

const attachRow = (row, target) => {
  row.replaceWith = (replacement) => {
    const index = target.rows.indexOf(row);
    if (index !== -1) target.rows.splice(index, 1, replacement);
    attachRow(replacement, target);
  };
  row.remove = () => {
    target.rows = target.rows.filter((current) => current !== row);
  };
  row.before = (...newRows) => {
    const index = target.rows.indexOf(row);
    target.rows.splice(index, 0, ...newRows);
    newRows.forEach((newRow) => attachRow(newRow, target));
  };
};

const row = (key, modified) => ({ dataset: { key, modified } });
const makeTable = (target) => {
  const table = Object.create(context.IndexTable.prototype);
  let refreshCalls = 0;
  Object.assign(table, {
    target,
    loaded: true,
    _created: [],
    _updated: [],
    view: {
      mobile: false,
      addFlash(...rows) {
        rows.forEach((newRow) => attachRow(newRow, target));
      },
    },
    sortingWidget: {
      initialized: true,
      refreshRows() {
        refreshCalls += 1;
        target.rows.sort(
          (a, b) => Number(b.dataset.modified) - Number(a.dataset.modified),
        );
      },
    },
    setEmptyRowVisibility() {},
  });
  return { table, get refreshCalls() { return refreshCalls; } };
};

(async () => {
  const refreshedTarget = makeTarget([row("older", "1")]);
  const refreshed = makeTable(refreshedTarget);
  const refreshedRows = [row("older", "1"), row("newest", "2")];
  await refreshed.table.refresh({
    html: {
      querySelectorAll(selector) {
        return selector === "tr[lp-entity]" ? refreshedRows : [];
      },
    },
  });
  if (refreshed.refreshCalls !== 1) {
    throw new Error(`Full refresh rebuilt sorting ${refreshed.refreshCalls} times`);
  }
  if (refreshedTarget.rows.map((item) => item.dataset.key).join(",") !== "newest,older") {
    throw new Error(`Full refresh lost the active sort: ${refreshedTarget.rows.map((item) => item.dataset.key)}`);
  }

  const reconciledTarget = makeTarget([row("older", "1")]);
  const reconciled = makeTable(reconciledTarget);
  reconciled.table._created = [row("newest", "2")];
  await reconciled.table.postreconcile();
  if (reconciled.refreshCalls !== 1) {
    throw new Error(`Row reconciliation rebuilt sorting ${reconciled.refreshCalls} times`);
  }
  if (reconciledTarget.rows.map((item) => item.dataset.key).join(",") !== "newest,older") {
    throw new Error(`Row reconciliation lost the active sort: ${reconciledTarget.rows.map((item) => item.dataset.key)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @matrix reconnect-refresh : batching cache-invalidation committed-delete delta-apply destination-invalidation fallback legacy-fallback manifest mounted-collection
# @pair polling:reentrancy
def test_core_refresh_batches_supported_widgets_and_falls_back_per_target(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const events = [];
let destinationElement = null;
const context = {
  console,
  events,
  refreshInvalidates: false,
  refreshUnchanged: false,
  document: {
    hidden: false,
    getElementById(id) {
      return destinationElement?.id === id ? destinationElement : null;
    },
    querySelector() { return null; },
  },
  URLSearchParams,
  window: {
    location: {
      search: "",
      reload() { events.push({ type: "reload" }); },
    },
    matchMedia() { return { addEventListener() {}, matches: false }; },
  },
};
vm.createContext(context);

let source = fs.readFileSync("src/script/views/base/reconciliation.mjs", "utf8");
source = source.replace(
  /^import [\s\S]*?(?=const COLLECTION_ONLY_CHANGE_TYPES)/,
  `
const clearRecentSearchResults = () => {};
const captureError = (error) => { throw error; };
const request = {
  async post(url, payload) {
    events.push({ type: "request", url, payload });
    if (refreshInvalidates) return { ok: true, reload: true };
    if (refreshUnchanged) {
      return { ok: true, fingerprint: "fresh-root", targets: [] };
    }
    return {
      ok: true,
      fingerprint: "fresh-root",
      authorization: "new-auth",
      collection_revision: "tasks-after",
      targets: payload.targets.map((target, index) => ({
        id: target.id,
        fallback: index === 1,
        upsert: [],
        remove: [],
        order: [],
      })),
    };
  },
};
`,
);
source = source.replaceAll("export const ", "const ");
source += `
globalThis.reconcileChange = reconcileChange;
globalThis.refreshCollectionComponents = refreshCollectionComponents;
`;
vm.runInContext(source, context);

const root = {
  dataset: {
    kind: "task",
    index: "tasks",
    fingerprint: "initial-root",
    authorization: "old-auth",
    collectionRevision: "tasks-before",
  },
  addEventListener() {},
  dispatchEvent() {},
  querySelector() { return null; },
  querySelectorAll() { return []; },
};
const view = {
  _pendingChanges: [],
  _reconcilePromise: null,
  components: {},
  elt: root,
  hash: "tasks",
  key: null,
  _applyStarState() {},
  async afterReconcileChange() {},
  ensureEditWatcher() { return Promise.resolve(this.EditWatcher); },
  getComponent() { return null; },
  async refresh() {
    return context.refreshCollectionComponents(
      this,
      Object.values(this.components),
    );
  },
  async refreshCollections() {
    return this.refresh();
  },
  async refreshSupplementalCollections() {},
  reconcileChange(change) {
    return context.reconcileChange(this, change);
  },
};
const deltaWidget = {
  refreshScope: "collection",
  refreshDescriptor() {
    return { rows: [{ key: "a", hash: "a", fingerprint: "old" }] };
  },
  async refreshDelta() { events.push({ type: "delta" }); },
  async refresh() { events.push({ type: "legacy-delta" }); },
};
const fallbackWidget = {
  refreshScope: "collection",
  refreshDescriptor() { return { rows: [] }; },
  async refreshDelta() { events.push({ type: "unexpected-delta" }); },
  async refresh() { events.push({ type: "legacy-fallback" }); },
};
const unsupportedWidget = {
  async refresh() { events.push({ type: "legacy-unsupported" }); },
};
view.components = {
  table: {
    name: "table",
    widgets: { deltaWidget, unsupportedWidget },
    async refreshCollections(skip) {
      for (const widget of Object.values(this.widgets)) {
		if (widget.refreshScope === "collection" && !skip.has(widget)) {
			await widget.refresh?.();
		}
      }
    },
  },
  tasks: {
    name: "tasks",
    widgets: { fallbackWidget },
    async refreshCollections(skip) {
      for (const widget of Object.values(this.widgets)) {
		if (widget.refreshScope === "collection" && !skip.has(widget)) {
			await widget.refresh?.();
		}
      }
    },
  },
};
view.Notifications = { async refresh() { events.push({ type: "notifications" }); } };

(async () => {
  await view.refresh();
  const requests = events.filter((event) => event.type === "request");
  if (requests.length !== 1 || requests[0].url !== "/l/refresh") {
    throw new Error(`Expected one refresh request: ${JSON.stringify(events)}`);
  }
  if (requests[0].payload.targets.length !== 2) {
    throw new Error("Supported widgets were not batched");
  }
  if (requests[0].payload.view.index !== "tasks") {
    throw new Error("View identity was not sent once at the envelope level");
  }
  if (requests[0].payload.view.hash !== "tasks") {
    throw new Error("View hash was not sent once at the envelope level");
  }
  if (requests[0].payload.view.fingerprint !== "initial-root") {
    throw new Error("View fingerprint was not sent at the envelope level");
  }
  if (requests[0].payload.targets.map((target) => target.id).join(",") !== "table,tasks") {
    throw new Error("Component IDs did not identify refresh targets");
  }
  if (requests[0].payload.view.authorization !== "old-auth" ||
      requests[0].payload.view.collection_revision !== "tasks-before") {
    throw new Error("Independent authorization/collection revisions were not sent");
  }
  if (root.dataset.authorization !== "new-auth" || root.dataset.collectionRevision !== "tasks-after") {
    throw new Error("Independent refresh revisions were not committed");
  }
  const types = events.map((event) => event.type);
  for (const expected of ["delta", "legacy-fallback"]) {
    if (!types.includes(expected)) throw new Error(`Missing ${expected}: ${types}`);
  }
  if (types.includes("notifications")) {
    throw new Error("Collection reconciliation fetched the notification list");
  }
  if (types.includes("legacy-delta") || types.includes("unexpected-delta")) {
    throw new Error(`Incorrect per-target fallback: ${types}`);
  }
  if (types.includes("legacy-unsupported")) {
    throw new Error(`Non-collection widget was refreshed: ${types}`);
  }
  if (root.dataset.fingerprint !== "fresh-root") {
    throw new Error("Successful refresh did not advance the root fingerprint");
  }

  context.refreshUnchanged = true;
  const unchangedStart = events.length;
  await view.refresh();
  const unchangedTypes = events
    .slice(unchangedStart)
    .map((event) => event.type);
  if (
    unchangedTypes.includes("delta") ||
    unchangedTypes.includes("legacy-delta") ||
    unchangedTypes.includes("legacy-fallback")
  ) {
    throw new Error(`Unchanged root refreshed a collection: ${unchangedTypes}`);
  }
  if (unchangedTypes.includes("legacy-unsupported")) {
    throw new Error("Unchanged root refreshed a non-collection widget");
  }

  context.refreshUnchanged = false;
  context.refreshInvalidates = true;
  await view.refresh();
  if (events.at(-1)?.type !== "reload") {
    throw new Error(`Cache invalidation did not reload: ${JSON.stringify(events)}`);
  }

  const collectionTarget = {
    dataset: { widget: "ModelTaskList" },
    matches() { return false; },
  };
  const mountedEntity = {
    dataset: { key: "model-task-a" },
    _lp_component: {
      destroy() { events.push({ type: "destroy-mounted" }); },
    },
    remove() { events.push({ type: "remove-mounted" }); },
    parentElement: {
      closest(selector) {
        return selector === "[data-widget]" ? collectionTarget : null;
      },
    },
  };
  root.querySelectorAll = (selector) =>
    ["[lp-entity][data-key]", "[data-key]"].includes(selector)
      ? [mountedEntity]
      : [];
  const collectionComponent = {
    async loadWidget(name) {
      events.push({ type: "load-mounted", name });
      return { refreshScope: "collection" };
    },
  };
  view.getComponent = (target) =>
    target === collectionTarget ? collectionComponent : null;
  view.EditWatcher = {
    async invalidate(keys) {
      events.push({ type: "invalidate", keys });
    },
    enqueue(keys) {
      events.push({ type: "enqueue-invalidation", keys });
    },
  };
  view.refreshCollections = async (_navigation, options = {}) => {
    options.beforeCommit?.();
    events.push({ type: "refresh-mounted" });
  };
  view.refreshSupplementalCollections = async () => {};
  view.afterReconcileChange = async () => {};
  context.refreshInvalidates = false;

  const reconcileStart = events.length;
  await view.reconcileChange({ type: "delete", key: "model-task-a" });
  const reconcileEvents = events.slice(reconcileStart);
  if (
    reconcileEvents[0]?.type !== "load-mounted" ||
    reconcileEvents[0]?.name !== "ModelTaskList" ||
    reconcileEvents[1]?.type !== "destroy-mounted" ||
    reconcileEvents[2]?.type !== "remove-mounted" ||
    reconcileEvents[3]?.type !== "refresh-mounted" ||
    reconcileEvents.some((event) => event.type === "invalidate")
  ) {
    throw new Error(`Mounted collection was not prepared before refresh: ${JSON.stringify(reconcileEvents)}`);
  }

  destinationElement = { id: "task-a" };
  const destinationComponent = {
    async loadWidget(name) {
      events.push({ type: "load-destination", name });
      return { key: "task-key-a" };
    },
  };
  view.getComponent = (target) =>
    target === destinationElement ? destinationComponent : null;
  const destinationStart = events.length;
  await view.reconcileChange({
    type: "deferred-complete",
    key: "page-key-a",
    destination: "task-a:TaskForm",
  });
  const destinationEvents = events.slice(destinationStart);
  const invalidation = destinationEvents.find(
    (event) => event.type === "invalidate",
  );
  if (
    destinationEvents[0]?.type !== "load-destination" ||
    destinationEvents[0]?.name !== "TaskForm" ||
    invalidation?.keys?.join(",") !== "page-key-a,task-key-a"
  ) {
    throw new Error(`Destination form key was not invalidated: ${JSON.stringify(destinationEvents)}`);
  }

  view.PollingCoordinator = { activePoll: Promise.resolve([]) };
  const reentrantStart = events.length;
  await view.reconcileChange({
    type: "entity-poll",
    key: "page-key-a",
  });
  const reentrantEvents = events.slice(reentrantStart);
  const queuedInvalidation = reentrantEvents.find(
    (event) => event.type === "enqueue-invalidation",
  );
  if (
    queuedInvalidation ||
    reentrantEvents.some((event) => event.type === "invalidate") ||
    !reentrantEvents.some((event) => event.type === "refresh-mounted")
  ) {
    throw new Error(`Root polling duplicated form reconciliation: ${JSON.stringify(reentrantEvents)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )
