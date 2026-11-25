import { primitives } from "../../elements/primitives.ts";
import { sessionStore } from "../../shared/storage.ts";
import { withTransition } from "../../shared/transitions.ts";
import type { LoadedWidget } from "../../types/widgets.d.ts";
import type ViewComponent from "../../views/base/component.ts";

type Row = HTMLTableRowElement;
type Sort = RadioSort | CheckboxSort;
type SortContainer = HTMLTableCellElement | HTMLDivElement;
type SortState = { value?: unknown; values?: unknown };

interface SavedSortState {
	lastReorderColumn?: string | null;
	sorts?: Record<string, SortState | null>;
}

interface TableSortingAttributes {
	view: { elt: HTMLElement; hash?: string; mobile?: boolean };
	component: ViewComponent;
	target: HTMLElement;
	kind?: string;
	visible?: boolean;
	modified?: boolean;
}

export class TableSorting {
	declare view: TableSortingAttributes["view"];
	declare component: ViewComponent;
	declare target: HTMLElement;
	declare kind?: string;
	declare visible?: boolean;
	declare modified?: boolean;
	declare name: LoadedWidget["name"];
	declare enable: LoadedWidget["enable"];
	declare disable: LoadedWidget["disable"];
	declare prepareReconcile: LoadedWidget["prepareReconcile"];
	declare reconcile: LoadedWidget["reconcile"];
	declare columns: unknown[];
	declare sorts: Map<string, Sort>;
	declare containers: Map<string, SortContainer>;
	declare toggles: Map<string, HTMLButtonElement>;
	declare headers: Map<string, HTMLTableCellElement>;
	declare lastReorderColumn: string | null;
	declare initialized: boolean;
	declare _destroyed: boolean;
	declare _onFilterToggle: (event: Event) => void;

	constructor(attributes: TableSortingAttributes) {
		Object.assign(this, attributes);
		const columns = this.component.preload("columns");
		this.columns = Array.isArray(columns) ? columns : [];
		this.sorts = new Map();
		this.containers = new Map();
		this.toggles = new Map();
		this.headers = new Map();
		this.lastReorderColumn = null;
		this.initialized = false;
		this._destroyed = false;
		this._onFilterToggle = this._filterToggle.bind(this);
	}

	get storageKey() {
		return `sorts-${this.view.hash}`;
	}

	get header() {
		return this.component.elt.querySelector<HTMLTableRowElement>(
			"thead > tr:first-child",
		);
	}

	get body() {
		return this.component.elt.querySelector("tbody");
	}

	get rows() {
		return Array.from(this.body?.querySelectorAll("tr") ?? []).filter(
			(row) =>
				row.dataset.visible !== "false" && row.dataset.role !== "loading",
		);
	}

	init() {
		if (this._destroyed || this.initialized) return;
		this.initialized = true;

		this._setSortingToggles();
		const saved = this._loadState();

		this.header
			?.querySelectorAll<HTMLTableCellElement>("th[data-ordering]")
			.forEach((th) => {
				const column = th.dataset.column;
				const ordering = th.dataset.ordering;
				if (!column || !ordering) return;
				this.headers.set(column, th);

				const sort = this._enableSort(this._createSort(column, ordering));
				sort.restore(saved?.sorts?.[column]);
			});

		this._restoreLastReorderColumn(saved);
		if (this._hasActiveSorts()) this.sort();

		this.view.elt.addEventListener(
			"toggle-column-filter",
			this._onFilterToggle,
		);
	}

	_filterToggle(e: Event) {
		if (this._destroyed || !("detail" in e)) return;
		const { detail } = e;
		if (
			!detail ||
			typeof detail !== "object" ||
			!("column" in detail) ||
			typeof detail.column !== "string"
		)
			return;
		const { column } = detail;
		if (this.view.mobile) {
			void withTransition(
				() => {
					if (this._destroyed) return;
					const current = this.sorts.get(column);
					if (!current) return;
					const sort = this._enableSort(current);
					if (sort.active) {
						const toggle = this.toggles.get(column);
						if (toggle) toggle.dataset.active = "true";
					}
					const container = this.containers.get(column);
					if (!container) return;
					const visible = container.dataset.visible === "true";
					container.dataset.visible = visible ? "false" : "true";
				},
				{ label: "table-sorting:toggle-mobile" },
			);
		} else {
			void this._toggleColumn(
				column,
				"button" in detail && detail.button instanceof HTMLElement
					? detail.button
					: null,
			);
		}
	}

