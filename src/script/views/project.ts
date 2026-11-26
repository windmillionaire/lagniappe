import { captureError } from "../shared/errors.ts";
import { request } from "../shared/index.ts";
import type { LoadedWidget } from "../types/widgets";
import type { FilterBar, SavedConditionData } from "../widgets/filterBar.ts";
import type { IndexTable } from "../widgets/tables/indexTable.ts";
import type {
	TableColumn,
	TableVisibilityState,
} from "../widgets/tables/visibilityState.ts";
import type { SubcomponentEvent } from "./base/component.ts";
import Entity from "./base/entity.ts";
import type { ViewRoot } from "./base/shell.ts";

interface StatusBarResponse {
	conditions?: SavedConditionData[];
}

function isTableColumn(value: unknown): value is TableColumn {
	return Boolean(
		value &&
			typeof value === "object" &&
			"field" in value &&
			typeof value.field === "string" &&
			(!("title" in value) || typeof value.title === "string") &&
			(!("selected" in value) || typeof value.selected === "boolean"),
	);
}

type LoadedIndexTable = IndexTable & LoadedWidget;

class Project extends Entity {
	declare TableVisibilityState?: TableVisibilityState | null;
	declare _tasksReadyPromise?: Promise<{
		filterBar: FilterBar | null;
		indexTable: LoadedIndexTable | null;
	}> | null;
	declare _suppressNextTasksLoad: boolean;
	declare _onProjectClick: (event: MouseEvent) => void;

	constructor(node: ViewRoot) {
		super(node);
		this._defaultTabId = this._tabElement("document") ? "document" : "tasks";
		this._suppressNextTasksLoad = false;
		this._tasksReadyPromise = null;
		this.TableVisibilityState = null;
		this._onProjectClick = (event) => {
			if (this._handleHeaderClick(event)) return;
			if (this._handleModelTaskFilterClick(event)) return;
		};
	}

	get secondaryCard() {
		return this.elt.querySelector<HTMLElement>("#model-tasks");
	}

	_initialTabId() {
		const raw = super._initialTabId();
		if (raw === "filters") return "tasks";
		if (raw === "info") return this._defaultTabId;
		return raw;
	}

	async init() {
		this.elt.addEventListener("click", this._onProjectClick);
		await super.init();

		const tasksTab = this._tabElement("tasks");
		if (tasksTab?.dataset.visible === "true") {
			void this._ensureTasksTab({ loadRows: true }).catch(captureError);
		}
	}

	_tabChange(event: SubcomponentEvent) {
		super._tabChange(event);
		if (event.detail.subcomponent.name === "tasks") {
			const shouldLoad = !this._suppressNextTasksLoad;
			void this._ensureTasksTab({ loadRows: shouldLoad }).catch(captureError);
		}
	}

	_handleHeaderClick(event: MouseEvent): boolean {
		const target = event.target as Element | null;
		if (!target?.closest) return false;

		const projectAction = target.closest<HTMLElement>("[data-project-action]");
		if (
			projectAction?.dataset.projectAction &&
			this.elt.contains(projectAction)
		) {
			const action = projectAction.dataset.projectAction;
			event.preventDefault();
			event.stopPropagation();
			void import("../widgets/projectHeader.ts").then((mod) => {
				if (this._destroyed) return;
				if (action === "rename") mod.startProjectRename(this);
				else if (action === "description")
					mod.startProjectDescriptionEdit(this);
			});
			return true;
		}

		const editableDescription = target.closest<HTMLElement>(
			"[data-role='description'][data-editable='true']",
		);
		if (
			editableDescription &&
			this.elt.contains(editableDescription) &&
			!target.closest("a, button, input, textarea, form")
		) {
			event.preventDefault();
			event.stopPropagation();
			void import("../widgets/projectHeader.ts").then((mod) => {
				if (!this._destroyed) mod.startProjectDescriptionEdit(this);
			});
			return true;
		}

		return false;
	}

