/**
 * Lightweight persisted column-state owner. It applies visibility CSS before
 * an index table is shown; the checkbox controller remains in the lazy
 * TableVisibility widget.
 *
 */
export class TableVisibilityState {
	declare component: VisibilityComponent;
	declare view: VisibilityView;
	declare selected: string[];
	declare columns: TableColumn[];
	declare columnIndexes: Map<string, number>;
	declare hiddenColumns: number[];
	declare temporaryVisible: Set<number>;
	declare stylesheet: CSSStyleSheet | null;
	declare initialized: boolean;

	constructor({
		component,
		view,
		selected = [],
		columns = [],
	}: TableVisibilityStateOptions) {
		this.component = component;
		this.view = view;
		this.selected = selected;
		this.columns = columns;
		this.columnIndexes = new Map();
		this.hiddenColumns = [];
		this.temporaryVisible = new Set();
		this.stylesheet = null;
		this.initialized = false;
		this._toggle = this._toggle.bind(this);
	}

	init() {
		if (this.initialized) return this;
		this.initialized = true;
		this.component.elt
			.querySelectorAll<HTMLTableCellElement>("th[data-column]")
			.forEach((th, i) => {
				if (th.dataset.column !== undefined)
					this.columnIndexes.set(th.dataset.column, i + 1);
			});

		const saved = localStorage.getItem(`columns-${this.view.hash}`);
		try {
			const parsed: unknown = saved ? JSON.parse(saved) : null;
			this.hiddenColumns =
				Array.isArray(parsed) &&
				parsed.every((index) => typeof index === "number")
					? parsed
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
				return (
					index !== undefined &&
					(!this.hiddenColumns.includes(index) ||
						this.temporaryVisible.has(index))
				);
			});
	}

	defaultHiddenColumns() {
		const hidden = this.selected.length
			? this.columns.filter((column) => !this.selected.includes(column.field))
			: this.columns.filter((column) => column.selected !== true);
		return hidden
			.map((column) => this.columnIndexes.get(column.field))
			.filter((index) => index !== undefined);
	}

	_toggle(event: Event) {
		if (!("detail" in event)) return;
		const { detail } = event;
		if (
			detail &&
			typeof detail === "object" &&
			"active" in detail &&
			typeof detail.active === "boolean" &&
			"column" in detail &&
			typeof detail.column === "string"
		) {
			this.toggle(detail.column, detail.active);
		}
	}

	toggle(column: string | undefined, visible: boolean) {
		if (column === undefined) return;
		const index = this.columnIndexes.get(column);
		if (!index) return;
		this.temporaryVisible.delete(index);
		this.hiddenColumns = visible
			? this.hiddenColumns.filter((value) => value !== index)
			: [...new Set([...this.hiddenColumns, index])];
		this.apply();
		void this.component.widgets.TableEditor?.refreshCheckboxes?.();
	}

	setTemporaryVisible(column: string | undefined, visible: boolean) {
		if (column === undefined) return false;
		const index = this.columnIndexes.get(column);
		if (!index) return false;
		if (visible) {
			if (
				!this.hiddenColumns.includes(index) ||
				this.temporaryVisible.has(index)
			) {
				return false;
			}
			this.temporaryVisible.add(index);
		} else {
			if (!this.temporaryVisible.has(index)) return false;
			this.temporaryVisible.delete(index);
		}
		this.apply({ persist: false });
		this.component.widgets.TableVisibility?.syncCheckboxes?.();
		return true;
	}

	apply({ persist = true } = {}) {
		if (persist) {
			localStorage.setItem(
				`columns-${this.view.hash}`,
				JSON.stringify(this.hiddenColumns),
			);
		}
		if (!this.stylesheet) {
			// CSSOM keeps dynamic rules compatible with a CSP that blocks <style>.
			this.stylesheet = new CSSStyleSheet();
			document.adoptedStyleSheets.push(this.stylesheet);
		}

		const id = this.component.elt.id;
		const rowSelector = `#${id} tr:not([data-widget], [data-embedded], [data-role="empty"], [data-role="loading"]) > td:not([data-column="delete"])`;
		const thSelector = `#${id} th:not([data-column="selector"], [data-embedded])`;
		const effectiveHidden = this.hiddenColumns.filter(
			(index) => !this.temporaryVisible.has(index),
		);
		this.stylesheet.replaceSync(
			effectiveHidden
				.map(
					(index) =>
						`${rowSelector}:nth-child(${index}), ${thSelector}:nth-child(${index}) { display: none; }`,
				)
				.join("\n"),
		);
	}

	destroy() {
		this.view?.elt?.removeEventListener(
			"toggle-column-visibility",
			this._toggle,
		);
		document.adoptedStyleSheets = document.adoptedStyleSheets.filter(
			(sheet) => sheet !== this.stylesheet,
		);
		this.stylesheet = null;
		this.initialized = false;
	}
}

import type { LoadedWidget } from "../../types/widgets.d.ts";
import type { TableWidgets } from "./types.d.ts";

export interface TableColumn {
	field: string;
	title?: string;
	selected?: boolean;
}

export interface TableVisibilityToggle {
	column?: string;
	active: boolean;
}

interface VisibilityView {
	elt: HTMLElement;
	hash?: string;
}

interface VisibilityComponent {
	elt: HTMLElement;
	widgets: Record<string, LoadedWidget> & TableWidgets;
}

interface TableVisibilityStateOptions {
	component: VisibilityComponent;
	view: VisibilityView;
	selected?: string[];
	columns?: TableColumn[];
}
