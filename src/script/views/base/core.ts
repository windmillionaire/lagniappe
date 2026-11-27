import type { SearchBox } from "../../elements/combobox/search.ts";
import type { EntityMenu } from "../../elements/entityMenu.ts";
import type { Notifications } from "../../elements/notifications.ts";
import type { EditWatcher } from "../../forms/revisions/watcher.ts";
import { connectivity } from "../../shared/connectivity.ts";
import type { DeferredOperationManager } from "../../shared/deferredOperations.ts";
import { ENDPOINTS } from "../../shared/endpoints.ts";
import { captureError } from "../../shared/errors.ts";
import type {
	DeleteModal,
	HelpModal,
	Modal,
	OfflineModal,
} from "../../shared/modal.ts";
import type { OfflineQueue } from "../../shared/offlineQueue.ts";
import type {
	PollDescriptor,
	PollingCoordinator,
} from "../../shared/polling.ts";
import { request } from "../../shared/request.ts";
import type { SyncManager } from "../../shared/sync.ts";
import { withTransition } from "../../shared/transitions.ts";
import type { RequestResult } from "../../types/api";
import ViewComponent from "./component.ts";
import {
	collectRefreshTargets,
	reconcileChange,
	refreshCollectionComponents,
} from "./reconciliation.ts";
import {
	ensureDeferredOperations,
	ensureEditWatcher,
	ensureEntityMenu,
	ensureModalClasses,
	ensureNotifications,
	ensureOfflineModal,
	ensureOfflineQueue,
	ensurePollingCoordinator,
	ensureSearchBox,
	ensureSubmissionManager,
	ensureSyncManager,
	initializeCoreServices,
} from "./services.ts";
import ShellView, { type ViewRoot, type ViewSyncOptions } from "./shell.ts";
import type { SubmissionManager } from "./submission.ts";
import { Task } from "./task.ts";

type PollChannel = PollDescriptor<"channel">["channel"];

const ROOT_COLLECTION_CHANNELS: ReadonlySet<string> = new Set([
	"categories",
	"projects",
	"pages",
	"tasks",
	"forms",
	"users",
	"ingress",
	"home",
] satisfies PollChannel[]);

const isRootCollectionChannel = (
	channel: string | null | undefined,
): channel is PollChannel =>
	Boolean(channel && ROOT_COLLECTION_CHANNELS.has(channel));

export interface ReconcileChange {
	type?: string;
	key?: string | null;
	starred?: boolean;
	destination?: string | null;
	source_widget?: string | null;
	deferred_revision?: string;
}

export interface RefreshOptions {
	fingerprint?: string | null;
	deferCommit?: boolean;
	beforeCommit?: (() => void) | null;
}

export type ComponentElement = HTMLElement & { _lp_component?: ViewComponent };

export type ModalClasses = {
	DeleteModal: typeof DeleteModal;
	HelpModal: typeof HelpModal;
	Modal: typeof Modal;
};

export type ViewNotifications = Notifications & {
	notify?(message: string): unknown;
};

export type EssentialService = Awaited<
	ReturnType<Core["ensurePollingCoordinator"]> | ReturnType<Core["prefetch"]>
>;

export type CoreServicesReady =
	| []
	| [
			essential: PromiseSettledResult<EssentialService>[],
			optional: PromiseSettledResult<
				ViewNotifications | DeferredOperationManager | EditWatcher | null
			>[],
			offlineQueue: OfflineQueue | null,
			syncManager: SyncManager | null,
			initialReplayCount: number,
	  ];

export default class Core extends ShellView {
	declare servicesReady: Promise<this | CoreServicesReady>;

