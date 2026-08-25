/*! Third-party licenses: /third-party-licenses.txt */
import { r as request, E as ENDPOINTS, w as withTransition } from './foundation.js?v=b66dffd0';
import './connectivity.js?v=b66dffd0';
import { STYLES } from './styles.js?v=b66dffd0';
import { p as primitives } from './primitives.js?v=b66dffd0';
import { s as setIcon } from './icons.js?v=b66dffd0';
import { TableElement } from './table.js?v=b66dffd0';
import './baseElement.js?v=b66dffd0';
import './checkbox.js?v=b66dffd0';
import './input.js?v=b66dffd0';
import './formatting.js?v=b66dffd0';
import './link.js?v=b66dffd0';
import './facets.js?v=b66dffd0';
import './combobox.js?v=b66dffd0';
import './results.js?v=b66dffd0';
import './storage.js?v=b66dffd0';
import './submitter.js?v=b66dffd0';
import './loader.js?v=b66dffd0';

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_visibility_persists_after_reload
 * @pairs tasks:history
 * @pairs table-controls:column-visibility table-controls:persistence
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
 * @features embedded-table
 * @dimensions table-cell-expand visibility
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

/**
 * @testable infrastructure
 */
class IndexTable extends BaseTable {
	constructor(attributes) {
		super(attributes);
		this.refreshScope = "collection";
		this.loading = false;
		this.loaded = !this.prefetched || this.target.hasAttribute("loaded");
		this._empty = false;
		this._updated = [];
		this._created = [];
	}

	async updated(response) {
		this._updated = response.html?.querySelectorAll("tr[lp-entity]") || [];
		const append = response.html?.querySelector("tr[lp-load]");
		this.loaded = !append;
		return append;
	}

	async created(response) {
		this._created = response.html.querySelectorAll("tr");
	}

	get selector() {
		return this.component.elt.querySelector(
			"th[data-column='selector'] button",
		);
	}

	setEmptyRowVisibility() {
		const emptyRow = this.target.querySelector("tr[data-role='empty']");
		const notEmpty = this.target.querySelector("tr[lp-entity]");
		if (emptyRow) {
			if (!this.view.mobile) {
				emptyRow.dataset.visible = notEmpty ? "false" : "true";
			} else {
				emptyRow.style.display = notEmpty ? "none" : "block";
			}
		}
		if (!notEmpty) {
			this.loaded = true;
			this.target.setAttribute("loaded", "");
		}
	}

	get prefetched() {
		return this.target.hasAttribute("lp-prefetch");
	}

	/**
	 * @testable true
	 * @tests tests_e2e/003_forms/test_003a_forms.py::test_forms_index_page
	 * @tests tests_js/test_022_refresh_frontend.py::test_core_refresh_batches_supported_widgets_and_falls_back_per_target
	 * @pair reconnect-refresh:manifest
	 * @pair indexes:fingerprint-gate
	 */
	refreshDescriptor() {
		if (
			this.component.name !== "table" ||
			!this.target.hasAttribute("loaded")
		) {
			return null;
		}
		const supported =
			Boolean(this.view.key) ||
			["forms", "tasks", "users"].includes(this.view.elt.dataset.index);
		if (!supported) return null;

		return {
			rows: Array.from(
				this.target.querySelectorAll("tr[lp-entity]"),
				(row) => ({
					key: row.dataset.key,
					modified: row.dataset.modified || "",
				}),
			),
		};
	}

	_parseRefreshRow(html) {
		if (!html) return null;
		const template = document.createElement("template");
		template.innerHTML = html.trim();
		return template.content.querySelector("tr[lp-entity]");
	}

	/**
	 * @testable infrastructure
	 * @covered-by src/script/views/base/core.mjs::Core._refreshCollectionComponents
	 */
	refreshDelta(delta) {
		const existing = new Map(
			Array.from(this.target.querySelectorAll("tr[lp-entity]"), (row) => [
				row.dataset.key,
				row,
			]),
		);
		for (const key of delta.remove || []) {
			existing.get(key)?.remove();
			existing.delete(key);
		}

		const added = [];
		for (const update of delta.upsert || []) {
			const row = this._parseRefreshRow(update.html);
			if (!row || row.dataset.key !== update.key) {
				throw new Error("Invalid table refresh row");
			}
			const current = existing.get(update.key);
			if (current) current.replaceWith(row);
			else added.push(row);
			existing.set(update.key, row);
		}

		const order = Array.isArray(delta.order) ? delta.order : [];
		for (const key of order) {
			const row = existing.get(key);
			if (!row) throw new Error("Table refresh order references a missing row");
			this.target.append(row);
		}
		if (added.length) this.view.addFlash(...added);

		let empty = this.target.querySelector("tr[data-role='empty']");
		if (!order.length && !empty && delta.empty) {
			const template = document.createElement("template");
			template.innerHTML = delta.empty.trim();
			empty = template.content.querySelector("tr[data-role='empty']");
			if (empty) this.target.append(empty);
		}

		this.setEmptyRowVisibility();
		this.sortingWidget?.refreshRows?.();
	}

