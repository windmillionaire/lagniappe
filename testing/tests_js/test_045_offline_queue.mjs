import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser, installIndexedDB } from "../utility/js/environment.mjs";

async function setup(t, options = {}) {
	const dom = createBrowser(t, { formData: "native", ...options });
	installIndexedDB(t, dom.window);
	const storage = await import("../../src/script/shared/offline.mjs");
	let respond = () => ({ ok: true });
	let handle = () => {};
	const sent = [];
	const phases = [];
	const send = t.mock.fn(async (route, data) => {
		sent.push({
			id: route.slice(1),
			fingerprint: data.get("offline-fingerprint"),
			data,
		});
		return respond(route, data);
	});
	const { OfflineQueue } = await esmock.strict(
		"../../src/script/shared/offlineQueue.mjs",
		{
			"../../src/script/shared/request.mjs": {
				request: { post: send, put: send, delete: send },
			},
		},
	);
	const widget = {
		handleOfflineQueue: async (context) => {
			if (context.phase !== "queued")
				phases.push(`${context.phase}:${context.record.id}`);
			return handle(context);
		},
	};
	const view = {
		online: true,
		components: { main: { widgets: { test: widget } } },
	};
	return {
		dom,
		storage,
		sent,
		phases,
		OfflineQueue,
		view,
		respond(fn) {
			respond = fn;
		},
		handle(fn) {
			handle = fn;
		},
		async seed(records) {
			await storage.deleteOfflineMutations(
				(await storage.getOfflineMutations()).map(({ id }) => id),
			);
			for (const record of records) await storage.setOfflineMutation(record);
			const queue = new OfflineQueue(view);
			await queue.init();
			return queue;
		},
	};
}

function record(id, created_at, overrides = {}) {
	return {
		id,
		created_at,
		action: "update",
		kind: "test",
		method: "POST",
		route: `/${id}`,
		target_key: id,
		fingerprint: `fingerprint-${id}`,
		fields: [],
		files: [],
		...overrides,
	};
}

async function remaining(env, queue, ids) {
	assert.deepEqual(queue.records.map(({ id }) => id).sort(), [...ids].sort());
	assert.deepEqual(
		(await env.storage.getOfflineMutations()).map(({ id }) => id).sort(),
		[...ids].sort(),
	);
	assert.equal(queue._replaying, false);
}

/** @matrix offline : queue-preserved replay-order */
test("test_offline_replay_blocks_later_records_after_the_oldest_record_fails", async (t) => {
	const env = await setup(t);
	for (const [response, expectedPhases] of [
		[{ ok: true, conflict: true }, ["conflict:first"]],
		[{ ok: false }, []],
		[{ ok: true, error: "Replay failed" }, []],
	]) {
		env.sent.length = 0;
		env.phases.length = 0;
		env.respond(() => response);
		const queue = await env.seed([record("first", 1), record("second", 2)]);
		assert.equal(await queue.replay(), 0);
		assert.deepEqual(
			env.sent.map(({ id }) => id),
			["first"],
		);
		assert.deepEqual(env.phases, expectedPhases);
		await remaining(env, queue, ["first", "second"]);
	}
});

/** @matrix offline : queue-preserved replay-order retry-boundary */
test("test_offline_replay_returns_the_completed_prefix_and_retries_the_oldest_record", async (t) => {
	const env = await setup(t);
	let secondFailed = false;
	env.respond((route) => {
		if (route === "/second" && !secondFailed) {
			secondFailed = true;
			return { ok: false, error: "Temporary failure" };
		}
		return { ok: true };
	});
	const queue = await env.seed([record("first", 1), record("second", 2)]);
	assert.equal(await queue.replay(), 1);
	assert.deepEqual(
		env.sent.map(({ id }) => id),
		["first", "second"],
	);
	assert.deepEqual(env.phases, ["replayed:first"]);
	await remaining(env, queue, ["second"]);
	assert.equal(await queue.replay(), 1);
	assert.deepEqual(
		env.sent.map(({ id }) => id),
		["first", "second", "second"],
	);
	assert.deepEqual(env.phases, ["replayed:first", "replayed:second"]);
	await remaining(env, queue, []);
});

