import { primitives } from "../../elements/primitives.ts";
import type { LoadedWidget } from "../../types/widgets.d.ts";
import type ViewComponent from "../../views/base/component.ts";
import type { TableEditor } from "./editor.ts";
import { type TableColumn, TableVisibilityState } from "./visibilityState.ts";

interface VisibilityAttributes {
	component: ViewComponent;
	view: {
		elt: HTMLElement;
		hash?: string;
		TableVisibilityState?: TableVisibilityState | null;
	};
	target: HTMLElement;
	kind?: string;
	visible?: boolean;
}

export class TableVisibility {
	declare component: ViewComponent;
	declare view: VisibilityAttributes["view"];
	declare target: HTMLElement;
	declare kind: string | undefined;
	declare visible: boolean | undefined;
	declare name: LoadedWidget["name"];
	declare enable: LoadedWidget["enable"];
	declare disable: LoadedWidget["disable"];
	declare prepareReconcile: LoadedWidget["prepareReconcile"];
	declare reconcile: LoadedWidget["reconcile"];
	declare selected: string[];
	declare columns: TableColumn[];
	declare state: TableVisibilityState;
	declare _ownsState: boolean;
	declare _preservedEditor: TableEditor | null;

	constructor(attributes: VisibilityAttributes) {
		Object.assign(this, attributes);
		const selected = this.component.preload("selected");
		const columns = this.component.preload("columns");
		this.selected = Array.isArray(selected)
			? selected.filter((field): field is string => typeof field === "string")
			: [];
		this.columns = Array.isArray(columns)
			? columns.filter(
					(column): column is TableColumn =>
						column !== null &&
						typeof column === "object" &&
						typeof column.field === "string",
				)
			: [];
		this.state =
			this.view.TableVisibilityState ||
			new TableVisibilityState({
				component: this.component,
				view: this.view,
				selected: this.selected,
				columns: this.columns,
			});
		this._ownsState = !this.view.TableVisibilityState;
		this._preservedEditor = null;
	}

	init() {
		this.state.init();
		this._createController();
	}

	get visibleColumns() {
		return this.state.visibleColumns;
	}

	_toggleColumn(column: string, visible: boolean) {
		this.state.toggle(column, visible);
	}

	syncCheckboxes() {
		const visibleColumns = this.visibleColumns;
		this.target
			.querySelectorAll<HTMLInputElement>("input[type='checkbox'][name]")
			.forEach((checkbox) => {
				checkbox.checked = visibleColumns.includes(checkbox.name);
			});
	}

	/**
	 * Keep quick edit active while the column picker is temporarily displayed.
	 *
	 */
	preserveEditor(editor: TableEditor) {
		this._preservedEditor = editor;
	}

	postreconcile() {
		if (this.visible || !this._preservedEditor) return;

		const editor = this._preservedEditor;
		this._preservedEditor = null;
		if (!editor.visible) return;

		if (!this.component.active || this.component.active === this) {
			this.component.active = editor;
		}
	}

	_createController() {
		const cell = this.target.appendChild(document.createElement("td"));
		cell.colSpan = this.component.elt.querySelectorAll("th").length;
		cell.className = `p-3 border-t bg-kind-bg border-slate-300 group`;

		const container = cell.appendChild(document.createElement("div"));
		container.className = "flex flex-wrap gap-3";

		const visibleColumns = this.visibleColumns;

		for (const column of this.columns) {
			const checkbox = container.appendChild(
				primitives.checkbox({
					name: column.field,
					checked: visibleColumns.includes(column.field),
					kind: this.kind,
					label: column.title,
				}),
			);

			checkbox.dataset.role = "selector";
		}

		cell.addEventListener("change", (e) => {
			if (
				!(e.target instanceof HTMLInputElement) ||
				e.target.type !== "checkbox"
			)
				return;
			this._toggleColumn(e.target.name, e.target.checked);
		});
	}

	destroy() {
		if (this._ownsState) this.state.destroy();
	}
}
