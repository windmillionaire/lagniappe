/*! Third-party licenses: /third-party-licenses.txt */
import { E as EntityMenu, S as SearchBox } from './entityMenu.js?v=b30f3f24';
import { S as STYLES, r as request, E as ENDPOINTS, j as createIcon, l as loadWidget, w as withTransition, m as showBriefly, a as captureError, M as Modal, c as connectivity, P as PollingCoordinator, n as DeferredOperationManager, o as EditWatcher, p as OfflineQueue, q as SyncManager, f as clearRecentSearchResults, O as OfflineModal, D as DeleteModal, H as HelpModal } from './shared.js?v=b30f3f24';
import { D as Dropdown } from './dropdown.js?v=b30f3f24';

/**
 * @testable infrastructure
 */
class NavElement {
	constructor(component, elt) {
		this.component = component;
		this.active = true;
		this.modified = false;
		this._widget = null;

		this.element = elt;
		this.name = elt.dataset.nav;

		this.title = elt.querySelector("[data-role='title']");

		this.nav =
			document.querySelector(`nav[data-nav="${this.name}"]`) ||
			this.component.elt.querySelector("nav");
		this.standalone = this.nav.dataset.standalone === "true";
		this.persistent = this.nav.dataset.persistent === "true";
		this.componentToggles = this._initNavToggles();

		if (this.nav.querySelector(".loader")) {
			this.nav.addEventListener("click", this._click.bind(this));
		}

		this._hideNavContainer = new Set();
		this._navContainer =
			this.element.querySelector("[data-flipped]") || this.nav;
		this.header = elt.querySelector("[data-role='header']");
		this.widgetToggles = this.header
			? this._initWidgetToggles(this.header)
			: {};

		this.controls = elt.querySelector("[data-role='controls']");
		this.widgetControls = this.controls ? this._initControls() : {};
		this.navToggles = elt.querySelector("[data-role='nav-toggles']");
	}

	_initNavToggles() {
		return Object.fromEntries(
			Array.from(
				this.nav.querySelectorAll("button[lp-show]:not([lp-control])"),
			).map((button) => {
				const [component, widget] = button.getAttribute("lp-show").split(":");
				return [
					["active", "nav"].includes(widget) ? component : widget,
					button,
				];
			}),
		);
	}

	_initWidgetToggles() {
		return Object.fromEntries(
			Array.from(
				this.header.querySelectorAll("button[lp-show]:not([lp-control])"),
			).map((button) => {
				const [component, widget] = button.getAttribute("lp-show").split(":");
				this._hideNavContainer.add(widget);
				return [component, button];
			}),
		);
	}

	_initControls() {
		return Object.fromEntries(
			Array.from(this.controls.querySelectorAll("button[lp-control]")).map(
				(button) => [button.getAttribute("lp-control"), button],
			),
		);
	}

	_click(event) {
		if (!event.target.closest("[lp-show]:not([lp-control])")) return;

		Object.values(this.componentToggles).forEach((button) => {
			if (!button.classList.contains("loader")) return;

			const selected = button.contains(event.target);
			if (selected) {
				button.disabled = true;
			} else {
				button.classList.add("opacity-50");
			}
			this.modified = true;
		});
	}

	_setSubToggleVisibility(hideToggles, component) {
		const controlsVisible = this.settings.controls === "true";
		const keepSubToggles = this.settings.subtoggles === "true";
		hideToggles = hideToggles || (controlsVisible && !keepSubToggles);

		Object.entries(this.widgetToggles).forEach(([name, toggle]) => {
			const hidden = hideToggles || name !== component;
			toggle.dataset.visible = hidden ? "false" : "true";
		});
	}

	_setComponentToggleVisibility(hideToggles, widget, selected) {
		const mobile = this.component.view.mobile;

		if (this._hideNavContainer.has(widget) && hideToggles) {
			this._navContainer.dataset.visible = "false";
			return false;
		}
		if (this._navContainer) this._navContainer.dataset.visible = "true";

		Object.entries(this.componentToggles).forEach(([show, toggle]) => {
			if (hideToggles) {
				toggle.dataset.visible = "false";
			} else if (this.name === selected) {
				toggle.dataset.visible = "true";
			} else {
				toggle.dataset.selected = show === selected ? "true" : "false";
				toggle.dataset.visible = mobile ? toggle.dataset.selected : "true";
			}
		});

		return true;
	}

	_setNavVisibility(widget) {
		const togglesVisible = widget ? this.settings.nav !== "false" : true;
		const visible =
			this.persistent || this.component.active === this || togglesVisible
				? "true"
				: "false";

		this.nav.dataset.visible = visible;
	}

	_updateLoadingToggles() {
		if (!this.modified) return;
		this.modified = false;

		this.nav.querySelectorAll(".loader").forEach((toggle) => {
			toggle.disabled = false;
			toggle.classList.remove("opacity-50");
		});
	}

