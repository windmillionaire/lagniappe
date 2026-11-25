import { NavElement } from "../../elements/nav.ts";
import { captureError } from "../../shared/errors.ts";
import { withTransition } from "../../shared/transitions.ts";
import type { RequestResult } from "../../types/api";
import type { LoadedWidget } from "../../types/widgets";
import { loadWidget } from "../../widgets/loader.ts";
import type { PageTaskList } from "../../widgets/pageTaskList.ts";
import type { TableWidgets } from "../../widgets/tables/types.d.ts";
import type Core from "./core.ts";

export type SubcomponentEvent = CustomEvent<{ subcomponent: ViewComponent }>;

declare global {
	interface HTMLElementEventMap {
		"set-subcomponent": SubcomponentEvent;
	}
}

export default class ViewComponent {
	declare view: Core;
	declare elt: HTMLElement;
	declare key: string | undefined;
	declare name: string;
	declare kind: string | undefined;
	declare widgets: Record<string, LoadedWidget> &
		TableWidgets & {
			PageTaskList?: PageTaskList & LoadedWidget;
		};
	declare widgetLoads: Map<string, Promise<LoadedWidget | null>>;
	declare active: LoadedWidget | NavElement | null;
	declare attributes: Record<string, unknown>;
	declare _nav: NavElement | null;
	declare _activeSubComponent: ViewComponent | null;
	declare _creating: boolean;
	declare _destroyed: boolean;
	declare reconcile: (() => void) | null;

	constructor(node: HTMLElement, view: Core) {
		this.view = view;
		this.elt = node;
		this.key = node.closest<HTMLElement>("[data-key]")?.dataset.key;
		this.name = node.id;
		this.kind = node.dataset.kind || view.kind;

		this.widgets = {};
		this.widgetLoads = new Map();
		this.active = null;
		this.attributes = {};
		this._nav = null;
		this._activeSubComponent = null;

		this._creating = false;
		this._destroyed = false;

		this.reconcile = null;
	}

	get readonly() {
		return this.view.readonly || this.elt.dataset.readonly === "true";
	}

	get default() {
		return this.elt.dataset.default;
	}

	get navElt() {
		return this.elt.querySelector<HTMLElement>(
			`[lp-nav][data-nav="${this.name}"]`,
		);
	}

	get nav(): NavElement | null {
		if (this._nav) return this._nav;

		const nav = this.elt.dataset.parentNav;
		const navElt = nav ? document.getElementById(nav) : null;

		if (navElt && !this.elt.contains(navElt)) {
			this._nav = this.view.getComponent(navElt)?.nav ?? null;
		} else {
			this._nav = this.navElt ? new NavElement(this, this.navElt) : null;
			if (this.navElt) this.navElt.dataset.visible = "true";
		}

		return this._nav;
	}

	set nav(newNav: NavElement | null) {
		this._nav = newNav;

		if (this.navElt) this.navElt.dataset.visible = newNav ? "false" : "true";
	}

	get activeWidget(): LoadedWidget | null {
		return this.active instanceof NavElement ? null : this.active;
	}

	get subComponents() {
		const filtered = Array.from(
			this.elt.querySelectorAll<HTMLElement>(":scope [lp-component]"),
		).filter((component) => {
			return component.parentElement?.closest("[lp-component]") === this.elt;
		});
		return filtered;
	}

	get parentComponent() {
		return (
			this.elt.parentElement?.closest<HTMLElement>("[lp-component]") ?? null
		);
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
		return this.elt.querySelector<HTMLElement>("[data-role='error']");
	}

	async activate(show?: string | null): Promise<boolean> {
		if (this._destroyed) return false;
		this.view?.DeferredOperations?.suspendTaskForm?.(this.activeWidget?.target);
		this.active?.disable();

		if (!show) {
			this.active = null;
			this.nav?.reconcile(null, this.name);
			return false;
		} else if (["default", "active"].includes(show)) {
			show = this.default;
			if (!show) {
				this.active = null;
				return true;
			}
		} else if (show === "nav" && this.nav?.standalone) {
			this.active = this.nav;
			return true;
		}

		this.active = await this.loadWidget(show);
		if (this._destroyed) {
			this.active?.destroy?.();
			this.active = null;
			return false;
		}

		const createForm = this.active?.ifEmpty;
		if (createForm && !this._creating) {
			const createTarget = Array.from(
				this.elt.querySelectorAll<HTMLElement>("[data-widget]"),
			).some((target) => target.dataset.widget === createForm);
			if (createTarget) return await this.activate(createForm);
		}

		this.active?.enable();
		this.view?.DeferredOperations?.resumeTaskForm?.(this.active?.target);
		return true;
	}

