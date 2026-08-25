/*! Third-party licenses: /third-party-licenses.txt */
import { p as primitives } from './primitives.js?v=bcdf9883';
import { w as withTransition } from './foundation.js?v=bcdf9883';
import './connectivity.js?v=bcdf9883';
import { s as sessionStore } from './storage.js?v=bcdf9883';
import './styles.js?v=bcdf9883';
import './icons.js?v=bcdf9883';

/**
 * @testable infrastructure
 */
class TableSorting {
	constructor(attributes) {
		Object.assign(this, attributes);
		this.columns = this.component.preload("columns") || [];
		this.sorts = new Map();
		this.containers = new Map();
		this.toggles = new Map();
		this.headers = new Map();
		this.lastReorderColumn = null;
		this.initialized = false;
	}

	get storageKey() {
		return `sorts-${this.view.hash}`;
	}

	get header() {
		return this.component.elt.querySelector("thead > tr:first-child");
	}

	get body() {
		return this.component.elt.querySelector("tbody");
	}

	get rows() {
		return Array.from(this.body.querySelectorAll("tr")).filter(
			(row) => row.dataset.visible !== "false",
		);
	}

	init() {
		if (this.initialized) return;
		this.initialized = true;

		this._setSortingToggles();
		const saved = this._loadState();

		this.header.querySelectorAll("th[data-ordering]").forEach(async (th) => {
			const column = th.dataset.column;
			const ordering = th.dataset.ordering;
			this.headers.set(column, th);

			const sort = this._enableSort(this._createSort(column, ordering));
			sort.restore(saved?.sorts?.[column]);
		});

		this._restoreLastReorderColumn(saved);
		if (this._hasActiveSorts()) this.sort();

		this.view.elt.addEventListener("toggle-column-filter", (e) => {
			const column = e.detail.column;

			if (this.view.mobile) {
				void withTransition(
					() => {
						const sort = this._enableSort(this.sorts.get(column));
						if (sort.active) {
							const toggle = this.toggles.get(column);
							toggle.dataset.active = "true";
						}
						const container = this.containers.get(column);
						const visible = container.dataset.visible === "true";
						container.dataset.visible = visible ? "false" : "true";
					},
					{ label: "table-sorting:toggle-mobile" },
				);
				return;
			} else {
				const button = e.detail.button;
				this._toggleColumn(column, button);
			}
		});
	}

	reset() {
		this.containers.forEach((container) => {
			container.remove();
		});
		this.sorts.forEach((sort) => {
			sort.clear();
		});
		this._clearState();
		this.containers = new Map();
		this.toggles = new Map();
		this.headers = new Map();
		this.lastReorderColumn = null;
		this._setSortingToggles();
		this.header.querySelectorAll("th[data-ordering]").forEach((th) => {
			const column = th.dataset.column;
			this.headers.set(column, th);
			th.dataset.sorting = "false";
			this._enableSort(this._createSort(column, th.dataset.ordering));
		});
	}

	/**
	 * Rebuild row-value caches after server row replacement while preserving active sorts.
	 *
	 * @testable infrastructure
	 * @covered-by src/script/widgets/tables.mjs::IndexTable.refreshDelta
	 * @covered-by src/script/widgets/tables.mjs::IndexTable.refresh
	 */
	refreshRows() {
		if (!this.initialized) return;

		const saved = {
			lastReorderColumn: this.lastReorderColumn,
			sorts: Object.fromEntries(
				Array.from(this.sorts, ([column, sort]) => [column, sort.state]),
			),
		};
		this.containers.forEach((container) => {
			container.remove();
		});
		this.sorts = new Map();
		this.containers = new Map();
		this.toggles = new Map();
		this.headers = new Map();
		this.lastReorderColumn = null;
		this._setSortingToggles();

		this.header.querySelectorAll("th[data-ordering]").forEach((th) => {
			const column = th.dataset.column;
			this.headers.set(column, th);
			th.dataset.sorting = "false";
			const sort = this._enableSort(
				this._createSort(column, th.dataset.ordering),
			);
			sort.restore(saved.sorts[column]);
		});

		this._restoreLastReorderColumn(saved);
		if (this._hasActiveSorts()) this.sort();
	}