	_setControlOptions(widget) {
		const controlsVisible = widget ? this.settings.controls === "true" : false;
		this.controls.dataset.visible = controlsVisible ? "true" : "false";
		if (this.navToggles) {
			this.navToggles.dataset.visible = controlsVisible ? "false" : "true";
		}
		if (!controlsVisible) return;

		if ("flipped" in this._navContainer.dataset) {
			this._navContainer.dataset.flipped = "false";
		}

		Object.entries(this.widgetControls).forEach(([option, element]) => {
			this._setControlOption(option, element);
		});
	}

	_setTitle() {
		const title = this.settings.title || this.component.elt.dataset.title;
		this.title.textContent = title || "";
	}

	enable(component) {
		this.component = component;
		this.active = true;
	}

	disable() {
		this.active = false;
	}

	hide() {
		this.element.classList.add(
			"[&>*:not([data-role='error'])]:opacity-50",
			"pointer-events-none",
		);
	}

	show() {
		this.element.classList.remove(
			"[&>*:not([data-role='error'])]:opacity-50",
			"pointer-events-none",
		);
	}

	reconcile(widget, component) {
		const selected = this.componentToggles[widget] ? widget : component;
		const hideToggles = this.settings.nav === "false";
		this._setComponentToggleVisibility(hideToggles, widget, selected);
		this.element.dataset.visible = this.active ? "true" : "false";

		if (!this.active) return;

		this._setSubToggleVisibility(hideToggles, component);
		this._setNavVisibility(widget);
		this._updateLoadingToggles();
		this._setTitle();
		this._setControlOptions(widget);
	}

	get settings() {
		if (this.component.active === this) {
			return this.nav.dataset;
		}
		return this.component.active?.target?.dataset || {};
	}

	_setControlOption(option, element = this.widgetControls[option]) {
		if (!element) return;

		const settings = this.settings;
		const value = this.component.active
			? settings[option]
			: this.component.elt.dataset?.[option];

		if (option === "delete") {
			element.dataset.visible = settings.key ? "true" : "false";
			return;
		} else if (!value && element) {
			element.dataset.visible = "false";
			return;
		}

		const controls = element.dataset.controls;
		if (controls) {
			element.setAttribute(`lp-${controls}`, value);
		}

		element.dataset.visible = "true";
	}
}

const CLEAR_ALL_KEY = "__clear_all_notifications__";

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_renders_target_and_preserves_pending_state
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_notification_menu_deletes_and_clears
 * @features notifications
 * @dimensions menu-open dropdown-refresh delete clear-all long-text-wrap
 */
class Notifications {
	constructor(view) {
		this.view = view;
		this.dropdown = null;
		this.button = document.querySelector("[data-role='notifications']");
		this.count = document.querySelector("[data-role='notification-count']");
		this.notifications = [];

		this._selectNotification = this._selectNotification.bind(this);
		this._clearNotifications = this._clearNotifications.bind(this);
		this._closeOnNotificationClick = this._closeOnNotificationClick.bind(this);
	}

	get visible() {
		return this.button?.dataset.visible === "true";
	}

	set visible(value) {
		if (!this.button) return;
		this.button.dataset.visible = value ? "true" : "false";
	}

	init(notifications = []) {
		if (!this.button) return;

		this.notifications = this.notifications.concat(notifications);
		this.dropdown = new Dropdown(this.button).init({
			items: this._dropdownItems(),
			placement: "bottom-end",
			styles: {
				panel: `${STYLES.dropdown.panel} mt-2 w-80 max-w-[calc(100vw-1rem)] sm:w-96`,
			},
		});
		this._updateCount();
		this._unsubscribe = this.view.PollingCoordinator?.subscribe(
			{
				id: "personal:notifications",
				type: "channel",
				channel: "notifications",
				revision: null,
			},
			{
				onResult: async (result) => {
					if (result.status !== "changed") return;
					if (!(await this.refresh())) return false;
					return true;
				},
			},
		);
	}

	/**
	 * @testable false
	 * @manual true
	 * @reason pending/completed replacement is covered through dropdown refresh
	 * @features notifications
	 * @dimensions upsert pending-complete
	 */
	upsertNotification(html) {
		if (!this.dropdown || !html) return;

		const option = this._notificationOption(html);
		const index = option.key
			? this.notifications.findIndex((item) => item.key === option.key)
			: -1;

		if (index >= 0) {
			this.notifications.splice(index, 1, option);
		} else {
			this.notifications.splice(0, 0, option);
		}
		this._updateDropdown();
	}

	async refresh() {
		if (!this.dropdown || !this.view.online) return false;

		const response = await request.get(ENDPOINTS.notifications);
		if (!response?.ok || !response.html) return false;

		this.notifications = this._optionsFromHtml(response.html);
		this._updateDropdown();
		return true;
	}

	_optionsFromHtml(html) {
		return Array.from(html.querySelectorAll("[role='option']")).map(
			(option) => {
				return this._notificationOption(option.outerHTML, option.dataset.key);
			},
		);
	}