	async prefetch() {
		const widgets = this.elt.querySelectorAll<HTMLElement>(
			"[data-widget][lp-prefetch]",
		);
		await Promise.all(
			Array.from(widgets).map(async (elt) => {
				await this.loadWidget(elt.dataset.widget);
			}),
		);
	}

	async prepareCollectionRefresh(skip = new Set<LoadedWidget>()) {
		const widgets = Object.values(this.widgets);
		const commits = await Promise.all(
			widgets.map(async (widget) => {
				if (skip.has(widget)) return null;
				if (widget.refreshScope !== "collection") return null;
				if (!widget.refresh) return null;
				if (
					widget.unsavedState === true ||
					widget.form?._queued === true ||
					widget.target?.querySelector?.(
						"[lp-edited-marker][data-visible='true']",
					)
				)
					return null;
				const response = await this.view.load(this, widget.route);
				if (!response || response.updated === false) return null;
				if (widget.prepareRefresh) {
					return await widget.prepareRefresh(response);
				}
				return () => {
					const result = widget.refresh?.(response);
					if (result instanceof Promise) void result.catch(captureError);
				};
			}),
		);
		return commits.filter((commit) => commit != null);
	}

	async refreshCollections(skip = new Set<LoadedWidget>()) {
		const commits = await this.prepareCollectionRefresh(skip);
		commits.forEach((commit) => {
			commit();
		});
	}

