/**
 * Widget Contract:
 * - target: Element - DOM element for this widget
 * - enable(): Set this.active = true,
 * - disable(): Set this.active = false, cleanup
 * - prereconcile(): Optional async preparation without connected-DOM writes
 * - reconcile(): Sync this.visible and prepared state to the DOM (in transition)
 * - updated(response): Handle server response
 * - created(response): Post-create handling (reset forms)
 * - formData: FormData getter for submissions
 * - destroy(): Cleanup listeners
 */

import { ENDPOINTS } from "../shared/endpoints.mjs";
import { captureError } from "../shared/errors.mjs";

const WIDGETS = {
	BaseList: () => import("../elements/base/baseList.mjs"),
	CategoryInfo: () => import("./category.mjs"),
	CollaborativeDocument: () => import("../elements/editor/collaborative.mjs"),
	CreateCategory: () => import("./category.mjs"),
	CreateForm: () => import("./form.mjs"),
	CreateModelTask: () => import("./modelTasks.mjs"),
	CreateNote: () => import("./note.mjs"),
	CreatePage: () => import("./pageInfo.mjs"),
	CreateProject: () => import("./projectInfo.mjs"),
	CreateToolReport: () => import("./tools.mjs"),
	CreateUserTask: () => import("./taskSettings.mjs"),
	CreateTask: () => import("./taskSettings.mjs"),
	CreateUser: () => import("./user.mjs"),
	CreateUserGroup: () => import("./user.mjs"),
	DirectoryList: () => import("./home/lists.mjs"),
	DocumentSettings: () => import("./documentSettings.mjs"),
	FileInfo: () => import("./fileInfo.mjs"),
	PDFPreview: () => import("./filePdfPreview.mjs"),
	FileUpload: () => import("./uploadFile.mjs"),
	Filters: () => import("./filters.mjs"),
	FilterResults: () => import("./filterResults.mjs"),
	GroupPermissions: () => import("./userPermissions.mjs"),
	HomeActivityList: () => import("./home/activity.mjs"),
	HomePageList: () => import("./home/lists.mjs"),
	HomeTaskList: () => import("./home/tasks.mjs"),
	HomeProjectList: () => import("./home/lists.mjs"),
	HomeCategoryList: () => import("./home/lists.mjs"),
	ImportData: () => import("./ingress.mjs"),
	IndexTable: () => import("./tables/indexTable.mjs"),
	IngressFileUpload: () => import("./ingressUpload.mjs"),
	IngressList: () => import("./home/lists.mjs"),
	MobileTableControls: () => import("./tables/mobileControls.mjs"),
	ModelTaskInfo: () => import("./modelTasks.mjs"),
	ModelTaskList: () => import("./modelTasks.mjs"),
	PageInfo: () => import("./pageInfo.mjs"),
	PagePermissions: () => import("./pagePermissions.mjs"),
	PagePhoto: () => import("./pagePhoto.mjs"),
	PageTaskList: () => import("./pageTaskList.mjs"),
	ProjectInfo: () => import("./projectInfo.mjs"),
	PublicPermissions: () => import("./userPermissions.mjs"),
	SavedFilters: () => import("./filters.mjs"),
	SiteAiModels: () => import("./siteSettings/aiModels.mjs"),
	SiteAdministrators: () => import("./siteSettings/administrators.mjs"),
	SiteDeployment: () => import("./siteSettings/deployment.mjs"),
	SiteInstallationAccess: () => import("./siteSettings/installationAccess.mjs"),
	SiteImage: () => import("./siteSettings/image.mjs"),
	SiteMaintenance: () => import("./siteSettings/maintenance.mjs"),
	SiteServiceProviders: () => import("./siteSettings/providers.mjs"),
	SiteSettings: () => import("./siteSettings.mjs"),
	StarredList: () => import("./home/lists.mjs"),
	TableEditor: () => import("./tables/editor.mjs"),
	TableSorting: () => import("./tables/sorting.mjs"),
	TableVisibility: () => import("./tables/visibility.mjs"),
	TaskForm: () => import("./taskForm.mjs"),
	TaskHistory: () => import("./taskHistory.mjs"),
	TaskCombine: () => import("./taskSettings.mjs"),
	TaskMove: () => import("./taskSettings.mjs"),
	ToolReportList: () => import("./home/lists.mjs"),
	TaskSettings: () => import("./taskSettings.mjs"),
	UserSettings: () => import("./userSettings.mjs"),
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
