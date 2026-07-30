import { NavElement } from "../../elements/nav";
import { showBriefly, withTransition } from "../../shared";
import { loadWidget } from "../../widgets/loader";

/**
 * @testable infrastructure
 * @covered-by src/script/views/base/core.mjs::Core.getComponent
 * @covered-by src/script/views/base/core.mjs::Core.renderComponent
 * @covered-by src/script/views/base/core.mjs::Core.update
 * @covered-by src/script/views/base/core.mjs::Core.create
 */
export default class ViewComponent {
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