	_notificationOption(html, key = null) {
		const element = this._htmlOption(html);
		return {
			key: key || element?.dataset.key || null,
			html: element?.outerHTML || html,
			onClick: this._selectNotification,
			closeOnClick: this._closeOnNotificationClick,
		};
	}

	_dropdownItems() {
		if (!this.notifications.length) return [];
		return [this._clearAllOption(), ...this.notifications];
	}

	_clearAllOption() {
		return {
			key: CLEAR_ALL_KEY,
			html: `
				<button role="option"
					type="button"
					data-action="clear-notifications"
					class="${STYLES.dropdown.option.action} border-b border-base-light !rounded-none mb-1 pb-2 text-delete-default">
					${createIcon("trash.inactive", STYLES.dropdown.icon).outerHTML}
					<span>Clear all notifications</span>
				</button>
			`,
			onClick: this._clearNotifications,
			closeOnClick: false,
		};
	}

	/**
	 * @testable false
	 * @covered-by src/script/elements/notifications.mjs::Notifications
	 * @reason parsing is internal to notification option replacement
	 */
	_htmlOption(html) {
		const template = document.createElement("template");
		template.innerHTML = String(html || "").trim();
		return template.content.querySelector("[role='option']");
	}

	async _selectNotification(option, event) {
		const deleteButton = event?.target?.closest(
			"[data-action='delete-notification']",
		);
		if (deleteButton) {
			event.preventDefault();
			event.stopPropagation();
			await this._deleteNotification(deleteButton.dataset.key);
			return;
		}

		const link =
			event?.target?.closest("a[href]") || option.querySelector("a[href]");
		if (link) window.location.href = link.href;
	}

	_closeOnNotificationClick(_option, event) {
		return !event?.target?.closest("[data-action='delete-notification']");
	}

	async _clearNotifications() {
		if (!this.notifications.length) return;

		const response = await request.delete(ENDPOINTS.notifications);
		if (!response?.ok) return;

		this.notifications = [];
		this._updateDropdown();
	}

	async _deleteNotification(key) {
		if (!key) return;

		const response = await request.delete(ENDPOINTS.activity(key));
		if (!response?.ok) return;

		this.notifications = this.notifications.filter((item) => item.key !== key);
		this._updateDropdown();
	}

	_updateDropdown() {
		if (!this.dropdown) return;

		this.dropdown.updateOptions(this._dropdownItems());
		this._updateCount();
	}

	_updateCount() {
		const count = this.notifications.length;
		if (this.count) this.count.textContent = count;
		if (this.button) {
			this.button.setAttribute("aria-label", `Notifications: ${count}`);
		}
		this.visible = count > 0;
	}

	destroy() {
		this._unsubscribe?.();
		this._unsubscribe = null;
		this.dropdown?.destroy?.();
		this.dropdown = null;
	}
}

/**
 * @testable infrastructure
 * @covered-by src/script/views/base/core.mjs::Core.getComponent
 * @covered-by src/script/views/base/core.mjs::Core.renderComponent
 * @covered-by src/script/views/base/core.mjs::Core.update
 * @covered-by src/script/views/base/core.mjs::Core.create
 */
class ViewComponent {
	constructor(node, view) {
		this.view = view;
		this.elt = node;
		this.key = node.closest("[data-key]")?.dataset.key;
		this.name = node.id;
		this.kind = node.dataset.kind || view.kind;

		this.widgets = {};
		this.widgetLoads = new Map();
		this.active = null;
		this.attributes = {};
		this._nav = null;
		this._activeSubComponent = null;

		this._creating = false;

		this.reconcile = null;
	}

	get readonly() {
		return this.view.readonly || this.elt.dataset.readonly === "true";
	}

	get default() {
		return this.elt.dataset.default;
	}

	get navElt() {
		return this.elt.querySelector(`[lp-nav][data-nav="${this.name}"]`);
	}

	get nav() {
		if (this._nav) return this._nav;

		const nav = this.elt.dataset.parentNav;
		const navElt = nav ? document.getElementById(nav) : null;

		if (navElt && !this.elt.contains(navElt)) {
			this._nav = this.view.getComponent(navElt).nav;
		} else {
			this._nav = this.navElt ? new NavElement(this, this.navElt) : null;
			if (this.navElt) this.navElt.dataset.visible = "true";
		}

		return this._nav;
	}

	set nav(newNav) {
		this._nav = newNav;

		if (this.navElt) this.navElt.dataset.visible = newNav ? "false" : "true";
	}

	get subComponents() {
		const filtered = Array.from(
			this.elt.querySelectorAll(":scope [lp-component]"),
		).filter((component) => {
			return component.parentElement.closest("[lp-component]") === this.elt;
		});
		return filtered;
	}

	get parentComponent() {
		return this.elt.parentElement.closest("[lp-component]");
	}

	get persistent() {
		return this.elt.dataset.persistent === "true";
	}

	set persistent(value) {
		this.elt.dataset.persistent = value ? "true" : "false";
	}