	async loadWidget(name?: string | null): Promise<LoadedWidget | null> {
		if (!name || this._destroyed) return null;
		if (this.widgets[name]) return this.widgets[name];
		const existing = this.widgetLoads.get(name);
		if (existing) return existing;

		const pending = (async () => {
			const widget = await loadWidget(this, name);
			if (!widget || this._destroyed) {
				widget?.destroy?.();
				return null;
			}
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
	async load(
		widget = this.activeWidget,
		route?: string | URL | null,
	): Promise<undefined | null> {
		if (!widget || widget?.loaded) return null;
		route = route || widget.route;

		const response = await this.view.load(this, route);
		widget.modified = true;
		if (!response) return null;
		if (response.updated === false && widget.initialized) return null;
		const html = response.html || null;
		const responseTarget = html?.querySelector<HTMLElement>(
			`[data-widget='${widget.name}']`,
		);
		if (responseTarget && response.pollChannel) {
			responseTarget.dataset.pollChannel = response.pollChannel;
		}
		if (responseTarget && response.pollRevision) {
			responseTarget.dataset.pollRevision = response.pollRevision;
		}

		const append = await widget.updated?.(response);
		if (append) void this.load(widget, append.dataset.route);
		if (widget !== this.active) {
			await widget.prepareReconcile();
			await withTransition(() => widget.reconcile(), {
				label: `${this.name}:${widget.name}:load`,
			});
		}
	}

	// triggered by a submit event, called by the core class's update() method
	// any loaded widgets that have targets in the server response will be updated
	// if the widget hasn't been loaded yet, its target will be replaced with the new html
	// otherwise the widget's updated() method will be called with the response
	async updated(response: RequestResult) {
		const updates = {
			replace: [] as { target: Element; elt: HTMLElement }[],
			append: [] as HTMLElement[],
		};

		const widgetUpdates: ReturnType<NonNullable<LoadedWidget["updated"]>>[] =
			[];
		const targets = response.html
			? response.html.querySelectorAll<HTMLElement>("[data-widget]")
			: [];
		targets.forEach((elt) => {
			const name = elt.dataset.widget;
			if (!name) return;
			const widget = this.widgets[name];
			const target = this.elt.querySelector(`[data-widget='${name}']`);

			if (widget?.updated) {
				widgetUpdates.push(widget.updated(response));
				widget.modified = true;
			} else if (target) {
				updates.replace.push({ target, elt });
			} else {
				updates.append.push(elt);
			}
		});
		await Promise.all(widgetUpdates);
		await this.prepareRender(true);

		await withTransition(
			() => {
				updates.replace.forEach(({ target, elt }) => {
					target.replaceWith(elt);
				});
				this.elt.append(...updates.append);
				this.activeWidget?.success?.();
				this.render(true);
			},
			{ label: `${this.name}:update` },
		);
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
	async created(response: RequestResult) {
		const originator = this.activeWidget;
		if (!originator) return;
		this._creating = true;

		originator.modified = true;

		const destination = originator.target?.dataset.destination;
		if (destination === undefined)
			throw new Error("Create widget requires data-destination");
		const [componentId, widgetName] = destination.split(":");

		await originator.created?.(response);

		let component: ViewComponent | null;
		if (widgetName) {
			if (componentId === this.name) {
				component = this;
				await this.activate(widgetName);
			} else {
				component = this.view.getComponent(
					document.getElementById(componentId),
				);
				await component?.activate(widgetName);
			}

			if (component?.active) {
				await component.activeWidget?.created?.(response);
				component.active.modified = true;
			}
		} else {
			component = null;
		}

		await this.prepareRender(true);
		if (component && this !== component) await component.prepareRender(true);
		await withTransition(
			() => {
				this.render(true);
				if (component && this !== component) component.render(true);
			},
			{ label: `${this.name}:create` },
		);
		this._creating = false;
	}

	preload(property: string): unknown {
		const data = this.elt.dataset.preload;
		const attributes: unknown = data ? JSON.parse(data) : {};
		this.attributes =
			attributes && typeof attributes === "object" && !Array.isArray(attributes)
				? (attributes as Record<string, unknown>)
				: {};
		return this.attributes[property] ?? null;
	}

	showError(message: string) {
		this.enable();

		const active = this.activeWidget;
		if (this.open !== "false" && active?.showError) {
			active.showError(message);
		} else {
			const errorElt = this.error;
			if (!errorElt) return;

			const error = document.createElement("span");
			error.textContent = message;

			void withTransition(
				() => {
					errorElt.replaceChildren(error);
					errorElt.dataset.visible = "true";
				},
				{ label: `${this.name}:error` },
			);
			active?.enable();
		}
	}

	// if widgets return data, it must be a FormData object
	// this FormData will have the data-role of the submitter added to it
	get formData() {
		return this.activeWidget?.formData;
	}

	get open() {
		return this.elt.dataset.open;
	}

	get route() {
		return (
			this.activeWidget?.route ||
			this.activeWidget?.target?.dataset.route ||
			this.elt.dataset.route
		);
	}

	deactivate(visible = true, originator: ViewComponent | null = null) {
		const active = this.active;
		if (active) {
			this.view?.DeferredOperations?.suspendTaskForm?.(
				this.activeWidget?.target,
			);
			if (active instanceof NavElement) active.disable();
			else active.disable(true);
			active.reconcile(true);
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
			if (subComponent && subComponent !== this) subComponent.deactivate(false);
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

	_setSubComponent(subComponent: ViewComponent) {
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

	async prepareRender(_visible?: boolean) {
		await Promise.all(
			Object.values(this.widgets).map((widget) => {
				return widget.prepareReconcile();
			}),
		);
	}

	// User actions and initial entity enhancement call this within a transition.
	// Connected-DOM manipulation in widgets belongs in postreconcile().
	render(visible: boolean) {
		const open = visible ? this.active?.name || "true" : false;
		this.elt.dataset.visible = this.persistent || visible ? "true" : "false";

		this._setParentComponent();

		Object.values(this.widgets).forEach((widget) => {
			widget.reconcile();
		});

		if (this.nav) {
			this.nav.enable(this);
			this.nav.reconcile(this.active?.name, this.name);
		}

		this.elt.dataset.open = open || "false";
		this.view.onComponentRendered?.(this);
		void this.view.schedulePollingReconciliation?.();
	}

	destroy() {
		this._destroyed = true;
		Object.values(this.widgets).forEach((widget) => {
			widget.destroy?.();
		});
		this.widgetLoads.clear();
		if (this.key !== undefined) delete this.view.components[this.key];
	}
}