	/**
	 * @testable true
	 * @tests tests_js/test_022_refresh_frontend.py::test_index_table_row_updates_rebuild_active_sort
	 * @pairs form-index:destination-refresh form-index:sorting form-index:delete-target
	 */
	refresh(response) {
		if (!response?.html) return;
		const newRows = [...response.html.querySelectorAll("tr[lp-entity]")];
		const newKeys = new Set(
			newRows.map((row) => row.dataset.key).filter(Boolean),
		);
		const prepend = [];

		for (const newRow of newRows) {
			const key = newRow.dataset.key;
			if (!key) continue;

			const existing = this.target.querySelector(`tr[data-key="${key}"]`);
			if (existing) existing.replaceWith(newRow);
			else prepend.push(newRow);
		}

		if (prepend.length) {
			const anchor = this.target.querySelector("tr[lp-entity]");
			if (anchor) anchor.before(...prepend);
			else this.target.append(...prepend);
			this.view.addFlash(...prepend);
		}

		if (!this.prefetched) {
			this.target.querySelectorAll("tr[lp-entity]").forEach((row) => {
				if (!newKeys.has(row.dataset.key)) row.remove();
			});
		}

		this.setEmptyRowVisibility();
		this.sortingWidget?.refreshRows?.();
	}

	/**
	 * @testable true
	 * @tests tests_js/test_022_refresh_frontend.py::test_index_table_row_updates_rebuild_active_sort
	 * @features form-index
	 * @dimensions created-row sorting
	 */
	async prereconcile() {
		const loaded = this.target.hasAttribute("loaded");
		if (!this.loaded || loaded) return;

		const sorting = await this.component.loadWidget("TableSorting");
		if (sorting) await sorting.init();
		this._finishLoading = true;
	}

	postreconcile() {
		const target = this.target;
		let rowsChanged = false;
		const sortingWasInitialized = this.sortingWidget?.initialized === true;

		if (this._created.length > 0) {
			target.prepend(...this._created);
			this.view.addFlash(...this._created);
			this._created = [];
			rowsChanged = true;

			if (this.view.mobile) {
				target.scrollIntoView({ behavior: "auto", block: "start" });
			}
		}

		if (this._updated.length > 0) {
			target.append(...this._updated);
			this._updated = [];
			rowsChanged = true;
		}

		if (this._finishLoading) {
			this._finishLoading = false;
			this.target.setAttribute("loaded", "");
			this.setEmptyRowVisibility();
			target.dataset.visible = true;
			this.loading = false;
		}

		if (rowsChanged) {
			this.setEmptyRowVisibility();
			if (sortingWasInitialized) this.sortingWidget.refreshRows();
		}
	}
}

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_appears_after_completion_cycle
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_visibility_persists_after_reload
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_expands_table_submission_cell
 * @pairs tasks:history tasks:completion-cycle tasks:reload
 * @pairs embedded-table:table-cell-expand
 */
class TaskHistory extends EmbeddedTable {
	constructor(attributes) {
		super(attributes);
		this._updated = null;
	}

	get table() {
		return this.target.querySelector("[data-role='table']");
	}

	async updated(response) {
		this._updated = response.html.querySelector("table");
	}

	postreconcile() {
		if (!this._updated) return;

		this.visible = true;
		this.target.dataset.visible = "true";
		this.table.replaceChildren(this._updated);
		this._updated.dataset.visible = "true";
		this.initVisibility(
			this._updated,
			`columns-${this.component.name}-history`,
		);
		this._updated = null;
	}
}

/**
 * @testable true
 * @tests tests_e2e/004_projects/test_004f_project_filters.py::test_filter_results_expands_table_submission_cell
 * @pairs embedded-table:run-results embedded-table:table-cell-expand
 * @pairs embedded-table:horizontal-scroll
 */
class FilterResults extends EmbeddedTable {
	constructor(attributes) {
		super(attributes);
		this.badges = null;
		this.table = null;
		this.tableContainer = null;
		this.container = null;
		this.filtering = this.target.dataset.kind;
	}

	async updated(response) {
		this.table =
			response.html.querySelector("#embedded-table") ||
			response.html.querySelector("table");
		if (this.filtering === "page") {
			this.badges = this.component.widgets.Filters.filters.cloneNode(true);
		}
	}

	get tbody() {
		return this.table.querySelector("tbody");
	}

	get rows() {
		return this.tbody.querySelectorAll("tr:not([data-role='empty'])");
	}

	get empty() {
		return this.tbody.querySelector("tr[data-role='empty']");
	}

	postreconcile() {
		if (this.target.children.length) return;
		if (!this.table) return;

		this.container = document.createElement("div");
		this.container.className =
			"min-w-0 overflow-hidden max-w-full rounded-md outline-2 outline-kind-default bg-white";
		this.tableContainer = document.createElement("div");
		this.tableContainer.className = "table-container px-4";
		this.tableContainer.dataset.role = "table";
		this.tableContainer.appendChild(this.table);
		this.container.appendChild(this.tableContainer);
		this.table.dataset.visible = "true";
		this.initVisibility(this.table);
		if (this.filtering === "page") {
			this.target.replaceChildren(this.badges, this.container);
		} else {
			this.target.replaceChildren(this.container);
		}
	}

	reset() {
		if (this.badges) {
			this.badges.remove();
			this.badges = null;
		}
		if (this.container) {
			this.container.remove();
			this.container = null;
		}
		if (this.tableContainer) {
			this.tableContainer = null;
		}
		if (this.table) {
			this.table = null;
		}
	}
}

export { FilterResults, IndexTable, TaskHistory };
