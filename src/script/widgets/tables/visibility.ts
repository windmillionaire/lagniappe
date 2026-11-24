import { primitives } from "../../elements/primitives.ts";
import { TableVisibilityState } from "./visibilityState.ts";

export class TableVisibility {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.selected = this.component.preload("selected") || [];
		this.columns = this.component.preload("columns") || [];
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

	_toggleColumn(column, visible) {
		this.state.toggle(column, visible);
	}

	/**
	 * Keep quick edit active while the column picker is temporarily displayed.
	 *
	 */
	preserveEditor(editor) {
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
			if (!e.target.matches("input[type='checkbox']")) return;
			this._toggleColumn(e.target.name, e.target.checked);
		});
	}

	destroy() {
		if (this._ownsState) this.state.destroy();
	}
}
