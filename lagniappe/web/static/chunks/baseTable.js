/*! Third-party licenses: /third-party-licenses.txt */
import { r as request, E as ENDPOINTS, w as withTransition } from './foundation.js?v=b158c05a';
import { STYLES } from './styles.js?v=b158c05a';
import { s as setIcon } from './icons.js?v=b158c05a';
import { p as primitives } from './primitives.js?v=b158c05a';
import { TableElement } from './table.js?v=b158c05a';

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_visibility_persists_after_reload
 * @matrix table-controls : column-visibility persistence
 * @pair tasks:history
 */
class EmbeddedTableVisibility {
	constructor(tableElt, storageKey = null) {
		const preload = JSON.parse(tableElt.dataset.preload);
		this.tableElt = tableElt;
		this.columns = preload.columns || [];
		this.storageKey = storageKey;
		this.selected = this._loadSelected();
		this.visibilityRow = this.tableElt.querySelector(
			"[data-widget='TableVisibility']",
		);
		this.header = this.tableElt.querySelector("[data-role='column-header']");
		this.actions = null;
		this.toggle = null;
		this._headerClick = this._headerClick.bind(this);
	}

	init() {
		this._createHeaderAction();
		this.header.addEventListener("click", this._headerClick);

		this.columns.forEach((column) => {
			this._setColumnVisibility(
				column.field,
				this.selected.includes(column.field),
			);
		});
		this._saveSelected();
		this._createController();
	}

	_loadSelected() {
		const defaults = this.columns
			.filter((column) => column.selected)
			.map((column) => column.field);
		if (!this.storageKey) return defaults;

		const saved = localStorage.getItem(this.storageKey);
		if (saved === null) return defaults;

		try {
			const selected = JSON.parse(saved);
			if (!Array.isArray(selected)) return defaults;

			const available = new Set(this.columns.map((column) => column.field));
			return [...new Set(selected)].filter((field) => available.has(field));
		} catch {
			return defaults;
		}
	}

	_saveSelected() {
		this.tableElt.dataset.selected = JSON.stringify(this.selected);
		if (this.storageKey) {
			localStorage.setItem(this.storageKey, JSON.stringify(this.selected));
		}
	}

	_createHeaderAction() {
		const cell = this.header.appendChild(document.createElement("th"));
		cell.className = STYLES.table.thead.actionCell;
		cell.scope = "col";

		this.actions = cell.appendChild(document.createElement("div"));
		this.actions.className = STYLES.table.thead.actions;
		this.actions.dataset.role = "embedded-table-actions";

		this.toggle = this.actions.appendChild(document.createElement("button"));
		this.toggle.type = "button";
		this.toggle.className = STYLES.table.thead.actionButton;
		this.toggle.dataset.role = "embedded-table-visibility";
		this.toggle.setAttribute("aria-label", "Choose visible columns");
		this.toggle.setAttribute("aria-expanded", "false");
		this.toggle.title = "Choose visible columns";

		const icon = this.toggle.appendChild(document.createElement("span"));
		setIcon(icon, "column", STYLES.table.thead.actionIcon);
	}

	_headerClick(e) {
		if (!e.target.closest("[data-role='embedded-table-visibility']")) return;

		e.preventDefault();
		e.stopPropagation();
		this._toggleController();
	}

	_toggleController() {
		const visible = this.visibilityRow.dataset.visible === "true";
		return this._setControllerVisible(!visible);
	}

	_setControllerVisible(visible) {
		this.visibilityRow.dataset.visible = visible ? "true" : "false";
		this.toggle?.setAttribute("aria-expanded", visible ? "true" : "false");
		return visible;
	}

