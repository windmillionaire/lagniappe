/*! Third-party licenses: /third-party-licenses.txt */
import { c as connectivity } from './connectivity.js?v=bb782d98';
import { c as captureError, E as ENDPOINTS, w as withTransition, s as showBriefly, a as clearRecentSearchResults, r as request, b as whenIdle, m as markPerformance, S as ShellView } from './foundation.js?v=bb782d98';

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

/**
 * Widget Contract:
 * - target: Element - DOM element for this widget
 * - enable(): Set this.active = true,
 * - disable(): Set this.active = false, cleanup
 * - prereconcile(): Optional async preparation without connected-DOM writes
 * - reconcile(): Sync this.visible and prepared state to the DOM (in transition)
 * - updated(response): Handle server response
 * - created(response): Post-create handling (reset forms)
 * - data: FormData getter for submissions
 * - destroy(): Cleanup listeners
 */


const WIDGETS = {
	BaseList: () => import('./baseList.js?v=bb782d98'),
	CategoryInfo: () => import('./category.js?v=bb782d98'),
	CollaborativeDocument: () => import('./collaborative.js?v=bb782d98'),
	CreateCategory: () => import('./category.js?v=bb782d98'),
	CreateForm: () => import('./form.js?v=bb782d98'),
	CreateModelTask: () => import('./modelTasks.js?v=bb782d98'),
	CreateNote: () => import('./note.js?v=bb782d98'),
	CreatePage: () => import('./pageInfo.js?v=bb782d98'),
	CreateProject: () => import('./projectInfo.js?v=bb782d98'),
	CreateToolReport: () => import('./tools.js?v=bb782d98'),
	CreateUserTask: () => import('./taskSettings.js?v=bb782d98'),
	CreateTask: () => import('./taskSettings.js?v=bb782d98'),
	CreateUser: () => import('./user.js?v=bb782d98'),
	CreateUserGroup: () => import('./user.js?v=bb782d98'),
	DirectoryList: () => import('./lists.js?v=bb782d98'),
	DocumentSettings: () => import('./documentSettings.js?v=bb782d98'),
	FileInfo: () => import('./fileInfo.js?v=bb782d98'),
	PDFPreview: () => import('./filePdfPreview.js?v=bb782d98'),
	FileUpload: () => import('./uploadFile.js?v=bb782d98'),
	Filters: () => import('./filters.js?v=bb782d98'),
	FilterResults: () => import('./tables.js?v=bb782d98'),
	GeneratePages: () => import('./category.js?v=bb782d98'),
	GroupPermissions: () => import('./user.js?v=bb782d98'),
	HomeActivityList: () => import('./activity.js?v=bb782d98'),
	HomePageList: () => import('./lists.js?v=bb782d98'),
	HomeTaskList: () => import('./tasks.js?v=bb782d98'),
	HomeProjectList: () => import('./lists.js?v=bb782d98'),
	HomeCategoryList: () => import('./lists.js?v=bb782d98'),
	ImportData: () => import('./ingress.js?v=bb782d98'),
	IndexTable: () => import('./tables.js?v=bb782d98'),
	IngressFileUpload: () => import('./ingressUpload.js?v=bb782d98'),
	IngressList: () => import('./lists.js?v=bb782d98'),
	MobileTableControls: () => import('./mobileTableControls.js?v=bb782d98'),
	ModelTaskInfo: () => import('./modelTasks.js?v=bb782d98'),
	ModelTaskList: () => import('./modelTasks.js?v=bb782d98'),
	PageInfo: () => import('./pageInfo.js?v=bb782d98'),
	PagePermissions: () => import('./pagePermissions.js?v=bb782d98'),
	PagePhoto: () => import('./pagePhoto.js?v=bb782d98'),
	PageTaskList: () => import('./pageTaskList.js?v=bb782d98'),
	ProjectInfo: () => import('./projectInfo.js?v=bb782d98'),
	PublicPermissions: () => import('./user.js?v=bb782d98'),
	SavedFilters: () => import('./filters.js?v=bb782d98'),
	SiteAiModels: () => import('./aiModels.js?v=bb782d98'),
	SiteAdministrators: () => import('./administrators.js?v=bb782d98'),
	SiteDeployment: () => import('./deployment.js?v=bb782d98'),
	SiteInstallationAccess: () => import('./installationAccess.js?v=bb782d98'),
	SiteImage: () => import('./image.js?v=bb782d98'),
	SiteMaintenance: () => import('./maintenance.js?v=bb782d98'),
	SiteServiceProviders: () => import('./providers.js?v=bb782d98'),
	SiteSettings: () => import('./siteSettings.js?v=bb782d98'),
	StarredList: () => import('./lists.js?v=bb782d98'),
	TableEditor: () => import('./tableEditor.js?v=bb782d98'),
	TableSorting: () => import('./tableSorting.js?v=bb782d98'),
	TableVisibility: () => import('./tableVisibility.js?v=bb782d98'),
	TaskForm: () => import('./taskForm.js?v=bb782d98'),
	TaskHistory: () => import('./tables.js?v=bb782d98'),
	TaskCombine: () => import('./taskSettings.js?v=bb782d98'),
	TaskMove: () => import('./taskSettings.js?v=bb782d98'),
	ToolReportList: () => import('./lists.js?v=bb782d98'),
	TaskSettings: () => import('./taskSettings.js?v=bb782d98'),
	UserSettings: () => import('./pageInfo.js?v=bb782d98'),
};

