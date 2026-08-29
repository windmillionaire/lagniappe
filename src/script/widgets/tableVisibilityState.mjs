/**
 * Lightweight persisted column-state owner. It applies visibility CSS before
 * an index table is shown; the checkbox controller remains in the lazy
 * TableVisibility widget.
 *
 * @testable true
 * @tests tests_js/test_038_startup_specializations.py::test_column_visibility_state_applies_before_lazy_panel
 * @tests tests_e2e/007_categories/test_007c_category_visibility_and_sorting.py::test_column_visibility_persists_after_reload
 * @matrix table-controls : column-visibility eager-column-state lazy-checkbox-panel persistence
 */
export class TableVisibilityState {
	constructor({ component, view, selected = [], columns = [] }) {
		this.component = component;
		this.view = view;
		this.selected = selected;
		this.columns = columns;
		this.columnIndexes = new Map();
		this.hiddenColumns = [];
		this.stylesheet = null;
		this.initialized = false;
		this._toggle = this._toggle.bind(this);
	}

	init() {
		if (this.initialized) return this;
		this.initialized = true;
		this.component.elt.querySelectorAll("th[data-column]").forEach((th, i) => {
			this.columnIndexes.set(th.dataset.column, i + 1);
		});

		const saved = localStorage.getItem(`columns-${this.view.hash}`);
		try {
			this.hiddenColumns = saved
				? JSON.parse(saved)
				: this.defaultHiddenColumns();
		} catch {
			this.hiddenColumns = this.defaultHiddenColumns();
		}
		this.apply();
		this.view.elt.addEventListener("toggle-column-visibility", this._toggle);
		return this;
	}

	get visibleColumns() {
		return this.columns
			.map((column) => column.field)
			.filter((field) => {
				const index = this.columnIndexes.get(field);
				return index && !this.hiddenColumns.includes(index);
			});
	}

	defaultHiddenColumns() {
		const hidden = this.selected.length
			? this.columns.filter((column) => !this.selected.includes(column.field))
			: this.columns.filter((column) => column.selected !== true);
		return hidden
			.map((column) => this.columnIndexes.get(column.field))
			.filter(Boolean);
	}

	_toggle(event) {
		this.toggle(event.detail.column, event.detail.active);
	}

	toggle(column, visible) {
		const index = this.columnIndexes.get(column);
		if (!index) return;
		this.hiddenColumns = visible
			? this.hiddenColumns.filter((value) => value !== index)
			: [...new Set([...this.hiddenColumns, index])];
		this.apply();
		void this.component.widgets.TableEditor?.refreshCheckboxes?.();
	}

	apply() {
		localStorage.setItem(
			`columns-${this.view.hash}`,
			JSON.stringify(this.hiddenColumns),
		);
		if (!this.stylesheet) {
			this.stylesheet = document.createElement("style");
			this.stylesheet.id = `column-visibility-${this.view.hash}`;
			document.head.appendChild(this.stylesheet);
		}

		const id = this.component.elt.id;
		const rowSelector = `#${id} tr:not([data-widget], [data-embedded], [data-role="empty"]) > td:not([data-column="delete"])`;
		const thSelector = `#${id} th:not([data-column="selector"], [data-embedded])`;
		this.stylesheet.textContent = this.hiddenColumns
			.map(
				(index) =>
					`${rowSelector}:nth-child(${index}), ${thSelector}:nth-child(${index}) { display: none; }`,
			)
			.join("\n");
	}

	destroy() {
		this.view?.elt?.removeEventListener(
			"toggle-column-visibility",
			this._toggle,
		);
		this.stylesheet?.remove();
		this.stylesheet = null;
		this.initialized = false;
	}
}
