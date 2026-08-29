"""Node-backed contracts for ordered application mutation replay."""


OFFLINE_QUEUE_HARNESS = r'''
const fs = require("node:fs");
const vm = require("node:vm");

const deleted = [];
const context = {
  console,
  deleteOfflineMutations: async (ids) => { deleted.push(...ids); },
  document: { querySelector() { return null; } },
  File: class {},
  FormData: class {},
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

const makeRecord = (id, createdAt, overrides = {}) => ({
  id,
  action: "update",
  kind: "test",
  method: "POST",
  route: `/${id}`,
  target_key: id,
  fingerprint: `fingerprint-${id}`,
  fields: [],
  files: [],
  created_at: createdAt,
  ...overrides,
});

const makeQueue = (records) => {
  const queue = new context.OfflineQueue({ online: true, components: {} });
  queue.records = records;
  return queue;
};
'''


def run_offline_queue_check(run_node, script):
    run_node(OFFLINE_QUEUE_HARNESS + script)


# @matrix offline : queue-preserved replay-order
def test_offline_replay_blocks_later_records_after_the_oldest_record_fails(
    run_node,
):
    run_offline_queue_check(
        run_node,
        r'''
(async () => {
  const scenarios = [
    {
      name: "unchanged conflict",
      response: { ok: true, conflict: true },
      expectedPhases: ["conflict"],
    },
    {
      name: "non-OK response",
      response: { ok: false },
      expectedPhases: [],
    },
    {
      name: "error envelope",
      response: { ok: true, error: "Replay failed" },
      expectedPhases: [],
    },
  ];

  for (const scenario of scenarios) {
    deleted.length = 0;
    const queue = makeQueue([
      makeRecord("first", 1),
      makeRecord("second", 2),
    ]);
    const sent = [];
    const phases = [];
    queue._send = async (record) => {
      sent.push(record.id);
      return scenario.response;
    };
    queue._dispatch = async ({ phase }) => { phases.push(phase); };

    const completed = await queue.replay();
    const remaining = queue.records.map(({ id }) => id);
    if (
      completed !== 0 ||
      sent.join(",") !== "first" ||
      deleted.length !== 0 ||
      remaining.join(",") !== "first,second" ||
      JSON.stringify(phases) !== JSON.stringify(scenario.expectedPhases) ||
      queue._replaying
    ) {
      throw new Error(
        `${scenario.name} crossed the ordered replay boundary: ${JSON.stringify({
          completed,
          sent,
          deleted,
          remaining,
          phases,
          replaying: queue._replaying,
        })}`,
      );
    }
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
''',
    )


# @matrix offline : queue-preserved replay-order retry-boundary
def test_offline_replay_returns_the_completed_prefix_and_retries_the_oldest_record(
    run_node,
):
    run_offline_queue_check(
        run_node,
        r'''
(async () => {
  const queue = makeQueue([
    makeRecord("first", 1),
    makeRecord("second", 2),
  ]);
  const sent = [];
  const phases = [];
  let secondFailed = false;
  queue._send = async (record) => {
    sent.push(record.id);
    if (record.id === "second" && !secondFailed) {
      secondFailed = true;
      return { ok: false, error: "Temporary failure" };
    }
    return { ok: true };
  };
  queue._dispatch = async ({ phase, record }) => {
    phases.push(`${phase}:${record.id}`);
  };

  const firstPass = await queue.replay();
  if (
    firstPass !== 1 ||
    sent.join(",") !== "first,second" ||
    deleted.join(",") !== "first" ||
    queue.records.map(({ id }) => id).join(",") !== "second" ||
    phases.join(",") !== "replayed:first" ||
    queue._replaying
  ) {
    throw new Error(
      `Replay did not retain the failed suffix: ${JSON.stringify({
        firstPass,
        sent,
        deleted,
        remaining: queue.records,
        phases,
        replaying: queue._replaying,
      })}`,
    );
  }

  const secondPass = await queue.replay();
  if (
    secondPass !== 1 ||
    sent.join(",") !== "first,second,second" ||
    deleted.join(",") !== "first,second" ||
    queue.records.length !== 0 ||
    phases.join(",") !== "replayed:first,replayed:second" ||
    queue._replaying
  ) {
    throw new Error(
      `Fresh replay did not resume from the oldest record: ${JSON.stringify({
        secondPass,
        sent,
        deleted,
        remaining: queue.records,
        phases,
        replaying: queue._replaying,
      })}`,
    );
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
''',
    )


