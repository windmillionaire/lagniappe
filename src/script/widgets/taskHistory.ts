import {
	EmbeddedTable,
	type EmbeddedTableAttributes,
} from "../elements/base/baseTable.ts";

import type { ExpandedTableView } from "../elements/embeddedTable.ts";
import type { RequestResult } from "../types/api";

type TaskHistoryComponent = { name: string };
type TaskHistoryAttributes = EmbeddedTableAttributes<
	ExpandedTableView,
	TaskHistoryComponent
>;

export class TaskHistory extends EmbeddedTable<
	ExpandedTableView,
	TaskHistoryComponent
> {
	declare _updated: HTMLElement | null;

	constructor(attributes: TaskHistoryAttributes) {
		super(attributes);
		this._updated = null;
	}

	get table() {
		return this.target.querySelector("[data-role='table']");
	}

	async updated(response: RequestResult) {
		this._updated =
			(response.html || null)?.querySelector<HTMLElement>(
				"[data-role='completion-history']",
			) ?? null;
	}

	postreconcile() {
		if (!this._updated) return;

		this.visible = true;
		this.target.dataset.visible = "true";
		this.table?.replaceChildren(this._updated);
		this._updated.dataset.visible = "true";
		for (const table of this._updated.querySelectorAll("table")) {
			table.dataset.visible = "true";
			this.initVisibility(table, `columns-${this.component.name}-history`);
		}
		this._updated = null;
	}
}
