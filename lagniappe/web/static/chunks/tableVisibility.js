/*! Third-party licenses: /third-party-licenses.txt */
import { p as primitives } from './primitives.js?v=b30f3f24';
import './shared.js?v=b30f3f24';

/**
 * @testable infrastructure
 */
class TableVisibility {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.selected = this.component.preload("selected") || [];
		this.columns = this.component.preload("columns") || [];
		this._columnIndexes = new Map();
		this._hiddenColumns = [];
		this._stylesheet = null;
		this._preservedEditor = null;
	}

	init() {
		const headers = this.component.elt.querySelectorAll("th[data-column]");
		headers.forEach((th, i) => {
			this._columnIndexes.set(th.dataset.column, i + 1);
		});

		const saved = localStorage.getItem(`columns-${this.view.hash}`);
		this._hiddenColumns = saved ? JSON.parse(saved) : this._setHiddenColumns();

		this._setVisibility();
		this._createController();

		this.view.elt.addEventListener("toggle-column-visibility", (e) => {
			this._toggleColumn(e.detail.column, e.detail.active);
		});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006e_task_index_mobile_ui.py::test_task_index_mobile_controls_open_with_task_columns
	 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_controls_open_with_page_columns
	 * @features table-controls
	 * @dimensions mobile-controls columns
	 */
	get visibleColumns() {
		return this.columns
			.map((col) => col.field)
			.filter((field) => {
				const index = this._columnIndexes.get(field);
				return index && !this._hiddenColumns.includes(index);
			});
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006e_task_index_mobile_ui.py::test_task_index_mobile_visibility_toggle_hides_column
	 * @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_quick_edit_keeps_revealed_completed_column_editable
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_hiding_column_updates_visible_headers_and_cells
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_visibility_panel_includes_category_form_columns
	 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_visibility_toggle_hides_column
	 * @features table-controls
	 * @dimensions mobile-controls column-visibility quick-edit checkbox-cell
	 */
	_toggleColumn(column, visible) {
		const index = this._columnIndexes.get(column);
		if (!index) return;

		this._hiddenColumns = visible
			? this._hiddenColumns.filter((i) => i !== index)
			: [...this._hiddenColumns, index];

		this._setVisibility();
		void this.component.widgets.TableEditor?.refreshCheckboxes?.();
	}

	/**
	 * Keep quick edit active while the column picker is temporarily displayed.
	 *
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_quick_edit_keeps_revealed_completed_column_editable
	 * @features task-index table-controls
	 * @dimensions quick-edit column-visibility checkbox-cell
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

	/**
	 * @testable true
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_column_visibility_panel_opens
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_visibility_panel_includes_category_form_columns
	 * @features table-controls
	 * @dimensions visibility-panel columns form-columns
	 */
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

	_setHiddenColumns() {
		if (this.selected.length) {
			return this.columns
				.filter((col) => !this.selected.includes(col.field))
				.map((col) => this._columnIndexes.get(col.field))
				.filter(Boolean);
		} else {
			return this.columns
				.filter((col) => col.selected !== true)
				.map((col) => this._columnIndexes.get(col.field))
				.filter(Boolean);
		}
	}

	/**
	 * @testable true
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_column_visibility_persists_after_reload
	 * @features table-controls
	 * @dimensions column-visibility persistence
	 */
	_setVisibility() {
		localStorage.setItem(
			`columns-${this.view.hash}`,
			JSON.stringify(this._hiddenColumns),
		);

		if (!this._stylesheet) {
			this._stylesheet = document.createElement("style");
			this._stylesheet.id = `column-visibility-${this.view.hash}`;
			document.head.appendChild(this._stylesheet);
		}

		const id = this.component.elt.id;
		const rowSelector = `#${id} tr:not([data-widget], [data-embedded], [data-role="empty"]) > td:not([data-column="delete"])`;
		const thSelector = `#${id} th:not([data-column="selector"], [data-embedded])`;
		const css = this._hiddenColumns
			.map(
				(i) =>
					`${rowSelector}:nth-child(${i}), ${thSelector}:nth-child(${i}) { display: none; }`,
			)
			.join("\n");

		this._stylesheet.textContent = css;
	}

	destroy() {
		this._stylesheet?.remove();
	}
}

export { TableVisibility };
