import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";

function replaceGlobal(t, name, value) {
	const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
	Object.defineProperty(globalThis, name, {
		configurable: true,
		writable: true,
		value,
	});
	t.after(() => {
		if (descriptor) Object.defineProperty(globalThis, name, descriptor);
		else delete globalThis[name];
	});
}

async function setupPolling(
	t,
	{
		post,
		now = null,
		random = null,
		notificationState = null,
		captureError = (error) => {
			throw error;
		},
		storageValue = null,
	} = {},
) {
	const timers = new Map();
	const cleared = new Set();
	const listeners = new Map();
	let timerId = 0;
	const storage = {
		value: storageValue,
		getItem() {
			return this.value;
		},
		setItem(_key, value) {
			this.value = value;
		},
	};
	const windowBoundary = {
		__NOTIFICATION_STATE__: notificationState,
		addEventListener(name, listener) {
			listeners.set(name, listener);
		},
		removeEventListener(name) {
			listeners.delete(name);
		},
		clearTimeout(id) {
			cleared.add(id);
			timers.delete(id);
		},
		setTimeout(callback, delay) {
			timerId += 1;
			timers.set(timerId, { id: timerId, callback, delay });
			return timerId;
		},
	};
	replaceGlobal(t, "window", windowBoundary);
	replaceGlobal(t, "sessionStorage", storage);
	replaceGlobal(t, "crypto", { randomUUID: () => "client-1" });
	if (now) replaceGlobal(t, "Date", { now });
	if (random) {
		const deterministicMath = Object.create(Math);
		deterministicMath.random = random;
		replaceGlobal(t, "Math", deterministicMath);
	}
	const request = { post };
	const { PollingCoordinator } = await esmock.strict(
		"../../src/script/shared/polling.mjs",
		{
			"../../src/script/shared/endpoints.mjs": {
				ENDPOINTS: { poll: "/l/poll" },
			},
			"../../src/script/shared/errors.mjs": { captureError },
			"../../src/script/shared/request.mjs": { request },
		},
	);
	return {
		cleared,
		listeners,
		PollingCoordinator,
		storage,
		timers,
		window: windowBoundary,
	};
}

const view = () => ({ elt: {}, hidden: false, online: true });

/** @matrix polling : acknowledgement batching cadence coalescing lifecycle terminal-operation-order */
test("test_polling_coordinator_batches_due_subscriptions_and_applies_results", async (t) => {
	const calls = [];
	const handled = [];
	let beforePolls = 0;
	let blockBeforePoll = false;
	const beforePollReleases = [];
	let blockPollResponse = false;
	let releasePollResponse = null;
	const context = await setupPolling(t, {
		async post(url, body, options = {}) {
			calls.push({ url, body, options });
			if (!body.subscriptions.length) return { ok: true };
			if (blockPollResponse)
				await new Promise((resolve) => {
					releasePollResponse = resolve;
				});
			return {
				ok: true,
				version: 1,
				results: body.subscriptions.map((item, index) => {
					const changed =
						item.id === "retry:three" ||
						index === 0 ||
						item.type === "operation";
					const revision =
						item.type === "operation" ? index + 10 : `revision-${index + 10}`;
					return {
						id: item.id,
						type: item.type,
						status: changed ? "changed" : "unchanged",
						revision,
						poll_after_ms: 15000,
						...(changed
							? {
									payload:
										item.type === "operation"
											? { key: item.key, revision, terminal: true }
											: { refresh: true },
								}
							: {}),
					};
				}),
			};
		},
	});
	const currentView = view();
	const coordinator = new context.PollingCoordinator(currentView).init();
	const beforePoll = async () => {
		beforePolls += 1;
		if (blockBeforePoll)
			await new Promise((resolve) => beforePollReleases.push(resolve));
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
		{
			id: "retry:three",
			type: "channel",
			channel: "home",
			revision: "retry-old",
		},
		{ beforePoll, onResult: () => false },
	);
	assert.equal(context.timers.size, 1);
	assert.deepEqual([...context.cleared], [1, 2]);
	await coordinator.trigger();
	assert.equal(calls.length, 1);
	assert.equal(calls[0].body.subscriptions.length, 3);
	assert.equal(beforePolls, 1);
	assert.deepEqual(
		handled.map(({ id }) => id),
		["operation:two", "entity:one"],
	);
	assert.equal(coordinator.get("entity:one").revision, "revision-10");
	assert.equal(coordinator.get("operation:two").revision, 11);
	assert.equal(coordinator.get("retry:three").revision, "retry-old");
	assert.equal(
		coordinator.subscriptions.get("entity:one").dueAt,
		coordinator.subscriptions.get("retry:three").dueAt,
	);

	blockBeforePoll = true;
	const firstTrigger = coordinator.trigger();
	const overlappingTrigger = coordinator.trigger();
	assert.equal(firstTrigger, overlappingTrigger);
	for (const release of beforePollReleases.splice(0)) release();
	await Promise.all([firstTrigger, overlappingTrigger]);
	blockBeforePoll = false;
	assert.equal(calls.length, 2);
	currentView.hidden = true;
	await coordinator.trigger();
	assert.equal(calls.length, 2);
	currentView.hidden = false;
	await coordinator.resume();
	assert.equal(calls.length, 2);
	await coordinator.catchUp();
	assert.equal(calls.length, 3);

	blockPollResponse = true;
	const activePoll = coordinator.trigger();
	for (let attempt = 0; attempt < 10 && !releasePollResponse; attempt += 1)
		await Promise.resolve();
	assert.ok(releasePollResponse);
	const closePresence = coordinator.closeDocuments([
		"one:document",
		"one:document",
	]);
	assert.equal(
		calls.some((call) => call.body.closed_documents?.length),
		false,
	);
	const handledBefore = handled.length;
	const revisionBefore = coordinator.get("entity:one").revision;
	currentView.hidden = true;
	releasePollResponse();
	await activePoll;
	await closePresence;
	assert.equal(handled.length, handledBefore);
	assert.equal(coordinator.get("entity:one").revision, revisionBefore);
	currentView.hidden = false;
	assert.equal(calls.length, 5);
	assert.deepEqual(calls[4].body.closed_documents, ["one:document"]);
	coordinator.destroy();
	assert.equal(coordinator.subscriptions.size, 0);
});