/** @matrix offline : conflict-rebase replay-order */
test("test_offline_replay_retries_rebased_record_before_later_record", async (t) => {
	const env = await setup(t);
	env.respond((route, data) =>
		route === "/first" && data.get("offline-fingerprint") === "originating"
			? { ok: true, conflict: true }
			: { ok: true },
	);
	let rebasedIdentity;
	env.handle(async ({ phase, record, queue }) => {
		if (phase !== "conflict") return;
		await queue.rebaseSubmit(
			record,
			{ formData: new FormData() },
			{ fingerprint: "current" },
		);
		const persisted = (await env.storage.getOfflineMutations()).find(
			({ id }) => id === record.id,
		);
		rebasedIdentity = {
			id: persisted.id,
			created_at: persisted.created_at,
			fingerprint: persisted.fingerprint,
		};
	});
	const queue = await env.seed([
		record("first", 1, { fingerprint: "originating" }),
		record("second", 2),
	]);
	assert.equal(await queue.replay(), 2);
	assert.deepEqual(
		env.sent.map(({ id, fingerprint }) => `${id}:${fingerprint}`),
		["first:originating", "first:current", "second:fingerprint-second"],
	);
	assert.deepEqual(env.phases, [
		"conflict:first",
		"replayed:first",
		"replayed:second",
	]);
	assert.deepEqual(rebasedIdentity, {
		id: "first",
		created_at: 1,
		fingerprint: "current",
	});
	await remaining(env, queue, []);
});

/** @matrix offline : queue-preserved replay-order retry-boundary */
test("test_offline_replay_releases_ownership_after_handler_errors", async (t) => {
	const env = await setup(t);
	env.respond(() => ({ ok: true, conflict: true }));
	env.handle(() => {
		throw new Error("Conflict handler failed");
	});
	const conflictQueue = await env.seed([
		record("conflict-first", 1),
		record("conflict-second", 2),
	]);
	await assert.rejects(conflictQueue.replay(), /Conflict handler failed/);
	assert.deepEqual(
		env.sent.map(({ id }) => id),
		["conflict-first"],
	);
	await remaining(env, conflictQueue, ["conflict-first", "conflict-second"]);
	env.respond(() => ({ ok: true }));
	env.handle(() => {});
	assert.equal(await conflictQueue.replay(), 2);
	assert.deepEqual(
		env.sent.map(({ id }) => id),
		["conflict-first", "conflict-first", "conflict-second"],
	);
	await remaining(env, conflictQueue, []);
	env.sent.length = 0;
	env.handle(({ phase, record }) => {
		if (phase === "replayed" && record.id === "replayed-first")
			throw new Error("Replayed handler failed");
	});
	const replayedQueue = await env.seed([
		record("replayed-first", 1),
		record("replayed-second", 2),
	]);
	await assert.rejects(replayedQueue.replay(), /Replayed handler failed/);
	assert.deepEqual(
		env.sent.map(({ id }) => id),
		["replayed-first"],
	);
	await remaining(env, replayedQueue, ["replayed-second"]);
	env.handle(() => {});
	assert.equal(await replayedQueue.replay(), 1);
	assert.deepEqual(
		env.sent.map(({ id }) => id),
		["replayed-first", "replayed-second"],
	);
	await remaining(env, replayedQueue, []);
});

/**
 * @matrix offline : queue-submit reload replay queue-preserved
 * @source src/script/shared/offline.mjs::setOfflineMutation
 * @source src/script/shared/offline.mjs::getOfflineMutations
 * @source src/script/shared/offline.mjs::deleteOfflineMutations
 */
test("test_offline_queue_recovers_persisted_mutation_and_replaces_optimistic_dom", async (t) => {
	const env = await setup(t, {
		html: '<ul><li data-key="offline:client-1">Pending title</li></ul>',
	});
	const data = new FormData();
	data.set("title", "Saved title");
	const queue = new env.OfflineQueue(env.view);
	await queue.queue({
		id: "client-1",
		action: "create",
		kind: "test",
		method: "POST",
		route: "/create",
		data,
		fingerprint: "original",
	});
	assert.equal((await env.storage.getOfflineMutations()).length, 1);
	const recovered = new env.OfflineQueue(env.view);
	await recovered.init();
	assert.equal(recovered.records.length, 1);
	env.respond(() => ({ ok: false }));
	assert.equal(await recovered.replay(), 0);
	await remaining(env, recovered, ["client-1"]);
	assert.equal(document.querySelector("li").textContent, "Pending title");
	env.respond((_route, payload) => {
		assert.equal(payload.get("title"), "Saved title");
		assert.equal(payload.get("offline"), "True");
		assert.equal(payload.get("offline-fingerprint"), "original");
		return {
			ok: true,
			html: new DOMParser().parseFromString(
				'<li data-key="server-1">Saved title</li>',
				"text/html",
			),
		};
	});
	assert.equal(await recovered.replay(), 1);
	assert.equal(document.querySelector('[data-key="offline:client-1"]'), null);
	assert.equal(
		document.querySelector('[data-key="server-1"]').textContent,
		"Saved title",
	);
	await remaining(env, recovered, []);
});
