"""Node-backed checks for the polling-based SyncManager."""


# @features sync polling
# @dimensions document collaboration offline-replay cursor-retention presence lifecycle batching active-widget visibility retry-boundary reconnect-generation
# @pairs sync:active-widget sync:visibility sync:offline-replay
# @pairs polling:active-widget polling:visibility polling:document
# @pairs sync:checkpoint sync:persistence sync:dirty-state
# @pairs offline:offline-replay offline:queue-preserved offline:reconnect-generation
# @pairs offline:retry-boundary sync:reconnect-generation sync:retry-boundary
def test_sync_manager_uses_polling_subscriptions(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const requestCalls = [];
const offlineWrites = [];
const deletedSyncIds = [];
const closed = [];
let checkpointAccepted = true;
let headlessFactory = async () => null;
let offlineRecords = [];
let pollResult = null;
let responseOk = true;
const subscriptions = new Map();
const coordinator = {
  clientId: "client-1",
  subscribe(descriptor, hooks) {
    subscriptions.set(descriptor.id, { descriptor: { ...descriptor }, ...hooks });
    return () => subscriptions.delete(descriptor.id);
  },
  get(id) { return subscriptions.get(id)?.descriptor ?? null; },
  update(id, patch) {
    const subscription = subscriptions.get(id);
    if (subscription) Object.assign(subscription.descriptor, patch);
  },
  async trigger(id) {
    const result = {
      id,
      ...(pollResult ?? {
        status: "changed",
        revision: 0,
        payload: {
          mode: "snapshot",
          generation: "generation-1",
          revision: 0,
          ydoc: "snapshot-1",
        },
      }),
    };
    const subscription = subscriptions.get(id);
    if (subscription) {
      subscription.descriptor.revision = result.revision;
      if (result.payload?.generation) {
        subscription.descriptor.generation = result.payload.generation;
      }
      await subscription.onResult?.(result);
    }
    return [result];
  },
  async closeDocuments(ids) { closed.push(...ids); },
};
const offline = {
  deleteSyncRecord: async (syncId) => deletedSyncIds.push(syncId),
  deleteSyncRecords: async () => undefined,
  getAllOfflineRecords: async () => ({ sync: offlineRecords }),
  getSyncRecord: async () => null,
  updateSyncRecord: async (record) => offlineWrites.push(record),
};
const context = {
  console,
  ENDPOINTS: { sync: "/l/sync" },
  loadHeadlessWidget: async (settings) => headlessFactory(settings),
  offline,
  request: {
    async post(url, body, options = {}) {
      requestCalls.push({ url, body, options });
      if (!responseOk) return { ok: false, error: "temporarily unavailable" };
      return {
        ok: true,
        updates: body.updates.map((update) => {
          const accepted = Boolean(checkpointAccepted && update.ydoc);
          const persisted = Boolean(
            accepted && update.save && Object.hasOwn(update, "html"),
          );
          const touchOnly = Boolean(
            update.touch_parent &&
            !update.update &&
            !update.ydoc &&
            !Object.hasOwn(update, "html"),
          );
          return {
            sync_id: update.sync_id,
            generation: "generation-1",
            revision: requestCalls.length,
            checkpoint_accepted: accepted,
            checkpoint_persisted: persisted,
            entity_touched: Boolean(
              update.touch_parent && (persisted || touchOnly),
            ),
          };
        }),
      };
    },
  },
  waitForAttribute: async () => undefined,
  window: { addEventListener() {}, removeEventListener() {} },
};
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/sync.mjs", "utf8");
source = source.replace(
  'import { loadHeadlessWidget } from "../widgets/loader";',
  "const loadHeadlessWidget = globalThis.loadHeadlessWidget;",
);
source = source.replace(
  'import { ENDPOINTS } from "./endpoints";',
  "const ENDPOINTS = globalThis.ENDPOINTS;",
);
source = source.replace(
  /import \{[\s\S]*?\} from "\.\/offline";/,
  `const {
    deleteSyncRecord,
    deleteSyncRecords,
    getAllOfflineRecords,
    getSyncRecord,
    updateSyncRecord,
  } = globalThis.offline;`,
);
source = source.replace(
  'import { request } from "./request";',
  "const request = globalThis.request;",
);
source = source.replace(
  'import { waitForAttribute } from "./utilities";',
  "const waitForAttribute = globalThis.waitForAttribute;",
);
source = source.replace("export class SyncManager", "class SyncManager");
source += "\nglobalThis.SyncManager = SyncManager;";
vm.runInContext(source, context);

const payloads = [{ update: "delta-1", ydoc: "checkpoint-1" }];
const savePayloads = [];
const component = { key: "entity-key", visible: true, widgets: {} };
const widget = {
  component,
  fingerprint: "fingerprint-1",
  initialized: false,
  syncId: "entity:document",
  visible: true,
  get syncData() { return payloads.shift() ?? null; },
  get saveData() { return savePayloads.shift() ?? null; },
  commitSavedBaseline(snapshot) {
    this.snapshot = snapshot;
    this.commitCalls = (this.commitCalls ?? 0) + 1;
  },
  async sync() {},
};
component.active = widget;
component.widgets.document = widget;
const hiddenAncestor = {
  dataset: { visible: "false" },
  parentElement: { closest() { return null; } },
};
const hiddenComponent = {
  key: "entity-key",
  visible: true,
  widgets: {},
  elt: {
    parentElement: {
      closest(selector) {
        return selector === "[lp-component]" ? hiddenAncestor : null;
      },
    },
  },
};
const hiddenWidget = {
  component: hiddenComponent,
  fingerprint: "fingerprint-hidden",
  initialized: true,
  syncId: "hidden:document",
  visible: true,
  get syncData() { return null; },
  get saveData() { return null; },
  async sync() {},
};
hiddenComponent.active = hiddenWidget;
hiddenComponent.widgets.document = hiddenWidget;
const view = {
  components: { document: component, hiddenDocument: hiddenComponent },
  hidden: false,
  online: true,
  PollingCoordinator: coordinator,
};
const manager = new context.SyncManager(view);

(async () => {
  const remote = await manager.state(widget);
  if (remote?.generation !== "generation-1") {
    throw new Error(`State did not come from polling: ${JSON.stringify(remote)}`);
  }
  let subscription = subscriptions.get("document:entity:document");
  if (!subscription || subscription.descriptor.type !== "document") {
    throw new Error("Document polling subscription was not installed");
  }
  if (
    subscription.descriptor.generation !== "generation-1" ||
    subscription.descriptor.revision !== 0
  ) {
    throw new Error("Initial document state did not retain its accepted cursor");
  }
  await manager.reconcileSubscriptions();
  if (!subscriptions.has("document:entity:document")) {
    throw new Error("Mounting active document lost its polling subscription");
  }
  widget.initialized = true;
  if (subscriptions.has("document:hidden:document")) {
    throw new Error("Document inside a hidden parent received a subscription");
  }
  await manager.sendUpdates(false);
  if (requestCalls.length !== 1 ||
      requestCalls[0].body.client_id !== "client-1" ||
      requestCalls[0].body.updates[0].generation !== "generation-1" ||
      requestCalls[0].body.updates[0].revision !== 0) {
    throw new Error(`Revisioned sync request was malformed: ${JSON.stringify(requestCalls)}`);
  }
  if (subscription.descriptor.revision !== 1) {
    throw new Error("Sync acknowledgement did not advance the poll cursor");
  }

  checkpointAccepted = false;
  await manager.sendUpdates(true, [{
    key: "entity-key",
    sync_id: "entity:document",
    generation: "generation-1",
    revision: 1,
    ydoc: "stale-checkpoint",
    html: "<p>Stale</p>",
    save: true,
  }]);
  if (subscription.descriptor.revision !== 1 ||
      offlineWrites.at(-1)?.ydoc !== "stale-checkpoint") {
    throw new Error("Rejected checkpoint advanced the cursor or was not retained");
  }

  checkpointAccepted = true;
  Object.assign(subscription.descriptor, { generation: "generation-1", revision: 2 });
  savePayloads.push({ ydoc: "merged-checkpoint", html: "<p>Merged</p>" });
  await subscription.beforePoll();
  if (requestCalls.length !== 2) {
    throw new Error("Rejected checkpoint was retried before polling missing deltas");
  }
  await subscription.onResult({
    id: subscription.descriptor.id,
    status: "changed",
    payload: {
      mode: "delta",
      generation: "generation-1",
      revision: 2,
      updates: [{ revision: 2, update: "remote-delta" }],
    },
  });
  if (requestCalls.length !== 3 ||
      requestCalls[2].body.updates[0].ydoc !== "merged-checkpoint" ||
      subscription.descriptor.revision !== 3 ||
      widget.snapshot !== "merged-checkpoint" ||
      widget.commitCalls !== 1) {
    throw new Error("Rejected checkpoint was not retried after polling");
  }

  responseOk = false;
  savePayloads.push({
    ydoc: "retry-after-transport-error",
    html: "<p>Retry</p>",
  });
  await manager.sendUpdates(true);
  if (offlineWrites.at(-1)?.ydoc !== "retry-after-transport-error") {
    throw new Error("Failed checkpoint was not retained for retry");
  }
  responseOk = true;
  savePayloads.push({
    ydoc: "retry-after-transport-error",
    html: "<p>Retry</p>",
  });
  await subscription.beforePoll();
  if (requestCalls.length !== 5 ||
      widget.snapshot !== "retry-after-transport-error") {
    throw new Error("Retained checkpoint was not retried before document poll");
  }

  view.connectivityGeneration = 1;
  manager._offlineReplayAttempts.set(widget.syncId, 1);
  savePayloads.push({
    ydoc: "blocked-same-reconnect",
    html: "<p>Blocked same reconnect</p>",
  });
  const requestsBeforeBlockedReplay = requestCalls.length;
  await manager.sendUpdates(true);
  if (requestCalls.length !== requestsBeforeBlockedReplay) {
    throw new Error("Failed replay was retried by catch-up in the same generation");
  }
  view.connectivityGeneration = 2;
  await manager.sendUpdates(true);
  if (requestCalls.length !== requestsBeforeBlockedReplay + 1) {
    throw new Error("Retained replay did not become eligible in a new generation");
  }

  widget.visible = false;
  component.active = null;
  await manager.reconcileSubscriptions();
  const deactivationTouch = requestCalls.at(-1)?.body?.updates?.[0];
  if (
      subscriptions.has("document:entity:document") ||
      closed.at(-1) !== "entity:document" ||
      deactivationTouch?.touch_parent !== true ||
      deactivationTouch?.ydoc !== undefined ||
      manager._pendingParentTouches.has("entity:document")
  ) {
    throw new Error(
      `Deactivated document did not mask its lifecycle touch: ${JSON.stringify({
        deactivationTouch,
        closed,
      })}`,
    );
  }
  component.active = widget;
  widget.visible = true;
  await manager.reconcileSubscriptions();
  subscription = subscriptions.get("document:entity:document");
  if (!subscription) {
    throw new Error("Reactivated document did not restore polling");
  }

  view.online = false;
  savePayloads.push({
    ydoc: "offline-checkpoint",
    html: "<p>Offline checkpoint</p>",
  });
  const descriptorBeforeDeregister = { ...subscription.descriptor };
  await manager.deregister();
  if (closed.at(-1) !== "entity:document" || closed.length !== 2) {
    throw new Error(`Presence was not closed: ${JSON.stringify(closed)}`);
  }
  const offlineCheckpoint = offlineWrites.at(-1);
  if (
      offlineCheckpoint?.generation !== descriptorBeforeDeregister.generation ||
      offlineCheckpoint?.revision !== descriptorBeforeDeregister.revision ||
      offlineCheckpoint?.ydoc !== "offline-checkpoint" ||
      offlineCheckpoint?.touch_parent !== true) {
    throw new Error(
      `Deregister discarded the document cursor before saving: ${JSON.stringify(offlineCheckpoint)}`,
    );
  }

  payloads.push({ update: "offline-delta", ydoc: "offline-state" });
  await manager.sendUpdates(false);
  const offlineDelta = offlineWrites.at(-1);
  if (
      offlineDelta?.update !== "offline-delta" ||
      offlineDelta?.generation !== descriptorBeforeDeregister.generation ||
      offlineDelta?.revision !== descriptorBeforeDeregister.revision) {
    throw new Error(
      `Offline document update lost its retained cursor: ${JSON.stringify(offlineDelta)}`,
    );
  }

  const replayRecord = {
    key: "replay-key",
    sync_id: "replay:document",
    fingerprint: "fingerprint-replay",
    generation: "generation-1",
    revision: 2,
    ydoc: "offline-state",
    html: "<p>Offline</p>",
    save: true,
    touch_parent: true,
  };
  offlineRecords = [replayRecord];
  pollResult = {
    status: "changed",
    revision: 4,
    payload: {
      mode: "delta",
      generation: "generation-1",
      revision: 4,
      updates: [{ revision: 4, update: "remote-delta" }],
    },
  };
  let merged = false;
  let replayDestroyed = false;
  headlessFactory = async ({ sync_id }) => ({
    syncId: sync_id,
    key: replayRecord.key,
    fingerprint: replayRecord.fingerprint,
    initialized: true,
    readonly: true,
    remote: null,
    offlineRecord: null,
    async init() {},
    async sync() {
      merged = (
        this.remote?.updates?.[0]?.update === "remote-delta" &&
        this.offlineRecord?.ydoc === "offline-state"
      );
      this.remote = null;
      this.offlineRecord = null;
    },
    get saveData() {
      return merged
        ? {
            update: "merged-update",
            ydoc: "merged-checkpoint",
            html: "<p>Remote Offline</p>",
          }
        : null;
    },
    destroy() { replayDestroyed = true; },
  });

  const replayView = {
    components: {},
    online: true,
    PollingCoordinator: coordinator,
  };
  const replayManager = new context.SyncManager(replayView).init();
  await replayManager.ready;
  const replayRequest = requestCalls.at(-1)?.body?.updates?.[0];
  if (
      !merged ||
      replayRequest?.generation !== "generation-1" ||
      replayRequest?.revision !== 4 ||
      replayRequest?.ydoc !== "merged-checkpoint" ||
      replayRequest?.touch_parent !== true ||
      !deletedSyncIds.includes("replay:document") ||
      !replayDestroyed ||
      closed.at(-1) !== "replay:document") {
    throw new Error(
      `Headless replay did not fetch, merge, checkpoint, and clear: ${JSON.stringify({
        merged,
        replayRequest,
        deletedSyncIds,
        replayDestroyed,
        closed,
      })}`,
    );
  }

  const requestsBeforeFailedReplay = requestCalls.length;
  replayView.connectivityGeneration = 1;
  responseOk = false;
  await replayManager.register();
  if (requestCalls.length !== requestsBeforeFailedReplay + 1) {
    throw new Error("Failed replay did not make exactly one request");
  }
  await replayManager.register();
  if (requestCalls.length !== requestsBeforeFailedReplay + 1) {
    throw new Error("Coalesced registration retried within one connectivity generation");
  }

  replayView.connectivityGeneration = 2;
  responseOk = true;
  await replayManager.register();
  if (requestCalls.length !== requestsBeforeFailedReplay + 2) {
    throw new Error("A new connectivity generation did not retry retained replay work");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )
