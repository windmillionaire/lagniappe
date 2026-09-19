import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

class EntityBoundary {
	async reconcilePollingSubscriptions() {}
}

async function loadPage() {
	return (
		await esmock.strict("../../src/script/views/page.mjs", {
			"../../src/script/shared/icons.mjs": { setIcon() {} },
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => callback(),
			},
			"../../src/script/views/base/entity.mjs": { default: EntityBoundary },
		})
	).default;
}

/** @matrix polling tasks : channel refresh */
test("test_page_task_collection_watches_task_form_changes", async () => {
	const Page = await loadPage();
	const page = new Page();
	const list = { name: "PageTaskList", loaded: false };
	const component = { widgets: { list } };
	let subscription;
	let subscriptions = 0;
	let refreshes = 0;
	let unsubscriptions = 0;
	Object.assign(page, {
		key: "page-key",
		elt: { dataset: { collectionRevision: "known-tasks" } },
		components: { tasks: component },
		PollingCoordinator: {
			subscribe(descriptor, options) {
				subscriptions += 1;
				subscription = { descriptor, options };
				return () => {
					unsubscriptions += 1;
				};
			},
		},
		async _refreshCollectionComponents(components) {
			assert.deepEqual(components, [component]);
			refreshes += 1;
		},
	});
	await page.reconcilePollingSubscriptions();
	assert.equal(subscriptions, 0);
	list.loaded = true;
	await page.reconcilePollingSubscriptions();
	await page.reconcilePollingSubscriptions();
	assert.equal(subscriptions, 1);
	assert.equal(subscription.descriptor.channel, "tasks");
	assert.equal(subscription.descriptor.revision, "known-tasks");
	assert.equal(subscription.options.mode, "periodic");
	await subscription.options.onResult({ status: "unchanged" });
	await subscription.options.onResult({ status: "changed" });
	assert.equal(refreshes, 1);
	list.loaded = false;
	await page.reconcilePollingSubscriptions();
	assert.equal(unsubscriptions, 1);
});

/** @matrix polling startup : subscription-lifecycle deferred-services */
test("test_page_task_subscription_survives_list_loading_before_polling_service", async (t) => {
	createBrowser(t);
	const Page = await loadPage();
	for (const listFirst of [true, false]) {
		const descriptors = [];
		const reconciliations = [];
		class PollingCoordinator {
			init() {
				return this;
			}
			subscribe(descriptor) {
				descriptors.push(descriptor);
				return () => {};
			}
		}
		const { ensurePollingCoordinator } = await esmock.p(
			"../../src/script/views/base/services.mjs",
			{
				"../../src/script/views/base/shell.mjs": {
					markPerformance() {},
					whenIdle: async () => {},
				},
				"../../src/script/shared/polling.mjs": { PollingCoordinator },
			},
		);
		const page = new Page();
		const list = { name: "PageTaskList", loaded: listFirst };
		Object.assign(page, {
			key: "page-key",
			elt: { dataset: {} },
			components: { tasks: { widgets: { list } } },
			_initPollingSubscription() {},
			schedulePollingReconciliation() {
				const pending = this.reconcilePollingSubscriptions();
				reconciliations.push(pending);
				return new Promise(() => {});
			},
		});
		if (listFirst) await page.reconcilePollingSubscriptions();
		const first = ensurePollingCoordinator(page);
		const second = ensurePollingCoordinator(page);
		assert.equal(await first, await second);
		if (!listFirst) {
			list.loaded = true;
			page.schedulePollingReconciliation();
		}
		await Promise.all(reconciliations);
		await ensurePollingCoordinator(page);
		assert.deepEqual(
			descriptors.map(({ id }) => id),
			["page:tasks:page-key"],
		);
	}
});

/** @matrix reconnect-refresh : manifest */
/** @source src/script/widgets/tables/indexTable.mjs::IndexTable.refreshDescriptor */
test("test_collection_manifests_include_hash_and_fingerprint", async () => {
	class Base {}
	const [{ IndexTable }, { PageTaskList }] = await Promise.all([
		esmock.strict("../../src/script/widgets/tables/indexTable.mjs", {
			"../../src/script/elements/base/baseTable.mjs": { BaseTable: Base },
		}),
		esmock.strict("../../src/script/widgets/pageTaskList.mjs", {
			"../../src/script/elements/base/baseList.mjs": { BaseList: Base },
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => callback(),
			},
		}),
	]);
	for (const [Owner, name] of [
		[IndexTable, "IndexTable"],
		[PageTaskList, "PageTaskList"],
	]) {
		const widget = Object.create(Owner.prototype);
		Object.assign(widget, {
			component: { name: name === "IndexTable" ? "table" : "tasks" },
			view: { key: "page", elt: { dataset: {} } },
			target: {
				hasAttribute: () => true,
				querySelectorAll: () => [
					{
						dataset: {
							key: "entity",
							hash: "hash",
							fingerprint: "revision",
							modified: "timestamp",
						},
					},
				],
			},
		});
		assert.deepEqual(widget.refreshDescriptor().rows, [
			{ key: "entity", hash: "hash", fingerprint: "revision" },
		]);
	}
});

