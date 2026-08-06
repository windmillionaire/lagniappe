"""Node-backed checks for the shared adaptive polling scheduler."""


# @features polling
# @dimensions batching cadence lifecycle coalescing acknowledgement
def test_polling_coordinator_batches_due_subscriptions_and_applies_results(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const calls = [];
const handled = [];
let beforePolls = 0;
let blockBeforePoll = false;
const beforePollReleases = [];
let blockPollResponse = false;
let releasePollResponse = null;
let timerId = 0;
const clearedTimers = [];
const context = {
  console,
  crypto: { randomUUID: () => "client-1" },
  Date,
  ENDPOINTS: { poll: "/l/poll" },
  Math,
  queueMicrotask,
  sessionStorage: {
    value: null,
    getItem() { return this.value; },
    setItem(_key, value) { this.value = value; },
  },
  captureError(error) { throw error; },
  request: {
    async post(url, body, options = {}) {
      calls.push({ url, body, options });
      if (!body.subscriptions.length) return { ok: true };
      if (blockPollResponse) {
        await new Promise((resolve) => { releasePollResponse = resolve; });
      }
      return {
        ok: true,
        version: 1,
        results: body.subscriptions.map((item, index) => ({
          id: item.id,
          type: item.type,
          status: item.id === "retry:three" || index === 0 ? "changed" : "unchanged",
          revision: item.type === "operation" ? index + 10 : `revision-${index + 10}`,
          poll_after_ms: 15000,
          ...(item.id === "retry:three" || index === 0
            ? { payload: { refresh: true } }
            : {}),
        })),
      };
    },
  },
  window: {
    clearTimeout(id) { clearedTimers.push(id); },
    setTimeout() { timerId += 1; return timerId; },
  },
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/polling.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replace("export class PollingCoordinator", "class PollingCoordinator");
source += "\nglobalThis.PollingCoordinator = PollingCoordinator;";
vm.runInContext(source, context);

const view = { elt: {}, hidden: false, online: true };
const coordinator = new context.PollingCoordinator(view).init();
const beforePoll = async () => {
  beforePolls += 1;
  if (blockBeforePoll) {
    await new Promise((resolve) => beforePollReleases.push(resolve));
  }
};
coordinator.subscribe(
  { id: "entity:one", type: "entity", key: "one", revision: "old" },
  { beforePoll, onResult: (result) => handled.push(result) },
);
coordinator.subscribe(
  { id: "operation:two", type: "operation", key: "two", revision: 2 },
  { beforePoll, onResult: (result) => handled.push(result) },
);
coordinator.subscribe(
  { id: "retry:three", type: "channel", channel: "home", revision: "retry-old" },
  { beforePoll, onResult: () => false },
);
if (timerId !== 3 || clearedTimers.join(",") !== "1,2") {
  throw new Error("New subscriptions did not advance an existing timer");
}

(async () => {
  await coordinator.trigger();
  if (calls.length !== 1 || calls[0].body.subscriptions.length !== 3) {
    throw new Error(`Due subscriptions were not batched: ${JSON.stringify(calls)}`);
  }
  if (beforePolls !== 1) {
    throw new Error(`Shared beforePoll hook ran ${beforePolls} times`);
  }
  if (handled.length !== 2 ||
      coordinator.get("entity:one").revision !== "revision-10" ||
      coordinator.get("operation:two").revision !== 11 ||
      coordinator.get("retry:three").revision !== "retry-old") {
    throw new Error("Polling results did not advance subscription cursors");
  }
  if (
    coordinator.subscriptions.get("entity:one").dueAt !==
    coordinator.subscriptions.get("retry:three").dueAt
  ) {
    throw new Error("Same-cadence subscriptions drifted into separate requests");
  }

  blockBeforePoll = true;
  const firstTrigger = coordinator.trigger();
  const overlappingTrigger = coordinator.trigger();
  if (firstTrigger !== overlappingTrigger) {
    throw new Error("Overlapping callers did not share one poll-cycle promise");
  }
  beforePollReleases.splice(0).forEach((release) => release());
  await Promise.all([firstTrigger, overlappingTrigger]);
  blockBeforePoll = false;
  if (calls.length !== 2) {
    throw new Error("Overlapping pre-poll work created duplicate requests");
  }

  view.hidden = true;
  await coordinator.trigger();
  if (calls.length !== 2) throw new Error("Hidden view continued polling");
  view.hidden = false;
  await coordinator.resume();
  if (calls.length !== 2) throw new Error("Resume performed an eager catch-up");
  await coordinator.catchUp();
  if (calls.length !== 3) throw new Error("Visible view did not catch up polling");

  blockPollResponse = true;
  const activePoll = coordinator.trigger();
  for (let attempt = 0; attempt < 10 && !releasePollResponse; attempt += 1) {
    await Promise.resolve();
  }
  if (!releasePollResponse) {
    throw new Error("Active poll did not reach the request boundary");
  }
  const closePresence = coordinator.closeDocuments([
    "one:document",
    "one:document",
  ]);
  if (calls.some((call) => call.body.closed_documents?.length)) {
    throw new Error("Presence closed before the active registration poll settled");
  }
  const handledBeforeBackgroundResponse = handled.length;
  const revisionBeforeBackgroundResponse =
    coordinator.get("entity:one").revision;
  view.hidden = true;
  releasePollResponse();
  await activePoll;
  await closePresence;
  if (
    handled.length !== handledBeforeBackgroundResponse ||
    coordinator.get("entity:one").revision !== revisionBeforeBackgroundResponse
  ) {
    throw new Error("A response arriving after suspension mutated view state");
  }
  view.hidden = false;
  if (calls.length !== 5 ||
      calls[4].body.closed_documents.join(",") !== "one:document") {
    throw new Error("Presence close was not deduplicated");
  }
  coordinator.destroy();
  if (coordinator.subscriptions.size) {
    throw new Error("Destroy did not clear subscriptions");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


# @pair polling:foreground
# @pair polling:scheduled-initial
# @pair notifications:cold-seed
def test_polling_coordinator_schedules_modes_and_notification_seed(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const calls = [];
const timers = [];
let timerId = 0;
const context = {
  console,
  crypto: { randomUUID: () => "client-1" },
  Date,
  ENDPOINTS: { poll: "/l/poll" },
  Math,
  queueMicrotask,
  sessionStorage: { getItem() { return null; }, setItem() {} },
  captureError(error) { throw error; },
  request: {
    async post(_url, body) {
      calls.push(body);
      return {
        ok: true,
        version: 1,
        results: body.subscriptions.map((item) => ({
          id: item.id,
          type: item.type,
          status: "unchanged",
          revision: item.revision,
          poll_after_ms: 15000,
        })),
      };
    },
  },
  window: {
    __NOTIFICATION_STATE__: null,
    addEventListener() {},
    removeEventListener() {},
    clearTimeout() {},
    setTimeout(callback, delay) {
      timerId += 1;
      timers.push({ callback, delay });
      return timerId;
    },
  },
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/polling.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replace("export class PollingCoordinator", "class PollingCoordinator");
source += "\nglobalThis.PollingCoordinator = PollingCoordinator;";
vm.runInContext(source, context);

const view = { elt: {}, hidden: false, online: true };
const coordinator = new context.PollingCoordinator(view).init();
coordinator.subscribe(
  { id: "channel:tasks", type: "channel", channel: "tasks", revision: "same" },
  { mode: "foreground", initial: "scheduled" },
);
if (timers.length !== 0) {
  throw new Error("Foreground-only subscription installed an idle timer");
}
coordinator.subscribe(
  { id: "entity:one", type: "entity", key: "one", revision: "same" },
  { mode: "periodic", initial: "scheduled" },
);
if (timers.length !== 1 || timers[0].delay < 14_900) {
  throw new Error(`Scheduled entity did not wait for its interval: ${JSON.stringify(timers)}`);
}

(async () => {
  await coordinator.catchUp();
  if (calls.length !== 1 || calls[0].subscriptions.length !== 2) {
    throw new Error("Foreground catch-up did not batch mounted subscriptions");
  }
  if (coordinator.subscriptions.get("channel:tasks").dueAt !== Infinity) {
    throw new Error("Foreground subscription acquired a periodic due time");
  }
  coordinator.destroy();

  context.window.__NOTIFICATION_STATE__ = {
    generation: null,
    revision: null,
    count: null,
    miss: true,
  };
  const cold = new context.PollingCoordinator(view).init();
  await cold.trigger();
  const seeded = calls.at(-1);
  if (seeded.subscriptions.length !== 0 || !seeded.notification_state?.seed) {
    throw new Error(`Cold state did not send one personal seed poll: ${JSON.stringify(seeded)}`);
  }
  cold.destroy();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


# @pair polling:reentrancy
# @pair polling:requested-cycle
# @pair polling:freshness
def test_polling_coordinator_enqueues_reentrant_followup_without_waiting(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const calls = [];
let handled = 0;
let blockResponse = false;
let releaseResponse = null;
const context = {
  console,
  crypto: { randomUUID: () => "client-1" },
  Date,
  ENDPOINTS: { poll: "/l/poll" },
  Math,
  queueMicrotask,
  sessionStorage: {
    getItem() { return null; },
    setItem() {},
  },
  captureError(error) { throw error; },
  request: {
    async post(_url, body) {
      calls.push(body);
      if (blockResponse) {
        await new Promise((resolve) => { releaseResponse = resolve; });
      }
      return {
        ok: true,
        version: 1,
        results: body.subscriptions.map((item) => ({
          id: item.id,
          type: item.type,
          status: "changed",
          revision: `revision-${calls.length}`,
          poll_after_ms: 15000,
          payload: { refresh: true },
        })),
      };
    },
  },
  window: {
    clearTimeout() {},
    setTimeout() { return 1; },
  },
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/polling.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replace("export class PollingCoordinator", "class PollingCoordinator");
source += "\nglobalThis.PollingCoordinator = PollingCoordinator;";
vm.runInContext(source, context);

const coordinator = new context.PollingCoordinator({
  elt: {},
  hidden: false,
  online: true,
}).init();
coordinator.subscribe(
  { id: "entity:one", type: "entity", key: "one", revision: "old" },
  {
    onResult() {
      handled += 1;
      if (handled === 1) {
        const result = coordinator.enqueue("entity:one");
        if (result !== undefined) {
          throw new Error("Enqueue exposed an awaitable active-cycle result");
        }
      }
    },
  },
);

(async () => {
  await coordinator.trigger();
  for (let attempt = 0; attempt < 20 && handled < 2; attempt += 1) {
    await Promise.resolve();
  }
  if (calls.length !== 2 || handled !== 2) {
    throw new Error(
      `Reentrant enqueue did not run one follow-up cycle: ${calls.length}/${handled}`,
    );
  }
  if (coordinator.queuedIds.size) {
    throw new Error("Completed follow-up left queued subscription IDs");
  }
  if (coordinator.activePoll) await coordinator.activePoll;
  await Promise.resolve();

  blockResponse = true;
  const staleCycle = coordinator.trigger("entity:one");
  for (let attempt = 0; attempt < 20 && !releaseResponse; attempt += 1) {
    await Promise.resolve();
  }
  const freshCycle = coordinator.trigger("entity:one", { fresh: true });
  if (freshCycle === staleCycle) {
    throw new Error("Fresh trigger reused a poll that began before invalidation");
  }
  if (!releaseResponse) {
    throw new Error("Stale cycle did not reach the response boundary");
  }
  blockResponse = false;
  releaseResponse();
  await staleCycle;
  await freshCycle;
  if (calls.length !== 4 ||
      !calls.slice(-2).every((call) =>
        call.subscriptions.some((item) => item.id === "entity:one"))) {
    throw new Error("Fresh invalidation did not run one post-write poll cycle");
  }

  blockResponse = true;
  releaseResponse = null;
  const active = coordinator.trigger("entity:one");
  for (let attempt = 0; attempt < 20 && !releaseResponse; attempt += 1) {
    await Promise.resolve();
  }
  coordinator.subscribe(
    { id: "entity:two", type: "entity", key: "two", revision: "old" },
  );
  const requested = coordinator.trigger("entity:two");
  if (requested === active) {
    throw new Error("New subscription reused a cycle that could not contain it");
  }
  if (!releaseResponse) {
    throw new Error("Active cycle did not reach the response boundary");
  }
  blockResponse = false;
  releaseResponse();
  await active;
  await requested;
  if (!calls.at(-1).subscriptions.some((item) => item.id === "entity:two")) {
    throw new Error("Awaited trigger resolved without polling its requested ID");
  }

  coordinator.destroy();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


# @pairs polling:validation polling:diagnostics polling:presence
# @pairs polling:protocol polling:revision polling:batching
def test_polling_coordinator_captures_and_isolates_contract_failures(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

const calls = [];
const captured = [];
const handled = [];
let mode = "normal";
const context = {
  console,
  crypto: { randomUUID: () => "client-1" },
  Date,
  ENDPOINTS: { poll: "/l/poll" },
  Math,
  queueMicrotask,
  sessionStorage: {
    value: "   ",
    getItem() { return this.value; },
    setItem(_key, value) { this.value = value; },
  },
  captureError(error, _element, details) { captured.push({ error, details }); },
  request: {
    async post(_url, body) {
      calls.push(body);
      if (mode === "rejected") {
        return {
          ok: false,
          status: 422,
          code: "invalid_poll_contract",
          path: "subscriptions[0].revision",
          reason: "type",
        };
      }
      let subscriptions = body.subscriptions;
      if (mode === "missing-document") {
        subscriptions = subscriptions.filter((item) => item.type !== "document");
      }
      return {
        ok: true,
        version: 1,
        results: subscriptions.map((item) => {
          if (item.type === "document") {
            return {
              id: item.id,
              type: item.type,
              status: "changed",
              revision: 1,
              poll_after_ms: 2000,
              payload: {
                generation: "generation-one",
                revision: 1,
                presence_digest: "presence-one",
              },
            };
          }
          const changed = item.revision !== "entity-new";
          return {
            id: item.id,
            type: item.type,
            status: changed ? "changed" : "unchanged",
            revision: "entity-new",
            poll_after_ms: 15000,
            ...(changed ? { payload: { refresh: true } } : {}),
          };
        }),
      };
    },
  },
  window: {
    addEventListener() {},
    removeEventListener() {},
    clearTimeout() {},
    setTimeout() { return 1; },
  },
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/polling.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replace("export class PollingCoordinator", "class PollingCoordinator");
source += "\nglobalThis.PollingCoordinator = PollingCoordinator;";
vm.runInContext(source, context);

const coordinator = new context.PollingCoordinator({
  elt: {}, hidden: false, online: true,
}).init();
if (coordinator.clientId !== "client-1" || context.sessionStorage.value !== "client-1") {
  throw new Error("Invalid stored client identity was not replaced");
}

coordinator.subscribe({
  id: "document:invalid:document",
  type: "document",
  key: "entity-invalid",
  sync_id: "invalid:document",
  generation: null,
  revision: 0,
  presence_digest: null,
  fingerprint: "must-not-be-sent",
});
if (coordinator.get("document:invalid:document")) {
  throw new Error("Invalid descriptor was registered");
}
coordinator.subscribe({
  id: "operation:unsafe",
  type: "operation",
  key: "operation-unsafe",
  revision: Number.MAX_SAFE_INTEGER + 1,
});
if (coordinator.get("operation:unsafe")) {
  throw new Error("Unsafe integer descriptor was registered");
}

coordinator.subscribe(
  { id: "entity:one", type: "entity", key: "entity-one", revision: "entity-old" },
  { onResult: (result) => handled.push(result) },
);
coordinator.subscribe(
  {
    id: "document:one:document",
    type: "document",
    key: "entity-one",
    sync_id: "one:document",
    generation: null,
    revision: 0,
    presence_digest: null,
  },
  { onResult: (result) => handled.push(result) },
);
const external = coordinator.get("entity:one");
external.revision = "tampered";
coordinator.update("entity:one", { revision: { invalid: true } });
if (coordinator.get("entity:one").revision !== "entity-old") {
  throw new Error("Invalid external/update mutation changed the accepted descriptor");
}

(async () => {
  const first = await coordinator.trigger();
  if (first.length !== 2 || coordinator.get("entity:one").revision !== "entity-new") {
    throw new Error(`Valid results were not applied: ${JSON.stringify(first)}`);
  }
  const documentBody = calls[0].subscriptions.find((item) => item.type === "document");
  if (Object.hasOwn(documentBody, "fingerprint") ||
      documentBody.presence_digest !== null) {
    throw new Error(`Document request was not canonical: ${JSON.stringify(documentBody)}`);
  }

  mode = "missing-document";
  const second = await coordinator.trigger();
  const missing = second.find((result) => result.id === "document:one:document");
  if (missing?.status !== "error") {
    throw new Error(`Missing result was not isolated: ${JSON.stringify(second)}`);
  }

  await coordinator.closeDocuments([
    "one:document",
    "one:document",
    "not-a-document",
  ]);
  const close = calls.at(-1);
  if (close.closed_documents.join(",") !== "one:document") {
    throw new Error(`Close request was not canonical: ${JSON.stringify(close)}`);
  }

  mode = "rejected";
  await coordinator.trigger("entity:one");
  const contexts = captured.map((entry) => entry.details?.context);
  for (const expected of [
    "polling-request-contract",
    "polling-response-contract",
    "polling-request-rejected",
  ]) {
    if (!contexts.includes(expected)) {
      throw new Error(`Missing ${expected} capture: ${JSON.stringify(contexts)}`);
    }
  }
  coordinator.destroy();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )


# @pair polling:transport-error
def test_polling_coordinator_treats_failed_transport_as_retryable(run_node):
    run_node(
        r"""
const fs = require("node:fs");
const vm = require("node:vm");

let captured = 0;
const results = [];
const context = {
  console,
  crypto: { randomUUID: () => "client-1" },
  Date,
  ENDPOINTS: { poll: "/l/poll" },
  Math,
  queueMicrotask,
  sessionStorage: { getItem() { return null; }, setItem() {} },
  captureError() { captured += 1; },
  request: { async post() { return { ok: false, error: "Failed to fetch" }; } },
  window: { clearTimeout() {}, setTimeout() { return 1; } },
};
context.globalThis = context;
vm.createContext(context);
let source = fs.readFileSync("src/script/shared/polling.mjs", "utf8");
source = source.replace(/^import .*;\n/gm, "");
source = source.replace("export class PollingCoordinator", "class PollingCoordinator");
source += "\nglobalThis.PollingCoordinator = PollingCoordinator;";
vm.runInContext(source, context);

const coordinator = new context.PollingCoordinator({
  elt: {}, hidden: false, online: true,
}).init();
coordinator.subscribe(
  { id: "entity:one", type: "entity", key: "one", revision: "old" },
  { onResult: (result) => results.push(result) },
);

(async () => {
  await coordinator.trigger();
  if (captured !== 0) throw new Error("Transport failure was captured as a defect");
  if (results.length !== 1 || results[0].status !== "error") {
    throw new Error(`Transport failure did not schedule an error result: ${JSON.stringify(results)}`);
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
    )