	declare offlineIndicator: HTMLElement | null;
	declare offlineModal: OfflineModal | null;
	declare Notifications: ViewNotifications | null;
	declare offlineQueue: OfflineQueue | null;
	declare DeferredOperations: DeferredOperationManager | null;
	declare SyncManager: SyncManager | null;
	declare EditWatcher: EditWatcher | null;
	declare SubmissionManager: SubmissionManager | null;
	declare EntityMenu: EntityMenu | null;
	declare ModalClasses: ModalClasses | null;
	declare offlineQueueReady: Promise<OfflineQueue | null>;
	declare syncReady: Promise<SyncManager | null>;
	declare initialReplayReady: Promise<number>;
	declare replayReady: Promise<number>;
	declare _offlineQueuePromise?: Promise<OfflineQueue | null> | null;
	declare _syncPromise?: Promise<SyncManager | null> | null;
	declare _editWatcherPromise?: Promise<EditWatcher | null> | null;
	declare _deferredOperationsPromise?: Promise<DeferredOperationManager | null> | null;
	declare _entityMenuPromise?: Promise<EntityMenu | null> | null;
	declare _submissionPromise?: Promise<SubmissionManager | null> | null;
	declare _offlineModalPromise?: Promise<OfflineModal | null> | null;
	declare _modalClassesPromise?: Promise<ModalClasses | null> | null;
	declare _servicesInitialized?: boolean;
	declare _serviceStart?: Promise<this>;
	declare connectivityGeneration: number;
	declare blurred: boolean;
	declare blurredAt: number | null;

	declare _pendingChanges: ReconcileChange[];
	declare _reconcilePromise: Promise<void> | null;
	declare private _componentActions: Map<HTMLElement, Promise<boolean | null>>;
	declare private _pollingReconcileTask: Promise<void> | null;
	declare private _pollingReconcileRequested: boolean;
	declare private _offlineReplayTask: Promise<number> | null;
	declare private _coldControlListener: EventListener | null;

	constructor(node: ViewRoot) {
		super(node);
		this.hasDeferredServices = true;
		this.offlineIndicator = document.querySelector<HTMLElement>(
			'[data-role="offline"]',
		);
		this.offlineModal = null;

		this.Notifications = null;
		this.offlineQueue = null;
		this.PollingCoordinator = null;
		this.DeferredOperations = null;
		this.SyncManager = null;
		this.EditWatcher = null;
		this.SubmissionManager = null;
		this.SearchBox = null;
		this.EntityMenu = null;
		this.ModalClasses = null;
		this.offlineQueueReady = Promise.resolve(null);
		this.syncReady = Promise.resolve(null);
		this.initialReplayReady = Promise.resolve(0);
		// Latest reconnect replay. This remains an optional observation boundary;
		// rendering and the foreground sync lifecycle never await it.
		this.replayReady = Promise.resolve(0);
		this.connectivityGeneration = 0;

		this._pendingChanges = [];
		this._reconcilePromise = null;
		this._componentActions = new Map();
		this._pollingReconcileTask = null;
		this._pollingReconcileRequested = false;
		this._offlineReplayTask = null;
		this._coldControlListener = null;
		this.blurred = false;
		this.blurredAt = null;
	}

	queryParam(name: string) {
		const value = new URLSearchParams(window.location.search).get(name);
		return value?.trim() || null;
	}

	querySlug(value?: string | null) {
		return value
			?.trim()
			.replace(/([a-z0-9])([A-Z])/g, "$1-$2")
			.replace(/[^a-zA-Z0-9]+/g, "-")
			.replace(/^-|-$/g, "")
			.toLowerCase();
	}

	operationId() {
		return (
			globalThis.crypto?.randomUUID?.() ||
			`operation-${Date.now()}-${Math.random().toString(16).slice(2)}`
		);
	}

	init(): Promise<this> | Promise<void>;
	async init() {
		await super.init();
		initializeCoreServices(this);
		return this;
	}

	reportStartupError(
		error: unknown,
		element: Element | null = this.elt,
		context = "lazy-control",
	) {
		captureError(error, element, { context });
	}

	ensureOfflineQueue(): Promise<OfflineQueue | null> {
		return ensureOfflineQueue(this);
	}

