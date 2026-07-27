import { SearchBox } from "../../elements/combobox/search";
import { EntityMenu } from "../../elements/entityMenu";
import { Notifications } from "../../elements/notifications";
import {
	captureError,
	clearRecentSearchResults,
	connectivity,
	DeferredOperationManager,
	DeleteModal,
	EditWatcher,
	ENDPOINTS,
	EVENTS,
	HelpModal,
	initializeMessaging,
	OfflineModal,
	OfflineQueue,
	request,
	SyncManager,
	withTransition,
} from "../../shared";
import ViewComponent from "./component";
import { SubmissionManager } from "./submission";
import { Task } from "./task";

const MESSAGING_FEATURE_SELECTOR = [
	"[lp-sync]",
	"[lp-deferred]",
	"[data-widget='ImportData']",
	"[data-role='run-report-form']",
	"[data-role='revise-report-form']",
].join(",");

const COLLECTION_ONLY_CHANGE_TYPES = new Set(["delete", "star", "unstar"]);

/**
 * @testable infrastructure
 */
export default class Core {
	constructor(node) {
		this.elt = node;
		this.kind = node.dataset.kind;
		this.hash = node.dataset.hash || node.dataset.index;
		this.key = node.dataset.key;
		this.readonly = node.dataset.readonly === "true";
		this.messagingDisabled =
			this.readonly ||
			document.querySelector("meta[name='messaging-disabled']")?.content ===
				"true";
		this.mobile = window.matchMedia("(max-width: 640px)").matches;
		this.offlineIndicator = document.querySelector('[data-role="offline"]');
		this.offlineModal = null;
		this.online = connectivity.online;
		this.hidden = connectivity.hidden;
		this.fcmToken = null;

		this.Notifications = null;
		this.offlineQueue = null;
		this.DeferredOperations = null;
		this.SyncManager = null;
		this.EditWatcher = null;
		this.SubmissionManager = new SubmissionManager(this);
		this.SearchBox = null;
		this.EntityMenu = new EntityMenu(this);
		this.syncReady = null;
		this.initialReplayReady = Promise.resolve(0);

		this.components = {};
		this._pendingChanges = [];
		this._reconcilePromise = null;
		this._syncPromise = null;
		this._initialReplayTask = Promise.resolve(0);
		this._destroyed = false;

		this._click = this._click.bind(this);
		this._receiveServerChange = this._receiveServerChange.bind(this);
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
	 * @tests tests_js/test_029_core_startup.py::test_core_init_does_not_wait_for_messaging_or_initial_replay
	 * @pair startup:queue-hydration
	 * @pair startup:background-messaging
	 */
	async init() {
		await this._initOfflineQueue();
		this.syncReady = this._initSync();
		this._startInitialReplay();
		this.DeferredOperations = new DeferredOperationManager(this).init();
		this.prefetch();
		this._addListeners();
		this._setOfflineIndicator();
		this._initSearch();
		this._initNotifications();
		this._initEditWatcher();

		this.elt.setAttribute("initialized", "");
		this.elt._lp_view = this;
		return this;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_core_init_does_not_wait_for_messaging_or_initial_replay
	 * @pair offline:background-replay
	 */
	_startInitialReplay() {
		this.initialReplayReady = Promise.resolve().then(async () => {
			if (!this.online || this._destroyed) return 0;
			try {
				return (await this.offlineQueue?.replay()) || 0;
			} catch (error) {
				captureError(error, this.elt, { context: "initial-offline-replay" });
				return 0;
			}
		});

		this._initialReplayTask = this.initialReplayReady
			.then(async (replayed) => {
				if (replayed && !this._destroyed) await this.refresh();
				return replayed;
			})
			.catch((error) => {
				captureError(error, this.elt, { context: "initial-replay-refresh" });
				return 0;
			});
		return this._initialReplayTask;
	}

	_initNotifications() {
		this.Notifications = new Notifications(this);
		this.Notifications.init();
	}

	_initEditWatcher() {
		if (this.EditWatcher) return;
		this.EditWatcher = new EditWatcher(this);
		this.EditWatcher.init();
	}

	async _initOfflineQueue() {
		if (this.offlineQueue) return;

		this.offlineQueue = new OfflineQueue(this);
		await this.offlineQueue.init();
	}

	/**
	 * @testable true
	 * @tests tests_e2e/001_site/test_001c_messaging.py::test_manual_page_does_not_prompt_for_messaging_without_messaging_features
	 * @features messaging
	 * @dimensions permission-modal feature-gate
	 */
	_shouldInitializeMessaging() {
		if (window.__TESTING__) return true;
		if (globalThis.Notification?.permission === "granted") return true;
		return Boolean(this.elt.querySelector(MESSAGING_FEATURE_SELECTOR));
	}

	/**
	 * @testable true
	 * @tests tests_js/test_023_deferred_operations.py::test_core_keeps_non_push_controls_editable_without_fcm_token
	 * @pair messaging:unavailable-token
	 * @pair messaging:editability
	 * @pair sync:state-only
	 * @pair deferred-jobs:polling
	 */
	_initSync() {
		if (this._syncPromise) return this._syncPromise;

		this._syncPromise = (async () => {
			if (this.SyncManager) return this.SyncManager;
			const shouldInitializeMessaging =
				(!this.messagingDisabled || window.__TESTING__) &&
				this._shouldInitializeMessaging();
			if (shouldInitializeMessaging) {
				try {
					this.fcmToken = await initializeMessaging();
				} catch (error) {
					captureError(error, this.elt, { context: "messaging-startup" });
				}
			}
			if (this._destroyed) return null;

			try {
				this.SyncManager = new SyncManager(this);
				this.SyncManager.init();
				return this.SyncManager;
			} catch (error) {
				captureError(error, this.elt, { context: "sync-manager-startup" });
				this.SyncManager = null;
				return null;
			}
		})();
		return this._syncPromise;
	}

	async _initSearch() {
		const search = document.querySelector("[lp-search]");
		if (search) {
			this.SearchBox = new SearchBox(search);
			await this.SearchBox.init();
		}
	}

	_addListeners() {
		this.elt.addEventListener("click", this._click);
		this.elt.addEventListener("submit", this.SubmissionManager.submit);
		window.addEventListener(EVENTS.SERVER_CHANGE, this._receiveServerChange);

		const mobileQuery = window.matchMedia("(max-width: 640px)");
		mobileQuery.addEventListener("change", (e) => {
			this.mobile = e.matches;
			this.elt.dispatchEvent(new CustomEvent("mobile-resize"));
		});

		this._initDrag();
	}

	/**
	 * @testable true
	 * @tests tests_js/test_023_deferred_operations.py::test_server_change_defers_completion_to_authoritative_status
	 * @pairs deferred-jobs:operation-order deferred-jobs:stale-event
	 * @pairs messaging:push-acceleration messaging:stale-event
	 */
	_receiveServerChange(event) {
		const change = event.detail || {};
		if (change.type === "deferred-complete" && change.operation) {
			this.DeferredOperations?.nudge(change.operation, change.revision);
			return;
		}
		void this.reconcileChange(change);
	}

	/**
	 * @testable false
	 * @covered-by src/script/views/base/core.mjs::Core.reconcileChange
	 * @reason destination loading prepares the named widget for the shared reconciliation pass
	 */
	async _loadChangeDestination(destination) {
		if (!destination) return null;
		const [componentId, widgetName] = destination.split(":");
		if (!componentId || !widgetName) return null;
		const componentElt = document.getElementById(componentId);
		const component = this.getComponent(componentElt);
		if (!component) return null;
		return await component.loadWidget(widgetName);
	}

	/**
	 * Load rendered collection owners before invalidating them. Some persistent
	 * collections are present in the initial HTML without ever becoming the
	 * component's active widget, so they otherwise have no refresh contract yet.
	 *
	 * @testable true
	 * @tests tests_js/test_022_refresh_frontend.py::test_core_refresh_batches_supported_widgets_and_falls_back_per_target
	 * @pair reconnect-refresh:mounted-collection
	 */
	async _loadMountedCollectionOwners(keys) {
		const requested = new Set(keys);
		const targets = new Set();
		for (const entity of this.elt.querySelectorAll("[lp-entity][data-key]")) {
			if (!requested.has(entity.dataset.key)) continue;
			const target = entity.parentElement?.closest?.("[data-widget]");
			if (target?.dataset.widget && !target.matches?.("form")) {
				targets.add(target);
			}
		}

		await Promise.all(
			Array.from(targets, async (target) => {
				const component = this.getComponent(target);
				await component?.loadWidget(target.dataset.widget);
			}),
		);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_022_refresh_frontend.py::test_core_refresh_batches_supported_widgets_and_falls_back_per_target
	 * @tests tests_e2e/008_users/test_008b_user_groups.py::test_delete_group_refreshes_group_navigation
	 * @pair reconnect-refresh:committed-delete
	 */
	_removeDeletedEntity(key) {
		for (const element of this.elt.querySelectorAll("[data-key]")) {
			if (element.dataset.key !== key) continue;
			element._lp_component?.destroy?.();
			element.remove();
		}
	}

	/**
	 * Reconcile committed server changes without treating push payloads as data.
	 * Concurrent messages share one pass and any messages received mid-pass are
	 * handled by the next iteration.
	 *
	 * @testable true
	 * @tests tests_js/test_022_refresh_frontend.py::test_core_refresh_batches_supported_widgets_and_falls_back_per_target
	 * @pairs reconnect-refresh:mounted-collection reconnect-refresh:committed-delete
	 * @pair reconnect-refresh:destination-invalidation
	 */
	reconcileChange(change = {}) {
		this._pendingChanges.push({ ...change });
		if (this._reconcilePromise) return this._reconcilePromise;

		this._reconcilePromise = (async () => {
			try {
				do {
					const changes = this._pendingChanges.splice(0);
					const fingerprint = this.elt.dataset.fingerprint || null;
					const destinationKeys = [];
					for (const item of changes) {
						if (item.type === "delete") clearRecentSearchResults();
						if (["star", "unstar"].includes(item.type)) {
							this._applyStarState(item);
						}
						const destination = await this._loadChangeDestination(
							item.destination,
						);
						if (
							destination?.key &&
							!COLLECTION_ONLY_CHANGE_TYPES.has(item.type)
						) {
							destinationKeys.push(destination.key);
						}
					}
					const keys = [
						...new Set(changes.map(({ key }) => key).filter(Boolean)),
					];
					if (keys.length) await this._loadMountedCollectionOwners(keys);
					for (const { key, type } of changes) {
						if (type === "delete" && key) this._removeDeletedEntity(key);
					}
					const formKeys = [
						...new Set([
							...changes
								.filter(({ type }) => !COLLECTION_ONLY_CHANGE_TYPES.has(type))
								.map(({ key }) => key)
								.filter(Boolean),
							...destinationKeys,
						]),
					];
					if (formKeys.length) await this.EditWatcher?.invalidate(formKeys);
					await this.refreshCollections(false, { fingerprint });
					await this.refreshSupplementalCollections(changes);
					for (const item of changes) await this.afterReconcileChange(item);
				} while (this._pendingChanges.length);
			} finally {
				this._reconcilePromise = null;
			}
		})();
		return this._reconcilePromise;
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
		const offlineModal = new OfflineModal(this, this.offlineIndicator);
		offlineModal.enable();
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
	 * @tests tests_e2e/001_site/test_001d_offline.py::test_rapid_offline_online_transitions
	 * @tests tests_e2e/001_site/test_001d_offline.py::test_testing_mode_navigation_resets_offline_state
	 * @tests tests_js/test_028_form_state_split.py::test_visibility_sync_stages_remote_form_edits_before_refresh
	 * @features offline
	 * @dimensions indicator browser-state server-health transitions view-reset dirty-form-preservation
	 * @pair offline:dirty-form-preservation
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
			this.SyncManager?.deregister();
		} else {
			if (wasInactive && !hidden) {
				const refreshFingerprint = this.elt.dataset.fingerprint || null;
				await this._initialReplayTask;
				await this.offlineQueue?.replay();
				this.DeferredOperations?.nudge();
				await this.EditWatcher?.resume();
				await this.refresh(force, { fingerprint: refreshFingerprint });
			} else {
				await this.EditWatcher?.resume();
			}
			await this.SyncManager?.register();
		}
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
		const targets = new Map();

		for (const component of components) {
			if (component.elt && !component.elt.isConnected) continue;
			for (const widget of Object.values(component.widgets)) {
				if (widget.refreshScope !== "collection") continue;
				if (!widget.refreshDescriptor || !widget.refreshDelta) continue;
				try {
					const descriptor = widget.refreshDescriptor();
					if (!descriptor) continue;
					const id = component.name;
					if (!id || targets.has(id)) continue;
					targets.set(id, { descriptor: { ...descriptor, id }, widget });
				} catch (error) {
					captureError(error);
				}
			}
		}
		return targets;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_022_refresh_frontend.py::test_core_refresh_batches_supported_widgets_and_falls_back_per_target
	 * @pair reconnect-refresh:delta-apply
	 * @pair reconnect-refresh:legacy-fallback
	 * @pair reconnect-refresh:cache-invalidation
	 */
	async _refreshCollectionComponents(
		components,
		{ fingerprint = this.elt.dataset.fingerprint || null } = {},
	) {
		const targets = this._collectRefreshTargets(components);
		const reconciled = new Set();
		let refreshedFingerprint = null;

		if (targets.size) {
			const response = await request.post("/refresh", {
				view: {
					key: this.key || null,
					hash: this.hash || null,
					index: this.elt.dataset.index || null,
					mode: this.elt.dataset.userMode || null,
					fingerprint,
				},
				targets: Array.from(targets.values(), ({ descriptor }) => descriptor),
			});
			if (response?.reload) {
				window.location.reload();
				return;
			}

			if (response?.ok && Array.isArray(response.targets)) {
				refreshedFingerprint = response.fingerprint || null;
				if (!response.targets.length && refreshedFingerprint) {
					for (const { widget } of targets.values()) reconciled.add(widget);
				}
				const results = new Map(
					response.targets.map((target) => [target.id, target]),
				);
				for (const [id, { widget }] of targets) {
					const result = results.get(id);
					if (!result || result.fallback) continue;
					try {
						await widget.refreshDelta(result);
						reconciled.add(widget);
					} catch (error) {
						captureError(error);
					}
				}
			}
		}

		await Promise.all(
			components.map(async (component) => {
				if (component.elt && !component.elt.isConnected) return;
				await component.refreshCollections(reconciled);
			}),
		);
		if (refreshedFingerprint) {
			this.elt.dataset.fingerprint = refreshedFingerprint;
		}
		await this.Notifications?.refresh?.();
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
		await this.Notifications.notify(message);
	}

	_initDrag() {
		this.isDragging = false;
		this.dragStarted = false;
		let startX, startY;

		this.elt.addEventListener("mousedown", (e) => {
			this.isDragging = false;
			this.dragStarted = true;
			startX = e.clientX;
			startY = e.clientY;
		});

		this.elt.addEventListener("mousemove", (e) => {
			if (!this.dragStarted) return;

			const deltaX = Math.abs(e.clientX - startX);
			const deltaY = Math.abs(e.clientY - startY);

			if (deltaX > 5 || deltaY > 5) {
				this.isDragging = true;
			}
		});

		this.elt.addEventListener("mouseup", () => {
			this.dragStarted = false;
		});
	}

	_click(e) {
		if (this.isDragging) {
			this.isDragging = false;
			return;
		}

		const menuTrigger = e.target.closest("[data-role='menu-trigger']");
		const menu = menuTrigger?.closest("[lp-menu]");
		if (menu && this.elt.contains(menu)) {
			e.preventDefault();
			e.stopPropagation();
			this.EntityMenu.toggle(menu);
			return;
		}

		const button = e.target.closest("button");
		const control = button?.getAttribute("lp-control");

		if (button?.matches("[data-role='flipper']")) {
			const flip = button.closest("[data-flipped]");
			const flipped = flip.dataset.flipped === "false";
			flip.dataset.flipped = flipped ? "true" : "false";
			return;
		} else if (control === "help") {
			this._showHelpModal(button);
			return;
		} else if (control === "star") {
			void this._toggleStar(button);
			return;
		} else if (control === "delete") {
			this._showDeleteModal(button);
			return;
		} else if (["previous", "next"].includes(control)) {
			if (!this.online) return;
			const widget = e.target.closest("[data-widget]");
			const component = this.getComponent(widget);
			request.get(button.dataset.route).then((response) => {
				component.widgets[widget.dataset.widget]?.refresh(response);
			});
			return;
		} else if (control || button?.hasAttribute("lp-show")) {
			this.renderComponent(button);
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
			this.renderComponent(toggle);
			return;
		}

		const link = e.target.closest("[lp-link]");
		if (link) {
			link.querySelector("[data-role='title']")?.click();
			return;
		}
	}

	async _showDeleteModal(button) {
		const modal = new DeleteModal(this, button);
		await modal.init();
	}

	async _showHelpModal(button) {
		const modal = new HelpModal(this, button);
		await modal.init();
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
		return this.SubmissionManager.successfulResponse(response, component);
	}

	update(component, data, route = component.route) {
		return this.SubmissionManager.update(component, data, route);
	}

	create(component, data, route = component.route) {
		return this.SubmissionManager.create(component, data, route);
	}

	async load(component, route) {
		if (!route) return null;
		const response = await request.get(route);

		if (!this.successfulResponse(response, component)) return null;
		return this.offlineQueue?.applyResponse(response, route) ?? response;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/002_home/test_002a_home.py::test_model_lists_load_on_toggle
	 * @features home
	 * @dimensions lazy-load loading-indicator
	 */
	_setLoadingTrigger(trigger, component, widgetName) {
		const target = component.elt.querySelector(`[data-widget="${widgetName}"]`);
		const loadsAsync =
			target?.hasAttribute("lp-load") || target?.hasAttribute("lp-prefetch");
		if (!target || target.hasAttribute("loaded") || !loadsAsync) return null;

		trigger.dataset.loading = "true";
		trigger.setAttribute("aria-busy", "true");
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

		component
			.activate(widgetName)
			.then((activated) => {
				return withTransition(async () => {
					await component.render(activated);
				});
			})
			.finally(() => {
				this._clearLoadingTrigger(loadingTrigger);
			});
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
		this._destroyed = true;
		this.elt.removeEventListener("click", this._click);
		this.elt.removeEventListener("submit", this.SubmissionManager.submit);
		window.removeEventListener(EVENTS.SERVER_CHANGE, this._receiveServerChange);
		this.SubmissionManager?.destroy();
		this.SyncManager?.destroy();
		this.DeferredOperations?.destroy();
		this.EntityMenu?.destroy();
		this.EditWatcher?.destroy();

		Object.values(this.components).forEach((component) => {
			if (component.destroy) component.destroy();
		});
		this.components = {};
	}
}
