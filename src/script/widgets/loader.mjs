/**
 * Widget Contract:
 * - target: Element - DOM element for this widget
 * - enable(): Set this.active = true,
 * - disable(): Set this.active = false, cleanup
 * - reconcile(): Sync this.visible → target.dataset.visible (in transition)
 * - updated(response): Handle server response
 * - created(response): Post-create handling (reset forms)
 * - data: FormData getter for submissions
 * - destroy(): Cleanup listeners
 */

import { ENDPOINTS } from "../shared/endpoints";

const WIDGETS = {
	BaseList: () => import("../elements/base/baseList"),
	CategoryInfo: () => import("./category"),
	CollaborativeDocument: () => import("../elements/editor/collaborative"),
	CreateCategory: () => import("./category"),
	CreateForm: () => import("./form"),
	CreateModelTask: () => import("./modelTasks"),
	CreateNote: () => import("./note"),
	CreatePage: () => import("./pageInfo"),
	CreateProject: () => import("./projectInfo"),
	CreateToolReport: () => import("./tools"),
	CreateUserTask: () => import("./taskSettings"),
	CreateTask: () => import("./taskSettings"),
	CreateUser: () => import("./user"),
	CreateUserGroup: () => import("./user"),
	DirectoryList: () => import("./home/lists"),
	DocumentSettings: () => import("./documentSettings"),
	FileInfo: () => import("./fileInfo"),
	PDFPreview: () => import("./filePdfPreview"),
	FileUpload: () => import("./uploadFile"),
	Filters: () => import("./filters"),
	FilterResults: () => import("./tables"),
	GeneratePages: () => import("./category"),
	GroupPermissions: () => import("./user"),
	HomeActivityList: () => import("./home/activity"),
	HomePageList: () => import("./home/lists"),
	HomeTaskList: () => import("./home/tasks"),
	HomeProjectList: () => import("./home/lists"),
	HomeCategoryList: () => import("./home/lists"),
	ImportData: () => import("./ingress"),
	IndexTable: () => import("./tables"),
	IngressFileUpload: () => import("./ingressUpload"),
	IngressList: () => import("./home/lists"),
	MobileTableControls: () => import("./mobileTableControls"),
	ModelTaskInfo: () => import("./modelTasks"),
	ModelTaskList: () => import("./modelTasks"),
	PageInfo: () => import("./pageInfo"),
	PagePermissions: () => import("./pagePermissions"),
	PagePhoto: () => import("./pagePhoto"),
	PageTaskList: () => import("./pageTaskList"),
	ProjectInfo: () => import("./projectInfo"),
	PublicPermissions: () => import("./user"),
	SavedFilters: () => import("./filters"),
	SiteExport: () => import("./siteExport"),
	SiteSettings: () => import("./siteSettings"),
	StarredList: () => import("./home/lists"),
	TableEditor: () => import("./tableEditor"),
	TableSorting: () => import("./tableSorting"),
	TableVisibility: () => import("./tableVisibility"),
	TaskForm: () => import("./taskForm"),
	TaskHistory: () => import("./tables"),
	TaskCombine: () => import("./taskSettings"),
	TaskMove: () => import("./taskSettings"),
	ToolReportList: () => import("./home/lists"),
	TaskSettings: () => import("./taskSettings"),
	UserSettings: () => import("./pageInfo"),
};

/** Sync-capable widgets that can run without a mounted view (offline replay). */
const HEADLESS_WIDGETS = {
	document: {
		load: () => import("../elements/editor/collaborative"),
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
			return component.readonly || widget.target?.dataset.readonly === "true";
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
export async function loadWidget(component, show, extraAttributes = {}) {
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

	// All DOM manipulation should be done here, this is wrapped in a transition
	// it is called for each changed widget in the component's render() method
	widget.reconcile = async (silent = false) => {
		if (widget.target && !widget.persistent) {
			widget.target.dataset.visible = widget.visible ? "true" : "false";
		}

		if (!widget.modified) return;
		widget.modified = false;

		if (widget.postreconcile && !silent) await widget.postreconcile();
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
export async function loadRevisionPreview(
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
	if (preview.postreconcile) await preview.postreconcile();
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
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_replay_does_not_duplicate_after_reload
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_headless_offline_replay_merges_concurrent_remote_edits
 * @features sync
 * @dimensions headless-widget document offline-replay concurrency
 *
 * Construct a sync-capable widget with no view or DOM chrome.
 * Caller runs init(), assigns remote/offlineRecord, then sync().
 */
export async function loadHeadlessWidget({ sync_id, remote, offline }) {
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
