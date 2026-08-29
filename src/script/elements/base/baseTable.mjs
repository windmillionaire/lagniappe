import { withTransition } from "../../shared";
import { EmbeddedTableVisibility, ExpandedTableCell } from "../embeddedTable";

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_results_expands_table_submission_cell
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_expands_table_submission_cell
 * @matrix embedded-table : table-cell-expand visibility
 */
export class EmbeddedTable {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.click = this._click.bind(this);
		this._visibility = null;
	}

	init() {
		document.addEventListener("click", this.click);
		this.modified = true;
		this.visible = true;
	}

	_click(e) {
		this._clickExpandedTableCell(e);
	}

	_clickExpandedTableCell(e) {
		const expand = e.target.closest("button[data-role='expand']");
		if (!expand || !this.target.contains(expand)) return false;

		e.preventDefault();
		e.stopPropagation();
		this._expandTableCell(expand);
		return true;
	}

	initVisibility(table, storageKey = null) {
		if (!table) return null;

		this._visibility = new EmbeddedTableVisibility(table, storageKey);
		this._visibility.init();
		return this._visibility;
	}

	async _expandTableCell(button) {
		if (!button._embeddedTable) {
			button._embeddedTable = new ExpandedTableCell(this.view, button);
		}
		button._embeddedTable.toggle();
	}

	destroy() {
		document.removeEventListener("click", this.click);
	}
}

/**
 * @testable infrastructure
 */
export class BaseTable extends EmbeddedTable {
	constructor(attributes) {
		super(attributes);
		this.keydown = this._keydown.bind(this);
	}

	init() {
		super.init();
		document.addEventListener("keydown", this.keydown);
	}

	get header() {
		return this.component.elt.querySelector("thead > tr:first-child");
	}

	get visibilityWidget() {
		return this.component.widgets.TableVisibility;
	}

	get sortingWidget() {
		return this.component.widgets.TableSorting;
	}

	_click(e) {
		if (this._clickExpandedTableCell(e)) return;

		const visibility = this.visibilityWidget;
		const sorting = this.sortingWidget;
		const open = visibility?.visible || sorting?.visible;

		if (!e.target.closest("thead")) {
			open &&
				withTransition(() => {
					[visibility, sorting].forEach((widget) => {
						if (widget) widget.disable();
						if (widget) widget.reconcile();
					});
				});
			return;
		}

		if (e.target.closest("button[lp-show='table:TableVisibility']")) {
			return;
		} else if (this.header.contains(e.target)) {
			const header = e.target.closest("th[data-ordering]");
			if (!header) return;

			const event = new CustomEvent("toggle-column-filter", {
				detail: {
					button: e.target.closest("button"),
					column: header.dataset.column,
				},
				bubbles: true,
			});
			this.target.dispatchEvent(event);
		}
	}

	_keydown(e) {
		if (e.key === "Escape") {
			const visibility = this.visibilityWidget;
			const sorting = this.sortingWidget;
			const open = visibility?.visible || sorting?.visible;
			if (!open) return;

			withTransition(() => {
				[visibility, sorting].forEach((widget) => {
					if (widget) widget.disable();
					if (widget) widget.reconcile();
				});
			});
		}
	}

	destroy() {
		super.destroy();
		document.removeEventListener("keydown", this.keydown);
	}
}
