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

import { ENDPOINTS } from "../shared/endpoints.ts";
import { captureError } from "../shared/errors.ts";

const WIDGETS = {
	BaseList: () => import("../elements/base/baseList.ts"),
	CategoryInfo: () => import("./category.ts"),
	CollaborativeDocument: () => import("../elements/editor/collaborative.ts"),
	CreateCategory: () => import("./category.ts"),
	CreateForm: () => import("./form.ts"),
	CreateModelTask: () => import("./modelTasks.ts"),
	CreateNote: () => import("./note.ts"),
	CreatePage: () => import("./pageInfo.ts"),
	CreateProject: () => import("./projectInfo.ts"),
	CreateToolReport: () => import("./tools.ts"),
	CreateUserTask: () => import("./taskSettings.ts"),
	CreateTask: () => import("./taskSettings.ts"),
	CreateUser: () => import("./user.ts"),
	CreateUserGroup: () => import("./user.ts"),
	DirectoryList: () => import("./home/lists.ts"),
	DocumentSettings: () => import("./documentSettings.ts"),
	FileInfo: () => import("./fileInfo.ts"),
	PDFPreview: () => import("./filePdfPreview.ts"),
	FileUpload: () => import("./uploadFile.ts"),
	Filters: () => import("./filters.ts"),
	FilterResults: () => import("./filterResults.ts"),
	GroupPermissions: () => import("./userPermissions.ts"),
	HomeActivityList: () => import("./home/activity.ts"),
	HomePageList: () => import("./home/lists.ts"),
	HomeTaskList: () => import("./home/tasks.ts"),
	HomeProjectList: () => import("./home/lists.ts"),
	HomeCategoryList: () => import("./home/lists.ts"),
	ImportData: () => import("./ingress.ts"),
	IndexTable: () => import("./tables/indexTable.ts"),
	IngressFileUpload: () => import("./ingressUpload.ts"),
	IngressList: () => import("./home/lists.ts"),
	MobileTableControls: () => import("./tables/mobileControls.ts"),
	ModelTaskInfo: () => import("./modelTasks.ts"),
	ModelTaskList: () => import("./modelTasks.ts"),
	PageInfo: () => import("./pageInfo.ts"),
	PagePermissions: () => import("./pagePermissions.ts"),
	PagePhoto: () => import("./pagePhoto.ts"),
	PageTaskList: () => import("./pageTaskList.ts"),
	ProjectInfo: () => import("./projectInfo.ts"),
	PublicPermissions: () => import("./userPermissions.ts"),
	SavedFilters: () => import("./filters.ts"),
	SiteAiModels: () => import("./siteSettings/aiModels.ts"),
	SiteAdministrators: () => import("./siteSettings/administrators.ts"),
	SiteDeployment: () => import("./siteSettings/deployment.ts"),
	SiteInstallationAccess: () => import("./siteSettings/installationAccess.ts"),
	SiteImage: () => import("./siteSettings/image.ts"),
	SiteMaintenance: () => import("./siteSettings/maintenance.ts"),
	SiteServiceProviders: () => import("./siteSettings/providers.ts"),
	SiteSettings: () => import("./siteSettings.ts"),
	StarredList: () => import("./home/lists.ts"),
	TableEditor: () => import("./tables/editor.ts"),
	TableSorting: () => import("./tables/sorting.ts"),
	TableVisibility: () => import("./tables/visibility.ts"),
	TaskForm: () => import("./taskForm.ts"),
	TaskHistory: () => import("./taskHistory.ts"),
	TaskCombine: () => import("./taskSettings.ts"),
	TaskMove: () => import("./taskSettings.ts"),
	ToolReportList: () => import("./home/lists.ts"),
	TaskSettings: () => import("./taskSettings.ts"),
	UserSettings: () => import("./userSettings.ts"),
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

const _defineReadonly = (widget, component) => {
	Object.defineProperty(widget, "readonly", {
		configurable: true,
		enumerable: true,
		get() {
			return component.readonly || this.target?.dataset.readonly === "true";
		},
	});
};

class DefaultWidget {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.DEFAULT = true;
	}
}

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