	ensurePollingCoordinator(): Promise<PollingCoordinator | null> {
		return ensurePollingCoordinator(this);
	}

	ensureSyncManager(): Promise<SyncManager | null> {
		return ensureSyncManager(this);
	}

	ensureEditWatcher(): Promise<EditWatcher | null> {
		return ensureEditWatcher(this);
	}

	ensureDeferredOperations(): Promise<DeferredOperationManager | null> {
		return ensureDeferredOperations(this);
	}

	ensureNotifications(): Promise<ViewNotifications | null> {
		return ensureNotifications(this);
	}

	ensureSearchBox(): Promise<SearchBox | null> {
		return ensureSearchBox(this);
	}

	ensureEntityMenu(): Promise<EntityMenu | null> {
		return ensureEntityMenu(this);
	}

	ensureSubmissionManager(): Promise<SubmissionManager | null> {
		return ensureSubmissionManager(this);
	}

	ensureOfflineModal(): Promise<OfflineModal | null> {
		return ensureOfflineModal(this);
	}

	ensureModalClasses(): Promise<ModalClasses | null> {
		return ensureModalClasses(this);
	}

	/**
	 * Subscribe the root view to its durable entity or collection revision.
	 *
	 */
	_initPollingSubscription() {
		if (!this.PollingCoordinator) return;
		// The coordinator validates server-provided channel names at subscription.
		const pollChannel = this.elt.dataset.pollChannel as PollChannel | undefined;
		const entityRevision = this.elt.dataset.pollEntityRevision;
		if (pollChannel) {
			this.PollingCoordinator.subscribe(
				{
					id: `view:channel:${pollChannel}`,
					type: "channel",
					channel: pollChannel,
					revision: this.elt.dataset.pollRevision ?? null,
				},
				{
					mode: entityRevision ? "periodic" : "foreground",
					initial: "scheduled",
					onResult: async (result) => {
						if (result.status === "changed") await this.refresh();
					},
				},
			);
			if (!entityRevision) return;
		}
		const key = this.key;
		if (key) {
			const id = `view:entity:${key}`;
			this.PollingCoordinator.subscribe(
				{
					id,
					type: "entity",
					key,
					revision: entityRevision ?? this.elt.dataset.fingerprint ?? null,
				},
				{
					mode: "periodic",
					initial: "scheduled",
					onResult: async (result) => {
						const watcher = this.elt.querySelector("[lp-edited-marker]")
							? await this.ensureEditWatcher()
							: this.EditWatcher;
						await watcher?.receiveEntityResult?.(key, result);
						if (result.status === "unavailable") {
							await this.reconcileChange({ type: "delete", key });
							return;
						}
						if (result.status !== "changed") return;
						await this.reconcileChange({
							type: "entity-poll",
							key,
						});
					},
				},
			);
			return;
		}

		const channel = this.elt.dataset.index || this.kind;
		if (!isRootCollectionChannel(channel)) return;
		this.PollingCoordinator.subscribe(
			{
				id: `view:channel:${channel}`,
				type: "channel",
				channel,
				revision: this.elt.dataset.fingerprint ?? null,
			},
			{
				mode: "foreground",
				initial: "scheduled",
				onResult: async (result) => {
					if (result.status === "changed") await this.refresh();
				},
			},
		);
	}

	/**
	 * Reconcile committed server invalidations without treating poll payloads as
	 * authoritative replacement data. Concurrent invalidations share one pass
	 * and any invalidations received mid-pass are
	 * handled by the next iteration.
	 *
	 */
	reconcileChange(
		change: ReconcileChange = {},
	): Promise<void> | Promise<boolean> {
		return reconcileChange(this, change);
	}

	async refreshSupplementalCollections(_changes: ReconcileChange[]) {}

	afterReconcileChange(_change: ReconcileChange): void | Promise<void> {
		return Promise.resolve();
	}