	_createController() {
		const cell = this.visibilityRow.appendChild(document.createElement("td"));
		cell.colSpan = this.header.querySelectorAll("th").length;
		cell.className = `p-3 border-t bg-kind-bg border-slate-300 group`;

		const container = cell.appendChild(document.createElement("div"));
		container.className = "flex flex-col gap-3";

		for (const column of this.columns) {
			const checkbox = container.appendChild(
				primitives.checkbox({
					name: column.field,
					checked: this.selected.includes(column.field),
					kind: this.tableElt.dataset.kind,
					label: column.title,
				}),
			);

			checkbox.dataset.role = "selector";
		}

		cell.addEventListener("change", (e) => {
			if (!e.target.matches("input[type='checkbox']")) return;

			const [column, visible] = [e.target.name, e.target.checked];

			this.selected = visible
				? [...new Set([...this.selected, column])]
				: this.selected.filter((field) => field !== column);
			this._saveSelected();

			this._setColumnVisibility(column, visible);
		});
	}

	_setColumnVisibility(column, visible) {
		const display = visible ? "table-cell" : "none";

		this.tableElt
			.querySelectorAll(`[data-column="${column}"]`)
			.forEach((col) => {
				col.style.display = display;
			});
	}
}

/**
 * @testable infrastructure
 */
class ExpandedTableCell {
	constructor(view, button) {
		this.view = view;
		this.button = button;
		this.row = null;
		this.table = null;
		this.destroy = this.destroy.bind(this);
		this.mobileQuery = window.matchMedia("(max-width: 640px)");
		this.kind = null;
		this.submission = null;
		this.schema = null;
	}

	async create() {
		const row = this.button.closest("tr");
		const colSpan = Array.from(row.querySelectorAll("td")).length;

		this.row = document.createElement("tr");
		this.row.dataset.embedded = "true";
		this.row.dataset.visible = "false";
		this.row.className =
			"rounded-md border border-base-light/50 mx-4 mb-3 overflow-hidden sm:rounded-none sm:border-t sm:border-b sm:border-x-0 sm:mx-0 sm:mb-0";
		row.after(this.row);

		const tableEmbed = this.row.appendChild(document.createElement("td"));
		tableEmbed.colSpan = colSpan;

		const key = row.dataset.key;
		const tableId = this.button.closest("[data-column]").dataset.column;
		if (!this.kind || !this.submission || !this.schema) {
			const response = await request.get(
				ENDPOINTS.renderer.expandTableCell(key, tableId),
			);
			if (!response.ok) return;
			Object.assign(this, response);
			this.kind = this.kind || "form";
		}

		this.table = new TableElement(
			{ readonly: true },
			this.schema,
			this.submission,
		).embedded;
		this.table.dataset.embedded = "true";
		this.table.querySelectorAll("tr, th, table").forEach((tr) => {
			tr.dataset.embedded = "true";
		});
		this.table.querySelector("tbody").classList.add(`bg-${this.kind}-bg`);

		tableEmbed.appendChild(this.table);

		this.mobileQuery.addEventListener("change", this.destroy);
	}

	get visible() {
		return this.row.dataset.visible === "true";
	}

	async toggle(hide = false) {
		if (!this.table) await this.create();
		await withTransition(
			() => {
				const visible = hide ? true : this.visible;
				this.row.dataset.visible = visible ? "false" : "true";
				if (
					this.view.mobile &&
					this.row.closest("[data-widget='IndexTable']")
				) {
					this.row.style.display = visible ? "none" : "block";
				}
				this.button.dataset.open = visible ? "false" : "true";
				this.button.setAttribute("aria-expanded", visible ? "false" : "true");
			},
			{ label: "embedded-table:toggle" },
		);
	}

	destroy() {
		this.row.remove();
		this.row = null;
		this.table = null;
		this.button.dataset.open = "false";
		this.button.setAttribute("aria-expanded", "false");
		this.button._embeddedTable = null;
		this.mobileQuery.removeEventListener("change", this.destroy);
	}
}

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_results_expands_table_submission_cell
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_expands_table_submission_cell
 * @matrix embedded-table : table-cell-expand visibility
 */
class EmbeddedTable {
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
class BaseTable extends EmbeddedTable {
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

export { BaseTable as B, EmbeddedTable as E };