	get visible() {
		return this.elt.dataset.visible === "true";
	}

	set visible(value) {
		this.elt.dataset.visible = value ? "true" : "false";
	}

	get error() {
		return this.elt.querySelector("[data-role='error']");
	}

	/**
	 * @testable false
	 * @reason foundational view lifecycle plumbing
	 */
	async activate(show) {
		this.active?.disable();

		if (!show) {
			this.active = null;
			this.nav?.reconcile(null, this.name);
			return false;
		} else if (["default", "active"].includes(show)) {
			show = this.default;
			if (!show) return false;
		} else if (show === "nav" && this.nav?.standalone) {
			this.active = this.nav;
			return true;
		}

		this.active = await this.loadWidget(show);

		const createForm = this.active?.ifEmpty;
		if (createForm && !this._creating) {
			const createTarget = Array.from(
				this.elt.querySelectorAll("[data-widget]"),
			).some((target) => target.dataset.widget === createForm);
			if (createTarget) return await this.activate(createForm);
		}

		this.active?.enable();
		return true;
	}

	/**
	 * @testable false
	 * @reason foundational view lifecycle plumbing
	 */
	async prefetch() {
		const widgets = this.elt.querySelectorAll("[data-widget][lp-prefetch]");
		await Promise.all(
			Array.from(widgets).map(async (elt) => {
				await this.loadWidget(elt.dataset.widget);
			}),
		);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_component_refresh_only_loads_collection_widgets
	 * @features reconnect-refresh collections forms
	 * @dimensions explicit-collection-scope form-exclusion
	 */
	async refreshCollections(skip = new Set()) {
		const widgets = Object.values(this.widgets);
		await Promise.all(
			widgets.map(async (widget) => {
				if (skip.has(widget)) return;
				if (widget.refreshScope !== "collection") return;
				if (!widget.refresh) return;
				if (
					widget.unsavedState === true ||
					widget.form?._queued === true ||
					widget.target?.querySelector?.(
						"[lp-edited-marker][data-visible='true']",
					)
				)
					return;
				const response = await this.view.load(this, widget.route);
				if (!response || response.updated === false) return;
				await widget.refresh(response);
			}),
		);
	}

	/**
	 * @testable false
	 * @reason foundational view lifecycle plumbing
	 */
	async loadWidget(name) {
		if (!name) return null;
		if (this.widgets[name]) return this.widgets[name];
		if (this.widgetLoads.has(name)) return this.widgetLoads.get(name);

		const pending = (async () => {
			const widget = await loadWidget(this, name);
			this.widgets[name] = widget;
			if (widget.loading || widget.loaded) return widget;
			widget.loading = true;
			const shouldLoad =
				widget.target?.hasAttribute("lp-load") ||
				widget.target?.hasAttribute("lp-prefetch");
			if (shouldLoad) await this.load(widget);
			return widget;
		})();
		this.widgetLoads.set(name, pending);

		try {
			return await pending;
		} finally {
			if (this.widgetLoads.get(name) === pending) {
				this.widgetLoads.delete(name);
			}
		}
	}

	// this is called when a widget needs to be loaded/reloaded in response to an event
	/**
	 * @testable false
	 * @reason foundational view lifecycle plumbing
	 */
	async load(widget = this.active, route = null) {
		if (!widget || widget?.loaded) return null;
		route = route || widget.route;

		const response = await this.view.load(this, route);
		widget.modified = true;
		if (!response) return null;

		const append = await widget.updated(response);
		if (append) this.load(widget, append.dataset.route);
		if (widget !== this.active) {
			await widget.postreconcile();
		}
	}

	// triggered by a submit event, called by the core class's update() method
	// any loaded widgets that have targets in the server response will be updated
	// if the widget hasn't been loaded yet, its target will be replaced with the new html
	// otherwise the widget's updated() method will be called with the response
	async updated(response) {
		const updates = { replace: [], append: [] };

		response.html?.querySelectorAll("[data-widget]").forEach((elt) => {
			const name = elt.dataset.widget;
			const widget = this.widgets[name];
			const target = this.elt.querySelector(`[data-widget='${name}']`);

			if (widget?.updated) {
				widget.updated(response);
				widget.modified = true;
			} else if (target) {
				updates.replace.push({ target, elt });
			} else {
				updates.append.push(elt);
			}
		});

		await withTransition(async () => {
			updates.replace.forEach(({ target, elt }) => {
				target.replaceWith(elt);
			});
			this.elt.append(...updates.append);
			this.active?.success?.();
			await this.render(true);
		});
	}

	disable() {
		this.nav?.hide();
	}

	enable() {
		this.nav?.show();
	}

	// triggered by a submit event, called by the core class's create() method
	// this.active is the form that triggered the event
	// if it needs to be reset or modified, that should happen in its postreconcile() method
	// receiver is the widget that will receive the new html, this will be activated
	// it may be the same component or a different component, both components will be rendered
	async created(response) {
		if (!this.active) return;
		const originator = this.active;
		this._creating = true;

		originator.modified = true;

		const [componentId, widgetName] =
			originator.target.dataset.destination.split(":");

		await originator.created(response);

		let component;
		if (widgetName) {
			if (componentId === this.name) {
				component = this;
				await this.activate(widgetName);
			} else {
				component = this.view.getComponent(
					document.getElementById(componentId),
				);
				await component.activate(widgetName);
			}

			if (component.active) {
				await component.active.created?.(response);
				component.active.modified = true;
			}
		} else {
			component = null;
		}

		await withTransition(async () => {
			await this.render(true);
			if (component && this !== component) await component.render(true);
		});
		this._creating = false;
	}

	preload(property) {
		const data = this.elt.dataset.preload;
		this.attributes = data ? JSON.parse(data) : {};
		return this.attributes[property] ?? null;
	}

	showError(message) {
		this.enable();

		if (this.active?.showError) {
			this.active.showError(message);
		} else {
			const errorElt = this.error;
			if (!errorElt) return;

			const error = document.createElement("span");
			error.textContent = message;

			showBriefly(errorElt, error);
			this.active?.enable();
		}
	}

	// if widgets return data, it must be a FormData object
	// this FormData will have the data-role of the submitter added to it
	get formData() {
		return this.active?.formData;
	}

	get open() {
		return this.elt.dataset.open;
	}

	get route() {
		return (
			this.active?.route ||
			this.active?.target.dataset.route ||
			this.elt.dataset.route
		);
	}

	deactivate(visible = true, originator = null) {
		if (this.active) {
			this.active.disable(true);
			this.active.reconcile(true);
			this.nav?.reconcile(null, this.name);
		}

		if (!visible) {
			this.elt.dataset.visible = this.persistent ? "true" : "false";
			this.elt.dataset.open = "false";
		}

		if (originator) {
			this.nav?.disable();
			this.nav?.reconcile(originator.active?.name, originator.name);
		}
	}

	_setParentComponent() {
		const parentElt = this.parentComponent;
		const parent = parentElt ? this.view.getComponent(parentElt) : null;
		const subComponents = parent ? parent.subComponents : this.subComponents;

		subComponents.forEach((elt) => {
			const subComponent = this.view.getComponent(elt);
			if (subComponent !== this) subComponent.deactivate(false);
		});

		if (!parent) return;

		if (!this.nav && parent.nav) {
			this.nav = parent.nav;
		} else if (this.nav !== parent.nav && this.nav?.standalone) {
			parent.deactivate(true, this);
			parent.elt.dataset.visible = "true";
		}

		parent._setSubComponent(this);
	}

	_setSubComponent(subComponent) {
		const activeSubComponent = this._activeSubComponent;
		if (activeSubComponent && activeSubComponent !== subComponent) {
			const visible = activeSubComponent.persistent ? "true" : "false";
			activeSubComponent.elt.dataset.visible = visible;
		}
		this._activeSubComponent = subComponent;

		const event = new CustomEvent("set-subcomponent", {
			detail: {
				subcomponent: subComponent,
			},
			bubbles: true,
		});
		subComponent.elt.dispatchEvent(event);
	}

	// this should always be called with a transition, it will trigger the reconciliation of all widgets
	// any DOM manipulation in a widget should be done in the widget's postreconcile() method
	/**
	 * @testable false
	 * @reason foundational view lifecycle plumbing
	 */
	async render(visible) {
		const open = visible ? this.active?.name || "true" : false;
		this.elt.dataset.visible = this.persistent || visible ? "true" : "false";

		this._setParentComponent();

		await Promise.all(
			Object.values(this.widgets).map((widget) => {
				return widget.reconcile();
			}),
		);

		if (this.nav) {
			this.nav.enable(this);
			this.nav.reconcile(this.active?.name, this.name);
		}

		this.elt.dataset.open = open || "false";
		await this.view.reconcilePollingSubscriptions?.();
	}

	destroy() {
		Object.values(this.widgets).forEach((widget) => {
			widget.destroy?.();
		});
		this.widgetLoads.clear();
		delete this.view.components[this.key];
	}
}

/**
 * Coordinates the view-scoped form submission lifecycle.
 *
 * @testable true
 * @tests tests_js/test_015_core_submit_frontend.py::test_submit_abandons_stale_widget_after_async_prepare
 * @tests tests_js/test_015_core_submit_frontend.py::test_submit_does_not_show_upload_error_after_stale_prepare
 * @tests tests_js/test_015_core_submit_frontend.py::test_submit_stops_before_appending_when_form_data_is_missing
 * @tests tests_js/test_015_core_submit_frontend.py::test_submit_uses_explicit_action_route_over_active_widget_route
 * @features submit
 * @dimensions stale-widget direct-upload-navigation direct-upload-error missing-form-data route-override active-widget
 */
class SubmissionManager {
	constructor(view) {
		this.view = view;
		this.activeSubmitter = null;
		this.submit = this.submit.bind(this);
	}