	onComponentRendered(_component: ViewComponent): void {}

	_applyStarState({ key, starred, type }: ReconcileChange = {}) {
		if (!key) return;
		const active = starred ?? type === "star";
		const buttons = new Set([
			...this.elt.querySelectorAll<HTMLElement>(
				`[data-key="${key}"] [lp-control="star"]`,
			),
			...document.querySelectorAll<HTMLElement>(
				`[data-entity-key="${key}"][lp-control="star"]`,
			),
		]);
		for (const button of buttons) {
			button.dataset.active = active ? "true" : "false";
			const label = active ? "Unstar" : "Star";
			button.setAttribute("aria-label", label);
			button.title = label;
			const text = button.querySelector('[data-role="star-label"]');
			if (text) text.textContent = label;
		}
	}

	_adjustStarredCount(_delta: number): void {}

	_setStarredCount(_count: number): void {}

	async _toggleStar(button: HTMLButtonElement) {
		if (!this.online) return;
		const entity =
			button.closest<HTMLElement>("[lp-entity]") ||
			button.closest<HTMLElement>("[data-key]");
		const key = entity?.id || entity?.dataset.key;
		if (!key) return;

		const active = button.dataset.active === "true";
		button.disabled = true;
		this._applyStarState({ key, starred: !active });
		this._adjustStarredCount(!active ? 1 : -1);
		try {
			const response = await request.patch<{
				starred: boolean;
				count?: number;
			}>(ENDPOINTS.toggleStar(key));
			if (!response?.ok) throw new Error("Unable to update star");
			if (typeof response.count === "number") {
				this._setStarredCount(response.count);
			}
			button.disabled = false;
			await this.reconcileChange({
				type: response.starred ? "star" : "unstar",
				key,
				starred: response.starred,
			});
		} catch (error) {
			captureError(error, button);
			this._applyStarState({ key, starred: active });
			this._adjustStarredCount(active ? 1 : -1);
		} finally {
			button.disabled = false;
		}
	}

	_setOfflineIndicator() {
		this.offline = !this.online;
	}

	get offline() {
		return !this.online;
	}

	set offline(offline) {
		if (this.offlineIndicator) {
			this.offlineIndicator.dataset.visible = offline ? "true" : "false";
			this.offlineIndicator.setAttribute(
				"aria-hidden",
				offline ? "false" : "true",
			);
		}
		this.elt.dispatchEvent(
			new CustomEvent("offline-status", {
				detail: { offline: Boolean(offline) },
			}),
		);
	}

	async sync({
		hidden = document.hidden,
		blurred = false,
		blurredAt = null,
		force = false,
	}: ViewSyncOptions = {}) {
		const online = connectivity.online;
		const visibleBlur = Boolean(hidden && blurred);

		const wasInactive = this.hidden || !this.online || force;
		const changed =
			force ||
			hidden !== this.hidden ||
			visibleBlur !== this.blurred ||
			online !== this.online;
		if (!changed) {
			return;
		}

		if (visibleBlur && !this.blurred) this.blurredAt = blurredAt ?? Date.now();
		else if (!visibleBlur) this.blurredAt = null;
		if (online && !this.online) this.connectivityGeneration += 1;
		this.hidden = hidden;
		this.blurred = visibleBlur;
		this.online = online;
		this.offline = !online;

		if (!online || hidden) {
			this.EditWatcher?.pause();
			if (visibleBlur)
				this.PollingCoordinator?.blur(this.blurredAt ?? undefined);
			else this.PollingCoordinator?.pause();
			await this.SyncManager?.deregister();
		} else {
			await Promise.all([
				this.ensurePollingCoordinator(),
				this.SyncManager || this.elt.querySelector("[lp-sync]")
					? this.ensureSyncManager()
					: null,
				this.elt.querySelector("[lp-edited-marker]")
					? this.ensureEditWatcher()
					: null,
			]);
			if (wasInactive && !hidden) {
				this.scheduleOfflineReplay();
				await this.EditWatcher?.resume();
			} else {
				await this.EditWatcher?.resume();
			}
			await this.SyncManager?.register();
			await this.reconcilePollingSubscriptions();
			if (wasInactive && !hidden) {
				await this.PollingCoordinator?.catchUp();
			} else {
				await this.PollingCoordinator?.resume();
			}
		}
	}