	_loadState() {
		const saved = sessionStore.getJSON(this.storageKey);
		if (saved === null) return null;
		if (typeof saved === "object" && !Array.isArray(saved)) return saved;
		sessionStore.remove(this.storageKey);
		return null;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_name_column_sort_persists_after_back_navigation
	 * @features table-controls
	 * @dimensions sorting persistence
	 */
	_saveState() {
		const sorts = {};

		this.sorts.forEach((sort) => {
			const state = sort.state;
			if (state) sorts[sort.column] = state;
		});

		if (Object.keys(sorts).length) {
			sessionStore.setJSON(this.storageKey, {
				lastReorderColumn: this.lastReorderColumn,
				sorts: sorts,
			});
		} else {
			this._clearState();
		}
	}

	_clearState() {
		sessionStore.remove(this.storageKey);
	}

	_restoreLastReorderColumn(saved) {
		const savedSort = this.sorts.get(saved?.lastReorderColumn);
		if (savedSort?.active && savedSort.reordering) {
			this.lastReorderColumn = savedSort.column;
			return;
		}

		const activeSort = Array.from(this.sorts.values()).find((sort) => {
			return sort.active && sort.reordering;
		});
		this.lastReorderColumn = activeSort?.column || null;
	}

	_hasActiveSorts() {
		return Array.from(this.sorts.values()).some((sort) => sort.active);
	}

	_markSortActive(sort) {
		this.headers.get(sort.column).dataset.sorting = "true";
		if (!this.view.mobile) return;

		const toggle = this.toggles.get(sort.column);
		if (toggle) toggle.dataset.active = "true";
	}

	/**
	 * @testable true
	 * @tests tests_e2e/006_tasks/test_006e_task_index_mobile_ui.py::test_task_index_mobile_filter_button_opens_sorting_panel
	 * @tests tests_e2e/007_categories/test_007d_category_mobile_ui.py::test_category_mobile_filter_button_opens_sorting_panel
	 * @features table-controls
	 * @dimensions mobile-controls sorting
	 */
	_setSortingToggles() {
		const container = this.view.mobile
			? document.getElementById("mobile-controls")
			: this.header;

		container
			.querySelectorAll("button[data-toggle='filter']")
			.forEach((button) => {
				this.toggles.set(
					button.closest("[data-column]").dataset.column,
					button,
				);
			});
	}

	async _toggleColumn(column, button) {
		await withTransition(
			() => {
				const sort = this._enableSort(this.sorts.get(column));
				if (sort.disabled) return;

				const visible = this.visible;
				const container = this.containers.get(column);
				this.containers.forEach((candidate) => {
					if (candidate !== container) candidate.dataset.visible = "false";
				});

				if (button && sort.active) {
					this.visible = false;
					sort.sortedBy = null;
					this.sort();
				} else if (this.visible && container.dataset.visible === "true") {
					this.visible = false;
				} else {
					container.dataset.visible = "true";
					this.visible = true;
				}

				this.modified = visible !== this.visible;
				if (this.modified && this.visible) {
					this.component.active = this;
					this.component.render(true);
				} else if (this.modified && !this.visible) {
					this.component.active = null;
					this.component.render(false);
				}
			},
			{ label: "table-sorting:toggle" },
		);
	}

	_resetRows(reorderRows, showRows) {
		if (!reorderRows && showRows.size === 0) return null;
		const initialOrder = reorderRows ? new WeakMap() : null;

		this.body.querySelectorAll("tr").forEach((row) => {
			if (showRows.has(row)) {
				row.dataset.visible = "true";
			}
			if (!initialOrder) return;

			const modifiedColumn = Number(
				row.querySelector(`td[data-column="modified"]`)?.dataset.sortValue || 0,
			);
			initialOrder.set(row, modifiedColumn * -1);
		});

		return initialOrder;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_name_column_sort_ascending_reorders_rows
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_name_column_sort_descending_reorders_rows
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_clearing_sort_restores_default_order
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_boolean_column_filter_clear_restores_rows
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_exists_column_filter_treats_phone_values_as_present
	 * @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_name_sort_ascending_reorders_rows
	 * @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_due_date_sort_filters_to_dated_rows
	 * @features table-controls
	 * @dimensions sorting sort-asc sort-desc sort-clear name filtering due-date boolean-column exists-column phone
	 */
	sort() {
		let reorderRows = false;
		let showRows = new Set();

		// clear inactive sorts, track rows hidden by inactive sorts
		this.sorts.forEach((sort) => {
			if (sort.reordering && this.lastReorderColumn !== sort.column) {
				// deactivate previous reordering sort
				sort.sortedBy = null;
			}

			if (sort.active || !sort.sorted) return;

			showRows = sort.hiddenRows ? showRows.union(sort.hiddenRows) : showRows;

			if (sort.reordering) reorderRows = true;

			this._resetSort(sort);
		});

		// Active filters may change from one value to another. Restore rows hidden
		// by the previous active values before applying the current active filters.
		this.sorts.forEach((sort) => {
			if (!sort.active || !sort.hiddenRows) return;
			sort.hiddenRows.forEach((row) => {
				showRows.add(row);
			});
		});

		// Reset visibility and return initial order (date modified)
		const initialOrder = this._resetRows(reorderRows, showRows);

		// filter by non-reordering sorts
		this.sorts.forEach((sort) => {
			if (!sort.active || sort.reordering) return;
			sort.sort();
			this._markSortActive(sort);
		});

		// most recent reordering sort or initial order
		const reorderingSort = this.sorts.get(this.lastReorderColumn);
		if (reorderingSort?.active) {
			reorderingSort.sort();
			this._markSortActive(reorderingSort);
		} else if (initialOrder) {
			const rows = this.rows;
			rows.sort((a, b) => {
				return initialOrder.get(a) - initialOrder.get(b);
			});
			this.body.append(...rows);
			this.lastReorderColumn = null;
		}

		this._saveState();
	}

	_createContainer(column) {
		this.containers.set(
			column,
			this.view.mobile ? this._createSection(column) : this._createCell(column),
		);
		return this.containers.get(column);
	}

	_createCell(column) {
		const cell = document.createElement("td");
		cell.colSpan = this.component.elt.querySelectorAll("th").length;
		cell.className = `p-3 border-t bg-kind-bg border-slate-300`;
		cell.dataset.sorts = column;
		cell.dataset.visible = "false";
		this.target.appendChild(cell);
		return cell;
	}

	_createSection(column) {
		const section = document.createElement("div");
		section.className = `flex flex-col gap-2 p-4 bg-white outline-kind-default rounded-md outline-1`;
		section.dataset.sorts = column;
		section.dataset.visible = "false";
		const controls = document.getElementById("mobile-controls");
		controls.querySelector(`[data-column="${column}"]`).after(section);
		return section;
	}

	_createCheckboxElement(sort) {
		const container = this.containers.get(sort.column);
		const element = container.appendChild(document.createElement("div"));
		if (sort.options === null) return;

		if (Object.keys(sort.options).length > 4 && !this.view.mobile) {
			element.className = `grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-4`;
		} else if (!this.view.mobile) {
			element.className = `flex flex-row flex-wrap gap-4`;
		} else {
			element.className = `flex flex-col gap-2`;
		}
		sort.createOptions(element);
	}

	_createRadioElement(sort) {
		const container = this.containers.get(sort.column);
		const element = container.appendChild(document.createElement("fieldset"));
		element.className = `flex flex-row flex-wrap gap-4`;
		sort.createOptions(element);
	}

	_createSortElement(sort) {
		if (sort.ordering === "categorical") {
			this._createCheckboxElement(sort);
		} else {
			this._createRadioElement(sort);
		}
	}

	_enableSort(sort) {
		sort.init();

		const toggle = this.toggles.get(sort.column);
		toggle.dataset.visible = sort.disabled ? "false" : "true";
		if (sort.disabled) return sort;

		const container = this.containers.has(sort.column)
			? this.containers.get(sort.column)
			: this._createContainer(sort.column);

		if (!container.children.length) {
			this._createSortElement(sort);
		}

		return sort;
	}

	_resetSort(sort) {
		sort.clear();
		const container = this.containers.get(sort.column);
		if (container) {
			container.remove();
			this.containers.delete(sort.column);
		}
		const header = this.headers.get(sort.column);
		if (header) header.dataset.sorting = "false";
		if (this.view.mobile) {
			const toggle = this.toggles.get(sort.column);
			if (toggle) toggle.dataset.active = "false";
		}
	}

	_createSort(column, ordering) {
		this.sorts.set(
			column,
			ordering === "categorical"
				? new CheckboxSort(this, column, ordering)
				: new RadioSort(this, column, ordering),
		);

		return this.sorts.get(column);
	}
}

/**
 * @testable false
 * @covered-by src/script/widgets/tableSorting.mjs::TableSorting.sort
 * @reason private sort strategy exercised through the TableSorting orchestrator
 */
class RadioSort {
	constructor(orchestrator, column, ordering) {
		this.orchestrator = orchestrator;
		this.column = column;
		this.ordering = ordering;
		this.reordering =
			this.ordering === "numeric" || this.ordering === "lexical";
		this.rowValues = null;
		this.hiddenRows = null;
		this.sortedBy = null;
		this.sortValue = null;
		this.initialized = false;
		this.sorted = false;
	}

	get disabled() {
		return false;
	}

	get active() {
		return this.sortedBy != null;
	}

	get defaultValue() {
		return ["boolean", "exists"].includes(this.ordering) ? "all" : "none";
	}

	get state() {
		return this.active ? { value: this.sortValue } : null;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_image_column_sort_panel_offers_presence_options
	 * @features table-controls
	 * @dimensions sorting exists-column
	 */
	get options() {
		const setOptions = (options) => {
			if (this.sortValue === null) this.sortValue = this.defaultValue;
			return options;
		};

		switch (this.ordering) {
			case "boolean":
				return setOptions([
					{ value: "all", label: "All" },
					{ value: "true", label: "True" },
					{ value: "false", label: "False" },
				]);
			case "exists":
				return setOptions([
					{ value: "all", label: "All" },
					{ value: "with", label: "With" },
					{ value: "without", label: "Without" },
				]);
			case "numeric":
				return setOptions([
					{ value: "none", label: "None" },
					{ value: "asc", label: "Low → High" },
					{ value: "desc", label: "High → Low" },
				]);
			default:
				return setOptions([
					{ value: "none", label: "None" },
					{ value: "asc", label: "A → Z" },
					{ value: "desc", label: "Z → A" },
				]);
		}
	}

	createOptions(element) {
		for (const option of this.options) {
			element.appendChild(
				primitives.radio({
					name: this.column,
					value: option.value,
					label: option.label,
					kind: this.orchestrator.kind,
					checked: this.sortValue === option.value,
				}),
			);
		}

		element.addEventListener("change", (e) => {
			this.sortValue = e.target.value;
			this.sortedBy = this.sortBy(this.sortValue);
			if (!this.rowValues) this.init();
			if (this.reordering) {
				this.orchestrator.lastReorderColumn =
					this.sortedBy !== null ? this.column : null;
			}
			this.orchestrator.sort();
		});
	}

	restore(state) {
		if (!state?.value) return;
		if (!this.options.some((option) => option.value === state.value)) return;

		this.sortValue = state.value;
		this.sortedBy = this.sortBy(this.sortValue);
		if (!this.active) return;

		this.orchestrator.containers
			.get(this.column)
			?.querySelectorAll("input[type='radio']")
			.forEach((input) => {
				if (input.name === this.column) {
					input.checked = input.value === this.sortValue;
				}
			});
	}

	init() {
		if (this.initialized) return;

		this.rowValues = new WeakMap();
		this.orchestrator.rows.forEach((row) => {
			const cell = row.querySelector(
				`td[data-column="${this.column}"][data-sort-value]`,
			);
			if (!cell) return;
			this.rowValues.set(row, JSON.parse(cell.dataset.sortValue));
		});
		this.initialized = true;
		return this;
	}

	sortBy(value) {
		switch (value) {
			case "none":
				return null;
			case "all":
				return null;
			case "asc":
				return 1;
			case "desc":
				return -1;
			case "true":
				return true;
			case "false":
				return false;
			case "with":
				return true;
			case "without":
				return false;
			default:
				return null;
		}
	}

	sort() {
		this.hiddenRows = new Set();

		const rows = this.orchestrator.rows;

		if (typeof this.sortedBy === "boolean") {
			rows.forEach((row) => {
				const data = this.rowValues.get(row);
				if ((data ?? false) === this.sortedBy) {
					row.dataset.visible = "true";
				} else {
					row.dataset.visible = "false";
					this.hiddenRows.add(row);
				}
			});
			this.sorted = true;
			return;
		}

		const [visible, hidden] = [[], []];
		this.orchestrator.rows.forEach((row) => {
			this.rowValues.get(row) ? visible.push(row) : hidden.push(row);
		});

		hidden.forEach((row) => {
			row.dataset.visible = "false";
			this.hiddenRows.add(row);
		});

		if (this.ordering === "numeric") {
			visible.sort((a, b) => {
				const aVal = this.rowValues.get(a);
				const bVal = this.rowValues.get(b);
				return (aVal - bVal) * this.sortedBy;
			});
		} else if (this.ordering === "lexical") {
			visible.sort((a, b) => {
				const aVal = this.rowValues.get(a);
				const bVal = this.rowValues.get(b);
				return aVal.localeCompare(bVal) * this.sortedBy;
			});
		}

		this.orchestrator.body.append(...visible);
		this.sorted = true;
	}

	clear() {
		this.initialized = false;
		this.sortedBy = null;
		this.hiddenRows = null;
		this.rowValues = null;
		this.sorted = false;
		this.sortValue = this.defaultValue;
	}
}

const OPTIONS = Symbol("options");

/**
 * @testable false
 * @covered-by src/script/widgets/tableSorting.mjs::TableSorting.sort
 * @reason private sort strategy exercised through the TableSorting orchestrator
 */
class CheckboxSort {
	constructor(orchestrator, column, ordering) {
		this.orchestrator = orchestrator;
		this.column = column;
		this.ordering = ordering;
		this.reordering = false;
		this.rowValues = null;
		this.hiddenRows = null;
		this.options = OPTIONS;
		this.sortedBy = null;
		this.sortValues = [];
		this.initialized = false;
		this.sorted = false;
	}

	get active() {
		return this.sortedBy != null;
	}

	get state() {
		return this.active ? { values: this.sortValues } : null;
	}

	get disabled() {
		if (this.options === OPTIONS) this.init();
		return this.options === null;
	}

	init() {
		if (this.initialized) return;

		this.rowValues = new WeakMap();
		const options = {};

		for (const row of this.orchestrator.body.querySelectorAll("tr")) {
			const cell = row.querySelector(
				`td[data-column="${this.column}"][data-sort-value]`,
			);
			if (!cell) continue;

			const parsed = JSON.parse(cell.dataset.sortValue);
			Object.assign(options, parsed);
			this.rowValues.set(row, Object.keys(parsed));
		}

		this.options = Object.keys(options).length ? options : null;

		this.initialized = true;
		return this;
	}

	createOptions(element) {
		if (this.options === null) return;

		Object.entries(this.options).forEach(([key, value]) => {
			element.appendChild(
				primitives.checkbox({
					name: key,
					kind: this.orchestrator.kind,
					label: value,
					checked: this.sortValues.includes(key),
				}),
			);
		});

		element.addEventListener("change", (e) => {
			this.sortValues = e.target.checked
				? [...this.sortValues, e.target.name]
				: this.sortValues.filter((value) => value !== e.target.name);
			this.sortedBy = this.sortValues.length ? this.sortValues : null;
			this.orchestrator.sort();
		});
	}

	restore(state) {
		if (this.options === null || !Array.isArray(state?.values)) return;

		this.sortValues = state.values.filter((value) => {
			return Object.hasOwn(this.options, value);
		});
		this.sortedBy = this.sortValues.length ? this.sortValues : null;
		if (!this.active) return;

		this.orchestrator.containers
			.get(this.column)
			?.querySelectorAll("input[type='checkbox']")
			.forEach((input) => {
				input.checked = this.sortValues.includes(input.name);
			});
	}

	sort() {
		const hiddenRows = new Set();

		this.orchestrator.rows.forEach((row) => {
			const values = this.rowValues.get(row) || [];
			if (values.some((value) => this.sortValues.includes(value))) {
				row.dataset.visible = "true";
			} else {
				row.dataset.visible = "false";
				hiddenRows.add(row);
			}
		});

		this.hiddenRows = hiddenRows;
		this.sorted = true;
	}

	clear() {
		this.sortedBy = null;
		this.sortValues = [];
		this.rowValues = null;
		this.hiddenRows = null;
		this.sorted = false;
		this.options = OPTIONS;
		this.initialized = false;
	}
}

export { TableSorting };
