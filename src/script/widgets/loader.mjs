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

import { ENDPOINTS } from "../shared/endpoints";
import { captureError } from "../shared/errors";

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
	SiteAiModels: () => import("./siteSettings/aiModels"),
	SiteAdministrators: () => import("./siteSettings/administrators"),
	SiteDeployment: () => import("./siteSettings/deployment"),
	SiteInstallationAccess: () => import("./siteSettings/installationAccess"),
	SiteImage: () => import("./siteSettings/image"),
	SiteMaintenance: () => import("./siteSettings/maintenance"),
	SiteServiceProviders: () => import("./siteSettings/providers"),
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
	UserSettings: () => import("./userSettings"),
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