	_clearActiveSubmitter() {
		if (this.activeSubmitter) {
			this.activeSubmitter.disabled = false;
			this.activeSubmitter = null;
		}
		this._syncOfflineSubmitStates();
	}

	_syncOfflineSubmitStates() {
		for (const component of Object.values(this.view?.components ?? {})) {
			for (const widget of Object.values(component.widgets)) {
				widget.form?.syncOfflineState?.();
			}
		}
	}

	_setActiveSubmitter(submitter) {
		if (!submitter) return;

		this.activeSubmitter = submitter;
		this.activeSubmitter.disabled = true;
	}

	async submit(event) {
		const component = this.view.getComponent(event.target);
		if (!component) {
			captureError(new Error("No component found"), event.target);
			return;
		}

		event.preventDefault();
		event.stopPropagation();

		const submitWidget = component.active;
		const submitForm = event.target;
		const route = event.detail?.route || component.route;

		this._setActiveSubmitter(event.submitter);
		if (submitWidget?.form?.syncOfflineState?.()) {
			this._clearActiveSubmitter();
			return;
		}

		let prepared = true;
		try {
			prepared = await submitWidget?.prepareSubmit?.({
				route,
				submitter: event.submitter,
			});
		} catch (error) {
			if (
				component.active === submitWidget &&
				submitWidget?.target?.isConnected &&
				submitForm?.isConnected
			) {
				component.showError(error.message || "Could not prepare upload");
			}
			this._clearActiveSubmitter();
			return;
		}
		if (prepared === false) {
			this._clearActiveSubmitter();
			return;
		}

		if (
			component.active !== submitWidget ||
			!submitWidget?.target?.isConnected ||
			!submitForm?.isConnected
		) {
			this._clearActiveSubmitter();
			return;
		}

		const data = component.formData;
		if (!data) {
			captureError(new Error("No form data found"), submitWidget.target);
			this._clearActiveSubmitter();
			return;
		}

		const role = event.submitter?.dataset?.role || event.detail?.role;
		if (
			submitWidget.target?.hasAttribute("lp-deferred") &&
			(typeof data.has !== "function" || !data.has("operation-id"))
		) {
			data.append("operation-id", this.view.operationId());
		}
		if (role) data.append("role", role);

		const explain = event.submitter?.dataset?.explain;
		if (explain) data.append("explain", explain);

		if (submitWidget.target?.hasAttribute("lp-create")) {
			this.create(component, data, route);
		} else if (
			event.detail?.update ||
			submitWidget.target?.hasAttribute("lp-update")
		) {
			this.update(component, data, route);
		}
	}