/** Sync-capable widgets that can run without a mounted view (offline replay). */
const HEADLESS_WIDGETS = {
	document: {
		load: () => import('./collaborative.js?v=bb782d98'),
		name: "CollaborativeDocument",
	},
};

const JSON_ATTRIBUTES = [
	"attributes",
	"submission",
	"schema",
	"conditions",
	"columns",
	"selected",
	"preload",
	"options",
];

/**
 * @testable infrastructure
 */
const _attributes = (component, show) => {
	const settings = {
		component: component,
		view: component.view,
		name: show,
		visible: false,
		modified: false,
	};

	// Components that cam be toggled visibly should have a target element
	// either in the html or as a getter in the widget
	const target = component.elt.querySelector(`[data-widget="${show}"]`);
	if (target) {
		settings.target = target;
		settings.key = target.dataset.key || component.key || settings.view.key;
		settings.kind = target.dataset.kind || component.kind || "default";
		settings.persistent = target.dataset.persistent === "true";
		settings.visible = target.dataset.visible === "true";
		settings.loaded = target.hasAttribute("loaded");
	}

	settings.route = target?.dataset.route || component.elt.dataset.route;

	JSON_ATTRIBUTES.filter((attribute) => target?.dataset[attribute]).forEach(
		(attribute) => {
			settings[attribute] = JSON.parse(target.dataset[attribute]);
		},
	);

	if (show in ENDPOINTS) {
		settings.endpoints = ENDPOINTS[show](settings);
	}

	return settings;
};

/**
 * @testable false
 * @covered-by src/script/widgets/loader.mjs::loadWidget
 * @reason widget readonly is part of the widget construction contract
 */
const _defineReadonly = (widget, component) => {
	Object.defineProperty(widget, "readonly", {
		configurable: true,
		enumerable: true,
		get() {
			return component.readonly || this.target?.dataset.readonly === "true";
		},
	});
};

/**
 * @testable infrastructure
 */
class DefaultWidget {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.DEFAULT = true;
	}
}

/**
 * @testable infrastructure
 */
async function loadWidget(component, show, extraAttributes = {}) {
	let widget;
	const attributes = { ..._attributes(component, show), ...extraAttributes };
	const name = show.split("/")[0];

	if (name in WIDGETS) {
		const module = await WIDGETS[name]();
		widget = new module[name](attributes);
	} else {
		widget = new DefaultWidget(attributes);
	}

	_defineReadonly(widget, component);

	if (widget.init) await widget.init();

	widget.enable = () => {
		widget.modified = widget.modified || widget.visible !== true;
		widget.visible = true;
	};

	widget.disable = (force = false) => {
		widget.modified = force || widget.visible !== false;
		widget.visible = false;
	};

	widget.prepareReconcile = async (silent = false) => {
		if (!widget.modified || silent) return;
		await widget.prereconcile?.();
	};

	// Connected-DOM manipulation is committed here inside the component's
	// transition. Long-running work belongs in prereconcile().
	widget.reconcile = (silent = false) => {
		if (widget.target && !widget.persistent) {
			widget.target.dataset.visible = widget.visible ? "true" : "false";
		}

		if (!widget.modified) return;
		widget.modified = false;

		if (widget.postreconcile && !silent) {
			const result = widget.postreconcile();
			if (result?.then) {
				captureError(
					new TypeError(
						`${widget.name}.postreconcile() must commit synchronously. Move awaited work to prereconcile().`,
					),
					widget.target,
				);
				void result.catch(captureError);
			}
		}
	};

	if (widget.target) widget.target._lp_widget = widget;
	return widget;
}

