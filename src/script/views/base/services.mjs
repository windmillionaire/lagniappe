import { markPerformance, whenIdle } from "./shell";

/**
 * @testable false
 * @covered-by src/script/views/base/services.mjs::initializeCoreServices
 * @reason single-flight service loading is owned by core service initialization
 */
const loadOnce = (view, promiseKey, handleKey, loader) => {
	if (view[handleKey]) return Promise.resolve(view[handleKey]);
	if (view[promiseKey]) return view[promiseKey];

	const pending = Promise.resolve()
		.then(loader)
		.then((manager) => {
			if (view._destroyed) {
				manager?.destroy?.();
				return null;
			}
			if (manager) view[handleKey] = manager;
			return manager || null;
		})
		.catch((error) => {
			if (view[promiseKey] === pending) view[promiseKey] = null;
			throw error;
		});
	view[promiseKey] = pending;
	return pending;
};

/** @testable infrastructure */
export const ensureOfflineQueue = (view) =>
	loadOnce(view, "_offlineQueuePromise", "offlineQueue", async () => {
		const { OfflineQueue } = await import("../../shared/offlineQueue");
		if (view._destroyed) return null;
		const queue = new OfflineQueue(view);
		await queue.init();
		return queue;
	});

/** @testable infrastructure */
export const ensurePollingCoordinator = (view) =>
	loadOnce(view, "_pollingPromise", "PollingCoordinator", async () => {
		const { PollingCoordinator } = await import("../../shared/polling");
		if (view._destroyed) return null;
		const coordinator = new PollingCoordinator(view).init();
		view.PollingCoordinator = coordinator;
		view._initPollingSubscription();
		return coordinator;
	});

/** @testable infrastructure */
export const ensureSyncManager = (view) =>
	loadOnce(view, "_syncPromise", "SyncManager", async () => {
		await ensurePollingCoordinator(view);
		const { SyncManager } = await import("../../shared/sync");
		if (view._destroyed) return null;
		const manager = new SyncManager(view);
		manager.init();
		return manager;
	});

/** @testable infrastructure */
export const ensureEditWatcher = (view) =>
	loadOnce(view, "_editWatcherPromise", "EditWatcher", async () => {
		await ensurePollingCoordinator(view);
		const { EditWatcher } = await import("../../shared/editWatcher");
		if (view._destroyed) return null;
		const watcher = new EditWatcher(view);
		watcher.init();
		return watcher;
	});

/** @testable infrastructure */
export const ensureDeferredOperations = (view) =>
	loadOnce(
		view,
		"_deferredOperationsPromise",
		"DeferredOperations",
		async () => {
			await ensurePollingCoordinator(view);
			const { DeferredOperationManager } = await import(
				"../../shared/deferredOperations"
			);
			if (view._destroyed) return null;
			return new DeferredOperationManager(view).init();
		},
	);

/**
 * @testable infrastructure
 */
export const ensureNotifications = (view) =>
	loadOnce(view, "_notificationsPromise", "Notifications", async () => {
		if (!document.querySelector("[data-role='notifications']")) return null;
		const { Notifications } = await import("../../elements/notifications");
		if (view._destroyed) return null;
		const notifications = new Notifications(view);
		notifications.init();
		return notifications;
	});

/** @testable infrastructure */
export const ensureSearchBox = (view) =>
	loadOnce(view, "_searchPromise", "SearchBox", async () => {
		const search = document.querySelector("[lp-search]");
		if (!search) return null;
		const { SearchBox } = await import("../../elements/combobox/search");
		if (view._destroyed) return null;
		const box = new SearchBox(search);
		await box.init();
		return box;
	});

/** @testable infrastructure */
export const ensureEntityMenu = (view) =>
	loadOnce(view, "_entityMenuPromise", "EntityMenu", async () => {
		const { EntityMenu } = await import("../../elements/entityMenu");
		if (view._destroyed) return null;
		return new EntityMenu(view);
	});

/** @testable infrastructure */
export const ensureSubmissionManager = (view) =>
	loadOnce(view, "_submissionPromise", "SubmissionManager", async () => {
		const { SubmissionManager } = await import("./submission");
		if (view._destroyed) return null;
		return new SubmissionManager(view);
	});