	successfulResponse(response, component) {
		if (!response) return false;

		if (response.reload) {
			window.location.reload();
			return false;
		} else if (response.error) {
			component?.showError?.(response.error);
			this._clearActiveSubmitter();
			return false;
		} else if (response.modal) {
			const modal = new Modal(this.view);
			modal.attach(response.modal, component);
			this._clearActiveSubmitter();
			return false;
		}

		return true;
	}

	async update(component, data, route = component.route) {
		if (!this.view.online && this.view.offlineQueue) {
			const response = await this.view.offlineQueue.queueSubmit(
				component,
				data,
				route,
				"PUT",
			);
			if (response) {
				await withTransition(async () => {
					component.active?.form?.queued?.();
					this._clearActiveSubmitter();
				});
			} else {
				this._clearActiveSubmitter();
			}
			return;
		}

		const response = await request.put(route, data);
		if (!this.successfulResponse(response, component)) return;
		component.active?.form?.clearUnsavedState?.();
		if (response.deferred) {
			await this._deferredUpdated(response, component);
			return;
		}

		try {
			await component.updated(response);
		} finally {
			this._clearActiveSubmitter();
		}
	}

	async create(component, data, route = component.route) {
		if (!this.view.online && this.view.offlineQueue) {
			const response = await this.view.offlineQueue.queueSubmit(
				component,
				data,
				route,
				"POST",
			);
			if (response) {
				try {
					await component.created(response);
				} finally {
					this._clearActiveSubmitter();
				}
			} else {
				this._clearActiveSubmitter();
			}
			return;
		}

		const response = await request.post(route, data);
		if (!this.successfulResponse(response, component)) return;
		component.active?.form?.clearUnsavedState?.();
		if (response.deferred) {
			await this._deferredCreated(response, component);
			return;
		}

		try {
			await component.created(response);
		} finally {
			this._clearActiveSubmitter();
		}
	}