/**
 * Build a fully rendered, detached copy of a form widget for revision
 * comparison. The response document is cloned so the original remains
 * available if the user chooses to apply it.
 *
 * @testable infrastructure
 */
async function loadRevisionPreview(
	liveWidget,
	response,
	{ readonly = liveWidget.readonly } = {},
) {
	const responseTarget = response.html?.querySelector(
		`[data-widget='${liveWidget.name}']`,
	);
	if (!responseTarget) return null;

	const container = document.createElement("div");
	container.appendChild(responseTarget.cloneNode(true));
	const view = {
		key: liveWidget.key,
		kind: liveWidget.kind,
		readonly,
		online: true,
		hidden: false,
		showExtractReloadNotice() {},
	};
	const component = {
		elt: container,
		view,
		key: liveWidget.key,
		kind: liveWidget.kind,
		widgets: {},
		get readonly() {
			return readonly;
		},
	};
	const preview = await loadWidget(component, liveWidget.name, {
		revisionPreview: true,
		schema: response.schema ?? null,
		submission: response.submission ?? null,
	});
	const previewResponse = {
		...response,
		html: response.html?.cloneNode(true),
	};

	if (preview.updated) await preview.updated(previewResponse);
	if (preview.prereconcile) await preview.prereconcile();
	if (preview.postreconcile) preview.postreconcile();
	return preview;
}

/**
 * @testable false
 * @covered-by src/script/widgets/loader.mjs::loadHeadlessWidget
 * @reason helper owned by the headless sync widget loader
 */
function _headlessKind(sync_id) {
	if (sync_id.endsWith(":document")) return "document";
	return null;
}

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_headless_offline_replay_merges_concurrent_remote_edits
 * @matrix sync : concurrency document headless-widget offline-replay
 *
 * Construct a sync-capable widget with no view or DOM chrome.
 * Caller runs init(), assigns remote/offlineRecord, then sync().
 */