	/**
	 * Replay is background reconciliation, never a prerequisite for restoring
	 * polling, sync, EditWatcher, or the visible server render. OfflineQueue
	 * itself polls mounted updated forms as each replay succeeds.
	 *
	 */
	scheduleOfflineReplay(): Promise<number> {
		if (this._offlineReplayTask) return this._offlineReplayTask;
		const replay: Promise<number> = import("./offlineReplay.ts").then(
			({ replayOfflineQueue }) => replayOfflineQueue(this),
		);
		this._offlineReplayTask = replay;
		this.replayReady = replay;
		const complete = () => {
			if (this._offlineReplayTask === replay) this._offlineReplayTask = null;
		};
		void replay.then(complete, complete);
		return replay;
	}

	/**
	 * Reconcile widget-owned polling after a component activation or a return
	 * to the foreground. Managers retain state for hidden widgets, but only the
	 * active visible widget may own recurring form, document, or ingress work.
	 *
	 */
	async reconcilePollingSubscriptions() {
		if (this._destroyed || this.hidden || !this.online) return;
		await this.EditWatcher?.reconcileSubscriptions?.();
		await this.SyncManager?.reconcileSubscriptions?.();
		await Promise.all(
			Object.values(this.components).flatMap((component) =>
				Object.values(component.widgets).map((widget) =>
					widget?.syncPollingSubscription?.(),
				),
			),
		);
	}

	/**
	 * Schedule subscription ownership reconciliation without making component
	 * rendering wait for manager or network work. Repeated renders coalesce and
	 * request at most one follow-up pass if ownership changes while a pass runs.
	 *
	 */
	schedulePollingReconciliation() {
		if (this._destroyed || this.hidden || !this.online) {
			return Promise.resolve();
		}
		this._pollingReconcileRequested = true;
		if (this._pollingReconcileTask) return this._pollingReconcileTask;

		const pending = Promise.resolve()
			.then(async () => {
				while (this._pollingReconcileRequested && !this._destroyed) {
					this._pollingReconcileRequested = false;
					await this.reconcilePollingSubscriptions();
				}
			})
			.catch((error) => {
				this.reportStartupError(
					error,
					this.elt,
					"polling-subscription-reconciliation",
				);
			})
			.finally(() => {
				if (this._pollingReconcileTask === pending) {
					this._pollingReconcileTask = null;
				}
			});
		this._pollingReconcileTask = pending;
		return pending;
	}

	async prefetch() {
		const prefetch = this.elt.querySelectorAll("[lp-component][lp-prefetch]");
		await Promise.all(
			Array.from(prefetch).map(async (elt) => {
				const component = this.getComponent(elt);
				if (!component) return;
				await component.prefetch();
			}),
		);
	}

	_collectRefreshTargets(components: ViewComponent[]) {
		return collectRefreshTargets(this, components);
	}

	async _refreshCollectionComponents(
		components: ViewComponent[],
		options: RefreshOptions = {},
	) {
		return refreshCollectionComponents(this, components, options);
	}

	async refreshCollections(navigation = false, options: RefreshOptions = {}) {
		const components = Object.values(this.components);
		const { beforeCommit = null, ...refreshOptions } = options;
		const commit = await this._refreshCollectionComponents(components, {
			...refreshOptions,
			deferCommit: true,
		});
		if (!commit) return;
		const commitRefresh = () => {
			beforeCommit?.();
			commit();
		};
		if (navigation) {
			commitRefresh();
		} else {
			await withTransition(commitRefresh, { label: "collections:refresh" });
		}
	}

