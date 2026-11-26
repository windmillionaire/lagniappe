import {
	BaseTable,
	type BaseTableAttributes,
	type TableComponent,
} from "../../elements/base/baseTable.ts";
import { captureError } from "../../shared/errors.ts";
import type { RequestResult } from "../../types/api.d.ts";
import type { TableWidgets } from "./types.d.ts";

interface IndexTableView {
	elt: HTMLElement;
	key?: string | null;
	mobile?: boolean;
	addFlash(row: HTMLElement): void;
	clearTableLoading?(): void;
}

interface IndexTableComponent extends TableComponent {
	name: string;
	widgets: TableWidgets;
	loadWidget(
		name: "TableSorting",
	): Promise<{ init?(): void | Promise<void> } | null>;
	load(widget: unknown, route?: string | null): Promise<unknown>;
}

interface IndexTableDelta {
	remove?: string[];
	upsert?: { key: string; html?: string | null }[];
	order?: string[];
	empty?: string | null;
}

export class IndexTable extends BaseTable<IndexTableView, IndexTableComponent> {
	declare refreshScope: "collection";
	declare route?: string | null;
	declare loading: boolean;
	declare loaded: boolean;
	declare _empty: boolean;
	declare _updated: HTMLTableRowElement[];
	declare _created: HTMLTableRowElement[];
	declare _finishLoading?: boolean;
	declare _filtered: boolean;
	declare _completedSaves: Set<HTMLTableCellElement>;
	declare _completedTimers: Map<
		HTMLTableCellElement,
		ReturnType<typeof setTimeout>
	>;
	declare _onDirectCompletedChange: (event: Event) => void;

	constructor(
		attributes: BaseTableAttributes<IndexTableView, IndexTableComponent>,
	) {
		super(attributes);
		this.refreshScope = "collection";
		this.loading = false;
		this.loaded = !this.prefetched || this.target.hasAttribute("loaded");
		this._empty = false;
		this._updated = [];
		this._created = [];
		this._filtered = false;
		this._completedSaves = new Set();
		this._completedTimers = new Map();
		this._onDirectCompletedChange = (event) =>
			void this._handleCompletedToggle(event).catch(captureError);
		this.target.addEventListener("change", this._onDirectCompletedChange);
	}

	async _handleCompletedToggle(event: Event) {
		const input =
			event.target instanceof HTMLInputElement &&
			event.target.type === "checkbox"
				? event.target
				: null;
		if (!input) return;
		const toggle = input.closest("[data-role='task-complete-toggle']");
		const cell = input.closest<HTMLTableCellElement>(
			"td[data-column='completed'][data-editable='true']",
		);
		const row = cell?.closest<HTMLTableRowElement>("tr[data-key]");
		if (!toggle || !cell || !row || !this.target.contains(cell)) return;
		if (this._completedSaves.has(cell)) return;

		const key = row.dataset.key;
		if (!key) return;
		const checked = input.checked;

		this._completedSaves.add(cell);
		const prevTimer = this._completedTimers.get(cell);
		if (prevTimer !== undefined) {
			clearTimeout(prevTimer);
			this._completedTimers.delete(cell);
		}
		cell.querySelector("[data-role='quick-edit-error']")?.remove();
		cell.dataset.editState = "saving";
		cell.setAttribute("aria-busy", "true");
		input.disabled = true;

		try {
			const { request } = await import("../../shared/request.ts");
			const response = await request.patch(`/tasks/${key}/patch`, {
				schema_id: "completed",
				form_generation: cell.dataset.formGeneration || "0",
				value: checked,
			});
			if (!cell.isConnected || !this.target.contains(cell)) return;
			if (!response?.ok) {
				input.checked = !checked;
				cell.dataset.editState = "error";
				const error = document.createElement("p");
				error.dataset.role = "quick-edit-error";
				error.setAttribute("role", "alert");
				error.textContent =
					response?.error || "Could not update task completion.";
				cell.appendChild(error);
				return;
			}
			const serialized = JSON.stringify(checked);
			cell.dataset.editValue = serialized;
			cell.dataset.sortValue = serialized;
			const taskName =
				row.querySelector("td[data-column='name']")?.textContent?.trim() ||
				"task";
			input.setAttribute(
				"aria-label",
				`Mark ${taskName} ${checked ? "incomplete" : "complete"}`,
			);
			cell.dataset.editState = "saved";
			const timer = setTimeout(() => {
				if (this._completedTimers.get(cell) !== timer) return;
				this._completedTimers.delete(cell);
				if (cell.isConnected && cell.dataset.editState === "saved") {
					delete cell.dataset.editState;
				}
			}, 1200);
			this._completedTimers.set(cell, timer);
			this.sortingWidget?.refreshRows?.();
		} catch (error) {
			if (cell.isConnected && this.target.contains(cell)) {
				input.checked = !checked;
				cell.dataset.editState = "error";
				const message = document.createElement("p");
				message.dataset.role = "quick-edit-error";
				message.setAttribute("role", "alert");
				message.textContent = "Could not update task completion.";
				cell.appendChild(message);
			}
			captureError(error);
		} finally {
			this._completedSaves.delete(cell);
			if (cell.isConnected) {
				cell.removeAttribute("aria-busy");
				input.disabled = false;
			}
		}
	}