/** @testable infrastructure */
export const ensureOfflineModal = (view) =>
	loadOnce(view, "_offlineModalPromise", "offlineModal", async () => {
		if (!view.offlineIndicator) return null;
		const { OfflineModal } = await import("../../shared/modal");
		if (view._destroyed) return null;
		const modal = new OfflineModal(view, view.offlineIndicator);
		modal.enable();
		return modal;
	});

/** @testable infrastructure */
export const ensureModalClasses = (view) =>
	loadOnce(view, "_modalClassesPromise", "ModalClasses", async () => {
		const { DeleteModal, HelpModal, Modal } = await import(
			"../../shared/modal"
		);
		if (view._destroyed) return null;
		return { DeleteModal, HelpModal, Modal };
	});

/**
 * @testable false
 * @covered-by src/script/views/base/services.mjs::initializeCoreServices
 */
const hasSyncCapability = (view) =>
	Boolean(view.elt.querySelector("[lp-sync]"));

/**
 * @testable false
 * @covered-by src/script/views/base/services.mjs::initializeCoreServices
 * @reason startup failure aggregation is owned by core service initialization
 */
const settleServices = async (view, promises, context) => {
	const results = await Promise.allSettled(promises);
	for (const result of results) {
		if (result.status === "rejected") {
			view.reportStartupError(result.reason, view.elt, context);
		}
	}
	return results;
};

/**
 * Install stable readiness promises immediately, but do not start private
 * storage/network services until concrete view publication. Explicit ensure
 * methods use the same single-flight loaders and therefore bypass the
 * background schedule.
 *
 * @testable infrastructure
 * @tests tests_js/test_029_core_startup.py::test_initial_replay_is_scheduled_after_view_readiness
 */
export const initializeCoreServices = (view) => {
	if (view._servicesInitialized) return view.servicesReady;
	view._servicesInitialized = true;
	const start = view._publishedReady.then(() => view);
	view._serviceStart = start;
	const idle = start.then(() => whenIdle());
	const offlineWork = idle.then(async () => {
		const { inspectOfflineWork } = await import("../../shared/offlineWork");
		return inspectOfflineWork(view);
	});
	view.offlineQueueReady = offlineWork.then(({ mutations }) =>
		mutations ? ensureOfflineQueue(view) : null,
	);
	view.syncReady = hasSyncCapability(view)
		? start.then(() => ensureSyncManager(view))
		: offlineWork.then(({ sync }) => (sync ? ensureSyncManager(view) : null));
	view.initialReplayReady = view.offlineQueueReady.then(async (queue) => {
		if (!queue) return 0;
		const { replayOfflineQueue } = await import("./offlineReplay");
		return replayOfflineQueue(view, queue);
	});

	const essential = start.then(async () => {
		if (view._destroyed) return [];
		view._setOfflineIndicator();
		return await settleServices(
			view,
			[
				ensurePollingCoordinator(view),
				// Server-backed widgets are the visible page. Start them directly;
				// IndexedDB hydration and replay must never gate their first render.
				view.prefetch(),
			],
			"essential-service-startup",
		);
	});

	const optional = idle.then(async () => {
		if (view._destroyed) return [];
		const warmers = [];
		if (document.querySelector("[data-role='notifications']")) {
			warmers.push(ensureNotifications(view));
		}
		if (view.elt.querySelector("[data-operation]")) {
			warmers.push(ensureDeferredOperations(view));
		}
		if (view.elt.querySelector("[lp-edited-marker]")) {
			warmers.push(ensureEditWatcher(view));
		}
		return await settleServices(view, warmers, "optional-service-startup");
	});

	view.servicesReady = Promise.all([
		essential,
		optional,
		view.offlineQueueReady,
		view.syncReady,
		view.initialReplayReady,
	])
		.catch((error) => {
			view.reportStartupError(error, view.elt, "service-startup");
			return [];
		})
		.then(async (result) => {
			await view._publishedReady;
			if (!view._destroyed) markPerformance("lagniappe:services-ready");
			return result;
		});
	return view.servicesReady;
};