	_handleModelTaskFilterClick(event: MouseEvent): boolean {
		if (
			event.defaultPrevented ||
			event.button !== 0 ||
			event.metaKey ||
			event.ctrlKey ||
			event.shiftKey ||
			event.altKey
		) {
			return false;
		}

		const target = event.target as Element | null;
		const trigger = target?.closest<HTMLElement>("[data-project-task-filter]");
		if (!trigger || !this.elt.contains(trigger)) return false;

		const route = trigger.dataset.filterRoute;
		if (!route) return false;

		event.preventDefault();
		event.stopPropagation();
		void this._applyModelTaskFilter(route).catch(captureError);
		return true;
	}

	async _ensureTasksTab({ loadRows = true } = {}) {
		const ready = await this._initTasksTabWidgets();
		if (this._destroyed) return ready;

		const { indexTable } = ready;
		const tableEl = this.elt.querySelector<HTMLElement>("#project-tasks-table");
		const tableComp = this.getComponent(tableEl);
		if (
			loadRows &&
			indexTable &&
			tableComp &&
			!indexTable._filtered &&
			!indexTable.loading &&
			!indexTable.target.hasAttribute("loaded")
		) {
			indexTable.loaded = false;
			indexTable.loading = true;
			await tableComp.load(indexTable);
		}
		return ready;
	}

	_initTasksTabWidgets() {
		if (this._tasksReadyPromise) return this._tasksReadyPromise;
		this._tasksReadyPromise = (async () => {
			const filterBarEl = this.elt.querySelector<HTMLElement>("#filter-bar");
			const tableEl = this.elt.querySelector<HTMLElement>(
				"#project-tasks-table",
			);
			const filterBarComp = this.getComponent(filterBarEl);
			const tableComp = this.getComponent(tableEl);

			if (tableComp && !this.TableVisibilityState) {
				const { TableVisibilityState } = await import(
					"../widgets/tables/visibilityState.ts"
				);
				if (this._destroyed) return { filterBar: null, indexTable: null };
				const selected = tableComp.preload("selected");
				const columns = tableComp.preload("columns");
				this.TableVisibilityState = new TableVisibilityState({
					component: tableComp,
					view: this,
					selected: Array.isArray(selected)
						? selected.filter(
								(field): field is string => typeof field === "string",
							)
						: [],
					columns: Array.isArray(columns) ? columns.filter(isTableColumn) : [],
				}).init();
			}

			const [filterBar, indexTable] = await Promise.all([
				filterBarComp
					? (filterBarComp.loadWidget("FilterBar") as Promise<FilterBar | null>)
					: Promise.resolve(null),
				tableComp
					? (tableComp.loadWidget(
							"IndexTable",
						) as Promise<LoadedIndexTable | null>)
					: Promise.resolve(null),
			]);
			if (this._destroyed) return { filterBar: null, indexTable: null };

			if (tableComp) {
				const sorting = await tableComp.loadWidget("TableSorting");
				await sorting?.init?.();
			}

			return { filterBar, indexTable };
		})();
		return this._tasksReadyPromise;
	}

	async _applyModelTaskFilter(route: string) {
		const tasksTab = this._tabElement("tasks");
		const tasksVisible = tasksTab?.dataset.visible === "true";

		if (!tasksVisible) {
			const tabButton = this.elt.querySelector<HTMLElement>(
				"button[lp-show='tasks:active']",
			);
			this._suppressNextTasksLoad = true;
			try {
				if (tabButton) {
					await this.renderComponent(tabButton);
				} else {
					await this.updateLayout({ activeTabId: "tasks" });
				}
			} finally {
				this._suppressNextTasksLoad = false;
			}
		}

		const [{ filterBar }, response] = await Promise.all([
			this._ensureTasksTab({ loadRows: false }),
			request.get<StatusBarResponse>(route),
		]);
		if (this._destroyed || !filterBar) return;
		if (response?.ok && Array.isArray(response.conditions)) {
			await filterBar.applyConditions(response.conditions);
		}
	}

	destroy() {
		this.elt.removeEventListener("click", this._onProjectClick);
		this.TableVisibilityState?.destroy?.();
		this.TableVisibilityState = null;
		super.destroy();
	}
}

export default Project;
