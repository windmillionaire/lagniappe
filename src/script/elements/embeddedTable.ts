import { STYLES } from "../generated/styles.mjs";
import { ENDPOINTS } from "../shared/endpoints.ts";
import { setIcon } from "../shared/icons.ts";
import { request } from "../shared/request.ts";
import { withTransition } from "../shared/transitions.ts";
import type { ElementSchema } from "./base/baseElement.ts";
import { primitives } from "./primitives.ts";
import { TableElement } from "./table.ts";

interface EmbeddedTableColumn {
	field: string;
	title?: string;
	selected?: boolean;
}

function isEmbeddedColumn(value: unknown): value is EmbeddedTableColumn {
	return Boolean(
		value &&
			typeof value === "object" &&
			"field" in value &&
			typeof value.field === "string" &&
			(!("title" in value) || typeof value.title === "string") &&
			(!("selected" in value) || typeof value.selected === "boolean"),
	);
}

export class EmbeddedTableVisibility {
	declare tableElt: HTMLTableElement;
	declare columns: EmbeddedTableColumn[];
	declare storageKey: string | null;
	declare selected: string[];
	declare visibilityRow: HTMLTableRowElement | null;
	declare header: HTMLTableRowElement | null;
	declare actions: HTMLDivElement | null;
	declare toggle: HTMLButtonElement | null;

	constructor(tableElt: HTMLTableElement, storageKey: string | null = null) {
		const preload: unknown = JSON.parse(tableElt.dataset.preload ?? "{}");
		this.tableElt = tableElt;
		this.columns =
			preload &&
			typeof preload === "object" &&
			"columns" in preload &&
			Array.isArray(preload.columns)
				? preload.columns.filter(isEmbeddedColumn)
				: [];
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
		this.header?.addEventListener("click", this._headerClick);

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
			const selected: unknown = JSON.parse(saved);
			if (!Array.isArray(selected)) return defaults;

			const available = new Set(this.columns.map((column) => column.field));
			return [...new Set(selected)].filter(
				(field): field is string =>
					typeof field === "string" && available.has(field),
			);
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
		if (!this.header) return;
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
		this.toggle.dataset.kind = "default";
		this.toggle.setAttribute("aria-label", "Choose visible columns");
		this.toggle.setAttribute("aria-expanded", "false");
		this.toggle.title = "Choose visible columns";

		const icon = this.toggle.appendChild(document.createElement("span"));
		setIcon(icon, "column", STYLES.table.thead.actionIcon);
	}

	_headerClick(e: MouseEvent) {
		if (
			!(e.target instanceof Element) ||
			!e.target.closest("[data-role='embedded-table-visibility']")
		)
			return;

		e.preventDefault();
		e.stopPropagation();
		this._toggleController();
	}

	_toggleController() {
		const visible = this.visibilityRow?.dataset.visible === "true";
		return this._setControllerVisible(!visible);
	}

	_setControllerVisible(visible: boolean) {
		if (this.visibilityRow)
			this.visibilityRow.dataset.visible = visible ? "true" : "false";
		this.toggle?.setAttribute("aria-expanded", visible ? "true" : "false");
		return visible;
	}

	_createController() {
		if (!this.visibilityRow || !this.header) return;
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
			if (
				!(e.target instanceof HTMLInputElement) ||
				e.target.type !== "checkbox"
			)
				return;

			const [column, visible] = [e.target.name, e.target.checked];

			this.selected = visible
				? [...new Set([...this.selected, column])]
				: this.selected.filter((field) => field !== column);
			this._saveSelected();

			this._setColumnVisibility(column, visible);
		});
	}

	_setColumnVisibility(column: string, visible: boolean) {
		const display = visible ? "table-cell" : "none";

		this.tableElt
			.querySelectorAll<HTMLElement>(`[data-column="${column}"]`)
			.forEach((col) => {
				col.style.display = display;
			});
	}
}

export interface ExpandedTableView {
	mobile?: boolean;
}

export interface ExpandedTableButton extends HTMLButtonElement {
	_embeddedTable?: ExpandedTableCell | null;
}

interface ExpandedTableResponse {
	kind: string;
	submission: unknown;
	schema: ElementSchema;
}

export class ExpandedTableCell {
	declare view: ExpandedTableView;
	declare button: ExpandedTableButton;
	declare row: HTMLTableRowElement | null;
	declare table: HTMLDivElement | null;
	declare mobileQuery: MediaQueryList;
	declare kind: string | null;
	declare submission: unknown;
	declare schema: ElementSchema | null;

	constructor(view: ExpandedTableView, button: ExpandedTableButton) {
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
		const key = row?.dataset.key;
		const tableId =
			this.button.closest<HTMLElement>("[data-column]")?.dataset.column;
		if (!row || !key || !tableId) return;
		const colSpan = Array.from(row.querySelectorAll("td")).length;

		this.row = document.createElement("tr");
		this.row.dataset.embedded = "true";
		this.row.dataset.column = tableId;
		this.row.dataset.visible = "false";
		this.row.className =
			"rounded-md border border-base-light/50 mx-4 mb-3 overflow-hidden sm:rounded-none sm:border-t sm:border-b sm:border-x-0 sm:mx-0 sm:mb-0";
		row.after(this.row);

		const tableEmbed = this.row.appendChild(document.createElement("td"));
		tableEmbed.colSpan = colSpan;

		if (!this.kind || !this.submission || !this.schema) {
			const response = await request.get<ExpandedTableResponse>(
				ENDPOINTS.renderer.expandTableCell(key, tableId),
			);
			if (!response?.ok) return;
			this.kind = response.kind || "form";
			this.submission = response.submission;
			this.schema = response.schema ?? null;
		}
		if (!this.schema) return;

		this.table = new TableElement(
			{ readonly: true },
			this.schema,
			this.submission,
		).embedded;
		this.table.dataset.embedded = "true";
		this.table.querySelectorAll<HTMLElement>("tr, th, table").forEach((tr) => {
			tr.dataset.embedded = "true";
		});
		this.table.querySelector("tbody")?.classList.add(`bg-${this.kind}-bg`);

		tableEmbed.appendChild(this.table);

		this.mobileQuery.addEventListener("change", this.destroy);
	}

	get visible() {
		return this.row?.dataset.visible === "true";
	}

	async toggle(hide = false) {
		if (!this.table) await this.create();
		await withTransition(
			() => {
				if (!this.row) return;
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
		this.row?.remove();
		this.row = null;
		this.table = null;
		this.button.dataset.open = "false";
		this.button.setAttribute("aria-expanded", "false");
		this.button._embeddedTable = null;
		this.mobileQuery.removeEventListener("change", this.destroy);
	}
}