/** @matrix form-index : created-row delete-target destination-refresh sorting */
test("test_index_table_row_updates_rebuild_active_sort", async (t) => {
	createBrowser(t);
	class BaseTable {}
	const { IndexTable } = await esmock.strict(
		"../../src/script/widgets/tables/indexTable.mjs",
		{ "../../src/script/elements/base/baseTable.mjs": { BaseTable } },
	);
	const row = (key, modified) => {
		const element = document.createElement("tr");
		element.dataset.key = key;
		element.dataset.modified = modified;
		element.setAttribute("lp-entity", "");
		return element;
	};
	const makeTable = (rows) => {
		const target = document.createElement("tbody");
		target.setAttribute("loaded", "");
		target.append(...rows);
		const table = Object.create(IndexTable.prototype);
		let refreshCalls = 0;
		Object.assign(table, {
			target,
			loaded: true,
			_created: [],
			_updated: [],
			view: { mobile: false, addFlash() {} },
			sortingWidget: {
				initialized: true,
				refreshRows() {
					refreshCalls += 1;
					[...target.querySelectorAll("tr[lp-entity]")]
						.sort(
							(a, b) => Number(b.dataset.modified) - Number(a.dataset.modified),
						)
						.forEach((item) => {
							target.append(item);
						});
				},
			},
			setEmptyRowVisibility() {},
		});
		return { table, target, refreshCalls: () => refreshCalls };
	};
	const refreshed = makeTable([row("older", "1")]);
	const html = document.createElement("tbody");
	html.append(row("older", "1"), row("newest", "2"));
	await refreshed.table.refresh({ html });
	assert.equal(refreshed.refreshCalls(), 1);
	assert.deepEqual(
		[...refreshed.target.children].map((item) => item.dataset.key),
		["newest", "older"],
	);
	const reconciled = makeTable([row("older", "1")]);
	reconciled.table._created = [row("newest", "2")];
	await reconciled.table.postreconcile();
	assert.equal(reconciled.refreshCalls(), 1);
	assert.deepEqual(
		[...reconciled.target.children].map((item) => item.dataset.key),
		["newest", "older"],
	);
});

/**
 * @matrix reconnect-refresh : batching cache-invalidation committed-delete delta-apply destination-invalidation fallback legacy-fallback manifest mounted-collection
 * @pair polling:reentrancy
 */
