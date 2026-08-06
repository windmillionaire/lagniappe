import { connectivity } from "../../shared/connectivity";
import { ENDPOINTS } from "../../shared/endpoints";
import { captureError } from "../../shared/errors";
import { request } from "../../shared/request";
import { withTransition } from "../../shared/utilities";
import ViewComponent from "./component";
import {
	collectRefreshTargets,
	reconcileChange,
	refreshCollectionComponents,
} from "./reconciliation";
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
} from "./services";
import ShellView from "./shell";
import { Task } from "./task";

/**
 * @testable infrastructure
 */
export default class Core extends ShellView {
	constructor(node) {
		super(node);
		this.hasDeferredServices = true;
		this.offlineIndicator = document.querySelector('[data-role="offline"]');
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

		this._pendingChanges = [];
		this._reconcilePromise = null;
		this._componentActions = new Map();
		this._pollingReconcileTask = null;
		this._pollingReconcileRequested = false;
		this._offlineReplayTask = null;
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity._initialTabId
	 * @covered-by src/script/views/base/index.mjs::EntityIndex._defaultToolTarget
	 * @reason URL query helpers are exercised through view-specific defaults
	 */
	queryParam(name) {
		const value = new URLSearchParams(window.location.search).get(name);
		return value?.trim() || null;
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/entity.mjs::Entity._initialTabId
	 * @covered-by src/script/views/base/index.mjs::EntityIndex._defaultToolTarget
	 * @reason URL query helpers are exercised through view-specific defaults
	 */
	querySlug(value) {
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

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_shell_intercepts_interactions_before_deferred_services
	 * @pair startup:interaction-ready
	 * @pair startup:deferred-services
	 */
	async init() {
		await super.init();
		initializeCoreServices(this);
		return this;
	}

	reportStartupError(error, element = this.elt, context = "lazy-control") {
		captureError(error, element, { context });
	}

	ensureOfflineQueue() {
		return ensureOfflineQueue(this);
	}

	ensurePollingCoordinator() {
		return ensurePollingCoordinator(this);
	}

	ensureSyncManager() {
		return ensureSyncManager(this);
	}

	ensureEditWatcher() {
		return ensureEditWatcher(this);
	}

	ensureDeferredOperations() {
		return ensureDeferredOperations(this);
	}

	ensureNotifications() {
		return ensureNotifications(this);
	}

	ensureSearchBox() {
		return ensureSearchBox(this);
	}

	ensureEntityMenu() {
		return ensureEntityMenu(this);
	}

	ensureSubmissionManager() {
		return ensureSubmissionManager(this);
	}

	ensureOfflineModal() {
		return ensureOfflineModal(this);
	}

	ensureModalClasses() {
		return ensureModalClasses(this);
	}

	/**
	 * Subscribe the root view to its durable entity or collection revision.
	 *
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_core_polling_subscription_lifecycle
	 * @covered-by src/script/views/base/services.mjs::ensurePollingCoordinator
	 * @features polling
	 * @dimensions entity channel refresh
	 */
	_initPollingSubscription() {
		if (!this.PollingCoordinator) return;
		const pollChannel = this.elt.dataset.pollChannel;
		if (pollChannel) {
			this.PollingCoordinator.subscribe(
				{
					id: `view:channel:${pollChannel}`,
					type: "channel",
					channel: pollChannel,
					revision: this.elt.dataset.pollRevision ?? null,
				},
				{
					mode: "foreground",
					initial: "scheduled",
					onResult: async (result) => {
						if (result.status === "changed") await this.refresh();
					},
				},
			);
			return;
		}
		if (this.key) {
			const id = `view:entity:${this.key}`;
			this.PollingCoordinator.subscribe(
				{
					id,
					type: "entity",
					key: this.key,
					revision: this.elt.dataset.fingerprint ?? null,
				},
				{
					mode: "periodic",
					initial: "scheduled",
					onResult: async (result) => {
						const watcher = this.elt.querySelector("[lp-edited-marker]")
							? await this.ensureEditWatcher()
							: this.EditWatcher;
						await watcher?.receiveEntityResult?.(this.key, result);
						if (result.status === "unavailable") {
							await this.reconcileChange({ type: "delete", key: this.key });
							return;
						}
						if (result.status !== "changed") return;
						await this.reconcileChange({
							type: "entity-poll",
							key: this.key,
						});
					},
				},
			);
			return;
		}

		const channel = this.elt.dataset.index || this.kind;
		const supported = new Set([
			"categories",
			"projects",
			"pages",
			"tasks",
			"forms",
			"users",
			"ingress",
			"home",
		]);
		if (!supported.has(channel)) return;
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
	 * @testable true
	 * @tests tests_js/test_022_refresh_frontend.py::test_core_refresh_batches_supported_widgets_and_falls_back_per_target
	 * @pairs reconnect-refresh:mounted-collection reconnect-refresh:committed-delete
	 * @pair reconnect-refresh:destination-invalidation
	 * @pair polling:reentrancy
	 */
	reconcileChange(change = {}) {
		return reconcileChange(this, change);
	}

	async refreshSupplementalCollections() {}

	async afterReconcileChange() {}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_category
	 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_project
	 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_page
	 * @tests tests_e2e/002_home/test_002e_home_starred.py::test_star_file
	 * @pairs starred:title-menu starred:accessible-state
	 */
	_applyStarState({ key, starred, type } = {}) {
		if (!key) return;
		const active = starred ?? type === "star";
		const buttons = new Set([
			...this.elt.querySelectorAll(`[data-key="${key}"] [lp-control="star"]`),
			...document.querySelectorAll(
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

	async _toggleStar(button) {
		if (!this.online) return;
		const entity =
			button.closest("[lp-entity]") || button.closest("[data-key]");
		const key = entity?.id || entity?.dataset.key;
		if (!key) return;

		const active = button.dataset.active === "true";
		button.disabled = true;
		this._applyStarState({ key, starred: !active });
		try {
			const response = await request.patch(ENDPOINTS.toggleStar(key));
			if (!response?.ok) throw new Error("Unable to update star");
			await this.reconcileChange({
				type: response.starred ? "star" : "unstar",
				key,
				starred: response.starred,
			});
		} catch (error) {
			captureError(error, button);
			this._applyStarState({ key, starred: active });
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
		if (this.offlineIndicator)
			this.offlineIndicator.dataset.visible = offline ? "true" : "false";
		this.elt.dispatchEvent(
			new CustomEvent("offline-status", {
				detail: { offline: Boolean(offline) },
			}),
		);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/001_site/test_001d_offline.py::test_offline_indicator_toggles
	 * @tests tests_e2e/001_site/test_001d_offline.py::test_failed_ping_marks_view_offline_until_next_sync_event
	 * @tests tests_e2e/001_site/test_001d_offline.py::test_testing_mode_navigation_resets_offline_state
	 * @tests tests_js/test_028_form_state_split.py::test_visibility_sync_stages_remote_form_edits_without_waiting_for_offline_replay
	 * @features offline
	 * @dimensions indicator browser-state server-health transitions view-reset dirty-form-preservation
	 * @pair offline:dirty-form-preservation
	 * @pair offline:background-replay
	 * @pairs polling:nonblocking polling:catch-up
	 */
	async sync({ hidden = document.hidden, force = false } = {}) {
		const online = connectivity.online;

		const wasInactive = this.hidden || !this.online || force;
		const changed = force || hidden !== this.hidden || online !== this.online;
		if (!changed) {
			return;
		}

		this.hidden = hidden;
		this.online = online;
		this.offline = !online;

		if (!online || hidden) {
			this.EditWatcher?.pause();
			this.PollingCoordinator?.pause();
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
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_visibility_sync_stages_remote_form_edits_without_waiting_for_offline_replay
	 * @features offline polling
	 * @dimensions background-replay nonblocking
	 * @pair offline:background-replay
	 * @pair polling:nonblocking
	 */
	scheduleOfflineReplay() {
		if (this._offlineReplayTask) return this._offlineReplayTask;
		this._offlineReplayTask = import("./offlineReplay")
			.then(({ replayOfflineQueue }) => replayOfflineQueue(this))
			.finally(() => {
				this._offlineReplayTask = null;
			});
		return this._offlineReplayTask;
	}

	/**
	 * Reconcile widget-owned polling after a component activation or a return
	 * to the foreground. Managers retain state for hidden widgets, but only the
	 * active visible widget may own recurring form, document, or ingress work.
	 *
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_core_polling_subscription_lifecycle
	 * @features polling
	 * @dimensions active-widget visibility subscription-lifecycle
	 * @pairs polling:active-widget polling:visibility
	 * @pair polling:subscription-lifecycle
	 */
	async reconcilePollingSubscriptions() {
		if (this._destroyed || this.hidden || !this.online) return;
		await this.EditWatcher?.reconcileSubscriptions?.();
		await this.SyncManager?.reconcileSubscriptions?.();
		await Promise.all(
			Object.values(this.components).flatMap((component) =>
				Object.values(component.widgets).map((widget) =>
					widget.syncPollingSubscription?.(),
				),
			),
		);
	}

	/**
	 * Schedule subscription ownership reconciliation without making component
	 * rendering wait for manager or network work. Repeated renders coalesce and
	 * request at most one follow-up pass if ownership changes while a pass runs.
	 *
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_core_polling_subscription_lifecycle
	 * @features polling startup
	 * @dimensions subscription-lifecycle nonblocking single-flight
	 * @pairs polling:subscription-lifecycle polling:nonblocking
	 * @pairs startup:single-flight startup:nonblocking
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

	/**
	 * @testable true
	 * @tests tests_js/test_022_refresh_frontend.py::test_core_refresh_batches_supported_widgets_and_falls_back_per_target
	 * @features reconnect-refresh
	 * @dimensions manifest batching fallback
	 */
	_collectRefreshTargets(components) {
		return collectRefreshTargets(this, components);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_022_refresh_frontend.py::test_core_refresh_batches_supported_widgets_and_falls_back_per_target
	 * @pair reconnect-refresh:delta-apply
	 * @pair reconnect-refresh:legacy-fallback
	 * @pair reconnect-refresh:cache-invalidation
	 */
	async _refreshCollectionComponents(components, options = {}) {
		return refreshCollectionComponents(this, components, options);
	}

	async refreshCollections(navigation = false, options = {}) {
		const components = Object.values(this.components);
		const refreshed = async () =>
			await this._refreshCollectionComponents(components, options);
		if (navigation) {
			await refreshed();
		} else {
			await withTransition(refreshed);
		}
	}

	async refresh(navigation = false, options = {}) {
		return this.refreshCollections(navigation, options);
	}

	async notify(message) {
		const notifications = await this.ensureNotifications();
		await notifications?.notify?.(message);
	}

	_installColdControlListeners() {
		this._coldControlEvent = this._coldControlEvent.bind(this);
		for (const type of ["input", "click"]) {
			document.addEventListener(type, this._coldControlEvent, true);
		}
	}

	_removeColdControlListeners() {
		if (!this._coldControlEvent) return;
		for (const type of ["input", "click"]) {
			document.removeEventListener(type, this._coldControlEvent, true);
		}
		this._coldControlEvent = null;
	}

	_coldControlEvent(event) {
		const search = event.target?.closest?.("[lp-search]");
		if (search && !this.SearchBox) {
			this.runColdAction(
				search,
				() => this.ensureSearchBox(),
				(box) => this._activateSearchBox(box),
				search,
			);
			return;
		}

		const offline = event.target?.closest?.("[data-role='offline']");
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

		const notifications = event.target?.closest?.(
			"[data-role='notifications']",
		);
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

	_click(e) {
		const menuTrigger = e.target.closest("[data-role='menu-trigger']");
		const menu = menuTrigger?.closest("[lp-menu]");
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

		const button = e.target.closest("button");
		const control = button?.getAttribute("lp-control");

		if (button?.matches("[data-role='flipper']")) {
			e.preventDefault();
			const flip = button.closest("[data-flipped]");
			const flipped = flip.dataset.flipped === "false";
			flip.dataset.flipped = flipped ? "true" : "false";
			return;
		} else if (control === "help") {
			e.preventDefault();
			e.stopPropagation();
			void this._showHelpModal(button);
			return;
		} else if (control === "star") {
			e.preventDefault();
			void this._toggleStar(button);
			return;
		} else if (control === "delete") {
			e.preventDefault();
			e.stopPropagation();
			void this._showDeleteModal(button);
			return;
		} else if (["previous", "next"].includes(control)) {
			e.preventDefault();
			if (!this.online) return;
			const widget = e.target.closest("[data-widget]");
			const component = this.getComponent(widget);
			request.get(button.dataset.route).then((response) => {
				component.widgets[widget.dataset.widget]?.refresh(response);
			});
			return;
		} else if (control || button?.hasAttribute("lp-show")) {
			e.preventDefault();
			void this.renderComponent(button);
			return;
		}

		if (
			e.target.closest("form") ||
			e.target.closest("a") ||
			e.target.closest("input") ||
			e.target.closest("button")
		) {
			return;
		}

		const toggle = e.target.closest("[lp-show]");
		if (toggle) {
			e.preventDefault();
			void this.renderComponent(toggle);
			return;
		}

		const link = e.target.closest("[lp-link]");
		if (link) {
			link.querySelector("[data-role='title']")?.click();
			return;
		}
	}

	async _showDeleteModal(button) {
		return this.runColdAction(
			button,
			() => this.ensureModalClasses(),
			async ({ DeleteModal } = {}) => {
				if (!DeleteModal) return;
				const modal = new DeleteModal(this, button);
				await modal.init();
			},
		);
	}

	async _showHelpModal(button) {
		return this.runColdAction(
			button,
			() => this.ensureModalClasses(),
			async ({ HelpModal } = {}) => {
				if (!HelpModal) return;
				const modal = new HelpModal(this, button);
				await modal.init();
			},
		);
	}

	getComponent(itemElt) {
		const target = itemElt?.closest("[lp-component]");
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

	successfulResponse(response, component) {
		if (!response) return false;
		if (response.reload) {
			window.location.reload();
			return false;
		}
		if (response.error) {
			component?.showError?.(response.error);
			return false;
		}
		if (response.modal) {
			void this.ensureModalClasses().then(({ Modal } = {}) => {
				if (this._destroyed || !Modal) return;
				new Modal(this).attach(response.modal, component);
			});
			return false;
		}
		return true;
	}

	async update(component, data, route = component.route) {
		const manager = await this.ensureSubmissionManager();
		return manager?.update(component, data, route);
	}

	async create(component, data, route = component.route) {
		const manager = await this.ensureSubmissionManager();
		return manager?.create(component, data, route);
	}

	async load(component, route) {
		if (!route) return null;
		const response = await request.get(route);

		if (!this.successfulResponse(response, component)) return null;
		// Ordinary rendering is authoritative and completely independent of
		// OfflineQueue. Late replay is reconciled through polling/EditWatcher.
		return response;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002a_home.py::test_model_lists_load_on_toggle
	 * @features home
	 * @dimensions lazy-load loading-indicator
	 */
	_setLoadingTrigger(trigger, component, widgetName) {
		const target = component.elt.querySelector(`[data-widget="${widgetName}"]`);
		if (!target || target.hasAttribute("loaded")) return null;

		const loadsAsync =
			target?.hasAttribute("lp-load") || target?.hasAttribute("lp-prefetch");
		trigger.setAttribute("aria-busy", "true");
		if (loadsAsync) trigger.dataset.loading = "true";
		return trigger;
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/core.mjs::Core._setLoadingTrigger
	 * @reason paired cleanup for transient trigger loading state
	 */
	_clearLoadingTrigger(trigger) {
		if (!trigger) return;
		delete trigger.dataset.loading;
		trigger.removeAttribute("aria-busy");
	}

	renderComponent(trigger) {
		if (!trigger) return;
		if (this._componentActions.has(trigger)) {
			return this._componentActions.get(trigger);
		}

		const attribute =
			trigger.getAttribute("lp-show") || trigger.getAttribute("lp-close") || "";

		let [componentId, widgetName] = attribute.split(":");

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
		widgetName =
			widgetName === "active" && activeWidget ? activeWidget : widgetName;

		const toggleWidget =
			trigger.dataset.toggle === "true" && activeWidget === widgetName;
		const toggleComponent = component.visible && widgetName === "default";
		const showActiveWidget = widgetName === "active" && component.active;

		if (toggleWidget || toggleComponent) {
			widgetName = component.active?.visible ? null : activeWidget;
		} else if (showActiveWidget) {
			widgetName = activeWidget;
		}

		const loadingTrigger = widgetName
			? this._setLoadingTrigger(trigger, component, widgetName)
			: null;

		const pending = component
			.activate(widgetName)
			.then((activated) => {
				if (this._destroyed || trigger.isConnected === false) return null;
				return withTransition(async () => {
					if (this._destroyed) return;
					await component.render(activated);
				});
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

	addFlash(node) {
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
		this.offlineModal?.destroy?.();
		this._componentActions.clear();

		Object.values(this.components).forEach((component) => {
			if (component.destroy) component.destroy();
		});
		this.components = {};
	}
}