/** @pairs messaging:active-polling polling:cadence */
test("test_polling_coordinator_temporarily_boosts_a_subscription", async (t) => {
	let now = 1000;
	const context = await setupPolling(t, {
		now: () => now,
		post: async () => ({ ok: true, version: 1, results: [] }),
	});
	const coordinator = new context.PollingCoordinator(view()).init();
	coordinator.subscribe(
		{
			id: "view:channel:messages",
			type: "channel",
			channel: "messages",
			revision: null,
		},
		{ initial: "scheduled" },
	);
	const subscription = coordinator.subscriptions.get("view:channel:messages");
	assert.equal(
		coordinator.boost("view:channel:messages", {
			durationMs: 60000,
			pollAfterMs: 2000,
		}),
		true,
	);
	assert.equal(subscription.dueAt, now + 2000);
	assert.equal(
		coordinator._interval(subscription, { status: "unchanged" }),
		2000,
	);
	now += 60001;
	assert.ok(
		coordinator._interval(subscription, { status: "unchanged" }) >= 15000,
	);
});

/** @matrix polling : blur cadence visibility */
/** @pair deferred-jobs:polling */
test("test_polling_coordinator_limits_visible_blur_to_eligible_operations", async (t) => {
	const calls = [];
	const handled = [];
	let now = 1000;
	let operationVisible = true;
	let blockResponse = false;
	let releaseResponse = null;
	const context = await setupPolling(t, {
		now: () => now,
		async post(_url, body) {
			calls.push(body);
			if (blockResponse)
				await new Promise((resolve) => {
					releaseResponse = resolve;
				});
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
	});
	const currentView = view();
	const coordinator = new context.PollingCoordinator(currentView).init();
	coordinator.subscribe(
		{ id: "entity:ordinary", type: "entity", key: "ordinary", revision: "v1" },
		{ onResult: () => handled.push("entity:ordinary") },
	);
	coordinator.subscribe(
		{ id: "operation:visible", type: "operation", key: "visible", revision: 1 },
		{
			whileBlurred: () => operationVisible,
			onResult: () => handled.push("operation:visible"),
		},
	);
	currentView.hidden = true;
	coordinator.blur();
	await coordinator.trigger();
	assert.deepEqual(
		calls[0].subscriptions.map(({ id }) => id),
		["operation:visible"],
	);
	assert.deepEqual(handled, ["operation:visible"]);
	operationVisible = false;
	coordinator.notificationSeedPending = true;
	coordinator.reschedule();
	await coordinator.trigger();
	assert.equal(calls.length, 1);
	assert.equal(context.timers.size, 0);
	coordinator.notificationSeedPending = false;
	operationVisible = true;
	now = 601000;
	coordinator.reschedule();
	await coordinator.trigger();
	assert.equal(calls.length, 1);
	assert.equal(context.timers.size, 0);
	currentView.hidden = false;
	await coordinator.resume();
	handled.splice(0);
	blockResponse = true;
	const mixed = coordinator.trigger();
	for (let attempt = 0; attempt < 10 && !releaseResponse; attempt += 1)
		await Promise.resolve();
	assert.ok(releaseResponse);
	assert.equal(calls.at(-1).subscriptions.length, 2);
	currentView.hidden = true;
	coordinator.blur();
	releaseResponse();
	await mixed;
	assert.deepEqual(handled, ["operation:visible"]);
	coordinator.pause();
	const before = calls.length;
	await coordinator.trigger();
	assert.equal(calls.length, before);
	coordinator.destroy();
});

/** @matrix polling : foreground scheduled-initial */
/** @pair notifications:cold-seed */
test("test_polling_coordinator_schedules_modes_and_notification_seed", async (t) => {
	const calls = [];
	const context = await setupPolling(t, {
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
	});
	const currentView = view();
	const coordinator = new context.PollingCoordinator(currentView).init();
	coordinator.subscribe(
		{
			id: "channel:tasks",
			type: "channel",
			channel: "tasks",
			revision: "same",
		},
		{ mode: "foreground", initial: "scheduled" },
	);
	assert.equal(context.timers.size, 0);
	coordinator.subscribe(
		{ id: "entity:one", type: "entity", key: "one", revision: "same" },
		{ mode: "periodic", initial: "scheduled" },
	);
	assert.equal(context.timers.size, 1);
	assert.ok([...context.timers.values()][0].delay >= 14900);
	await coordinator.catchUp();
	assert.equal(calls.length, 1);
	assert.equal(calls[0].subscriptions.length, 2);
	assert.equal(coordinator.subscriptions.get("channel:tasks").dueAt, Infinity);
	coordinator.destroy();
	context.window.__NOTIFICATION_STATE__ = {
		generation: null,
		revision: null,
		count: null,
		miss: true,
	};
	const cold = new context.PollingCoordinator(currentView).init();
	await cold.trigger();
	assert.equal(calls.at(-1).subscriptions.length, 0);
	assert.equal(calls.at(-1).notification_state?.seed, true);
	cold.destroy();
});

/** @matrix notifications : acknowledgement bounded-backoff cold-seed zero-subscriptions */
test("test_polling_coordinator_retries_cold_seed_until_warm_acknowledgement", async (t) => {
	let now = 1000;
	const calls = [];
	let context;
	context = await setupPolling(t, {
		now: () => now,
		random: () => 0.5,
		notificationState: {
			generation: null,
			revision: null,
			count: null,
			miss: true,
		},
		async post(_url, body) {
			calls.push(body);
			if (calls.length === 1) return { ok: false, status: 503 };
			const warm = { generation: "warm", revision: 1, count: 0, miss: false };
			context.window.__NOTIFICATION_STATE__ = warm;
			context.listeners.get("notification-state")?.({ detail: warm });
			return { ok: true, version: 1, results: [] };
		},
	});
	const coordinator = new context.PollingCoordinator(view()).init();
	await coordinator.trigger();
	assert.equal(calls.length, 1);
	assert.equal(calls[0].notification_state?.seed, true);
	assert.equal(coordinator.notificationSeedPending, true);
	assert.equal(coordinator.notificationSeedDueAt, 5000);
	const retryTimer = [...context.timers.values()].at(-1);
	assert.equal(retryTimer.delay, 4000);
	assert.equal(context.cleared.has(retryTimer.id), false);
	now = coordinator.notificationSeedDueAt;
	await coordinator.trigger();
	assert.equal(calls.length, 2);
	assert.equal(calls[1].notification_state?.seed, true);
	assert.equal(coordinator.notificationSeedPending, false);
	assert.equal(coordinator.notificationSeedErrorCount, 0);
	now += 60000;
	await coordinator.trigger();
	assert.equal(calls.length, 2);
	coordinator.destroy();
});

/** @matrix polling : freshness reentrancy requested-cycle */
test("test_polling_coordinator_enqueues_reentrant_followup_without_waiting", async (t) => {
	const calls = [];
	let handled = 0;
	let blockResponse = false;
	let releaseResponse = null;
	const context = await setupPolling(t, {
		async post(_url, body) {
			calls.push(body);
			if (blockResponse)
				await new Promise((resolve) => {
					releaseResponse = resolve;
				});
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
	});
	const coordinator = new context.PollingCoordinator(view()).init();
	coordinator.subscribe(
		{ id: "entity:one", type: "entity", key: "one", revision: "old" },
		{
			onResult() {
				handled += 1;
				if (handled === 1)
					assert.equal(coordinator.enqueue("entity:one"), undefined);
			},
		},
	);
	await coordinator.trigger();
	for (let attempt = 0; attempt < 20 && handled < 2; attempt += 1)
		await Promise.resolve();
	assert.equal(calls.length, 2);
	assert.equal(handled, 2);
	assert.equal(coordinator.queuedIds.size, 0);
	if (coordinator.activePoll) await coordinator.activePoll;
	await Promise.resolve();

	blockResponse = true;
	const staleCycle = coordinator.trigger("entity:one");
	for (let attempt = 0; attempt < 20 && !releaseResponse; attempt += 1)
		await Promise.resolve();
	const freshCycle = coordinator.trigger("entity:one", { fresh: true });
	assert.notEqual(freshCycle, staleCycle);
	assert.ok(releaseResponse);
	blockResponse = false;
	releaseResponse();
	await staleCycle;
	await freshCycle;
	assert.equal(calls.length, 4);
	assert.equal(
		calls
			.slice(-2)
			.every((call) =>
				call.subscriptions.some(({ id }) => id === "entity:one"),
			),
		true,
	);

	blockResponse = true;
	releaseResponse = null;
	const active = coordinator.trigger("entity:one");
	for (let attempt = 0; attempt < 20 && !releaseResponse; attempt += 1)
		await Promise.resolve();
	coordinator.subscribe({
		id: "entity:two",
		type: "entity",
		key: "two",
		revision: "old",
	});
	const requested = coordinator.trigger("entity:two");
	assert.notEqual(requested, active);
	assert.ok(releaseResponse);
	blockResponse = false;
	releaseResponse();
	await active;
	await requested;
	assert.equal(
		calls.at(-1).subscriptions.some(({ id }) => id === "entity:two"),
		true,
	);
	coordinator.destroy();
});

/** @matrix polling : batching diagnostics presence protocol revision validation */
test("test_polling_coordinator_captures_and_isolates_contract_failures", async (t) => {
	const calls = [];
	const captured = [];
	const handled = [];
	let mode = "normal";
	const context = await setupPolling(t, {
		storageValue: "   ",
		captureError(error, _element, details) {
			captured.push({ error, details });
		},
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
			if (mode === "missing-document")
				subscriptions = subscriptions.filter(({ type }) => type !== "document");
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
	});
	const coordinator = new context.PollingCoordinator(view()).init();
	assert.equal(coordinator.clientId, "client-1");
	assert.equal(context.storage.value, "client-1");
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
	assert.equal(coordinator.get("document:invalid:document"), null);
	coordinator.subscribe({
		id: "operation:unsafe",
		type: "operation",
		key: "operation-unsafe",
		revision: Number.MAX_SAFE_INTEGER + 1,
	});
	assert.equal(coordinator.get("operation:unsafe"), null);
	coordinator.subscribe(
		{
			id: "entity:one",
			type: "entity",
			key: "entity-one",
			revision: "entity-old",
		},
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
	assert.equal(coordinator.get("entity:one").revision, "entity-old");
	const first = await coordinator.trigger();
	assert.equal(first.length, 2);
	assert.equal(coordinator.get("entity:one").revision, "entity-new");
	const documentBody = calls[0].subscriptions.find(
		({ type }) => type === "document",
	);
	assert.equal(Object.hasOwn(documentBody, "fingerprint"), false);
	assert.equal(documentBody.presence_digest, null);
	mode = "missing-document";
	const second = await coordinator.trigger();
	assert.equal(
		second.find(({ id }) => id === "document:one:document")?.status,
		"error",
	);
	await coordinator.closeDocuments([
		"one:document",
		"one:document",
		"not-a-document",
	]);
	assert.deepEqual(calls.at(-1).closed_documents, ["one:document"]);
	mode = "rejected";
	await coordinator.trigger("entity:one");
	const contexts = captured.map(({ details }) => details?.context);
	for (const expected of [
		"polling-request-contract",
		"polling-response-contract",
		"polling-request-rejected",
	])
		assert.equal(contexts.includes(expected), true);
	coordinator.destroy();
});

/** @pair polling:transport-error */
test("test_polling_coordinator_treats_failed_transport_as_retryable", async (t) => {
	let captured = 0;
	const calls = [];
	const results = [];
	const context = await setupPolling(t, {
		captureError() {
			captured += 1;
		},
		async post(url, body, options = {}) {
			calls.push({ url, body, options });
			return { ok: false, error: "Failed to fetch" };
		},
	});
	const coordinator = new context.PollingCoordinator(view()).init();
	coordinator.subscribe(
		{ id: "entity:one", type: "entity", key: "one", revision: "old" },
		{ onResult: (result) => results.push(result) },
	);
	await coordinator.trigger();
	await coordinator.closeDocuments(["one:document"]);
	assert.equal(captured, 0);
	assert.equal(results.length, 1);
	assert.equal(results[0].status, "error");
	assert.equal(calls.length, 2);
	assert.equal(
		calls.every(
			({ url, options }) =>
				url === "/l/poll" && options.replaceErrorPage === false,
		),
		true,
	);
	assert.notEqual(calls[0].options.keepalive, true);
	assert.equal(calls[1].options.keepalive, true);
});