	refresh(
		navigation?: boolean,
		options?: RefreshOptions,
	): Promise<void> | Promise<boolean>;
	async refresh(navigation = false, options: RefreshOptions = {}) {
		return this.refreshCollections(navigation, options);
	}

	async notify(message: string) {
		const notifications = await this.ensureNotifications();
		await notifications?.notify?.(message);
	}

	_installColdControlListeners() {
		this._coldControlListener = this._coldControlEvent.bind(this);
		for (const type of ["input", "click"]) {
			document.addEventListener(type, this._coldControlListener, true);
		}
	}

	_removeColdControlListeners() {
		if (!this._coldControlListener) return;
		for (const type of ["input", "click"]) {
			document.removeEventListener(type, this._coldControlListener, true);
		}
		this._coldControlListener = null;
	}

	_coldControlEvent(event: Event) {
		const { target } = event;
		if (!(target instanceof Element)) return;
		const search = target.closest("[lp-search]");
		if (search && !this.SearchBox) {
			this.runColdAction(
				search,
				() => this.ensureSearchBox(),
				(box) => this._activateSearchBox(box),
				search,
			);
			return;
		}

		const offline = target.closest("[data-role='offline']");
		if (offline && !this.offlineModal && event.type === "click") {
			event.preventDefault();
			event.stopImmediatePropagation?.();
			this.runColdAction(
				offline,
				() => this.ensureOfflineModal(),
				(modal) => modal?.attach?.(),
				offline,
			);
			return;
		}

		const notifications = target.closest("[data-role='notifications']");
		if (!notifications || this.Notifications) return;
		if (event.type === "click") {
			event.preventDefault();
			event.stopImmediatePropagation?.();
		}
		this.runColdAction(
			notifications,
			() => this.ensureNotifications(),
			(manager) => manager?.dropdown?.showPanel?.(),
			notifications,
		);
	}

	_click(e?: MouseEvent) {
		const target = e?.target;
		if (!e || !(target instanceof Element)) return;
		const menuTrigger = target.closest("[data-role='menu-trigger']");
		const menu = menuTrigger?.closest<HTMLElement>("[lp-menu]");
		if (menu && this.elt.contains(menu)) {
			e.preventDefault();
			e.stopPropagation();
			this.runColdAction(
				menu,
				() => this.ensureEntityMenu(),
				(manager) => manager?.toggle(menu),
				menuTrigger,
			);
			return;
		}

		const button = target.closest("button");
		const control = button?.getAttribute("lp-control");

		if (button?.matches("[data-role='flipper']")) {
			e.preventDefault();
			const flip = button.closest<HTMLElement>("[data-flipped]");
			if (!flip) return;
			const flipped = flip.dataset.flipped === "false";
			flip.dataset.flipped = flipped ? "true" : "false";
			return;
		} else if (button && control === "help") {
			e.preventDefault();
			e.stopPropagation();
			void this._showHelpModal(button);
			return;
		} else if (button && control === "star") {
			e.preventDefault();
			void this._toggleStar(button);
			return;
		} else if (button && control === "delete") {
			e.preventDefault();
			e.stopPropagation();
			void this._showDeleteModal(button);
			return;
		} else if (button && (control === "previous" || control === "next")) {
			e.preventDefault();
			if (!this.online) return;
			const widget = target.closest<HTMLElement>("[data-widget]");
			const widgetName = widget?.dataset.widget;
			const route = button.dataset.route;
			if (!widgetName || !route) return;
			const component = this.getComponent(widget);
			void request.get(route).then((response) => {
				component?.widgets[widgetName]?.refresh?.(response);
			});
			return;
		} else if (control || button?.hasAttribute("lp-show")) {
			e.preventDefault();
			void this.renderComponent(button);
			return;
		}

		if (
			target.closest("form") ||
			target.closest("a") ||
			target.closest("input") ||
			target.closest("label") ||
			target.closest("button") ||
			target.closest("td[data-column='completed'][data-editable='true']")
		) {
			return;
		}

		const toggle = target.closest<HTMLElement>("[lp-show]");
		if (toggle) {
			e.preventDefault();
			void this.renderComponent(toggle);
			return;
		}

		const link = target.closest("[lp-link]");
		if (link) {
			const title = link.matches("tr[lp-entity]")
				? "td[data-column='name'] [data-role='title']"
				: "[data-role='title']";
			link.querySelector<HTMLElement>(title)?.click();
			return;
		}
	}

