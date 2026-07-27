import { STYLES } from "styles";
import { primitives } from "../elements/primitives";
import { ENDPOINTS, request, withTransition } from "../shared";
import { setIcon } from "../shared/icons";
import { TableElement } from "./table";

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006f_task_history.py::test_task_history_visibility_persists_after_reload
 * @pairs tasks:history
 * @pairs table-controls:column-visibility table-controls:persistence
 */
export class EmbeddedTableVisibility {
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
export class ExpandedTableCell {
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

	toggle(hide = false) {
		withTransition(async () => {
			if (!this.table) await this.create();
			const visible = hide ? true : this.visible;
			this.row.dataset.visible = visible ? "false" : "true";
			if (this.view.mobile && this.row.closest("[data-widget='IndexTable']")) {
				this.row.style.display = visible ? "none" : "block";
			}
			this.button.dataset.open = visible ? "false" : "true";
			this.button.setAttribute("aria-expanded", visible ? "false" : "true");
		});
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