	async updated(response: RequestResult) {
		const html = response.html || null;
		const rows = html?.querySelectorAll<HTMLTableRowElement>("tr[lp-entity]");
		if (rows?.length) this._updated.push(...rows);
		const append = html?.querySelector<HTMLTableRowElement>("tr[lp-load]");
		this.loaded = !append;
		return append;
	}

	async created(response: RequestResult) {
		const rows = (response.html || null)?.querySelectorAll("tr");
		if (rows?.length) this._created.push(...rows);
	}

	get selector() {
		return this.component.elt.querySelector(
			"th[data-column='selector'] button",
		);
	}

	_clearLoadingState() {
		this.target.removeAttribute("aria-busy");
		for (const row of this.target.querySelectorAll("tr[data-role='loading']")) {
			row.remove();
		}
		this.view.clearTableLoading?.();
	}

	setEmptyRowVisibility() {
		this._clearLoadingState();
		const emptyRow = this.target.querySelector<HTMLTableRowElement>(
			"tr[data-role='empty']",
		);
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

	refreshDescriptor() {
		if (
			this._filtered ||
			this.component.name !== "table" ||
			!this.target.hasAttribute("loaded")
		) {
			return null;
		}
		const supported =
			Boolean(this.view.key) ||
			["forms", "tasks", "users"].includes(this.view.elt.dataset.index ?? "");
		if (!supported) return null;

		return {
			rows: Array.from(
				this.target.querySelectorAll<HTMLTableRowElement>("tr[lp-entity]"),
				(row) => ({
					key: row.dataset.key,
					hash: row.dataset.hash || "",
					fingerprint: row.dataset.fingerprint || "",
				}),
			),
		};
	}

	_parseRefreshRow(html: string | null | undefined) {
		if (!html) return null;
		const template = document.createElement("template");
		template.innerHTML = html.trim();
		return template.content.querySelector<HTMLTableRowElement>("tr[lp-entity]");
	}

	refreshDelta(delta: IndexTableDelta) {
		const editor = this.component?.widgets?.TableEditor;
		const existing = new Map(
			Array.from(
				this.target.querySelectorAll<HTMLTableRowElement>("tr[lp-entity]"),
				(row) => [row.dataset.key, row],
			),
		);
		editor?.releaseRows([
			...(delta.remove || []).map((key) => existing.get(key)),
			...(delta.upsert || []).map(({ key }) => existing.get(key)),
		]);
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
			if (current) {
				current.replaceWith(row);
			} else added.push(row);
			existing.set(update.key, row);
		}

		const order = Array.isArray(delta.order) ? delta.order : [];
		let next = this.target.querySelector("tr[lp-entity]");
		for (const key of order) {
			const row = existing.get(key);
			if (!row) throw new Error("Table refresh order references a missing row");
			if (row !== next) this.target.insertBefore(row, next);
			else {
				next = next.nextElementSibling;
				while (next && !next.matches("tr[lp-entity]")) {
					next = next.nextElementSibling;
				}
			}
		}
		for (const row of added) this.view.addFlash(row);

		let empty = this.target.querySelector("tr[data-role='empty']");
		if (!order.length && !empty && delta.empty) {
			const template = document.createElement("template");
			template.innerHTML = delta.empty.trim();
			empty = template.content.querySelector("tr[data-role='empty']");
			if (empty) this.target.append(empty);
		}

		this.setEmptyRowVisibility();
		this.sortingWidget?.refreshRows?.();
		void editor?.refreshCheckboxes().catch(captureError);
	}

	refresh(response: RequestResult | undefined) {
		if (!response?.html) return;
		const editor = this.component?.widgets?.TableEditor;
		const newRows = [
			...response.html.querySelectorAll<HTMLTableRowElement>("tr[lp-entity]"),
		];
		const newKeys = new Set(
			newRows.map((row) => row.dataset.key).filter(Boolean),
		);
		const prepend = [];
		editor?.releaseRows(
			Array.from(
				this.target.querySelectorAll<HTMLTableRowElement>("tr[lp-entity]"),
			).filter((row) => !this.prefetched || newKeys.has(row.dataset.key ?? "")),
		);

		for (const newRow of newRows) {
			const key = newRow.dataset.key;
			if (!key) continue;

			const existing = this.target.querySelector(`tr[data-key="${key}"]`);
			if (existing) {
				existing.replaceWith(newRow);
			} else prepend.push(newRow);
		}

		if (prepend.length) {
			const anchor = this.target.querySelector("tr[lp-entity]");
			if (anchor) anchor.before(...prepend);
			else this.target.append(...prepend);
			for (const row of prepend) this.view.addFlash(row);
		}

		if (!this.prefetched) {
			this.target
				.querySelectorAll<HTMLTableRowElement>("tr[lp-entity]")
				.forEach((row) => {
					if (!newKeys.has(row.dataset.key ?? "")) {
						row.remove();
					}
				});
		}

		this.setEmptyRowVisibility();
		this.sortingWidget?.refreshRows?.();
		void editor?.refreshCheckboxes().catch(captureError);
	}

