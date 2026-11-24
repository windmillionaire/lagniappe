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
import type { LoadedWidget, WidgetSettings } from "../types/widgets";

interface LoaderView {
	key?: string | null;
}

interface LoaderComponent {
	elt: HTMLElement;
	view: LoaderView;
	key?: string | null;
	kind?: string | null;
	readonly?: boolean;
}

type LoaderSettings = WidgetSettings<LoaderComponent, LoaderView> &
	Record<string, unknown>;
type WidgetConstructor = new (settings: LoaderSettings) => LoadedWidget;

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

const _attributes = (component: LoaderComponent, show: string) => {
	const settings: LoaderSettings = {
		component: component,
		view: component.view,
		name: show,
		visible: false,
		modified: false,
	};

	// Components that cam be toggled visibly should have a target element
	// either in the html or as a getter in the widget
	const target = component.elt.querySelector<HTMLElement>(
		`[data-widget="${show}"]`,
	);
	if (target) {
		settings.target = target;
		settings.key = target.dataset.key || component.key || settings.view.key;
		settings.kind = target.dataset.kind || component.kind || "default";
		settings.persistent = target.dataset.persistent === "true";
		settings.visible = target.dataset.visible === "true";
		settings.loaded = target.hasAttribute("loaded");
	}

	settings.route = target?.dataset.route || component.elt.dataset.route;

	for (const attribute of JSON_ATTRIBUTES) {
		const value = target?.dataset[attribute];
		if (value) settings[attribute] = JSON.parse(value) as unknown;
	}

	if (show in ENDPOINTS) {
		const endpoint =
			ENDPOINTS[show as keyof typeof WIDGETS & keyof typeof ENDPOINTS];
		// Keyed routes are registered for widgets whose markup identifies an entity.
		settings.endpoints = endpoint(settings as LoaderSettings & { key: string });
	}

	return settings;
};

const _defineReadonly = (widget: LoadedWidget, component: LoaderComponent) => {
	Object.defineProperty(widget, "readonly", {
		configurable: true,
		enumerable: true,
		get(this: LoadedWidget) {
			return component.readonly || this.target?.dataset.readonly === "true";
		},
	});
};

class DefaultWidget {
	declare name: string;
	declare DEFAULT: true;

	constructor(attributes: LoaderSettings) {
		Object.assign(this, attributes);
		this.DEFAULT = true;
	}
}

export async function loadWidget(
	component: LoaderComponent,
	show: string,
	extraAttributes: Partial<LoaderSettings> = {},
): Promise<LoadedWidget> {
	let widget: LoadedWidget;
	const attributes = { ..._attributes(component, show), ...extraAttributes };
	const name = show.split("/")[0];

	if (name in WIDGETS) {
		const module = await WIDGETS[name as keyof typeof WIDGETS]();
		// The selected template widget owns the shape of its dataset and endpoints.
		const Widget = (module as unknown as Record<string, WidgetConstructor>)[
			name
		];
		widget = new Widget(attributes);
	} else {
		widget = new DefaultWidget(attributes) as LoadedWidget;
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
			if (
				result &&
				typeof result === "object" &&
				"then" in result &&
				result.then
			) {
				captureError(
					new TypeError(
						`${widget.name}.postreconcile() must commit synchronously. Move awaited work to prereconcile().`,
					),
					widget.target,
				);
				void (result as Promise<unknown>).catch(captureError);
			}
		}
	};

	if (widget.target) {
		const target: HTMLElement & { _lp_widget?: LoadedWidget } = widget.target;
		target._lp_widget = widget;
	}
	return widget;
}