# @matrix offline : conflict-rebase replay-order
def test_offline_replay_retries_rebased_record_before_later_record(run_node):
    run_offline_queue_check(
        run_node,
        r'''
(async () => {
  const first = makeRecord("first", 1, { fingerprint: "originating" });
  const second = makeRecord("second", 2);
  const queue = makeQueue([first, second]);
  const sent = [];
  const phases = [];
  let rebasedIdentity = null;
  queue._send = async (record) => {
    sent.push(`${record.id}:${record.fingerprint}`);
    if (record.id === "first" && record.fingerprint === "originating") {
      return { ok: true, conflict: true };
    }
    return { ok: true };
  };
  queue._dispatch = async ({ phase, record }) => {
    phases.push(`${phase}:${record.id}`);
    if (phase !== "conflict") return;
    const rebased = { ...record, fingerprint: "current" };
    await queue._store(rebased);
    rebasedIdentity = { id: rebased.id, created_at: rebased.created_at };
  };

  const completed = await queue.replay();
  if (
    completed !== 2 ||
    sent.join(",") !==
      "first:originating,first:current,second:fingerprint-second" ||
    phases.join(",") !==
      "conflict:first,replayed:first,replayed:second" ||
    deleted.join(",") !== "first,second" ||
    rebasedIdentity?.id !== first.id ||
    rebasedIdentity?.created_at !== first.created_at ||
    queue.records.length !== 0
  ) {
    throw new Error(
      `Rebased replay advanced out of order: ${JSON.stringify({
        completed,
        sent,
        phases,
        deleted,
        rebasedIdentity,
        remaining: queue.records,
      })}`,
    );
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
''',
    )


# @matrix offline : queue-preserved replay-order retry-boundary
def test_offline_replay_releases_ownership_after_handler_errors(run_node):
    run_offline_queue_check(
        run_node,
        r'''
(async () => {
  const conflictQueue = makeQueue([
    makeRecord("conflict-first", 1),
    makeRecord("conflict-second", 2),
  ]);
  const conflictSent = [];
  conflictQueue._send = async (record) => {
    conflictSent.push(record.id);
    return { ok: true, conflict: true };
  };
  conflictQueue._dispatch = async () => {
    throw new Error("Conflict handler failed");
  };

  let conflictError = null;
  try {
    await conflictQueue.replay();
  } catch (error) {
    conflictError = error;
  }
  if (
    conflictError?.message !== "Conflict handler failed" ||
    conflictSent.join(",") !== "conflict-first" ||
    deleted.length !== 0 ||
    conflictQueue.records.map(({ id }) => id).join(",") !==
      "conflict-first,conflict-second" ||
    conflictQueue._replaying
  ) {
    throw new Error(
      `Conflict handler failure lost replay ownership: ${JSON.stringify({
        error: conflictError?.message,
        sent: conflictSent,
        deleted,
        remaining: conflictQueue.records,
        replaying: conflictQueue._replaying,
      })}`,
    );
  }

  conflictQueue._send = async (record) => {
    conflictSent.push(record.id);
    return { ok: true };
  };
  conflictQueue._dispatch = async () => {};
  const conflictRetry = await conflictQueue.replay();
  if (
    conflictRetry !== 2 ||
    conflictSent.join(",") !==
      "conflict-first,conflict-first,conflict-second" ||
    conflictQueue.records.length !== 0
  ) {
    throw new Error("Conflict handler retry did not restart at the oldest record");
  }

  deleted.length = 0;
  const replayedQueue = makeQueue([
    makeRecord("replayed-first", 1),
    makeRecord("replayed-second", 2),
  ]);
  const replayedSent = [];
  replayedQueue._send = async (record) => {
    replayedSent.push(record.id);
    return { ok: true };
  };
  replayedQueue._dispatch = async ({ phase, record }) => {
    if (phase === "replayed" && record.id === "replayed-first") {
      throw new Error("Replayed handler failed");
    }
  };

  let replayedError = null;
  try {
    await replayedQueue.replay();
  } catch (error) {
    replayedError = error;
  }
  if (
    replayedError?.message !== "Replayed handler failed" ||
    replayedSent.join(",") !== "replayed-first" ||
    deleted.join(",") !== "replayed-first" ||
    replayedQueue.records.map(({ id }) => id).join(",") !== "replayed-second" ||
    replayedQueue._replaying
  ) {
    throw new Error(
      `Replayed handler failure crossed the retained suffix: ${JSON.stringify({
        error: replayedError?.message,
        sent: replayedSent,
        deleted,
        remaining: replayedQueue.records,
        replaying: replayedQueue._replaying,
      })}`,
    );
  }

  replayedQueue._dispatch = async () => {};
  const replayedRetry = await replayedQueue.replay();
  if (
    replayedRetry !== 1 ||
    replayedSent.join(",") !== "replayed-first,replayed-second" ||
    deleted.join(",") !== "replayed-first,replayed-second" ||
    replayedQueue.records.length !== 0
  ) {
    throw new Error("Replayed handler retry did not resume at the retained suffix");
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
''',
    )