async function loadHeadlessWidget({ sync_id, remote, offline }) {
	const kind = _headlessKind(sync_id);
	if (!kind) return null;

	const { load, name } = HEADLESS_WIDGETS[kind];
	const module = await load();
	const Widget = module[name];

	const target = document.createElement("div");
	target.setAttribute("lp-sync", sync_id);
	const fingerprint = remote?.fingerprint ?? offline?.fingerprint;
	if (fingerprint) target.setAttribute("lp-fingerprint", fingerprint);
	return new Widget({
		target,
		headless: true,
		view: null,
		readonly: true,
		key: remote?.key ?? offline?.key,
	});
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
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_static_component_without_default_widget_activates
	 * @matrix navigation tabs : static-component visibility
	 */
	async activate(show) {
		if (this._destroyed) return false;
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
	 * @matrix collections forms reconnect-refresh : explicit-collection-scope form-exclusion
	 */
	async prepareCollectionRefresh(skip = new Set()) {
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
					const result = widget.refresh(response);
					if (result?.then) void result.catch(captureError);
				};
			}),
		);
		return commits.filter(Boolean);
	}

	async refreshCollections(skip = new Set()) {
		const commits = await this.prepareCollectionRefresh(skip);
		commits.forEach((commit) => {
			commit();
		});
	}

	/**
	 * @testable false
	 * @reason foundational view lifecycle plumbing
	 */
	async loadWidget(name) {
		if (!name || this._destroyed) return null;
		if (this.widgets[name]) return this.widgets[name];
		if (this.widgetLoads.has(name)) return this.widgetLoads.get(name);

		const pending = (async () => {
			const widget = await loadWidget(this, name);
			if (this._destroyed) {
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
		const responseTarget = response.html?.querySelector?.(
			`[data-widget='${widget.name}']`,
		);
		if (responseTarget && response.pollChannel) {
			responseTarget.dataset.pollChannel = response.pollChannel;
		}
		if (responseTarget && response.pollRevision) {
			responseTarget.dataset.pollRevision = response.pollRevision;
		}

		const append = await widget.updated(response);
		if (append) this.load(widget, append.dataset.route);
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
	async updated(response) {
		const updates = { replace: [], append: [] };

		const widgetUpdates = [];
		response.html?.querySelectorAll("[data-widget]").forEach((elt) => {
			const name = elt.dataset.widget;
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
				this.active?.success?.();
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

	async prepareRender() {
		await Promise.all(
			Object.values(this.widgets).map((widget) => {
				return widget.prepareReconcile();
			}),
		);
	}

	// User actions and initial entity enhancement call this within a transition.
	// Connected-DOM manipulation in widgets belongs in postreconcile().
	/**
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_component_render_does_not_wait_for_polling_reconciliation
	 * @matrix polling : component-render nonblocking subscription-lifecycle
	 * @matrix startup : component-render deferred-services nonblocking
	 */
	render(visible) {
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
		void this.view.schedulePollingReconciliation?.();
	}

	destroy() {
		this._destroyed = true;
		Object.values(this.widgets).forEach((widget) => {
			widget.destroy?.();
		});
		this.widgetLoads.clear();
		delete this.view.components[this.key];
	}
}

const COLLECTION_ONLY_CHANGE_TYPES = new Set(["delete", "star", "unstar"]);
const FORM_ALREADY_RECONCILED_CHANGE_TYPES = new Set([
	...COLLECTION_ONLY_CHANGE_TYPES,
	"entity-poll",
]);

/**
 * @testable false
 * @covered-by src/script/views/base/reconciliation.mjs::reconcileChange
 * @reason destination loading is a private stage of change reconciliation
 */
const loadChangeDestination = async (view, destination) => {
	if (!destination) return null;
	const [componentId, widgetName] = destination.split(":");
	if (!componentId || !widgetName) return null;
	const component = view.getComponent(document.getElementById(componentId));
	return component ? await component.loadWidget(widgetName) : null;
};

/**
 * @testable false
 * @covered-by src/script/views/base/reconciliation.mjs::reconcileChange
 * @reason mounted-owner discovery is a private stage of change reconciliation
 */
const loadMountedCollectionOwners = async (view, keys) => {
	const requested = new Set(keys);
	const targets = new Set();
	for (const entity of view.elt.querySelectorAll("[lp-entity][data-key]")) {
		if (!requested.has(entity.dataset.key)) continue;
		const target = entity.parentElement?.closest?.("[data-widget]");
		if (target?.dataset.widget && !target.matches?.("form"))
			targets.add(target);
	}
	await Promise.all(
		Array.from(targets, async (target) => {
			await view.getComponent(target)?.loadWidget(target.dataset.widget);
		}),
	);
};

/**
 * @testable false
 * @covered-by src/script/views/base/reconciliation.mjs::reconcileChange
 * @reason DOM removal is committed through the enclosing reconciliation contract
 */
const removeDeletedEntity = (view, key) => {
	for (const element of view.elt.querySelectorAll("[data-key]")) {
		if (element.dataset.key !== key) continue;
		element._lp_component?.destroy?.();
		element.remove();
	}
};

/**
 * @testable infrastructure
 * @covered-by src/script/views/base/core.mjs::Core.reconcileChange
 */
const reconcileChange = (view, change = {}) => {
	view._pendingChanges.push({ ...change });
	if (view._reconcilePromise) return view._reconcilePromise;

	view._reconcilePromise = (async () => {
		try {
			do {
				const changes = view._pendingChanges.splice(0);
				const fingerprint = view.elt.dataset.fingerprint || null;
				const destinationKeys = [];
				for (const item of changes) {
					if (item.type === "delete") clearRecentSearchResults();
					if (["star", "unstar"].includes(item.type)) {
						view._applyStarState(item);
					}
					const destination = await loadChangeDestination(
						view,
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
				if (keys.length) await loadMountedCollectionOwners(view, keys);
				const deletedKeys = changes
					.filter(({ key, type }) => type === "delete" && key)
					.map(({ key }) => key);
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
					const watcher = await view.ensureEditWatcher();
					if (view.PollingCoordinator?.activePoll) watcher?.enqueue(formKeys);
					else await watcher?.invalidate(formKeys);
				}
				await view.refreshCollections(false, {
					fingerprint,
					beforeCommit: () => {
						deletedKeys.forEach((key) => {
							removeDeletedEntity(view, key);
						});
					},
				});
				await view.refreshSupplementalCollections(changes);
				for (const item of changes) await view.afterReconcileChange(item);
			} while (view._pendingChanges.length);
		} finally {
			view._reconcilePromise = null;
		}
	})();
	return view._reconcilePromise;
};

/**
 * @testable false
 * @covered-by src/script/views/base/reconciliation.mjs::refreshCollectionComponents
 * @reason target collection is owned by the batched refresh contract
 */
const collectRefreshTargets = (_view, components) => {
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
};

/**
 * @testable infrastructure
 * @covered-by src/script/views/base/core.mjs::Core._refreshCollectionComponents
 */
const refreshCollectionComponents = async (
	view,
	components,
	{
		fingerprint = view.elt.dataset.fingerprint || null,
		deferCommit = false,
	} = {},
) => {
	const targets = collectRefreshTargets(view, components);
	const reconciled = new Set();
	const commits = [];
	let refreshedFingerprint = null;
	if (targets.size) {
		const response = await request.post("/l/refresh", {
			view: {
				key: view.key || null,
				hash: view.hash || null,
				index: view.elt.dataset.index || null,
				mode: view.elt.dataset.userMode || null,
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
					if (deferCommit && widget.prepareRefreshDelta) {
						commits.push(await widget.prepareRefreshDelta(result));
					} else if (deferCommit) {
						commits.push(() => {
							const pending = widget.refreshDelta(result);
							if (pending?.then) void pending.catch(captureError);
						});
					} else {
						await widget.refreshDelta(result);
					}
					reconciled.add(widget);
				} catch (error) {
					captureError(error);
				}
			}
		}
	}
	if (deferCommit) {
		const prepared = await Promise.all(
			components.map(async (component) => {
				if (component.elt && !component.elt.isConnected) return [];
				return await component.prepareCollectionRefresh(reconciled);
			}),
		);
		commits.push(...prepared.flat());
		return () => {
			commits.filter(Boolean).forEach((commit) => {
				commit();
			});
			if (refreshedFingerprint) {
				view.elt.dataset.fingerprint = refreshedFingerprint;
			}
		};
	}

	await Promise.all(
		components.map(async (component) => {
			if (component.elt && !component.elt.isConnected) return;
			await component.refreshCollections(reconciled);
		}),
	);
	if (refreshedFingerprint) view.elt.dataset.fingerprint = refreshedFingerprint;
	return null;
};

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
const ensureOfflineQueue = (view) =>
	loadOnce(view, "_offlineQueuePromise", "offlineQueue", async () => {
		const { OfflineQueue } = await import('./offlineQueue.js?v=bb782d98');
		if (view._destroyed) return null;
		const queue = new OfflineQueue(view);
		await queue.init();
		return queue;
	});

/** @testable infrastructure */
const ensurePollingCoordinator = (view) =>
	loadOnce(view, "_pollingPromise", "PollingCoordinator", async () => {
		const { PollingCoordinator } = await import('./polling.js?v=bb782d98');
		if (view._destroyed) return null;
		const coordinator = new PollingCoordinator(view).init();
		view.PollingCoordinator = coordinator;
		view._initPollingSubscription();
		return coordinator;
	});

/** @testable infrastructure */
const ensureSyncManager = (view) =>
	loadOnce(view, "_syncPromise", "SyncManager", async () => {
		await ensurePollingCoordinator(view);
		const { SyncManager } = await import('./sync.js?v=bb782d98');
		if (view._destroyed) return null;
		const manager = new SyncManager(view);
		manager.init();
		return manager;
	});

/** @testable infrastructure */
const ensureEditWatcher = (view) =>
	loadOnce(view, "_editWatcherPromise", "EditWatcher", async () => {
		await ensurePollingCoordinator(view);
		const { EditWatcher } = await import('./editWatcher.js?v=bb782d98');
		if (view._destroyed) return null;
		const watcher = new EditWatcher(view);
		watcher.init();
		return watcher;
	});

/** @testable infrastructure */
const ensureDeferredOperations = (view) =>
	loadOnce(
		view,
		"_deferredOperationsPromise",
		"DeferredOperations",
		async () => {
			await ensurePollingCoordinator(view);
			const { DeferredOperationManager } = await import(
				'./deferredOperations.js?v=bb782d98'
			);
			if (view._destroyed) return null;
			return new DeferredOperationManager(view).init();
		},
	);

/**
 * @testable infrastructure
 */
const ensureNotifications = (view) =>
	loadOnce(view, "_notificationsPromise", "Notifications", async () => {
		if (!document.querySelector("[data-role='notifications']")) return null;
		const { Notifications } = await import('./notifications.js?v=bb782d98');
		if (view._destroyed) return null;
		const notifications = new Notifications(view);
		notifications.init();
		return notifications;
	});

/** @testable infrastructure */
const ensureSearchBox = (view) =>
	loadOnce(view, "_searchPromise", "SearchBox", async () => {
		const search = document.querySelector("[lp-search]");
		if (!search) return null;
		const { SearchBox } = await import('./search.js?v=bb782d98');
		if (view._destroyed) return null;
		const box = new SearchBox(search);
		await box.init();
		return box;
	});

/** @testable infrastructure */
const ensureEntityMenu = (view) =>
	loadOnce(view, "_entityMenuPromise", "EntityMenu", async () => {
		const { EntityMenu } = await import('./entityMenu.js?v=bb782d98');
		if (view._destroyed) return null;
		return new EntityMenu(view);
	});

/** @testable infrastructure */
const ensureSubmissionManager = (view) =>
	loadOnce(view, "_submissionPromise", "SubmissionManager", async () => {
		const { SubmissionManager } = await import('./submission.js?v=bb782d98');
		if (view._destroyed) return null;
		return new SubmissionManager(view);
	});

/** @testable infrastructure */
const ensureOfflineModal = (view) =>
	loadOnce(view, "_offlineModalPromise", "offlineModal", async () => {
		if (!view.offlineIndicator) return null;
		const { OfflineModal } = await import('./modal.js?v=bb782d98');
		if (view._destroyed) return null;
		const modal = new OfflineModal(view, view.offlineIndicator);
		modal.enable();
		return modal;
	});

/** @testable infrastructure */
const ensureModalClasses = (view) =>
	loadOnce(view, "_modalClassesPromise", "ModalClasses", async () => {
		const { DeleteModal, HelpModal, Modal } = await import(
			'./modal.js?v=bb782d98'
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
const initializeCoreServices = (view) => {
	if (view._servicesInitialized) return view.servicesReady;
	view._servicesInitialized = true;
	const start = view._publishedReady.then(() => view);
	view._serviceStart = start;
	const idle = start.then(() => whenIdle());
	const offlineWork = idle.then(async () => {
		const { inspectOfflineWork } = await import('./offlineWork.js?v=bb782d98');
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
		const { replayOfflineQueue } = await import('./offlineReplay.js?v=bb782d98');
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

const ISOLATED_TASK_ACTIONS = new Set(["TaskMove", "TaskCombine"]);

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_task_update_preserves_open_widget_and_completed_readonly_state
 * @tests tests_e2e/006_tasks/test_006b_page_tasks.py::test_create_page_task_while_another_task_is_open_keeps_rows_clear
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_uncomplete_from_loaded_task_history_opens_settings
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_task_form_filters_compatible_tasks
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_combine_tasks_migrates_history_and_reconciles_task_delta
 * @matrix task-combine : delta isolated-form lazy-reload linked-page no-reload view-page
 * @matrix tasks : active-widget history-refresh settings uncomplete
 * @matrix tasks : create list-state readonly refresh update-state while-open
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
		const activeHistory =
			this.completed && this.active?.name === "TaskHistory"
				? this.active
				: null;
		const openSettings = Boolean(
			activeHistory &&
				update?.dataset.completed === "false" &&
				update.querySelector("[data-widget='TaskSettings']"),
		);
		const historyReplacement = openSettings
			? update.querySelector("[data-widget='TaskHistory']")?.cloneNode(true)
			: null;

		if (update) {
			Object.assign(this.elt.dataset, update.dataset);
			this._replaceNav(update);
			this._removeMissingWidgets(update);
		}

		await super.updated(response);
		if (!openSettings) return;

		await this.activate("TaskSettings");
		await this.prepareRender(true);
		await withTransition(
			() => {
				// Uncompletion archives a new row, so the loaded history is stale.
				if (historyReplacement) {
					activeHistory.target.replaceWith(historyReplacement);
				} else {
					activeHistory.target.remove();
				}
				activeHistory.destroy?.();
				delete this.widgets.TaskHistory;
				this.render(true);
			},
			{ label: `${this.name}:uncomplete-history` },
		);
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

/**
 * @testable infrastructure
 */
class Core extends ShellView {
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
		this.blurred = false;
		this.blurredAt = null;
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
	 * @matrix startup : deferred-services interaction-ready
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
	 * @matrix polling : channel entity refresh
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
	 * @matrix reconnect-refresh : committed-delete destination-invalidation mounted-collection
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
	 * @matrix starred : accessible-state title-menu
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
			button.disabled = false;
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

	/**
	 * @testable true
	 * @tests tests_e2e/001_site/test_001d_offline.py::test_offline_indicator_toggles
	 * @tests tests_e2e/001_site/test_001d_offline.py::test_failed_ping_marks_view_offline_until_next_sync_event
	 * @tests tests_e2e/001_site/test_001d_offline.py::test_testing_mode_navigation_resets_offline_state
	 * @tests tests_js/test_028_form_state_split.py::test_visibility_sync_stages_remote_form_edits_without_waiting_for_offline_replay
	 * @tests tests_js/test_029_core_startup.py::test_core_sync_distinguishes_visible_blur_from_hard_suspension
	 * @matrix offline : background-replay dirty-form-preservation
	 * @matrix polling : blur catch-up nonblocking visibility
	 * @pair sync:deregistration
	 * @matrix offline : indicator server-health view-reset
	 */
	async sync({
		hidden = document.hidden,
		blurred = false,
		blurredAt = null,
		force = false,
	} = {}) {
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
			if (visibleBlur) this.PollingCoordinator?.blur(this.blurredAt);
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
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_visibility_sync_stages_remote_form_edits_without_waiting_for_offline_replay
	 * @pairs offline:background-replay polling:nonblocking
	 */
	scheduleOfflineReplay() {
		if (this._offlineReplayTask) return this._offlineReplayTask;
		const replay = import('./offlineReplay.js?v=bb782d98').then(({ replayOfflineQueue }) =>
			replayOfflineQueue(this),
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
	 * @testable true
	 * @tests tests_js/test_029_core_startup.py::test_core_polling_subscription_lifecycle
	 * @matrix polling : active-widget subscription-lifecycle visibility
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
	 * @matrix polling : nonblocking subscription-lifecycle
	 * @matrix startup : nonblocking single-flight
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
	 * @matrix reconnect-refresh : batching fallback manifest
	 */
	_collectRefreshTargets(components) {
		return collectRefreshTargets(this, components);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_022_refresh_frontend.py::test_core_refresh_batches_supported_widgets_and_falls_back_per_target
	 * @matrix reconnect-refresh : cache-invalidation delta-apply legacy-fallback
	 */
	async _refreshCollectionComponents(components, options = {}) {
		return refreshCollectionComponents(this, components, options);
	}

	async refreshCollections(navigation = false, options = {}) {
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
	 * @matrix home : lazy-load loading-indicator
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
			.then(async (activated) => {
				if (this._destroyed || trigger.isConnected === false) return null;
				await component.prepareRender(activated);
				return withTransition(
					() => {
						if (this._destroyed) return;
						component.render(activated);
					},
					{ label: `${component.name}:activate` },
				);
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
		this.SearchBox?.destroy?.();
		this.offlineModal?.destroy?.();
		this._componentActions.clear();

		Object.values(this.components).forEach((component) => {
			if (component.destroy) component.destroy();
		});
		this.components = {};
	}
}

export { Core as C, NavElement as N, loadRevisionPreview as a, loadHeadlessWidget as l };