	async _showDeleteModal(button: HTMLButtonElement) {
		return this.runColdAction(
			button,
			() => this.ensureModalClasses(),
			async (classes) => {
				if (!classes?.DeleteModal) return;
				const modal = new classes.DeleteModal(this, button);
				await modal.init();
			},
		);
	}

	async _showHelpModal(button: HTMLButtonElement) {
		return this.runColdAction(
			button,
			() => this.ensureModalClasses(),
			async (classes) => {
				if (!classes?.HelpModal) return;
				const modal = new classes.HelpModal(this, button);
				await modal.init();
			},
		);
	}

	getComponent(itemElt?: Element | null): ViewComponent | null {
		const target = itemElt?.closest<ComponentElement>("[lp-component]");
		if (target?._lp_component) return target._lp_component;

		const id = target?.id || target?.dataset?.key;

		if (id && target?.hasAttribute("lp-component")) {
			const ComponentClass = target.matches(
				"li[lp-component][data-kind='task']",
			)
				? Task
				: ViewComponent;
			const component = new ComponentClass(target, this);
			this.components[id] = component;
			target._lp_component = component;
			target.setAttribute("initialized", "");
			return component;
		}

		return null;
	}

	successfulResponse(
		response: RequestResult | null | undefined,
		component?: { showError?(message: string): unknown } | null,
	) {
		if (!response) return false;
		if (response.reload) {
			window.location.reload();
			return false;
		}
		if (response.error) {
			component?.showError?.(response.error);
			return false;
		}
		const { modal } = response;
		if (modal) {
			void this.ensureModalClasses().then((classes) => {
				if (this._destroyed || !classes?.Modal) return;
				if (typeof modal === "string") {
					captureError(
						new TypeError("Modal markup must be parsed before attachment"),
						component,
					);
					return;
				}
				void new classes.Modal(this).attach(modal, component);
			});
			return false;
		}
		return true;
	}

	async update(
		component: ViewComponent,
		data: FormData,
		route: string | URL | undefined = component.route,
	): Promise<void> {
		const manager = await this.ensureSubmissionManager();
		return manager?.update(component, data, route);
	}

	async create(
		component: ViewComponent,
		data: FormData,
		route: string | URL | undefined = component.route,
	): Promise<void> {
		const manager = await this.ensureSubmissionManager();
		return manager?.create(component, data, route);
	}

	async load(
		component: ViewComponent,
		route?: string | URL | null,
	): Promise<RequestResult | null> {
		if (!route) return null;
		const response = await request.get(route);

		if (!response || !this.successfulResponse(response, component)) return null;
		// Ordinary rendering is authoritative and completely independent of
		// OfflineQueue. Late replay is reconciled through polling/EditWatcher.
		return response;
	}

	_setLoadingTrigger(
		trigger: HTMLElement,
		component: ViewComponent,
		widgetName: string,
	) {
		const target = component.elt.querySelector(`[data-widget="${widgetName}"]`);
		if (!target || target.hasAttribute("loaded")) return null;

		const loadsAsync =
			target?.hasAttribute("lp-load") || target?.hasAttribute("lp-prefetch");
		trigger.setAttribute("aria-busy", "true");
		if (loadsAsync) trigger.dataset.loading = "true";
		return trigger;
	}

