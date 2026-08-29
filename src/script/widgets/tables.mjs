import { BaseTable, EmbeddedTable } from "../elements/base/baseTable";

/**
 * @testable infrastructure
 */
export class IndexTable extends BaseTable {
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
	 * @pairs indexes:fingerprint-gate reconnect-refresh:manifest
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
	 * @matrix form-index : delete-target destination-refresh sorting
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
	 * @matrix form-index : created-row sorting
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
 * @matrix tasks : completion-cycle history reload
 * @pair embedded-table:table-cell-expand
 */
export class TaskHistory extends EmbeddedTable {
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
 * @matrix embedded-table : horizontal-scroll run-results table-cell-expand
 */
export class FilterResults extends EmbeddedTable {
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
