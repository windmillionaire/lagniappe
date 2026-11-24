import {
	EmbeddedTable,
	type EmbeddedTableAttributes,
} from "../elements/base/baseTable.ts";
import type { ExpandedTableView } from "../elements/embeddedTable.ts";
import { STYLES } from "../generated/styles.mjs";

type FilterResultsComponent = {
	widgets: { Filters: { filters: HTMLElement } };
};
type FilterResultsAttributes = EmbeddedTableAttributes<
	ExpandedTableView,
	FilterResultsComponent
>;

import type { RequestResult } from "../types/api";

export class FilterResults extends EmbeddedTable<
	ExpandedTableView,
	FilterResultsComponent
> {
	declare badges: HTMLElement | null;
	declare table: HTMLTableElement | null;
	declare tableContainer: HTMLElement | null;
	declare container: HTMLElement | null;
	declare filtering?: string;

	constructor(attributes: FilterResultsAttributes) {
		super(attributes);
		this.badges = null;
		this.table = null;
		this.tableContainer = null;
		this.container = null;
		this.filtering = this.target.dataset.kind;
	}

	async updated(response: RequestResult) {
		const html = response.html;
		if (!html) return;
		this.table =
			html.querySelector<HTMLTableElement>("#embedded-table") ||
			html.querySelector("table");
		if (this.filtering === "page") {
			this.badges = this.component.widgets.Filters.filters.cloneNode(
				true,
			) as HTMLElement;
		}
	}

	get tbody() {
		return this.table?.querySelector("tbody");
	}

	get rows() {
		return this.tbody?.querySelectorAll("tr:not([data-role='empty'])");
	}

	get empty() {
		return this.tbody?.querySelector("tr[data-role='empty']");
	}

	postreconcile() {
		if (!this.table || this.target.contains(this.table)) return;

		this.container = document.createElement("div");
		this.container.dataset.role = "results-table";
		this.container.className = STYLES.table.container;
		this.tableContainer = document.createElement("div");
		this.tableContainer.className = "table-container px-4";
		this.tableContainer.dataset.role = "table";
		this.tableContainer.dataset.embedded = "true";
		this.tableContainer.appendChild(this.table);
		this.container.appendChild(this.tableContainer);
		this.table.dataset.visible = "true";
		this.initVisibility(this.table);
		if (this.filtering === "page" && this.badges) {
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