	reset() {
		if (this._destroyed) return;
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
		this.header
			?.querySelectorAll<HTMLTableCellElement>("th[data-ordering]")
			.forEach((th) => {
				const column = th.dataset.column;
				const ordering = th.dataset.ordering;
				if (!column || !ordering) return;
				this.headers.set(column, th);
				th.dataset.sorting = "false";
				this._enableSort(this._createSort(column, ordering));
			});
	}

	/**
	 * Rebuild row-value caches after server row replacement while preserving active sorts.
	 *
	 */
	refreshRows() {
		if (this._destroyed || !this.initialized) return;

		const saved = {
			lastReorderColumn: this.lastReorderColumn,
			sorts: Object.fromEntries(
				Array.from(this.sorts, ([column, sort]): [string, SortState | null] => [
					column,
					sort.state,
				]),
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

		this.header
			?.querySelectorAll<HTMLTableCellElement>("th[data-ordering]")
			.forEach((th) => {
				const column = th.dataset.column;
				const ordering = th.dataset.ordering;
				if (!column || !ordering) return;
				this.headers.set(column, th);
				th.dataset.sorting = "false";
				const sort = this._enableSort(this._createSort(column, ordering));
				sort.restore(saved.sorts[column]);
			});

		this._restoreLastReorderColumn(saved);
		if (this._hasActiveSorts()) this.sort();
	}

	_loadState(): SavedSortState | null {
		const saved = sessionStore.getJSON(this.storageKey);
		if (saved === null) return null;
		if (typeof saved === "object" && saved !== null && !Array.isArray(saved))
			return saved;
		sessionStore.remove(this.storageKey);
		return null;
	}

	_saveState() {
		const sorts: Record<string, SortState> = {};

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

	_restoreLastReorderColumn(saved: SavedSortState | null) {
		const savedSort = saved?.lastReorderColumn
			? this.sorts.get(saved.lastReorderColumn)
			: undefined;
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

	_markSortActive(sort: Sort) {
		const header = this.headers.get(sort.column);
		if (header) header.dataset.sorting = "true";
		if (!this.view.mobile) return;

		const toggle = this.toggles.get(sort.column);
		if (toggle) toggle.dataset.active = "true";
	}

	_setSortingToggles() {
		const container = this.view.mobile
			? document.getElementById("mobile-controls")
			: this.header;

		container
			?.querySelectorAll<HTMLButtonElement>("button[data-toggle='filter']")
			.forEach((button) => {
				const column =
					button.closest<HTMLElement>("[data-column]")?.dataset.column;
				if (column) this.toggles.set(column, button);
			});
	}

	async _toggleColumn(column: string, button: HTMLElement | null) {
		await withTransition(
			() => {
				if (this._destroyed) return;
				const current = this.sorts.get(column);
				if (!current) return;
				const sort = this._enableSort(current);
				if (sort.disabled) return;

				const visible = this.visible;
				const container = this.containers.get(column);
				if (!container) return;
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

	_resetRows(reorderRows: boolean, showRows: Set<Row>) {
		if (!reorderRows && showRows.size === 0) return null;
		const initialOrder = reorderRows ? new WeakMap<Row, number>() : null;

		this.body?.querySelectorAll("tr").forEach((row) => {
			if (showRows.has(row)) {
				row.dataset.visible = "true";
			}
			if (!initialOrder) return;

			const modifiedColumn = Number(
				row.querySelector<HTMLTableCellElement>(`td[data-column="modified"]`)
					?.dataset.sortValue || 0,
			);
			initialOrder.set(row, modifiedColumn * -1);
		});

		return initialOrder;
	}

	sort() {
		if (this._destroyed) return;
		let reorderRows = false;
		const showRows = new Set<Row>();

		// clear inactive sorts, track rows hidden by inactive sorts
		this.sorts.forEach((sort) => {
			if (sort.reordering && this.lastReorderColumn !== sort.column) {
				// deactivate previous reordering sort
				sort.sortedBy = null;
			}

			if (sort.active || !sort.sorted) return;

			for (const row of sort.hiddenRows ?? []) showRows.add(row);

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
		const reorderingSort =
			this.lastReorderColumn === null
				? undefined
				: this.sorts.get(this.lastReorderColumn);
		if (reorderingSort?.active) {
			reorderingSort.sort();
			this._markSortActive(reorderingSort);
		} else if (initialOrder) {
			const rows = this.rows;
			rows.sort((a, b) => {
				return (initialOrder.get(a) ?? 0) - (initialOrder.get(b) ?? 0);
			});
			this.body?.append(...rows);
			this.lastReorderColumn = null;
		}

		this._saveState();
	}

	_createContainer(column: string) {
		const container = this.view.mobile
			? this._createSection(column)
			: this._createCell(column);
		this.containers.set(column, container);
		return container;
	}

	_createCell(column: string) {
		const cell = document.createElement("td");
		cell.colSpan = this.component.elt.querySelectorAll("th").length;
		cell.className = `p-3 border-t bg-kind-bg border-slate-300`;
		cell.dataset.sorts = column;
		cell.dataset.visible = "false";
		this.target.appendChild(cell);
		return cell;
	}

	_createSection(column: string) {
		const section = document.createElement("div");
		section.className = `flex flex-col gap-2 p-4 bg-white outline-kind-default rounded-md outline-1`;
		section.dataset.sorts = column;
		section.dataset.visible = "false";
		const controls = document.getElementById("mobile-controls");
		controls?.querySelector(`[data-column="${column}"]`)?.after(section);
		return section;
	}

	_createCheckboxElement(sort: CheckboxSort) {
		const container = this.containers.get(sort.column);
		if (!container) return;
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

	_createRadioElement(sort: RadioSort) {
		const container = this.containers.get(sort.column);
		if (!container) return;
		const element = container.appendChild(document.createElement("fieldset"));
		element.className = `flex flex-row flex-wrap gap-4`;
		sort.createOptions(element);
	}

	_createSortElement(sort: Sort) {
		if (sort instanceof CheckboxSort) {
			this._createCheckboxElement(sort);
		} else {
			this._createRadioElement(sort);
		}
	}

	_enableSort(sort: Sort) {
		sort.init();

		const toggle = this.toggles.get(sort.column);
		if (toggle) toggle.dataset.visible = sort.disabled ? "false" : "true";
		if (sort.disabled) return sort;

		const container =
			this.containers.get(sort.column) ?? this._createContainer(sort.column);

		if (!container.children.length) {
			this._createSortElement(sort);
		}

		return sort;
	}

	_resetSort(sort: Sort) {
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

	_createSort(column: string, ordering: string) {
		const sort =
			ordering === "categorical"
				? new CheckboxSort(this, column)
				: new RadioSort(this, column, ordering);
		this.sorts.set(column, sort);
		return sort;
	}

	destroy() {
		if (this._destroyed) return;
		this._destroyed = true;
		this.initialized = false;
		this.visible = false;
		this.view.elt.removeEventListener(
			"toggle-column-filter",
			this._onFilterToggle,
		);
		for (const container of this.containers.values()) container.remove();
		this.containers.clear();
		this.sorts.clear();
		this.toggles.clear();
		this.headers.clear();
		this.lastReorderColumn = null;
	}
}

class RadioSort {
	declare orchestrator: TableSorting;
	declare column: string;
	declare ordering: string;
	declare reordering: boolean;
	declare rowValues: WeakMap<Row, unknown> | null;
	declare hiddenRows: Set<Row> | null;
	declare sortedBy: number | boolean | null;
	declare sortValue: string | null;
	declare initialized: boolean;
	declare sorted: boolean;

	constructor(orchestrator: TableSorting, column: string, ordering: string) {
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

	get options() {
		const setOptions = (options: { value: string; label: string }[]) => {
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

	createOptions(element: HTMLElement) {
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
			if (!(e.target instanceof HTMLInputElement)) return;
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

	restore(state?: SortState | null) {
		if (typeof state?.value !== "string" || !state.value) return;
		if (!this.options.some((option) => option.value === state.value)) return;

		this.sortValue = state.value;
		this.sortedBy = this.sortBy(this.sortValue);
		if (!this.active) return;

		this.orchestrator.containers
			.get(this.column)
			?.querySelectorAll<HTMLInputElement>("input[type='radio']")
			.forEach((input) => {
				if (input.name === this.column) {
					input.checked = input.value === this.sortValue;
				}
			});
	}

	init() {
		if (this.initialized) return;

		const rowValues = new WeakMap<Row, unknown>();
		this.rowValues = rowValues;
		this.orchestrator.rows.forEach((row) => {
			const cell = row.querySelector<HTMLTableCellElement>(
				`td[data-column="${this.column}"][data-sort-value]`,
			);
			if (cell?.dataset.sortValue === undefined) return;
			rowValues.set(row, JSON.parse(cell.dataset.sortValue));
		});
		this.initialized = true;
		return this;
	}

	sortBy(value: string) {
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
		const { rowValues, sortedBy } = this;
		if (!rowValues || sortedBy === null) return;
		const hiddenRows = new Set<Row>();
		this.hiddenRows = hiddenRows;

		const rows = this.orchestrator.rows;

		if (typeof sortedBy === "boolean") {
			rows.forEach((row) => {
				const data = rowValues.get(row);
				if ((data ?? false) === sortedBy) {
					row.dataset.visible = "true";
				} else {
					row.dataset.visible = "false";
					hiddenRows.add(row);
				}
			});
			this.sorted = true;
			return;
		}

		const visible: Row[] = [];
		const hidden: Row[] = [];
		this.orchestrator.rows.forEach((row) => {
			const value = rowValues.get(row);
			if (value) visible.push(row);
			else hidden.push(row);
		});

		hidden.forEach((row) => {
			row.dataset.visible = "false";
			hiddenRows.add(row);
		});

		if (this.ordering === "numeric") {
			visible.sort((a, b) => {
				const aVal = rowValues.get(a);
				const bVal = rowValues.get(b);
				return (Number(aVal) - Number(bVal)) * sortedBy;
			});
		} else if (this.ordering === "lexical") {
			visible.sort((a, b) => {
				const aVal = rowValues.get(a);
				const bVal = rowValues.get(b);
				return String(aVal).localeCompare(String(bVal)) * sortedBy;
			});
		}

		this.orchestrator.body?.append(...visible);
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

class CheckboxSort {
	declare orchestrator: TableSorting;
	declare column: string;
	declare ordering: "categorical";
	declare reordering: false;
	declare rowValues: WeakMap<Row, string[]> | null;
	declare hiddenRows: Set<Row> | null;
	declare options: Record<string, string> | typeof OPTIONS | null;
	declare sortedBy: string[] | null;
	declare sortValues: string[];
	declare initialized: boolean;
	declare sorted: boolean;

	constructor(orchestrator: TableSorting, column: string) {
		this.orchestrator = orchestrator;
		this.column = column;
		this.ordering = "categorical";
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

		this.rowValues = new WeakMap<Row, string[]>();
		const options: Record<string, string> = {};

		for (const row of this.orchestrator.body?.querySelectorAll("tr") ?? []) {
			const cell = row.querySelector<HTMLTableCellElement>(
				`td[data-column="${this.column}"][data-sort-value]`,
			);
			if (cell?.dataset.sortValue === undefined) continue;

			const parsed: unknown = JSON.parse(cell.dataset.sortValue);
			if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
				continue;
			for (const [key, label] of Object.entries(parsed))
				options[key] = String(label);
			this.rowValues.set(row, Object.keys(parsed));
		}

		this.options = Object.keys(options).length ? options : null;

		this.initialized = true;
		return this;
	}

	createOptions(element: HTMLElement) {
		if (this.options === null || this.options === OPTIONS) return;

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
			if (!(e.target instanceof HTMLInputElement)) return;
			const { checked, name } = e.target;
			this.sortValues = checked
				? [...this.sortValues, name]
				: this.sortValues.filter((value) => value !== name);
			this.sortedBy = this.sortValues.length ? this.sortValues : null;
			this.orchestrator.sort();
		});
	}

	restore(state?: SortState | null) {
		const { options } = this;
		if (
			options === null ||
			options === OPTIONS ||
			!Array.isArray(state?.values)
		)
			return;

		this.sortValues = state.values.filter((value) => {
			return typeof value === "string" && Object.hasOwn(options, value);
		});
		this.sortedBy = this.sortValues.length ? this.sortValues : null;
		if (!this.active) return;

		this.orchestrator.containers
			.get(this.column)
			?.querySelectorAll<HTMLInputElement>("input[type='checkbox']")
			.forEach((input) => {
				input.checked = this.sortValues.includes(input.name);
			});
	}

	sort() {
		const hiddenRows = new Set<Row>();

		this.orchestrator.rows.forEach((row) => {
			const values = this.rowValues?.get(row) || [];
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