test("test_core_refresh_batches_supported_widgets_and_falls_back_per_target", async (t) => {
	createBrowser(t);
	const events = [];
	let refreshInvalidates = false;
	let refreshUnchanged = false;
	const browserWindow = {
		location: {
			search: "",
			reload() {
				events.push({ type: "reload" });
			},
		},
		matchMedia: () => ({ addEventListener() {}, matches: false }),
	};
	globalThis.window = browserWindow;
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
	const { reconcileChange, refreshCollectionComponents } = await esmock.strict(
		"../../src/script/views/base/reconciliation.mjs",
		{
			"../../src/script/shared/errors.mjs": {
				captureError(error) {
					throw error;
				},
			},
			"../../src/script/shared/request.mjs": { request },
			"../../src/script/shared/storage.mjs": {
				clearRecentSearchResults() {},
			},
		},
	);
	const root = document.createElement("main");
	Object.assign(root.dataset, {
		kind: "task",
		index: "tasks",
		fingerprint: "initial-root",
		authorization: "old-auth",
		collectionRevision: "tasks-before",
	});
	document.body.append(root);
	const view = {
		_pendingChanges: [],
		_reconcilePromise: null,
		components: {},
		elt: root,
		hash: "tasks",
		key: null,
		_applyStarState() {},
		async afterReconcileChange() {},
		ensureEditWatcher() {
			return Promise.resolve(this.EditWatcher);
		},
		getComponent() {
			return null;
		},
		async refresh() {
			return refreshCollectionComponents(this, Object.values(this.components));
		},
		async refreshCollections() {
			return this.refresh();
		},
		async refreshSupplementalCollections() {},
		reconcileChange(change) {
			return reconcileChange(this, change);
		},
	};
	const deltaWidget = {
		refreshScope: "collection",
		refreshDescriptor: () => ({
			rows: [{ key: "a", hash: "a", fingerprint: "old" }],
		}),
		async refreshDelta() {
			events.push({ type: "delta" });
		},
		async refresh() {
			events.push({ type: "legacy-delta" });
		},
	};
	const fallbackWidget = {
		refreshScope: "collection",
		refreshDescriptor: () => ({ rows: [] }),
		async refreshDelta() {
			events.push({ type: "unexpected-delta" });
		},
		async refresh() {
			events.push({ type: "legacy-fallback" });
		},
	};
	const unsupportedWidget = {
		async refresh() {
			events.push({ type: "legacy-unsupported" });
		},
	};
	const component = (name, widgets) => ({
		name,
		widgets,
		async refreshCollections(skip) {
			for (const widget of Object.values(widgets)) {
				if (widget.refreshScope === "collection" && !skip.has(widget)) {
					await widget.refresh?.();
				}
			}
		},
	});
	view.components = {
		table: component("table", { deltaWidget, unsupportedWidget }),
		tasks: component("tasks", { fallbackWidget }),
	};
	view.Notifications = {
		async refresh() {
			events.push({ type: "notifications" });
		},
	};

	await view.refresh();
	const requests = events.filter(({ type }) => type === "request");
	assert.equal(requests.length, 1);
	assert.equal(requests[0].url, "/l/refresh");
	assert.equal(requests[0].payload.targets.length, 2);
	assert.deepEqual(
		requests[0].payload.targets.map(({ id }) => id),
		["table", "tasks"],
	);
	assert.deepEqual(requests[0].payload.view, {
		key: null,
		hash: "tasks",
		index: "tasks",
		mode: null,
		fingerprint: "initial-root",
		authorization: "old-auth",
		collection_revision: "tasks-before",
	});
	assert.equal(root.dataset.authorization, "new-auth");
	assert.equal(root.dataset.collectionRevision, "tasks-after");
	const types = events.map(({ type }) => type);
	assert.equal(types.includes("delta"), true);
	assert.equal(types.includes("legacy-fallback"), true);
	for (const unexpected of [
		"notifications",
		"legacy-delta",
		"unexpected-delta",
		"legacy-unsupported",
	]) {
		assert.equal(types.includes(unexpected), false);
	}
	assert.equal(root.dataset.fingerprint, "fresh-root");

	refreshUnchanged = true;
	const unchangedStart = events.length;
	await view.refresh();
	const unchangedTypes = events.slice(unchangedStart).map(({ type }) => type);
	for (const unexpected of [
		"delta",
		"legacy-delta",
		"legacy-fallback",
		"legacy-unsupported",
	]) {
		assert.equal(unchangedTypes.includes(unexpected), false);
	}
	refreshUnchanged = false;
	refreshInvalidates = true;
	await view.refresh();
	assert.equal(events.at(-1)?.type, "reload");

	const collectionTarget = document.createElement("div");
	collectionTarget.dataset.widget = "ModelTaskList";
	const mountedEntity = document.createElement("article");
	mountedEntity.setAttribute("lp-entity", "");
	mountedEntity.dataset.key = "model-task-a";
	mountedEntity._lp_component = {
		destroy() {
			events.push({ type: "destroy-mounted" });
		},
	};
	collectionTarget.append(mountedEntity);
	root.append(collectionTarget);
	const originalRemove = mountedEntity.remove.bind(mountedEntity);
	mountedEntity.remove = () => {
		events.push({ type: "remove-mounted" });
		originalRemove();
	};
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
	refreshInvalidates = false;
	const reconcileStart = events.length;
	await view.reconcileChange({ type: "delete", key: "model-task-a" });
	const reconcileEvents = events.slice(reconcileStart);
	assert.deepEqual(
		reconcileEvents.slice(0, 4).map(({ type }) => type),
		["load-mounted", "destroy-mounted", "remove-mounted", "refresh-mounted"],
	);
	assert.equal(
		reconcileEvents.some(({ type }) => type === "invalidate"),
		false,
	);

	const destinationElement = document.createElement("div");
	destinationElement.id = "task-a";
	document.body.append(destinationElement);
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
	assert.equal(destinationEvents[0]?.type, "load-destination");
	assert.equal(destinationEvents[0]?.name, "TaskForm");
	assert.deepEqual(
		destinationEvents.find(({ type }) => type === "invalidate")?.keys,
		["page-key-a", "task-key-a"],
	);

	view.PollingCoordinator = { activePoll: Promise.resolve([]) };
	const reentrantStart = events.length;
	await view.reconcileChange({ type: "entity-poll", key: "page-key-a" });
	const reentrantEvents = events.slice(reentrantStart);
	assert.equal(
		reentrantEvents.some(({ type }) =>
			["enqueue-invalidation", "invalidate"].includes(type),
		),
		false,
	);
	assert.equal(
		reentrantEvents.some(({ type }) => type === "refresh-mounted"),
		true,
	);
});