	applyFilteredRows(html: Document): number {
		const editor = this.component?.widgets?.TableEditor;
		const currentRows = Array.from(
			this.target.querySelectorAll<HTMLTableRowElement>("tr[lp-entity]"),
		);
		editor?.releaseRows(currentRows);

		for (const row of this.target.querySelectorAll(
			"tr[lp-entity], tr[data-role='empty'], tr[lp-load]",
		)) {
			row.remove();
		}

		const incomingRows = Array.from(
			html.querySelectorAll<HTMLTableRowElement>("tr[lp-entity]"),
		);
		if (incomingRows.length) {
			this.target.append(...incomingRows);
		} else {
			const emptyRow = html.querySelector<HTMLTableRowElement>(
				"tr[data-role='empty']",
			);
			if (emptyRow) this.target.append(emptyRow);
		}

		this._filtered = true;
		this._updated = [];
		this.loading = false;
		this.loaded = true;
		this.target.setAttribute("loaded", "");
		this.setEmptyRowVisibility();
		this.sortingWidget?.refreshRows?.();
		void editor?.refreshCheckboxes().catch(captureError);
		return incomingRows.length;
	}

	async clearFilteredRows() {
		if (!this._filtered) return;
		this._filtered = false;

		const editor = this.component?.widgets?.TableEditor;
		const currentRows = Array.from(
			this.target.querySelectorAll<HTMLTableRowElement>("tr[lp-entity]"),
		);
		editor?.releaseRows(currentRows);

		for (const row of this.target.querySelectorAll(
			"tr[lp-entity], tr[data-role='empty'], tr[lp-load]",
		)) {
			row.remove();
		}

		this._updated = [];
		this.target.removeAttribute("loaded");
		this.loaded = false;
		this.loading = true;

		let route: string | null | undefined =
			this.route || this.target.dataset.route;
		if (!route) {
			this.loading = false;
			this.loaded = true;
			this.target.setAttribute("loaded", "");
			this.setEmptyRowVisibility();
			return;
		}

		const { request } = await import("../../shared/request.ts");
		while (route) {
			const response: RequestResult | undefined = await request.get(route);
			if (this._filtered || !this.target.isConnected) return;
			const html: Document | null =
				response?.html instanceof Document ? response.html : null;
			if (!html) break;

			const incomingRows = Array.from(
				html.querySelectorAll<HTMLTableRowElement>("tr[lp-entity]"),
			);
			if (incomingRows.length) {
				this.target.append(...incomingRows);
			} else if (!this.target.querySelector("tr[lp-entity]")) {
				const emptyRow = html.querySelector<HTMLTableRowElement>(
					"tr[data-role='empty']",
				);
				if (emptyRow) this.target.append(emptyRow);
			}

			const continuation: HTMLTableRowElement | null =
				html.querySelector<HTMLTableRowElement>("tr[lp-load]");
			route = continuation?.dataset.route || null;
		}

		if (this._filtered || !this.target.isConnected) return;
		this.loading = false;
		this.loaded = true;
		this.target.setAttribute("loaded", "");
		this.setEmptyRowVisibility();
		this.sortingWidget?.refreshRows?.();
		void editor?.refreshCheckboxes().catch(captureError);
	}

	async prereconcile() {
		const loaded = this.target.hasAttribute("loaded");
		if (!this.loaded || loaded) return;

		const sorting = await this.component.loadWidget("TableSorting");
		await sorting?.init?.();
		this._finishLoading = true;
	}

	postreconcile() {
		const target = this.target;
		let rowsChanged = false;
		const sortingWasInitialized = this.sortingWidget?.initialized === true;

		if (this._created.length > 0) {
			target.prepend(...this._created);
			for (const row of this._created) this.view.addFlash(row);
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

		let finishedLoading = false;
		if (this._finishLoading) {
			this._finishLoading = false;
			finishedLoading = true;
			this.target.setAttribute("loaded", "");
			this.setEmptyRowVisibility();
			target.dataset.visible = "true";
			this.loading = false;
		}

		if (rowsChanged || finishedLoading) {
			this.setEmptyRowVisibility();
			if (sortingWasInitialized || finishedLoading) {
				this.sortingWidget?.refreshRows?.();
			}
			if (rowsChanged) {
				void this.component?.widgets?.TableEditor?.refreshCheckboxes().catch(
					captureError,
				);
			}
		} else if (this.target.hasAttribute("loaded")) {
			this._clearLoadingState();
		}
	}

	destroy() {
		this.target.removeEventListener("change", this._onDirectCompletedChange);
		for (const timer of this._completedTimers.values()) clearTimeout(timer);
		this._completedTimers.clear();
		this._completedSaves.clear();
		this._clearLoadingState();
		super.destroy();
	}
}