	_clearLoadingTrigger(trigger: HTMLElement | null) {
		if (!trigger) return;
		delete trigger.dataset.loading;
		trigger.removeAttribute("aria-busy");
	}

	renderComponent(trigger?: HTMLElement | null) {
		if (!trigger) return;
		if (this._componentActions.has(trigger)) {
			return this._componentActions.get(trigger);
		}

		const attribute =
			trigger.getAttribute("lp-show") || trigger.getAttribute("lp-close") || "";

		const [componentId, requestedWidget] = attribute.split(":");

		if (!componentId) {
			captureError(new Error("No component ID found"), trigger);
			return;
		}

		const targetElt = document.getElementById(componentId);
		const component = this.getComponent(targetElt);
		if (!component) {
			captureError(new Error("No component found"), trigger, { componentId });
			return;
		}

		const activeWidget = component.active?.name;
		let widgetName: string | null | undefined =
			requestedWidget === "active" && activeWidget
				? activeWidget
				: requestedWidget;

		const editor = component.widgets?.TableEditor;
		const toggleEditorOff =
			trigger.dataset.toggle === "true" &&
			requestedWidget === "TableEditor" &&
			editor?.visible === true;
		const toggleWidget =
			(trigger.dataset.toggle === "true" && activeWidget === widgetName) ||
			toggleEditorOff;
		const toggleComponent = component.visible && widgetName === "default";
		const showActiveWidget = widgetName === "active" && component.active;

		if (toggleWidget || toggleComponent) {
			const active = component.active;
			const activeTarget =
				active && "target" in active && active.target instanceof HTMLElement
					? active.target
					: null;
			const activeVisible =
				Boolean(active && "visible" in active && active.visible) &&
				activeTarget?.dataset.visible !== "false";
			widgetName = activeVisible ? null : activeWidget;
		} else if (showActiveWidget) {
			widgetName = activeWidget;
		}

		const loadingTrigger = widgetName
			? this._setLoadingTrigger(trigger, component, widgetName)
			: null;

		const pending = component
			.activate(widgetName)
			.then(async (activated) => {
				if (this._destroyed || trigger.isConnected === false) return null;
				await component.prepareRender(activated);
				const committed = await withTransition(
					() => {
						if (this._destroyed) return;
						component.render(activated);
					},
					{ label: `${component.name}:activate` },
				);
				if (
					activated &&
					committed !== false &&
					!this._destroyed &&
					trigger.isConnected &&
					component.elt.isConnected
				) {
					component.elt.dispatchEvent(
						new CustomEvent("component-opened", {
							bubbles: true,
							detail: { component, trigger },
						}),
					);
				}
				return committed;
			})
			.catch((error) => {
				this.reportStartupError(error, trigger, "component-activation");
				return null;
			})
			.finally(() => {
				this._clearLoadingTrigger(loadingTrigger);
				if (this._componentActions.get(trigger) === pending) {
					this._componentActions.delete(trigger);
				}
			});
		this._componentActions.set(trigger, pending);
		return pending;
	}

	addFlash(node?: Element | null) {
		if (!node || node.classList.contains("flash")) return;

		node.classList.add("flash");
		node.addEventListener(
			"animationend",
			() => {
				node.classList.remove("flash");
			},
			{ once: true },
		);
	}

	destroy() {
		super.destroy();
		this._pollingReconcileRequested = false;
		this.SubmissionManager?.destroy();
		this.SyncManager?.destroy();
		this.DeferredOperations?.destroy();
		this.EntityMenu?.destroy();
		this.EditWatcher?.destroy();
		this.Notifications?.destroy?.();
		this.PollingCoordinator?.destroy();
		this.SearchBox?.destroy?.();
		this.offlineModal?.destroy?.();
		this._componentActions.clear();

		Object.values(this.components).forEach((component) => {
			if (component.destroy) component.destroy();
		});
		this.components = {};
	}
}