	/**
	 * @testable true
	 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_create_page_autofill_is_deferred
	 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_generate_pages_submit_marks_form_successful
	 * @features pages
	 * @dimensions deferred-submit
	 */
	async _deferredCreated(response, component) {
		this.view.DeferredOperations?.track(response.operation, {
			node: component.active?.target,
		});
		if (response.notification) {
			this.view.Notifications?.upsertNotification?.(response.notification);
		}

		if (response.html) {
			try {
				await component.created(response);
			} finally {
				this._clearActiveSubmitter();
			}
			return;
		}

		await withTransition(async () => {
			component.active?.created?.(response);
			await component.active?.postreconcile?.();
			component.active?.success?.();
			this._clearActiveSubmitter();
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
	 * @tests tests_e2e/006_tasks/test_006g_task_autofill.py::test_task_autofill_runs_deferred_with_page_file_context
	 * @pairs pages:autofill pages:deferred tasks:autofill tasks:deferred
	 * @pairs notifications:autofill notifications:deferred
	 * @pairs deferred-jobs:refresh deferred-jobs:form-schema
	 * @pairs pages:refresh pages:form-schema
	 */
	async _deferredUpdated(response, component) {
		if (response.locked) {
			component.active?.lockDeferredOperation?.(response);
		}
		this.view.DeferredOperations?.track(response.operation, {
			node: component.active?.target,
		});
		if (response.notification) {
			this.view.Notifications?.upsertNotification?.(response.notification);
		}

		if (response.html) {
			try {
				await component.updated(response);
			} finally {
				this._clearActiveSubmitter();
			}
			return;
		}

		await withTransition(() => {
			if (
				!component.active?.target?.querySelector(
					"[data-role='deferred-progress']",
				)
			) {
				component.active?.form?.success?.();
			}
			this._clearActiveSubmitter();
		});
	}

	destroy() {
		this._clearActiveSubmitter();
		this.view = null;
	}
}

const ISOLATED_TASK_ACTIONS = new Set(["TaskMove", "TaskCombine"]);

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_task_update_preserves_open_widget_and_completed_readonly_state
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_while_another_task_is_open_keeps_rows_clear
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_task_form_filters_compatible_tasks
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_tasks_migrates_history_and_reconciles_task_delta
 * @pairs tasks:update-state tasks:refresh tasks:readonly
 * @pairs tasks:create tasks:while-open tasks:list-state
 * @pairs task-combine:isolated-form task-combine:lazy-reload
 * @pairs task-combine:view-page task-combine:linked-page
 * @pairs task-combine:delta task-combine:no-reload
 */
class Task extends ViewComponent {
	async activate(show) {
		const existingCombine =
			show === "TaskCombine" ? this.widgets.TaskCombine : null;
		if (show === "TaskCombine" && this.view.key) {
			const target = this.elt.querySelector("[data-widget='TaskCombine']");
			if (target?.dataset.route) {
				const route = new URL(target.dataset.route, window.location.origin);
				route.searchParams.set("page", this.view.key);
				const scopedRoute = `${route.pathname}${route.search}`;
				target.dataset.route = scopedRoute;
				if (existingCombine) existingCombine.route = scopedRoute;
			}
		}
		const activated = await super.activate(show);
		if (activated && existingCombine) {
			const separator = existingCombine.route.includes("?") ? "&" : "?";
			await this.load(
				existingCombine,
				`${existingCombine.route}${separator}refresh=${Date.now()}`,
			);
		}
		return activated;
	}

	closeOpenWidget() {
		if (!this.open || this.open === "false") return false;

		this.deactivate(false);
		return true;
	}

	get completed() {
		return this.elt.dataset.completed === "true";
	}

	get showEmptyFields() {
		return this.readonly && !this.completed;
	}

	get formData() {
		if (ISOLATED_TASK_ACTIONS.has(this.active?.name)) {
			return this.active.formData;
		}

		const taskWidgets = Object.values(this.widgets).filter(
			(widget) =>
				!ISOLATED_TASK_ACTIONS.has(widget.name) &&
				(widget === this.active || widget.unsavedState === true) &&
				widget.target?.dataset.widget === widget.name &&
				this.elt.contains(widget.target),
		);
		const data = taskWidgets
			.map((widget) => {
				if (widget.formData instanceof FormData) return widget.formData;
				if (widget.target instanceof HTMLFormElement) {
					return new FormData(widget.target);
				}
				return null;
			})
			.filter(Boolean)
			.reduce((merged, current) => {
				for (const [key, value] of current.entries()) {
					merged.append(key, value);
				}
				return merged;
			}, new FormData());

		taskWidgets.forEach((widget) => {
			data.append("active", widget.name);
		});

		return data;
	}

	async updated(response) {
		if (response.task_delta) {
			this.deactivate(false);
			const parent = this.view.getComponent(this.parentComponent);
			await parent?.widgets?.PageTaskList?.refreshDelta(response.task_delta);
			return;
		}

		const update = response.html?.querySelector(`[id='${this.name}']`);

		if (update) {
			Object.assign(this.elt.dataset, update.dataset);
			this._replaceNav(update);
			this._removeMissingWidgets(update);
		}

		await super.updated(response);
	}

	_replaceNav(update) {
		const elt = update.querySelector("[lp-nav]");
		const target = this.nav?.element;
		if (!elt || !target) return;

		target.replaceWith(elt);
		this._nav = null;
	}

	_removeMissingWidgets(update) {
		this.elt.querySelectorAll("[data-widget]").forEach((elt) => {
			const name = elt.dataset.widget;
			const target = update.querySelector(`[data-widget='${name}']`);
			if (target) return;

			elt.remove();
			if (this.active?.name === name) this.active = null;
			this.widgets[name]?.destroy?.();
			delete this.widgets[name];
		});
	}
}

const COLLECTION_ONLY_CHANGE_TYPES = new Set(["delete", "star", "unstar"]);
const FORM_ALREADY_RECONCILED_CHANGE_TYPES = new Set([
	...COLLECTION_ONLY_CHANGE_TYPES,
	"entity-poll",
]);

/**
 * @testable infrastructure
 */
class Core {
	constructor(node) {
		this.elt = node;
		this.kind = node.dataset.kind;
		this.hash = node.dataset.hash || node.dataset.index;
		this.key = node.dataset.key;
		this.readonly = node.dataset.readonly === "true";
		this.mobile = window.matchMedia("(max-width: 640px)").matches;
		this.offlineIndicator = document.querySelector('[data-role="offline"]');
		this.offlineModal = null;
		this.online = connectivity.online;
		this.hidden = connectivity.hidden;

		this.Notifications = null;
		this.offlineQueue = null;
		this.PollingCoordinator = null;
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
	 * @tests tests_js/test_029_core_startup.py::test_core_init_starts_polling_without_waiting_for_initial_replay
	 * @pair startup:queue-hydration
	 * @pair startup:polling
	 */
	async init() {
		await this._initOfflineQueue();
		this.PollingCoordinator = new PollingCoordinator(this).init();
		this.syncReady = this._initSync();
		this._startInitialReplay();
		this.DeferredOperations = new DeferredOperationManager(this).init();
		this.prefetch();
		this._addListeners();
		this._setOfflineIndicator();
		this._initSearch();
		this._initNotifications();
		this._initEditWatcher();
		this._initPollingSubscription();

		this.elt.setAttribute("initialized", "");
		this.elt._lp_view = this;
		return this;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_core_init_starts_polling_without_waiting_for_initial_replay
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
	 * @tests tests_js/test_029_core_startup.py::test_core_init_starts_polling_without_waiting_for_initial_replay
	 * @pair polling:startup
	 * @pair sync:editor-readiness
	 */
	_initSync() {
		if (this._syncPromise) return this._syncPromise;

		this._syncPromise = (async () => {
			if (this.SyncManager) return this.SyncManager;
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

	/**
	 * Subscribe the root view to its durable entity or collection revision.
	 *
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_core_init_starts_polling_without_waiting_for_initial_replay
	 * @features polling
	 * @dimensions entity channel refresh
	 */
	_initPollingSubscription() {
		if (!this.PollingCoordinator) return;
		if (this.key) {
			const id = `view:entity:${this.key}`;
			this.PollingCoordinator.subscribe(
				{
					id,
					type: "entity",
					key: this.key,
					revision: this.elt.dataset.fingerprint || null,
				},
				{
					onResult: async (result) => {
						await this.EditWatcher?.receiveEntityResult?.(this.key, result);
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
				revision: this.elt.dataset.fingerprint || null,
			},
			{
				onResult: async (result) => {
					if (result.status === "changed") await this.refresh();
				},
			},
		);
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

		const mobileQuery = window.matchMedia("(max-width: 640px)");
		mobileQuery.addEventListener("change", (e) => {
			this.mobile = e.matches;
			this.elt.dispatchEvent(new CustomEvent("mobile-resize"));
		});

		this._initDrag();
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
								.filter(
									({ type }) => !FORM_ALREADY_RECONCILED_CHANGE_TYPES.has(type),
								)
								.map(({ key }) => key)
								.filter(Boolean),
							...destinationKeys,
						]),
					];
					if (formKeys.length) {
						if (this.PollingCoordinator?.activePoll) {
							this.EditWatcher?.enqueue(formKeys);
						} else {
							await this.EditWatcher?.invalidate(formKeys);
						}
					}
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
			this.PollingCoordinator?.pause();
			await this.SyncManager?.deregister();
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
			await this.reconcilePollingSubscriptions();
			await this.PollingCoordinator?.resume();
		}
	}

	/**
	 * Reconcile widget-owned polling after a component activation or a return
	 * to the foreground. Managers retain state for hidden widgets, but only the
	 * active visible widget may own recurring form, document, or ingress work.
	 *
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_core_init_starts_polling_without_waiting_for_initial_replay
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
		this.SubmissionManager?.destroy();
		this.SyncManager?.destroy();
		this.DeferredOperations?.destroy();
		this.EntityMenu?.destroy();
		this.EditWatcher?.destroy();
		this.Notifications?.destroy?.();
		this.PollingCoordinator?.destroy();

		Object.values(this.components).forEach((component) => {
			if (component.destroy) component.destroy();
		});
		this.components = {};
	}
}

export { Core as C, NavElement as N };
