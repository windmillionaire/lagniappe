"""Node-backed checks for the document/form state boundary."""


# @features offline
# @dimensions database-upgrade legacy-record-discard mutation-store
def test_offline_database_upgrade_discards_legacy_activity_records(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const stores = new Map([
  ["sync", []],
  ["activity", [{ id: "legacy-unsent-command" }]],
]);
const objectStoreNames = {
  contains(name) { return stores.has(name); },
};
const db = {
  objectStoreNames,
  close() {},
  createObjectStore(name) {
    stores.set(name, []);
    return {};
  },
  deleteObjectStore(name) { stores.delete(name); },
  transaction(storeNames) {
    const names = Array.isArray(storeNames) ? storeNames : [storeNames];
    return {
      objectStore(name) {
        if (!names.includes(name) || !stores.has(name)) {
          throw new Error(`Unknown store ${name}`);
        }
        return {
          getAll() {
            const request = {};
            queueMicrotask(() => {
              request.result = [...stores.get(name)];
              request.onsuccess?.();
            });
            return request;
          },
        };
      },
    };
  },
};
const indexedDB = {
  open(name, version) {
    if (name !== "offline-db" || version !== 5) {
      throw new Error(`Unexpected database request: ${name}@${version}`);
    }
    const request = { result: db };
    queueMicrotask(() => {
      request.onupgradeneeded?.({ target: { result: db }, oldVersion: 3 });
      request.onsuccess?.();
    });
    return request;
  },
};
const context = { console, indexedDB, queueMicrotask };
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/offline.mjs", "utf8");
source = source.replace(/export function /g, "function ");
source += "\nglobalThis.getOfflineMutations = getOfflineMutations;";
vm.runInContext(source, context);

(async () => {
  const records = await context.getOfflineMutations();
  if (stores.has("activity")) {
    throw new Error("Legacy activity store survived the database upgrade");
  }
  if (!stores.has("mutations")) {
    throw new Error("The mutations store was not created");
  }
  if (records.length !== 0) {
    throw new Error(`Legacy records were migrated unexpectedly: ${JSON.stringify(records)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features forms submission deferred-jobs
# @dimensions deliberate-submit form-lock no-live-sync
def test_form_submit_is_guarded_only_by_durable_autofill_lock(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const target = {
  dataset: {},
  cloneNode() { return { dataset: {} }; },
};
const context = { BaseForm: class {}, console };
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/form.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class FormElement", "class FormElement");
source += "\nglobalThis.FormElement = FormElement;";
vm.runInContext(source, context);

(async () => {
  const widget = new context.FormElement({
    target,
    view: { SyncManager: { sendUpdates() { throw new Error("form used live sync"); } } },
  });
  if (widget.syncId !== undefined || widget.syncData !== undefined) {
    throw new Error("FormElement still exposes the live-sync widget contract");
  }
  if (!(await widget.prepareSubmit())) {
    throw new Error("Ordinary form submit was unexpectedly blocked");
  }
  widget.lockDeferredOperation({ operation: "operation-1", revision: 3 });
  if (await widget.prepareSubmit()) {
    throw new Error("Durably locked autofill form was allowed to submit");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @pairs deferred-jobs:form-lock deferred-jobs:reload
def test_active_deferred_form_waits_for_root_operation_scan(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const scans = [];
let ensureCalls = 0;
let releaseManager;
const managerReady = new Promise((resolve) => { releaseManager = resolve; });

function operationForm() {
  return {
    dataset: { operation: "operation-1" },
    addEventListener() {},
    cloneNode() { return operationForm(); },
    matches(selector) { return selector === "[data-operation]"; },
    querySelector() { return null; },
    replaceWith() {},
  };
}

const context = {
  BaseForm: class {
    async init() {}
  },
  console,
};
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/form.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class FormElement", "class FormElement");
source += "\nglobalThis.FormElement = FormElement;";
vm.runInContext(source, context);

(async () => {
  const widget = new context.FormElement({
    target: operationForm(),
    view: {
      ensureDeferredOperations() {
        ensureCalls += 1;
        return managerReady;
      },
    },
  });

  let initialized = false;
  const pending = widget._initForm().then(() => { initialized = true; });
  await new Promise((resolve) => setImmediate(resolve));

  if (ensureCalls !== 1) {
    throw new Error(`Root operation did not request its manager: ${ensureCalls}`);
  }
  if (initialized) {
    throw new Error("Deferred form initialized before its manager was ready");
  }

  releaseManager({ scan(target) { scans.push(target); } });
  await pending;

  if (scans.length !== 1 || scans[0] !== widget.target) {
    throw new Error("Deferred manager did not scan the active root form");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features forms form-schema edited-entity-notice
# @dimensions latest-schema local-values remote-added-values no-schema-version-choice
def test_local_revision_uses_latest_schema_and_merges_submission_values(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const replacementTarget = {};
const responseDocument = {
  cloneNode() {
    return {
      querySelector() { return replacementTarget; },
    };
  },
};
const target = {
  cloneNode() { return {}; },
};
const context = { BaseForm: class {}, console, structuredClone };
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/form.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class FormElement", "class FormElement");
source += "\nglobalThis.FormElement = FormElement;";
vm.runInContext(source, context);

const widget = new context.FormElement({
  target,
  name: "PageInfo",
  schema: [
    { id: "retained", type: "input" },
    { id: "removed", type: "input" },
  ],
});
widget._applyQueuedFields = (targetNode, state) => {
  if (targetNode !== replacementTarget || state.fields[0][0] !== "name") {
    throw new Error("Ordinary local form controls were not projected");
  }
};
const local = widget.buildLocalRevision(
  {
    html: responseDocument,
    schema: [
      { id: "retained", type: "input" },
      { id: "added", type: "input" },
    ],
    submission: { retained: "Saved", added: "New saved value" },
  },
  {
    fields: [["name", "Local name"]],
    files: [],
    form_controls: [],
    renderer_submission: { retained: "Local", removed: "Old local value" },
  },
);

const submission = local.response.submission;
if (
  submission.retained !== "Local" ||
  submission.added !== "New saved value" ||
  Object.hasOwn(submission, "removed")
) {
  throw new Error(`Submission was not reconciled into the latest schema: ${JSON.stringify(submission)}`);
}
if (local.response.schema.length !== 2 || local.response.schema[1].id !== "added") {
  throw new Error("Local choice retained an obsolete schema version");
}
'''
    )


# @features offline
# @dimensions queue-submit fingerprint immutable-command
def test_offline_submit_record_keeps_originating_entity_fingerprint(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class FakeFile {}
class FakeFormData {
  constructor(entries = []) { this._entries = entries; }
  entries() { return this._entries[Symbol.iterator](); }
}
let stored = null;
const form = {
  dataset: {},
  hasAttribute(name) { return name === "lp-offline"; },
  closest(selector) {
    return selector === "[lp-entity]"
      ? {
          dataset: {
            fingerprint: "fingerprint-at-submit",
            modified: "2026-07-22T10:00:00+00:00",
          },
        }
      : null;
  },
};
const widget = {
  target: form,
  async offline() {
    return { id: "update:page:one", kind: "page", target_key: "page-one" };
  },
};
const context = {
  console,
  deleteOfflineMutations: async () => {},
  File: FakeFile,
  FormData: FakeFormData,
  getOfflineMutations: async () => [],
  request: {},
  setOfflineMutation: async () => {},
};
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/offlineQueue.mjs", "utf8");
source = source.replace(/import[\s\S]*?from ".*?";\n/g, "");
source = source.replace("export class OfflineQueue", "class OfflineQueue");
source += "\nglobalThis.OfflineQueue = OfflineQueue;";
vm.runInContext(source, context);

(async () => {
  const manager = new context.OfflineQueue({
    components: {},
    elt: { dataset: {} },
  });
  manager._destinationWidget = async () => null;
  manager._store = async (record) => { stored = record; };
  manager._dispatch = async () => [];
  await manager.queueSubmit(
    { active: widget },
    new FakeFormData([["name", "Offline edit"]]),
    "/pages/page-one/update",
    "PUT",
  );
  if (stored?.fingerprint !== "fingerprint-at-submit") {
    throw new Error(`Offline fingerprint was not persisted: ${stored?.fingerprint}`);
  }
  if (stored?.modified !== "2026-07-22T10:00:00+00:00") {
    throw new Error(`Offline modified stamp was not persisted: ${stored?.modified}`);
  }
  if (stored.fields[0][1] !== "Offline edit") {
    throw new Error("Offline submission was not stored as a complete command");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features offline
# @dimensions renderer-snapshot replay-payload reload
def test_offline_submit_record_keeps_renderer_snapshot_out_of_replay_payload(
    run_node,
):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class FakeFile {}
class FakeFormData {
  constructor(entries = []) { this._entries = [...entries]; }
  append(name, value) { this._entries.push([name, value]); }
  set(name, value) {
    this._entries = this._entries.filter(([key]) => key !== name);
    this._entries.push([name, value]);
  }
  entries() { return this._entries[Symbol.iterator](); }
}

let stored = null;
let replayed = null;
const target = {
  dataset: {},
  hasAttribute(name) { return name === "lp-offline"; },
  closest() {
    return {
      dataset: {
        fingerprint: "fingerprint-1",
        modified: "2026-07-22T10:00:00+00:00",
      },
    };
  },
  querySelectorAll() { return []; },
};
const rendererSubmission = {
  headline: "Queued headline",
  items: { rows: [{ note: "Queued row" }] },
};
const widget = {
  target,
  form: {
    renderer: {
      _packageSubmission() { return rendererSubmission; },
    },
  },
  async offline() {
    return { id: "update:page:one", kind: "page", target_key: "page-one" };
  },
};
const context = {
  console,
  deleteOfflineMutations: async () => {},
  File: FakeFile,
  FormData: FakeFormData,
  getOfflineMutations: async () => [],
  request: {
    async put(_route, data) {
      replayed = [...data.entries()];
      return { ok: true };
    },
  },
  setOfflineMutation: async () => {},
};
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/offlineQueue.mjs", "utf8");
source = source.replace(/import[\s\S]*?from ".*?";\n/g, "");
source = source.replace("export class OfflineQueue", "class OfflineQueue");
source += "\nglobalThis.OfflineQueue = OfflineQueue;";
vm.runInContext(source, context);

(async () => {
  const manager = new context.OfflineQueue({
    components: {},
    elt: { dataset: {} },
  });
  manager._destinationWidget = async () => null;
  manager._store = async (record) => { stored = record; };
  manager._dispatch = async () => [];

  await manager.queueSubmit(
    { active: widget },
    new FakeFormData([["headline", "Queued headline"]]),
    "/pages/page-one/update",
    "PUT",
  );

  if (JSON.stringify(stored.renderer_submission) !== JSON.stringify(rendererSubmission)) {
    throw new Error("Renderer-native submission was not stored on the offline mutation");
  }

  await manager._send(stored);
  const replayedNames = replayed.map(([name]) => name);
  if (replayedNames.includes("renderer_submission")) {
    throw new Error("Internal renderer snapshot leaked into replay FormData");
  }
  if (JSON.stringify(replayed) !== JSON.stringify([
    ["headline", "Queued headline"],
    ["offline", "True"],
    ["offline-fingerprint", "fingerprint-1"],
  ])) {
    throw new Error(`Unexpected replay payload: ${JSON.stringify(replayed)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features offline
# @dimensions fingerprint-precondition conflict-durability dispatch
def test_offline_replay_keeps_stale_submission_queued_for_reconciliation(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class FakeFormData {
  constructor() { this.values = []; }
  append(name, value) { this.values.push([name, value]); }
  set(name, value) {
    this.values = this.values.filter(([key]) => key !== name);
    this.values.push([name, value]);
  }
}
const deleted = [];
const phases = [];
let payload = null;
const record = {
  id: "update:page:one",
  action: "update",
  kind: "page",
  method: "PUT",
  route: "/pages/page-one/update",
  target_key: "page-one",
  fingerprint: "originating-fingerprint",
  modified: "2026-07-22T10:00:00+00:00",
  fields: [["name", "Queued name"]],
  files: [],
  created_at: 1,
};
const context = {
  console,
  deleteOfflineMutations: async (ids) => { deleted.push(...ids); },
  File: class {},
  FormData: FakeFormData,
  getOfflineMutations: async () => [],
  request: {
    async put(_route, data, options) {
      payload = { values: data.values, options };
      return {
        ok: true,
        conflict: true,
        entities: [{
          key: "page-one",
          fingerprint: "server-fingerprint",
          modified: "2026-07-22T11:00:00+00:00",
        }],
      };
    },
  },
  setOfflineMutation: async () => {},
};
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/offlineQueue.mjs", "utf8");
source = source.replace(/import[\s\S]*?from ".*?";\n/g, "");
source = source.replace("export class OfflineQueue", "class OfflineQueue");
source += "\nglobalThis.OfflineQueue = OfflineQueue;";
vm.runInContext(source, context);

(async () => {
  const manager = new context.OfflineQueue({ online: true, components: {} });
  manager.records = [record];
  manager._dispatch = async ({ phase }) => { phases.push(phase); };
  const completed = await manager.replay();
  if (completed !== 0 || deleted.length !== 0 || manager.records.length !== 1) {
    throw new Error("Conflicting replay was removed from the durable queue");
  }
  if (phases.join(",") !== "conflict" || !record.conflictResponse?.conflict) {
    throw new Error("Conflicting replay was not dispatched for form review");
  }
  const fields = Object.fromEntries(payload.values);
  if (
    fields["offline-fingerprint"] !== "originating-fingerprint" ||
    fields.offline !== "True"
  ) {
    throw new Error(`Replay precondition was missing: ${JSON.stringify(payload)}`);
  }
  if (payload.options.acknowledgeEntities !== false) {
    throw new Error("Conflict response advanced the live entity before review");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features offline
# @dimensions replay dispatch mounted-form-poll no-direct-acknowledgement
# @pair offline:replay-reconciliation
# @pair edited-entity-notice:replayed-response
def test_offline_replay_polls_mounted_form_without_direct_acknowledgement(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class FakeFormData {
  constructor() { this.values = []; }
  append(name, value) { this.values.push([name, value]); }
  set(name, value) {
    this.values = this.values.filter(([key]) => key !== name);
    this.values.push([name, value]);
  }
}
const events = [];
const record = {
  id: "update:page:one",
  action: "update",
  kind: "page",
  method: "PUT",
  route: "/pages/page-one/update",
  target_key: "page-one",
  fingerprint: "originating-fingerprint",
  fields: [["name", "Queued name"]],
  files: [],
  created_at: 1,
};
let queue = null;
const context = {
  console,
  deleteOfflineMutations: async (ids) => {
    events.push({ type: "delete", ids, remaining: queue.records.length });
  },
  document: { querySelector() { return null; } },
  File: class {},
  FormData: FakeFormData,
  getOfflineMutations: async () => [],
  request: {
    async put() {
      return {
        ok: true,
        entities: [{
          key: "page-one",
          fingerprint: "saved-fingerprint",
        }],
      };
    },
  },
  setOfflineMutation: async () => {},
};
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/offlineQueue.mjs", "utf8");
source = source.replace(/import[\s\S]*?from ".*?";\n/g, "");
source = source.replace("export class OfflineQueue", "class OfflineQueue");
source += "\nglobalThis.OfflineQueue = OfflineQueue;";
vm.runInContext(source, context);

(async () => {
  const mountedForm = {
    key: "page-one",
    target: {
      matches(selector) { return selector === "form[data-widget]"; },
    },
    handleOfflineQueue() {},
  };
  queue = new context.OfflineQueue({
    online: true,
    components: { info: { widgets: { PageInfo: mountedForm } } },
    async ensureEditWatcher() {
      return {
        async invalidate(key) {
          events.push({ type: "poll", key, remaining: queue.records.length });
        },
      };
    },
  });
  queue.records = [record];
  queue._dispatch = async ({ phase }, targets = []) => {
    events.push({
      type: phase,
      remaining: queue.recordsFor({ kind: "page" }).length,
      targets: targets.length,
    });
  };

  const completed = await queue.replay();
  if (completed !== 1 || queue.records.length !== 0) {
    throw new Error("Committed replay remained in the live queue");
  }
  if (
    events.map(({ type }) => type).join(",") !==
      "delete,replayed,poll" ||
    events[1].remaining !== 0 ||
    events[1].targets !== 0 ||
    events[2].remaining !== 0 ||
    events[2].key !== "page-one"
  ) {
    throw new Error(
      `Replay polling observed stale queue state: ${JSON.stringify(events)}`,
    );
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features offline
# @dimensions replay conflict-rebase
def test_offline_replay_retries_a_conflict_rebased_by_the_form(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class FakeFormData {
  constructor() { this.values = []; }
  append(name, value) { this.values.push([name, value]); }
  set(name, value) {
    this.values = this.values.filter(([key]) => key !== name);
    this.values.push([name, value]);
  }
}
const deleted = [];
const phases = [];
const fingerprints = [];
const record = {
  id: "update:page:one",
  action: "update",
  kind: "page",
  method: "PUT",
  route: "/pages/page-one/update",
  target_key: "page-one",
  fingerprint: "originating-fingerprint",
  fields: [["name", "Queued name"]],
  files: [],
  created_at: 1,
};
const context = {
  console,
  CustomEvent: class {
    constructor(type, options) { this.type = type; this.detail = options.detail; }
  },
  deleteOfflineMutations: async (ids) => { deleted.push(...ids); },
  document: { querySelector() { return null; } },
  File: class {},
  FormData: FakeFormData,
  getOfflineMutations: async () => [],
  request: {
    async put(_route, data) {
      const fingerprint = Object.fromEntries(data.values)["offline-fingerprint"];
      fingerprints.push(fingerprint);
      if (fingerprint === "originating-fingerprint") {
        return {
          ok: true,
          conflict: true,
          entities: [{
            key: "page-one",
            fingerprint: "current-fingerprint",
          }],
        };
      }
      return {
        ok: true,
        entities: [{
          key: "page-one",
          fingerprint: "saved-fingerprint",
        }],
      };
    },
  },
  setOfflineMutation: async () => {},
  window: { dispatchEvent() {} },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/offlineQueue.mjs", "utf8");
source = source.replace(/import[\s\S]*?from ".*?";\n/g, "");
source = source.replace("export class OfflineQueue", "class OfflineQueue");
source += "\nglobalThis.OfflineQueue = OfflineQueue;";
vm.runInContext(source, context);

(async () => {
  const queue = new context.OfflineQueue({ online: true, components: {} });
  queue.records = [record];
  queue._dispatch = async ({ phase, record: dispatched }) => {
    phases.push(phase);
    if (phase !== "conflict") return;
    await queue._store({
      ...dispatched,
      fingerprint: "current-fingerprint",
    });
  };

  const completed = await queue.replay();
  if (
    completed !== 1 ||
    fingerprints.join(",") !==
      "originating-fingerprint,current-fingerprint" ||
    phases.join(",") !== "conflict,replayed" ||
    deleted.join(",") !== record.id ||
    queue.records.length !== 0
  ) {
    throw new Error(
      `Rebased conflict was not retried in order: ${JSON.stringify({
        completed,
        fingerprints,
        phases,
        deleted,
        remaining: queue.records,
      })}`,
    );
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @pairs edited-entity-notice:renderer-capability edited-entity-notice:schema-only
# @pairs edited-entity-notice:local-values edited-entity-notice:submission-choice
# @pairs edited-entity-notice:latest-schema edited-entity-notice:whole-form-selection
# @pairs edited-entity-notice:active-state
def test_edit_watcher_separates_schema_and_renderer_value_changes(
    run_node,
):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const events = [];
const anchor = {
  dataset: {
    key: "page-one",
    fingerprint: "old",
    modified: "2026-07-22T10:00:00+00:00",
  },
};
const makeMarker = (widget) => {
  const button = { textContent: "", disabled: false };
  const message = { textContent: "" };
  const form = { _lp_widget: widget };
  const marker = {
    dataset: { visible: "false" },
    querySelector(selector) {
      return selector === "[data-role='edited-message']" ? message : button;
    },
    closest(selector) {
      if (selector === "[lp-entity]") return anchor;
      if (selector === "form[data-widget]") return form;
      return null;
    },
  };
  widget.target = { querySelector() { return marker; } };
  return marker;
};
const makeWidget = (schema, localSubmission) => ({
  name: "PageInfo",
  schema,
  submission: Object.fromEntries(schema.map(({ id }) => [id, "baseline"])),
  unsavedState: true,
  form: { renderer: {}, _queued: false },
  revisionBaseline: "baseline",
  revisionSnapshot() { return "local-current"; },
  revisionCanReset() { return true; },
  buildLocalRevision(response) {
    const submission = structuredClone(response.submission);
    const latestIds = new Set(response.schema.map(({ id }) => id));
    for (const { id } of this.schema) {
      if (latestIds.has(id) && Object.hasOwn(localSubmission ?? {}, id)) {
        submission[id] = structuredClone(localSubmission[id]);
      }
    }
    return {
      response: {
        ...response,
        snapshot: "local-current",
        submission,
      },
    };
  },
  async applyLocalRevision(response, options) {
    const local = this.buildLocalRevision(response);
    events.push({
      type: "apply-schema",
      options,
      schema: response.schema,
      submission: local.response.submission,
    });
    this.schema = response.schema;
    this.submission = local.response.submission;
  },
  commitRevisionBaseline() {},
  async applyRevision() {},
});
const context = {
  areEqual(left, right) { return JSON.stringify(left) === JSON.stringify(right); },
  captureError(error) { throw error; },
  console,
  ENDPOINTS: {},
  loadRevisionPreview(_widget, response) {
    return {
      name: "PageInfo",
      revisionSnapshot() { return response.snapshot; },
      destroy() {},
    };
  },
  Modal: class {},
  request: {},
  STYLES: {},
  structuredClone,
  withTransition(callback) { return callback(); },
  window: { addEventListener() {}, removeEventListener() {} },
};
vm.createContext(context);
let reconcilerSource = fs.readFileSync("src/script/shared/editReconciler.mjs", "utf8");
reconcilerSource = reconcilerSource.replace(/^import .*$/gm, "");
reconcilerSource = reconcilerSource.replace(
  "export class EditReconciler",
  "class EditReconciler",
);
reconcilerSource += "\nglobalThis.EditReconciler = EditReconciler;";
vm.runInContext(reconcilerSource, context);
let source = fs.readFileSync("src/script/shared/editWatcher.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class EditWatcher", "class EditWatcher");
source += "\nglobalThis.EditWatcher = EditWatcher;";
vm.runInContext(source, context);

(async () => {
  const watcher = new context.EditWatcher({
    addFlash() {},
    components: {},
    elt: { addEventListener() {}, querySelectorAll() { return []; } },
  });

  const schemaWidget = makeWidget(
    [
      { id: "retained", label: "Old label" },
      { id: "removed", label: "Removed field" },
    ],
    {
      retained: "Local value",
      removed: "Local removed value",
    },
  );
  const schemaMarker = makeMarker(schemaWidget);
  watcher._reconciler._state(schemaMarker).token = {};
  await watcher._reconciler._stageRevision(
    schemaMarker,
    schemaWidget,
    {
      schema: [
        { id: "retained", label: "Updated label" },
        { id: "added", label: "Added field" },
      ],
      submission: {
        retained: "Saved value",
        added: "New saved value",
      },
      snapshot: "server-current",
    },
    {
      fingerprint: "schema-fingerprint",
      modified: "2026-07-22T10:00:00+00:00",
    },
  );
  const schemaState = watcher._reconciler._state(schemaMarker);
  const schemaApplication = events.find((event) => event.type === "apply-schema");
  if (
    events.filter((event) => event.type === "apply-schema").length !== 1 ||
    schemaState.submissionChoice ||
    schemaState.mode !== "dismiss" ||
    schemaApplication.schema[0].label !== "Updated label" ||
    schemaApplication.submission.retained !== "Local value" ||
    schemaApplication.submission.added !== "New saved value" ||
    Object.hasOwn(schemaApplication.submission, "removed")
  ) {
    throw new Error(
      `Schema-only drift was not applied around local values: ${JSON.stringify({
        state: schemaState,
        application: schemaApplication,
      })}`,
    );
  }

  const valueWidget = makeWidget([{ id: "same" }], { same: "local" });
  const valueMarker = makeMarker(valueWidget);
  watcher._reconciler._state(valueMarker).token = {};
  await watcher._reconciler._stageRevision(
    valueMarker,
    valueWidget,
    {
      schema: [{ id: "same" }],
      submission: { same: "server" },
      snapshot: "server-newer",
    },
    {
      fingerprint: "submission-fingerprint",
      modified: "2026-07-22T11:00:00+00:00",
    },
  );
  const valueState = watcher._reconciler._state(valueMarker);
  if (!valueState.submissionChoice || valueState.mode !== "review") {
    throw new Error("A later saved submission did not request a value choice");
  }
  if (events.filter((event) => event.type === "apply-schema").length !== 1) {
    throw new Error("Later saved values were applied before review");
  }

  const activeWidget = makeWidget([{ id: "same" }], { same: "active-local" });
  activeWidget.unsavedState = false;
  activeWidget.visible = true;
  activeWidget.component = { active: activeWidget };
  const activeMarker = makeMarker(activeWidget);
  watcher._reconciler._state(activeMarker).token = {};
  await watcher._reconciler._stageRevision(
    activeMarker,
    activeWidget,
    {
      schema: [{ id: "same" }],
      submission: { same: "active-server" },
      snapshot: "active-server-newer",
    },
    {
      fingerprint: "active-submission-fingerprint",
      modified: "2026-07-22T11:15:00+00:00",
    },
  );
  const activeState = watcher._reconciler._state(activeMarker);
  if (
    !activeState.submissionChoice ||
    activeState.mode !== "review" ||
    activeMarker.dataset.visible !== "true"
  ) {
    throw new Error("An active clean form did not offer revision review");
  }
  if (events.filter((event) => event.type === "apply-schema").length !== 1) {
    throw new Error("An active clean form applied saved values before review");
  }

  const matchingWidget = makeWidget([{ id: "same" }], { same: "saved" });
  const matchingMarker = makeMarker(matchingWidget);
  watcher._reconciler._state(matchingMarker).token = {};
  await watcher._reconciler._stageRevision(
    matchingMarker,
    matchingWidget,
    {
      schema: [{ id: "same" }],
      submission: { same: "saved" },
      snapshot: "local-current",
    },
    {
      fingerprint: "matching-submission-fingerprint",
      modified: "2026-07-22T11:30:00+00:00",
    },
  );
  const matchingState = watcher._reconciler._state(matchingMarker);
  if (
    matchingState.submissionChoice ||
    matchingState.mode === "review" ||
    matchingMarker.dataset.visible !== "false"
  ) {
    throw new Error(
      `Matching values requested a value choice: ${JSON.stringify(matchingState)}`,
    );
  }

  const queuedWidget = makeWidget([{ id: "plain" }], { plain: "queued" });
  queuedWidget.form = { _queued: true };
  const queuedMarker = makeMarker(queuedWidget);
  watcher._reconciler._state(queuedMarker).token = {};
  await watcher._reconciler._stageRevision(
    queuedMarker,
    queuedWidget,
    {
      schema: [{ id: "plain" }],
      submission: { plain: "saved" },
      snapshot: "server-whole-form",
    },
    {
      fingerprint: "queued-fingerprint",
      modified: "2026-07-22T12:00:00+00:00",
      record: { id: "queued-mutation" },
    },
  );
  const queuedState = watcher._reconciler._state(queuedMarker);
  if (queuedState.mode !== "whole-review" || queuedState.submissionChoice !== true) {
    throw new Error("Queued non-renderer form did not use whole-form reconciliation");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features edited-entity-notice forms
# @dimensions per-field-selection saved-default mixed-submission
def test_edit_watcher_reconciles_independent_field_selections(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const applied = [];
const widget = {
  target: null,
  async applyRevision(response) {
    applied.push({ kind: "server", response });
  },
  async applyLocalRevision(response, options) {
    applied.push({ kind: "selected", response, options });
  },
};
const button = { textContent: "", disabled: false };
const message = { textContent: "" };
const form = { _lp_widget: widget };
const marker = {
  dataset: { visible: "true" },
  querySelector(selector) {
    return selector === "[data-role='edited-message']" ? message : button;
  },
  closest(selector) {
    if (selector === "form[data-widget]") return form;
    return null;
  },
};
widget.target = { querySelector() { return marker; } };

const context = {
  areEqual(left, right) { return JSON.stringify(left) === JSON.stringify(right); },
  captureError(error) { throw error; },
  console,
  ENDPOINTS: {},
  loadRevisionPreview() {},
  Modal: class {},
  request: {},
  STYLES: {},
  structuredClone,
  withTransition(callback) { return callback(); },
  window: { addEventListener() {}, removeEventListener() {} },
};
vm.createContext(context);
let reconcilerSource = fs.readFileSync("src/script/shared/editReconciler.mjs", "utf8");
reconcilerSource = reconcilerSource.replace(/^import .*$/gm, "");
reconcilerSource = reconcilerSource.replace(
  "export class EditReconciler",
  "class EditReconciler",
);
reconcilerSource += "\nglobalThis.EditReconciler = EditReconciler;";
vm.runInContext(reconcilerSource, context);
let source = fs.readFileSync("src/script/shared/editWatcher.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class EditWatcher", "class EditWatcher");
source += "\nglobalThis.EditWatcher = EditWatcher;";
vm.runInContext(source, context);

(async () => {
  const watcher = new context.EditWatcher({
    components: {},
    elt: { addEventListener() {}, querySelectorAll() { return []; } },
  });
  const state = watcher._reconciler._state(marker);
  state.response = {
    submission: { first: "Saved first", second: "Saved second" },
  };
  state.remoteSnapshot = "saved-snapshot";

  await watcher.resolveRevision(marker, {
    localResponse: {
      submission: { first: "Local first", second: "Local second" },
    },
    selections: { first: "local", second: "server" },
  });

  const selected = applied[0];
  if (
    selected?.kind !== "selected" ||
    selected.options.selectedSubmission.first !== "Local first" ||
    selected.options.selectedSubmission.second !== "Saved second" ||
    selected.options.remoteSnapshot !== "saved-snapshot" ||
    selected.options.markUnsaved !== true
  ) {
    throw new Error(`Mixed field choices were not reconciled: ${JSON.stringify(selected)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features edited-entity-notice deferred-jobs
# @dimensions active-operation reload form-lock
def test_edit_watcher_restores_active_autofill_without_form_sync(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const locked = [];
const tracked = [];
let ensureCalls = 0;
const widget = {
  _deferredOperation: null,
  target: { dataset: {} },
  lockDeferredOperation(descriptor) {
    this._deferredOperation = descriptor.operation;
    locked.push(descriptor);
    return true;
  },
};
const form = {
  dataset: { widget: "PageInfo" },
  _lp_widget: widget,
};
const marker = {
  closest(selector) {
    return selector === "form[data-widget]" ? form : null;
  },
};
const operations = {
  track(operation, options) { tracked.push({ operation, options }); },
};
const view = {
  ensureDeferredOperations() {
    ensureCalls += 1;
    return Promise.resolve(operations);
  },
};
const context = { console, Modal: class {} };
vm.createContext(context);
let reconcilerSource = fs.readFileSync("src/script/shared/editReconciler.mjs", "utf8");
reconcilerSource = reconcilerSource.replace(/^import .*$/gm, "");
reconcilerSource = reconcilerSource.replace(
  "export class EditReconciler",
  "class EditReconciler",
);
reconcilerSource += "\nglobalThis.EditReconciler = EditReconciler;";
vm.runInContext(reconcilerSource, context);
let source = fs.readFileSync("src/script/shared/editWatcher.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class EditWatcher", "class EditWatcher");
source += "\nglobalThis.EditWatcher = EditWatcher;";
vm.runInContext(source, context);

(async () => {
  const watcher = new context.EditWatcher(view);
  await watcher._lockEntity(
    { markers: new Set([marker]) },
    { operation: "operation-2", revision: 5, locked: true },
  );
  if (locked.length !== 1 || locked[0].operation !== "operation-2") {
    throw new Error("EditWatcher did not restore the form lock");
  }
  if (ensureCalls !== 1) {
    throw new Error("EditWatcher did not start the deferred manager on demand");
  }
  if (tracked.length !== 1 || tracked[0].options.node !== widget.target) {
    throw new Error("EditWatcher did not restore deferred progress tracking");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @pairs edited-entity-notice:owned-deferred-completion
# @pairs deferred-jobs:owned-deferred-completion
# @pairs edited-entity-notice:active-state edited-entity-notice:dirty-state
def test_owned_deferred_completion_replaces_clean_active_form(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const applications = [];
function formCase({ unsaved = false, entityKey = "page-one" } = {}) {
  const anchor = {
    dataset: {
      key: entityKey,
      fingerprint: "old-fingerprint",
      modified: "2026-07-22T10:00:00+00:00",
    },
  };
  const button = { textContent: "", disabled: false };
  const message = { textContent: "" };
  const widget = {
    name: "PageInfo",
    _deferredOperation: "operation-one",
    unsavedState: unsaved,
    visible: true,
    form: { _queued: false },
    revisionBaseline: "local",
    revisionCanReset() { return true; },
    revisionSnapshot() { return "local"; },
    buildLocalRevision(response) {
      return { response: { ...response, snapshot: "local" } };
    },
    commitRevisionBaseline() {},
    async applyRevision(response) {
      applications.push({ widget, response });
    },
  };
  widget.component = { active: widget };
  const form = { dataset: { widget: "PageInfo" }, _lp_widget: widget };
  const marker = {
    isConnected: true,
    dataset: {
      visible: "false",
      editedRoute: "/pages/page-one/info/replace",
    },
    querySelector(selector) {
      return selector === "[data-role='edited-message']" ? message : button;
    },
    closest(selector) {
      if (selector === "[lp-entity]") return anchor;
      if (selector === "form[data-widget]") return form;
      return null;
    },
  };
  widget.target = {
    querySelector() { return marker; },
    contains() { return true; },
  };
  return { marker, widget };
}

const context = {
  areEqual(left, right) { return JSON.stringify(left) === JSON.stringify(right); },
  captureError(error) { throw error; },
  console,
  document: { activeElement: {} },
  loadRevisionPreview(_widget, response) {
    return {
      revisionSnapshot() { return response.snapshot; },
      destroy() {},
    };
  },
  Modal: class {},
  request: {
    async get() {
      return { ok: true, snapshot: "saved" };
    },
  },
  STYLES: {},
  withTransition(callback) { return callback(); },
  window: { addEventListener() {}, removeEventListener() {} },
};
vm.createContext(context);
let reconcilerSource = fs.readFileSync("src/script/shared/editReconciler.mjs", "utf8");
reconcilerSource = reconcilerSource.replace(/^import .*$/gm, "");
reconcilerSource = reconcilerSource.replace(
  "export class EditReconciler",
  "class EditReconciler",
);
reconcilerSource += "\nglobalThis.EditReconciler = EditReconciler;";
vm.runInContext(reconcilerSource, context);
let source = fs.readFileSync("src/script/shared/editWatcher.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class EditWatcher", "class EditWatcher");
source += "\nglobalThis.EditWatcher = EditWatcher;";
vm.runInContext(source, context);

(async () => {
  const watcher = new context.EditWatcher({
    addFlash() {},
    components: {},
    elt: { addEventListener() {}, querySelectorAll() { return []; } },
  });

  const clean = formCase({ entityKey: "task-one" });
  watcher.expectDeferredCompletion("page-one", "operation-one");
  await watcher._reconciler.probe(
    clean.marker,
    "saved-fingerprint",
    "2026-07-22T11:00:00+00:00",
  );
  if (
    applications.length !== 1 ||
    clean.marker.dataset.visible !== "false" ||
    watcher._deferredCompletions.has("page-one")
  ) {
    throw new Error("A clean active form did not apply its own deferred completion");
  }

  const dirty = formCase({ unsaved: true, entityKey: "task-one" });
  watcher.expectDeferredCompletion("page-one", "operation-one");
  await watcher._reconciler.probe(
    dirty.marker,
    "newer-fingerprint",
    "2026-07-22T12:00:00+00:00",
  );
  if (
    applications.length !== 1 ||
    dirty.marker.dataset.visible !== "true" ||
    watcher._reconciler._state(dirty.marker).mode !== "reset"
  ) {
    throw new Error("An unsaved form bypassed revision protection for its deferred completion");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )



# @features reconnect-refresh edited-entity-notice forms
# @dimensions visibility ordering stale-fingerprint dirty-form-preservation
# @pair offline:dirty-form-preservation
# @pair offline:background-replay
# @pair polling:nonblocking
def test_visibility_sync_stages_remote_form_edits_without_waiting_for_offline_replay(
    run_node,
):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const events = [];
const context = {
  console,
  CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options?.detail; } },
  document: {
    hidden: false,
    getElementById() { return null; },
    querySelector() { return null; },
  },
  URLSearchParams,
  window: {
    location: { search: "" },
    matchMedia() { return { addEventListener() {}, matches: false }; },
  },
};
vm.createContext(context);

let replaySource = fs.readFileSync(
  "src/script/views/base/offlineReplay.mjs",
  "utf8",
);
replaySource = replaySource.replace(
  "export const replayOfflineQueue",
  "const replayOfflineQueue",
);
replaySource += "\nglobalThis.replayOfflineQueue = replayOfflineQueue;";
vm.runInContext(replaySource, context);

let source = fs.readFileSync("src/script/views/base/core.mjs", "utf8");
source = source.replace(
  /^import [\s\S]*?(?=\/\*\*)/,
  `
const ENDPOINTS = {};
const captureError = (error) => { throw error; };
const connectivity = { online: true, hidden: true };
const request = {};
const withTransition = async (callback) => await callback();
const ViewComponent = class {};
const collectRefreshTargets = () => [];
const reconcileChange = () => {};
const refreshCollectionComponents = () => {};
const ensureDeferredOperations = (view) => Promise.resolve(view.DeferredOperations);
const ensureEditWatcher = (view) => Promise.resolve(view.EditWatcher);
const ensureEntityMenu = () => Promise.resolve(null);
const ensureModalClasses = () => Promise.resolve(null);
const ensureNotifications = () => Promise.resolve(null);
const ensureOfflineModal = () => Promise.resolve(null);
const ensureOfflineQueue = (view) => Promise.resolve(view.offlineQueue);
const ensurePollingCoordinator = (view) => Promise.resolve(view.PollingCoordinator);
const ensureSearchBox = () => Promise.resolve(null);
const ensureSubmissionManager = () => Promise.resolve(null);
const ensureSyncManager = (view) => Promise.resolve(view.SyncManager);
const initializeCoreServices = () => {};
const ShellView = class {
  constructor(elt) {
    this.elt = elt;
    this.kind = elt.dataset.kind;
    this.key = elt.dataset.key;
    this.hash = elt.dataset.hash || elt.dataset.index;
    this.online = connectivity.online;
    this.hidden = connectivity.hidden;
    this.components = {};
    this._destroyed = false;
  }
};
const Task = class {};
`,
);
source = source.replace("export default class Core", "class Core");
source = source.replace(
  'import("./offlineReplay")',
  "Promise.resolve({ replayOfflineQueue: globalThis.replayOfflineQueue })",
);
source += "\nglobalThis.Core = Core;";
vm.runInContext(source, context);

const root = {
  dataset: { kind: "page", key: "page-1", fingerprint: "stale-root" },
  addEventListener() {},
  dispatchEvent() {},
  querySelector() { return null; },
};
const view = new context.Core(root);
let resolveReplay;
const replayReady = new Promise((resolve) => { resolveReplay = resolve; });
view.offlineQueue = {
  async replay() {
    events.push("replay");
    await replayReady;
    return 1;
  },
};
view.DeferredOperations = { nudge() { events.push("nudge"); } };
view.EditWatcher = {
  async resume() {
    events.push("watcher");
    root.dataset.fingerprint = "checked-root";
  },
};
view.SyncManager = { async register() { events.push("register"); } };
view.refresh = async (navigation, options) => {
  events.push(`refresh:${navigation}:${options?.fingerprint}`);
};

(async () => {
  const outcome = await Promise.race([
    view.sync({ hidden: false }).then(() => "synced"),
    new Promise((resolve) => setTimeout(() => resolve("blocked"), 50)),
  ]);
  if (outcome !== "synced") {
    throw new Error("Visibility sync waited for OfflineQueue replay");
  }
  const expected = [
    "nudge",
    "watcher",
    "replay",
    "refresh:false:stale-root",
    "register",
  ];
  if (JSON.stringify(events) !== JSON.stringify(expected)) {
    throw new Error(`Unexpected visibility order: ${JSON.stringify(events)}`);
  }
  resolveReplay();
  await view._offlineReplayTask;
  if (events.at(-1) !== "refresh:undefined:undefined") {
    throw new Error(`Replayed work did not reconcile afterward: ${JSON.stringify(events)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features reconnect-refresh collections forms
# @dimensions explicit-collection-scope form-exclusion
def test_component_refresh_only_loads_collection_widgets(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const events = [];
const context = {
  console,
  NavElement: class {},
  showBriefly() {},
  withTransition(callback) { return callback(); },
  loadWidget: async () => null,
};
vm.createContext(context);
let source = fs.readFileSync("src/script/views/base/component.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export default class ViewComponent", "class ViewComponent");
source += "\nglobalThis.ViewComponent = ViewComponent;";
vm.runInContext(source, context);

const clean = {
  route: "/clean",
  refreshScope: "collection",
  async refresh() { events.push("refresh:clean"); },
};
const dirty = {
  route: "/dirty",
  unsavedState: true,
  async refresh() { events.push("refresh:dirty"); },
};
const queued = {
  route: "/queued",
  form: { _queued: true },
  async refresh() { events.push("refresh:queued"); },
};
const staged = {
  route: "/staged",
  target: { querySelector() { return {}; } },
  async refresh() { events.push("refresh:staged"); },
};
const component = Object.create(context.ViewComponent.prototype);
component.widgets = { clean, dirty, queued, staged };
component.view = {
  async load(_component, route) {
    events.push(`load:${route}`);
    return { updated: true };
  },
};

(async () => {
  await component.refreshCollections();
  if (JSON.stringify(events) !== JSON.stringify(["load:/clean", "refresh:clean"])) {
    throw new Error(`Local forms were refreshed: ${JSON.stringify(events)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features tasks reconnect-refresh forms offline
# @dimensions active-row dirty-row queued-row staged-review replacement removal preservation
# @pair tasks:active-form-preservation
# @pair tasks:dirty-form-preservation
def test_task_list_refresh_preserves_rows_with_local_form_state(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const context = { BaseList: class {}, console };
vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/pageTaskList.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class PageTaskList", "class PageTaskList");
source += "\nglobalThis.PageTaskList = PageTaskList;";
vm.runInContext(source, context);

const removed = {
  remove() { throw new Error("Dirty removed row was discarded"); },
};
const replaced = {
  replaceWith() { throw new Error("Queued replacement row was discarded"); },
};
const replacement = {};
const active = {
  replaceWith() { throw new Error("Active form row was replaced before revision review"); },
};
const activeReplacement = {
  querySelector(selector) {
    return selector === "[data-widget='TaskForm']" ? {} : null;
  },
};
let incompatibleReplaced = false;
const incompatible = {
  replaceWith() { incompatibleReplaced = true; },
};
const incompatibleReplacement = {
  querySelector() { return null; },
};
let hiddenReplaced = false;
const hidden = {
  replaceWith() { hiddenReplaced = true; },
};
const hiddenReplacement = {};
const activeWidget = { name: "TaskForm", visible: true, unsavedState: false };
const incompatibleWidget = {
  name: "TaskForm",
  visible: true,
  unsavedState: false,
};
const hiddenWidget = { visible: false, unsavedState: false };
const components = new Map([
  [removed, { widgets: { TaskForm: { unsavedState: true } } }],
  [replaced, { widgets: { TaskForm: { form: { _queued: true } } } }],
  [
    active,
    {
      active: activeWidget,
      widgets: { TaskForm: activeWidget },
    },
  ],
  [
    incompatible,
    {
      active: incompatibleWidget,
      widgets: { TaskForm: incompatibleWidget },
      destroy() {},
    },
  ],
  [
    hidden,
    {
      active: hiddenWidget,
      widgets: { TaskForm: hiddenWidget },
      destroy() {},
    },
  ],
]);
const list = Object.create(context.PageTaskList.prototype);
list.component = { active: null };
list.view = { getComponent(node) { return components.get(node); } };
list.target = { setAttribute() {} };
list._updated = [];
list._removed = [removed];
list._replaced = [
  { from: replaced, to: replacement },
  { from: active, to: activeReplacement },
  { from: incompatible, to: incompatibleReplacement },
  { from: hidden, to: hiddenReplacement },
];
list._added = [];
list._created = [];
list._setListVisibility = () => {};
list._moveTaskIfNecessary = () => {};
Object.defineProperty(list, "activeCount", { value: 1 });
Object.defineProperty(list, "completedCount", { value: 0 });

(async () => {
  await list.postreconcile();
  if (list._removed.length || list._replaced.length) {
    throw new Error("Refresh work queues were not cleared");
  }
  if (!hiddenReplaced) {
    throw new Error("A hidden clean form row was not silently refreshed");
  }
  if (!incompatibleReplaced) {
    throw new Error("An active row survived after its form disappeared");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
'''
    )


# @features tasks
# @dimensions complete active-widget route-override
def test_task_completion_keeps_component_update_route_when_history_is_active(
    run_node,
):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class FakeCustomEvent {
  constructor(type, options) {
    this.type = type;
    this.bubbles = options.bubbles;
    this.detail = options.detail;
  }
}

const context = {
  BaseList: class {},
  console,
  CustomEvent: FakeCustomEvent,
  FormData,
};
vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/pageTaskList.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class PageTaskList", "class PageTaskList");
source += "\nglobalThis.PageTaskList = PageTaskList;";
vm.runInContext(source, context);

let submitted = null;
const submitter = {
  dataset: { role: "complete-toggle" },
  dispatchEvent(event) {
    submitted = event;
  },
};
const task = {
  active: { name: "TaskHistory", route: "/tasks/task/history" },
  disable() {},
  elt: { dataset: { route: "/tasks/task/update" } },
};
const list = Object.create(context.PageTaskList.prototype);
list.target = { contains() { return true; } };
list.view = { getComponent() { return task; } };

list._click({
  target: { closest() { return submitter; } },
  preventDefault() {},
  stopPropagation() {},
});

if (submitted?.type !== "submit") {
  throw new Error("Completion did not enter the shared submit pipeline");
}
if (submitted.detail.route !== "/tasks/task/update") {
  throw new Error(`Completion route drifted to ${submitted.detail.route}`);
}
if (submitted.detail.role !== "complete-toggle" || !submitted.detail.update) {
  throw new Error(`Unexpected completion detail: ${JSON.stringify(submitted.detail)}`);
}
'''
    )


# @pairs tasks:create-close tasks:empty-state tasks:completed-only
def test_task_list_empty_marker_requires_closed_create_form_and_no_tasks(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const context = { BaseList: class {}, console };
vm.createContext(context);
let source = fs.readFileSync("src/script/widgets/pageTaskList.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace("export class PageTaskList", "class PageTaskList");
source += "\nglobalThis.PageTaskList = PageTaskList;";
vm.runInContext(source, context);

const marker = { dataset: {} };
const activeTasks = {
  dataset: {},
  querySelector(selector) {
    return selector === "[data-role='empty']" ? marker : null;
  },
};
const completedHeader = { dataset: {} };
const list = Object.create(context.PageTaskList.prototype);
let activeCount = 0;
let completedCount = 0;

list.target = {
  dataset: { ifEmpty: "CreateTask" },
  hasAttribute(name) { return name === "loaded"; },
};
list._isEmpty = true;
list._created = [];
list.component = { active: { name: "CreateTask" }, widgets: {} };
Object.defineProperties(list, {
  activeTasks: { value: activeTasks },
  completedHeader: { value: completedHeader },
  activeCount: { get() { return activeCount; } },
  completedCount: { get() { return completedCount; } },
});

if (list.ifEmpty !== "CreateTask") {
  throw new Error("An initially empty task list did not default to CreateTask");
}
list.component.widgets.CreateTask = {
  visible: false,
  target: { dataset: { visible: "true" } },
};
if (list.ifEmpty !== false) {
  throw new Error("Closing CreateTask immediately reopened it");
}

list._setListVisibility();
if (marker.dataset.visible !== "false" || activeTasks.dataset.visible !== "false") {
  throw new Error("Empty marker appeared while CreateTask was open");
}

list.component.active = list;
list._setListVisibility();
if (marker.dataset.visible !== "true" || activeTasks.dataset.visible !== "true") {
  throw new Error("Empty marker did not appear after CreateTask closed");
}

completedCount = 1;
list._setListVisibility();
if (
  marker.dataset.visible !== "false" ||
  activeTasks.dataset.visible !== "false" ||
  completedHeader.dataset.visible !== "true"
) {
  throw new Error("Empty marker appeared beside a completed task");
}

completedCount = 0;
activeCount = 1;
list._setListVisibility();
if (marker.dataset.visible !== "false" || activeTasks.dataset.visible !== "true") {
  throw new Error("Active task visibility was affected by the empty marker");
}
'''
    )


# @features forms
# @dimensions direct-fields clear input textarea
def test_direct_form_controls_clear_inputs_and_textareas(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const baseContext = {
  console,
  primitives: {},
  setIcon() {},
  STYLES: {
    form: {
      icon: "",
      submission: { default: "", grows: "" },
    },
  },
};
vm.createContext(baseContext);
let baseSource = fs.readFileSync("src/script/elements/base/baseElement.mjs", "utf8");
baseSource = baseSource.replace(/^import .*$/gm, "");
baseSource = baseSource.replace("export class BaseElement", "class BaseElement");
baseSource += "\nglobalThis.BaseElement = BaseElement;";
vm.runInContext(baseSource, baseContext);

const label = { append() {} };
const root = {
  classList: { add() {} },
  dataset: {},
  querySelector(selector) {
    return selector === "[data-role='label']" ? label : null;
  },
};
const DirectElement = class extends baseContext.BaseElement {
  get edit() {
    return root;
  }
};
const direct = new DirectElement(
  { mode: "edit", readonly: false },
  { id: "name", type: "input" },
  null,
);
let clearCalls = 0;
direct.clear = () => {
  clearCalls += 1;
};
if (direct.elt._lp_element !== direct) {
  throw new Error("Direct form element did not publish its field instance");
}

const formContext = { BaseForm: class {}, console };
vm.createContext(formContext);
let formSource = fs.readFileSync("src/script/elements/form.mjs", "utf8");
formSource = formSource.replace(/^import .*$/gm, "");
formSource = formSource.replace("export class FormElement", "class FormElement");
formSource += "\nglobalThis.FormElement = FormElement;";
vm.runInContext(formSource, formContext);

const widget = new formContext.FormElement({
  readonly: false,
  target: { cloneNode() { return {}; } },
});
widget.form = { renderer: null };
const role = { dataset: { role: "clear" } };
const event = {
  preventDefault() {},
  stopPropagation() {},
  target: {
    closest(selector) {
      if (selector === ".form-element") return root;
      if (selector === "[data-role]") return role;
      return null;
    },
  },
};
widget._click(event);
if (clearCalls !== 1) {
  throw new Error("Direct form clear did not use the field attached to its root");
}

class TextareaBase {
  get submission() {
    return this._submission ?? null;
  }
  set submission(value) {
    this._submission = value;
  }
}
const textareaContext = {
  BaseElement: TextareaBase,
  console,
  primitives: {},
  STYLES: {},
};
vm.createContext(textareaContext);
let textareaSource = fs.readFileSync("src/script/elements/textarea.mjs", "utf8");
textareaSource = textareaSource.replace(/^import .*$/gm, "");
textareaSource = textareaSource.replace(
  "export class TextareaElement",
  "class TextareaElement",
);
textareaSource += "\nglobalThis.TextareaElement = TextareaElement;";
vm.runInContext(textareaSource, textareaContext);

const control = { value: "Project description" };
const textarea = new textareaContext.TextareaElement();
textarea.submission = "Project description";
textarea._edit = {
  matches() { return false; },
  querySelector(selector) {
    return selector === "textarea" ? control : null;
  },
};
textarea.clear();
if (textarea.submission !== null || control.value !== "") {
  throw new Error("Textarea clear did not reset submission and visible value");
}
'''
    )
