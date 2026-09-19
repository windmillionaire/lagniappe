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

/**
 * @matrix offline : offline-replay queue-preserved reconnect-generation retry-boundary
 * @matrix polling : active-widget document visibility
 * @matrix sync : active-widget checkpoint dirty-state offline-replay persistence reconnect-generation retry-boundary visibility
 */
test("test_sync_manager_uses_polling_subscriptions", async (t) => {
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
			subscriptions.set(descriptor.id, {
				descriptor: { ...descriptor },
				...hooks,
			});
			return () => subscriptions.delete(descriptor.id);
		},
		get(id) {
			return subscriptions.get(id)?.descriptor ?? null;
		},
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
		async closeDocuments(ids) {
			closed.push(...ids);
		},
	};
	const offline = {
		deleteSyncRecord: async (syncId) => deletedSyncIds.push(syncId),
		deleteSyncRecords: async () => undefined,
		getAllOfflineRecords: async () => ({ sync: offlineRecords }),
		getSyncRecord: async () => null,
		updateSyncRecord: async (record) => offlineWrites.push(record),
	};
	const request = {
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
	};
	replaceGlobal(t, "window", {
		addEventListener() {},
		removeEventListener() {},
	});
	const { SyncManager } = await esmock.strict(
		"../../src/script/shared/sync.mjs",
		{
			"../../src/script/elements/editor/headless.mjs": {
				loadHeadlessWidget: (settings) => headlessFactory(settings),
			},
			"../../src/script/shared/endpoints.mjs": {
				ENDPOINTS: { sync: "/l/sync" },
			},
			"../../src/script/shared/offline.mjs": offline,
			"../../src/script/shared/request.mjs": { request },
			"../../src/script/shared/utilities.mjs": {
				waitForAttribute: async () => undefined,
			},
		},
	);

	const payloads = [{ update: "delta-1", ydoc: "checkpoint-1" }];
	const savePayloads = [];
	const component = { key: "entity-key", visible: true, widgets: {} };
	const widget = {
		component,
		fingerprint: "fingerprint-1",
		initialized: false,
		syncId: "entity:document",
		visible: true,
		get syncData() {
			return payloads.shift() ?? null;
		},
		get saveData() {
			return savePayloads.shift() ?? null;
		},
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
		parentElement: { closest: () => null },
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
		get syncData() {
			return null;
		},
		get saveData() {
			return null;
		},
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
	const manager = new SyncManager(view);

	const remote = await manager.state(widget);
	assert.equal(remote?.generation, "generation-1", "state comes from polling");
	let subscription = subscriptions.get("document:entity:document");
	assert.equal(
		subscription?.descriptor.type,
		"document",
		"installs document subscription",
	);
	assert.deepEqual(
		{
			generation: subscription.descriptor.generation,
			revision: subscription.descriptor.revision,
		},
		{ generation: "generation-1", revision: 0 },
		"retains initial accepted cursor",
	);
	await manager.reconcileSubscriptions();
	assert.ok(
		subscriptions.has("document:entity:document"),
		"keeps active subscription",
	);
	widget.initialized = true;
	assert.ok(
		!subscriptions.has("document:hidden:document"),
		"skips hidden ancestor",
	);
	await manager.sendUpdates(false);
	assert.deepEqual(
		{
			calls: requestCalls.length,
			clientId: requestCalls[0].body.client_id,
			generation: requestCalls[0].body.updates[0].generation,
			revision: requestCalls[0].body.updates[0].revision,
		},
		{ calls: 1, clientId: "client-1", generation: "generation-1", revision: 0 },
		"sends revisioned sync request",
	);
	assert.equal(
		subscription.descriptor.revision,
		1,
		"acknowledgement advances cursor",
	);

	checkpointAccepted = false;
	await manager.sendUpdates(true, [
		{
			key: "entity-key",
			sync_id: "entity:document",
			generation: "generation-1",
			revision: 1,
			ydoc: "stale-checkpoint",
			html: "<p>Stale</p>",
			save: true,
		},
	]);
	assert.deepEqual(
		{
			revision: subscription.descriptor.revision,
			ydoc: offlineWrites.at(-1)?.ydoc,
		},
		{ revision: 1, ydoc: "stale-checkpoint" },
		"retains rejected checkpoint without advancing cursor",
	);

	checkpointAccepted = true;
	Object.assign(subscription.descriptor, {
		generation: "generation-1",
		revision: 2,
	});
	savePayloads.push({ ydoc: "merged-checkpoint", html: "<p>Merged</p>" });
	await subscription.beforePoll();
	assert.equal(
		requestCalls.length,
		2,
		"polls before retrying rejected checkpoint",
	);
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
	assert.deepEqual(
		{
			calls: requestCalls.length,
			ydoc: requestCalls[2].body.updates[0].ydoc,
			revision: subscription.descriptor.revision,
			snapshot: widget.snapshot,
			commitCalls: widget.commitCalls,
		},
		{
			calls: 3,
			ydoc: "merged-checkpoint",
			revision: 3,
			snapshot: "merged-checkpoint",
			commitCalls: 1,
		},
		"retries rejected checkpoint after polling",
	);

	responseOk = false;
	savePayloads.push({
		ydoc: "retry-after-transport-error",
		html: "<p>Retry</p>",
	});
	await manager.sendUpdates(true);
	assert.equal(
		offlineWrites.at(-1)?.ydoc,
		"retry-after-transport-error",
		"retains failed checkpoint",
	);
	responseOk = true;
	savePayloads.push({
		ydoc: "retry-after-transport-error",
		html: "<p>Retry</p>",
	});
	await subscription.beforePoll();
	assert.deepEqual(
		{ calls: requestCalls.length, snapshot: widget.snapshot },
		{ calls: 5, snapshot: "retry-after-transport-error" },
		"retries retained checkpoint before poll",
	);

	view.connectivityGeneration = 1;
	manager._offlineReplayAttempts.set(widget.syncId, 1);
	savePayloads.push({
		ydoc: "blocked-same-reconnect",
		html: "<p>Blocked same reconnect</p>",
	});
	const requestsBeforeBlockedReplay = requestCalls.length;
	await manager.sendUpdates(true);
	assert.equal(
		requestCalls.length,
		requestsBeforeBlockedReplay,
		"blocks same-generation retry",
	);
	view.connectivityGeneration = 2;
	await manager.sendUpdates(true);
	assert.equal(
		requestCalls.length,
		requestsBeforeBlockedReplay + 1,
		"retries in new generation",
	);

	widget.visible = false;
	component.active = null;
	await manager.reconcileSubscriptions();
	const deactivationTouch = requestCalls.at(-1)?.body?.updates?.[0];
	assert.deepEqual(
		{
			subscribed: subscriptions.has("document:entity:document"),
			closed: closed.at(-1),
			touchParent: deactivationTouch?.touch_parent,
			ydoc: deactivationTouch?.ydoc,
			pending: manager._pendingParentTouches.has("entity:document"),
		},
		{
			subscribed: false,
			closed: "entity:document",
			touchParent: true,
			ydoc: undefined,
			pending: false,
		},
		"masks deactivated document lifecycle touch",
	);
	component.active = widget;
	widget.visible = true;
	await manager.reconcileSubscriptions();
	subscription = subscriptions.get("document:entity:document");
	assert.ok(subscription, "restores polling for reactivated document");

	view.online = false;
	savePayloads.push({
		ydoc: "offline-checkpoint",
		html: "<p>Offline checkpoint</p>",
	});
	const descriptorBeforeDeregister = { ...subscription.descriptor };
	await manager.deregister();
	assert.deepEqual(
		closed,
		["entity:document", "entity:document"],
		"closes presence",
	);
	const offlineCheckpoint = offlineWrites.at(-1);
	assert.deepEqual(
		{
			generation: offlineCheckpoint?.generation,
			revision: offlineCheckpoint?.revision,
			ydoc: offlineCheckpoint?.ydoc,
			touchParent: offlineCheckpoint?.touch_parent,
		},
		{
			generation: descriptorBeforeDeregister.generation,
			revision: descriptorBeforeDeregister.revision,
			ydoc: "offline-checkpoint",
			touchParent: true,
		},
		"saves cursor and checkpoint before deregistration",
	);

	payloads.push({ update: "offline-delta", ydoc: "offline-state" });
	await manager.sendUpdates(false);
	const offlineDelta = offlineWrites.at(-1);
	assert.deepEqual(
		{
			update: offlineDelta?.update,
			generation: offlineDelta?.generation,
			revision: offlineDelta?.revision,
		},
		{
			update: "offline-delta",
			generation: descriptorBeforeDeregister.generation,
			revision: descriptorBeforeDeregister.revision,
		},
		"retains cursor on offline delta",
	);

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
	let renderSettled = false;
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
			merged =
				this.remote?.updates?.[0]?.update === "remote-delta" &&
				this.offlineRecord?.ydoc === "offline-state";
			renderSettled = false;
			this.remote = null;
			this.offlineRecord = null;
		},
		async waitForRender() {
			renderSettled = true;
		},
		get saveData() {
			assert.ok(renderSettled, "headless replay waits for rendering");
			return merged
				? {
						update: "merged-update",
						ydoc: "merged-checkpoint",
						html: "<p>Remote Offline</p>",
					}
				: null;
		},
		destroy() {
			replayDestroyed = true;
		},
	});

	const replayView = {
		components: {},
		online: true,
		PollingCoordinator: coordinator,
	};
	const replayManager = new SyncManager(replayView).init();
	await replayManager.ready;
	const replayRequest = requestCalls.at(-1)?.body?.updates?.[0];
	assert.deepEqual(
		{
			merged,
			renderSettled,
			generation: replayRequest?.generation,
			revision: replayRequest?.revision,
			ydoc: replayRequest?.ydoc,
			touchParent: replayRequest?.touch_parent,
			deleted: deletedSyncIds.includes("replay:document"),
			replayDestroyed,
			closed: closed.at(-1),
		},
		{
			merged: true,
			renderSettled: true,
			generation: "generation-1",
			revision: 4,
			ydoc: "merged-checkpoint",
			touchParent: true,
			deleted: true,
			replayDestroyed: true,
			closed: "replay:document",
		},
		"fetches, merges, checkpoints, and clears headless replay",
	);

	const requestsBeforeFailedReplay = requestCalls.length;
	replayView.connectivityGeneration = 1;
	responseOk = false;
	await replayManager.register();
	assert.equal(
		requestCalls.length,
		requestsBeforeFailedReplay + 1,
		"failed replay makes one request",
	);
	await replayManager.register();
	assert.equal(
		requestCalls.length,
		requestsBeforeFailedReplay + 1,
		"coalesced registration does not retry in same generation",
	);
	replayView.connectivityGeneration = 2;
	responseOk = true;
	await replayManager.register();
	assert.equal(
		requestCalls.length,
		requestsBeforeFailedReplay + 2,
		"new connectivity generation retries retained replay",
	);
});
