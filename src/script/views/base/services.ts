import type Core from "./core.ts";
import type { EssentialService, ViewNotifications } from "./core.ts";
import { loadViewService, markPerformance, whenIdle } from "./shell.ts";

export const ensureOfflineQueue = (view: Core) =>
	loadViewService(view, "_offlineQueuePromise", "offlineQueue", async () => {
		const { OfflineQueue } = await import("../../shared/offlineQueue.ts");
		if (view._destroyed) return null;
		const queue = new OfflineQueue(view);
		await queue.init();
		return queue;
	});

export const ensurePollingCoordinator = (view: Core) =>
	loadViewService(view, "_pollingPromise", "PollingCoordinator", async () => {
		const { PollingCoordinator } = await import("../../shared/polling.ts");
		if (view._destroyed) return null;
		const coordinator = new PollingCoordinator(view).init();
		view.PollingCoordinator = coordinator;
		view._initPollingSubscription();
		// Cached widgets can render before this deferred module arrives. Revisit
		// their subscriptions now that the coordinator is available.
		void view.schedulePollingReconciliation();
		return coordinator;
	});

export const ensureSyncManager = (view: Core) =>
	loadViewService(view, "_syncPromise", "SyncManager", async () => {
		await ensurePollingCoordinator(view);
		const { SyncManager } = await import("../../shared/sync.ts");
		if (view._destroyed) return null;
		const manager = new SyncManager(view);
		manager.init();
		return manager;
	});

export const ensureEditWatcher = (view: Core) =>
	loadViewService(view, "_editWatcherPromise", "EditWatcher", async () => {
		await ensurePollingCoordinator(view);
		const { EditWatcher } = await import("../../forms/revisions/watcher.ts");
		if (view._destroyed) return null;
		const watcher = new EditWatcher(view);
		watcher.init();
		return watcher;
	});

export const ensureDeferredOperations = (view: Core) =>
	loadViewService(
		view,
		"_deferredOperationsPromise",
		"DeferredOperations",
		async () => {
			await ensurePollingCoordinator(view);
			const { DeferredOperationManager } = await import(
				"../../shared/deferredOperations.ts"
			);
			if (view._destroyed) return null;
			return new DeferredOperationManager(view).init();
		},
	);

export const ensureNotifications = (
	view: Core,
): Promise<ViewNotifications | null> =>
	loadViewService(view, "_notificationsPromise", "Notifications", async () => {
		if (!document.querySelector("[data-role='notifications']")) return null;
		const { Notifications } = await import("../../elements/notifications.ts");
		if (view._destroyed) return null;
		const notifications = new Notifications(view);
		notifications.init();
		return notifications;
	});

export const ensureSearchBox = (view: Core) =>
	loadViewService(view, "_searchPromise", "SearchBox", async () => {
		const search = document.querySelector<HTMLElement>("[lp-search]");
		if (!search) return null;
		const { SearchBox } = await import("../../elements/combobox/search.ts");
		if (view._destroyed) return null;
		const box = new SearchBox(search);
		await box.init();
		return box;
	});

export const ensureEntityMenu = (view: Core) =>
	loadViewService(view, "_entityMenuPromise", "EntityMenu", async () => {
		const { EntityMenu } = await import("../../elements/entityMenu.ts");
		if (view._destroyed) return null;
		return new EntityMenu(view);
	});

export const ensureSubmissionManager = (view: Core) =>
	loadViewService(view, "_submissionPromise", "SubmissionManager", async () => {
		const { SubmissionManager } = await import("./submission.ts");
		if (view._destroyed) return null;
		return new SubmissionManager(view);
	});

export const ensureOfflineModal = (view: Core) =>
	loadViewService(view, "_offlineModalPromise", "offlineModal", async () => {
		if (!view.offlineIndicator) return null;
		const { OfflineModal } = await import("../../shared/modal.ts");
		if (view._destroyed) return null;
		const modal = new OfflineModal(view, view.offlineIndicator);
		modal.enable();
		return modal;
	});

export const ensureModalClasses = (view: Core) =>
	loadViewService(view, "_modalClassesPromise", "ModalClasses", async () => {
		const { DeleteModal, HelpModal, Modal } = await import(
			"../../shared/modal.ts"
		);
		if (view._destroyed) return null;
		return { DeleteModal, HelpModal, Modal };
	});

const hasSyncCapability = (view: Core) =>
	Boolean(view.elt.querySelector("[lp-sync]"));

const settleServices = async <Result>(
	view: Core,
	promises: Promise<Result>[],
	context: string,
) => {
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
 */
export const initializeCoreServices = (view: Core): Core["servicesReady"] => {
	if (view._servicesInitialized) return view.servicesReady;
	view._servicesInitialized = true;
	const start = view._publishedReady.then(() => view);
	view._serviceStart = start;
	const idle = start.then(() => whenIdle());
	const offlineWork = idle.then(async () => {
		const { inspectOfflineWork } = await import("../../shared/offlineWork.ts");
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
		const { replayOfflineQueue } = await import("./offlineReplay.ts");
		return replayOfflineQueue(view, queue);
	});

	const essential = start.then(
		async (): Promise<PromiseSettledResult<EssentialService>[]> => {
			if (view._destroyed) return [];
			view._setOfflineIndicator();
			return await settleServices<EssentialService>(
				view,
				[
					ensurePollingCoordinator(view),
					// Server-backed widgets are the visible page. Start them directly;
					// IndexedDB hydration and replay must never gate their first render.
					view.prefetch(),
				],
				"essential-service-startup",
			);
		},
	);

	type OptionalService = Awaited<
		ReturnType<
			| typeof ensureNotifications
			| typeof ensureDeferredOperations
			| typeof ensureEditWatcher
		>
	>;
	const optional = idle.then(
		async (): Promise<PromiseSettledResult<OptionalService>[]> => {
			if (view._destroyed) return [];
			const warmers: Promise<OptionalService>[] = [];
			if (document.querySelector("[data-role='notifications']")) {
				warmers.push(ensureNotifications(view));
			}
			if (
				view.elt.matches("[data-operation]") ||
				view.elt.querySelector("[data-operation]")
			) {
				warmers.push(ensureDeferredOperations(view));
			}
			if (view.elt.querySelector("[lp-edited-marker]")) {
				warmers.push(ensureEditWatcher(view));
			}
			return await settleServices(view, warmers, "optional-service-startup");
		},
	);

	view.servicesReady = Promise.all([
		essential,
		optional,
		view.offlineQueueReady,
		view.syncReady,
		view.initialReplayReady,
	])
		.catch((error): [] => {
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
