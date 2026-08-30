/*! Third-party licenses: /third-party-licenses.txt */
import { p as primitives } from './primitives.js?v=bd7dbd9a';
import { T as TableVisibilityState } from './index-foundation.js?v=bd7dbd9a';
import './styles.js?v=bd7dbd9a';
import './icons.js?v=bd7dbd9a';
import './foundation.js?v=bd7dbd9a';
import './connectivity.js?v=bd7dbd9a';
import './core-foundation.js?v=bd7dbd9a';

/**
 * @testable infrastructure
 */
class TableVisibility {
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

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006e_task_index_mobile_ui.py::test_task_index_mobile_controls_open_with_task_columns
	 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_controls_open_with_page_columns
	 * @matrix table-controls : columns mobile-controls
	 */
	get visibleColumns() {
		return this.state.visibleColumns;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006e_task_index_mobile_ui.py::test_task_index_mobile_visibility_toggle_hides_column
	 * @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_quick_edit_keeps_revealed_completed_column_editable
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_hiding_column_updates_visible_headers_and_cells
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_visibility_panel_includes_category_form_columns
	 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_visibility_toggle_hides_column
	 * @matrix table-controls : checkbox-cell column-visibility mobile-controls quick-edit
	 */
	_toggleColumn(column, visible) {
		this.state.toggle(column, visible);
	}

	/**
	 * Keep quick edit active while the column picker is temporarily displayed.
	 *
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_quick_edit_keeps_revealed_completed_column_editable
	 * @matrix table-controls task-index : checkbox-cell column-visibility quick-edit
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
	 * @matrix table-controls : columns form-columns visibility-panel
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

	destroy() {
		if (this._ownsState) this.state.destroy();
	}
}

export { TableVisibility };
