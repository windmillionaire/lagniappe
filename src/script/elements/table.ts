import { STYLES } from "../generated/styles.mjs";
import { ENDPOINTS } from "../shared/endpoints.ts";
import { captureError } from "../shared/errors.ts";
import { setIcon } from "../shared/icons.ts";
import { request } from "../shared/request.ts";
import { withTransition } from "../shared/transitions.ts";
import { areEqual } from "../shared/utilities.ts";
import type { FormFieldSchema, FormSubmission } from "../types/forms.d.ts";
import {
	BaseElement,
	type ElementRenderer,
	type ElementSchema,
} from "./base/baseElement.ts";
import { CheckboxElement } from "./checkbox.ts";
import { InputElement } from "./input.ts";
import { LinkElement } from "./link.ts";
import { getFormElement } from "./loader.ts";
import { primitives } from "./primitives.ts";

const COMPACT_COLUMN_TYPES = new Set(["checkbox"]);
const TABLE_CELL_ELEMENTS = {
	checkbox: CheckboxElement,
	input: InputElement,
	link: LinkElement,
};
const TAP_MOVE_TOLERANCE = 8;
const HOVER_SUPPRESSION_MS = 250;
const HOVER_HIDE_DELAY_MS = 500;
const TAP_SUPPRESSION_MS = 500;

const ACTIONS = [
	["moveUp", "up", "Move row up"],
	["moveDown", "down", "Move row down"],
	["edit", "edit", "Edit row"],
	["delete", "delete", "Delete row"],
] as const;

type MoveAction = "moveUp" | "moveDown";
type RowActionOptions = {
	after?: (() => void) | null;
	dispatchChange?: boolean;
};

interface PendingTouchAction {
	row: HTMLTableRowElement;
	pointerId: number;
	x: number;
	y: number;
	canceled: boolean;
}

function isRowSubmission(value: unknown): value is FormSubmission {
	return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function tableRows(value: unknown) {
	if (!isRowSubmission(value) || !Array.isArray(value.rows)) return null;
	return value.rows.filter(isRowSubmission);
}

export class TableElement extends BaseElement {
	declare _input: HTMLInputElement | null;
	declare _table: HTMLDivElement | null;
	declare _tbody: HTMLTableSectionElement | null;
	declare _thead: HTMLTableSectionElement | null;
	declare _form: HTMLFormElement | null;
	declare _container: HTMLDivElement | null;
	declare _createButton: HTMLButtonElement | null;
	declare _actions: HTMLElement | null;
	declare _activeRow: HTMLTableRowElement | null;
	declare _actionsOpen: boolean;
	declare _actionsPinned: boolean;
	declare _actionsListenersAdded: boolean;
	declare _hideActionsTimer: number | null;
	declare _pendingTouchAction: PendingTouchAction | null;
	declare _suppressHoverUntil: number;
	declare _suppressTapUntil: number;
	declare _validate?: string;
	declare _embedded?: HTMLDivElement;

	constructor(
		renderer: ElementRenderer,
		schema: ElementSchema,
		submission?: unknown,
	) {
		super(renderer, schema, submission);
		this._input = null;
		this._table = null;
		this._tbody = null;
		this._thead = null;
		this._form = null;
		this._container = null;
		this._createButton = null;
		this._actions = null;
		this._activeRow = null;
		this._actionsOpen = false;
		this._actionsPinned = false;
		this._actionsListenersAdded = false;
		this._hideActionsTimer = null;
		this._pendingTouchAction = null;
		this._suppressHoverUntil = 0;
		this._suppressTapUntil = 0;
		if (!this.renderer.readonly) {
			const key = this.renderer.form?.key;
			if (key)
				this._validate = ENDPOINTS.renderer.validateRow(key, this.schema.id);
			this._click = this._click.bind(this);
			this._rowPointerOver = this._rowPointerOver.bind(this);
			this._rowPointerDown = this._rowPointerDown.bind(this);
			this._rowPointerMove = this._rowPointerMove.bind(this);
			this._rowPointerUp = this._rowPointerUp.bind(this);
			this._rowPointerCancel = this._rowPointerCancel.bind(this);
			this._rowClick = this._rowClick.bind(this);
			this._rowFocusIn = this._rowFocusIn.bind(this);
			this._scheduleHideActions = this._scheduleHideActions.bind(this);
			this._cancelHideActions = this._cancelHideActions.bind(this);
			this._documentPointerDown = this._documentPointerDown.bind(this);
			this._documentKeyDown = this._documentKeyDown.bind(this);
		}
	}

	get value() {
		return this.submission;
	}

	get mode() {
		return this.renderer.readonly ? "read" : "edit";
	}

	changed(value: unknown) {
		if (areEqual(this.value, value)) return false;
		return true;
	}

	_setSubmission(value: unknown) {
		this.submission = value;
		if (this._input) {
			const rows = tableRows(value);
			this._input.value = rows ? JSON.stringify(rows) : "";
		}
	}

	updateSubmission(value: unknown) {
		this._hideActions();
		this._setSubmission(value);
		this._redrawRows();
	}

	_redrawRows() {
		const { _tbody: tbody, _container: container } = this;
		if (!tbody || !container) return;
		const rows = tableRows(this.submission) ?? [];
		if (rows.length === 0) {
			tbody.innerHTML = "";
			container.dataset.visible = "false";
			return;
		}

		const existing = Array.from(tbody.rows);

		for (let i = 0; i < rows.length; i++) {
			const serialized = JSON.stringify(rows[i]);
			if (i < existing.length) {
				if (existing[i].dataset.submission !== serialized) {
					existing[i].replaceWith(this.row(i, rows[i]));
				} else {
					existing[i].dataset.index = String(i);
					const actions = existing[i].querySelector<HTMLElement>(
						"[data-role='row-actions']",
					);
					if (actions) actions.dataset.index = String(i);
				}
			} else {
				tbody.appendChild(this.row(i, rows[i]));
			}
		}

		while (tbody.children.length > rows.length) {
			tbody.lastChild?.remove();
		}

		container.dataset.visible = "true";
	}

	_redrawTable({
		after = null,
		dispatchChange = false,
	}: RowActionOptions = {}) {
		return withTransition(() => {
			this._hideActions();
			this._redrawRows();
			if (after) after();
			if (dispatchChange) {
				this._edit?.dispatchEvent(new Event("change", { bubbles: true }));
			}
		});
	}

	_commitRows(rows: FormSubmission[], { after = null }: RowActionOptions = {}) {
		const value = rows.length > 0 ? { rows } : null;
		this._suppressHoverUntil = performance.now() + HOVER_SUPPRESSION_MS;
		this._setSubmission(value);
		return this._redrawTable({ after, dispatchChange: true });
	}

	_removeForm() {
		this._form?.remove();
		this._form = null;
		if (this._container) {
			this._container.dataset.visible = this._tbody?.children.length
				? "true"
				: "false";
		}
	}

	_actionRow(target: Element) {
		return (
			target.closest<HTMLTableRowElement>("tr[data-index]") || this._activeRow
		);
	}

	_moveRow(index: number, direction: MoveAction) {
		const rows = tableRows(this.submission) ?? [];
		const newIndex = direction === "moveUp" ? index - 1 : index + 1;
		if (newIndex < 0 || newIndex >= rows.length) return;

		[rows[index], rows[newIndex]] = [rows[newIndex], rows[index]];
		this._commitRows(rows);
	}

	async _click(e: MouseEvent) {
		e.stopPropagation();
		const target = e.target;
		if (!(target instanceof Element)) return;

		const role = target.closest<HTMLElement>("[data-role]")?.dataset.role;
		const handled = [
			"create",
			"cancel",
			"edit",
			"delete",
			"validate",
			"moveUp",
			"moveDown",
		];

		if (role && handled.includes(role)) {
			e.preventDefault();
			e.stopPropagation();
		} else if (role) {
			e.stopPropagation();
			return;
		}

		if (role === "create") {
			if (this._form) return;
			const form = await this.form();
			await withTransition(
				() => {
					if (!this._container || !this._edit) return;
					this._container.dataset.visible = "false";
					this._form = form;
					this._edit.appendChild(this._form);
				},
				{ label: "embedded-form:create" },
			);
		} else if (role === "cancel") {
			withTransition(() => {
				this._removeForm();
			});
		} else if (role === "edit") {
			const index = this._actionRow(target)?.dataset.index;
			if (index === undefined) return;
			this._hideActions();
			const form = await this.form(index);
			const success = await withTransition(
				() => {
					if (!this._container || !this._edit) return;
					this._container.dataset.visible = "false";
					this._form = form;
					this._edit.appendChild(this._form);
				},
				{ label: "embedded-form:edit" },
			);
			if (success) this._scrollFormIntoView();
		} else if (role === "delete") {
			const index = Number.parseInt(
				this._actionRow(target)?.dataset.index ?? "",
				10,
			);
			const previousRows = tableRows(this.submission);
			if (Number.isNaN(index) || !previousRows) return;

			const rows = previousRows.filter((_, rowIndex) => rowIndex !== index);
			this._commitRows(rows);
		} else if (role === "moveUp" || role === "moveDown") {
			const index = Number.parseInt(
				this._actionRow(target)?.dataset.index ?? "",
				10,
			);
			if (Number.isNaN(index)) return;
			this._moveRow(index, role);
		} else if (role === "validate") {
			const button = target.closest("button");
			const form = this._form;
			const route = this._validate;
			if (!button || !form || !route) return;

			const index = form.dataset.index;
			const formData = new FormData(form);
			button.disabled = true;
			try {
				const response = await request.get<{ row: unknown }>(route, formData);
				if (!response?.ok || this._form !== form) return;

				const row = response.row;
				if (!isRowSubmission(row)) return;
				const rows = tableRows(this.submission) ?? [];
				if (index !== undefined && index !== "") {
					rows[Number.parseInt(index, 10)] = row;
				} else {
					rows.push(row);
				}

				await this._commitRows(rows, { after: () => this._removeForm() });
			} catch (error) {
				captureError(error);
			} finally {
				button.disabled = false;
			}
		}
	}

	table() {
		this._container = document.createElement("div");
		this._container.className = "table-container";
		this._container.dataset.visible = "false";

		const table = this._container.appendChild(document.createElement("table"));
		table.className = STYLES.form.table.table;

		const thead = table.appendChild(document.createElement("thead"));
		this._thead = thead;
		thead.className = "bg-base-bg";

		this.schema.columns?.forEach((column) => {
			const headerCell = thead.appendChild(document.createElement("th"));
			headerCell.className = COMPACT_COLUMN_TYPES.has(column.type)
				? STYLES.form.table.cell.compact.th
				: STYLES.form.table.cell.th;

			const title = headerCell.appendChild(document.createElement("div"));
			title.className = STYLES.form.table.cell.title;

			const span = title.appendChild(document.createElement("span"));
			span.textContent = column.title ?? null;
		});
		if (!this.renderer.readonly) {
			const actionHeader = this._thead.appendChild(
				document.createElement("th"),
			);
			actionHeader.className = STYLES.form.table.rowActionHeader;
			actionHeader.setAttribute("aria-hidden", "true");
		}

		this._tbody = table.appendChild(document.createElement("tbody"));
		this._tbody.className = STYLES.form.table.body;
		if (!this.renderer.readonly) {
			this._tbody.addEventListener("pointerover", this._rowPointerOver);
			this._tbody.addEventListener("pointerdown", this._rowPointerDown);
			this._tbody.addEventListener("pointermove", this._rowPointerMove);
			this._tbody.addEventListener("click", this._rowClick);
			this._tbody.addEventListener("focusin", this._rowFocusIn);
			this._tbody.addEventListener("pointerleave", this._scheduleHideActions);
			this._tbody.addEventListener("focusout", this._scheduleHideActions);
		}

		const rows = tableRows(this.submission) ?? [];
		for (const [index, submission] of rows.entries()) {
			this._tbody.appendChild(this.row(index, submission));
		}

		if (rows.length > 0) {
			this._container.dataset.visible = "true";
		}

		return this._container;
	}

	get embedded() {
		if (this._embedded) return this._embedded;

		this._embedded = this.table();

		return this._embedded;
	}

	get edit() {
		if (this._edit) return this._edit;

		this._edit = document.createElement("div");
		this._edit.className = STYLES.form.table.container;
		this._edit.dataset.kind = String(this.renderer.kind);

		const rows = tableRows(this.submission);
		this._input = this._edit.appendChild(
			primitives.input({
				name: this.schema.id,
				type: "hidden",
				value: rows ? JSON.stringify(rows) : "",
			}),
		);
		const label = this._edit.appendChild(
			primitives.label({
				label: this.schema.title,
				tag: "h3",
				styles: { label: STYLES.label.row },
			}),
		);

		if (!this.renderer.readonly) {
			this._createButton = document.createElement("button");
			this._createButton.type = "button";
			this._createButton.dataset.role = "create";
			this._createButton.ariaLabel = `Add row to ${this.schema.title || "table"}`;
			this._createButton.title = "Add row";
			this._createButton.className = `group-data-[mode=read]/element:hidden ${STYLES.form.icon}`;
			this._createButton.dataset.kind = "add";
			setIcon(
				this._createButton.appendChild(document.createElement("span")),
				"addRow",
				"icon-xs",
			);
			const text = this._createButton.appendChild(
				document.createElement("span"),
			);
			text.textContent = "Add row";
			label.appendChild(this._createButton);
		}

		this._table = this.table();
		this._edit.appendChild(this._table);

		if (!this.renderer.readonly) {
			this._edit.addEventListener("click", this._click);

			this._edit.addEventListener("submit", (e) => {
				e.preventDefault();
				e.stopPropagation();
			});
		}

		return this._edit;
	}

	_tableCellElement(column: FormFieldSchema, submission: FormSubmission) {
		const ElementClass =
			column.type === "checkbox" ||
			column.type === "input" ||
			column.type === "link"
				? TABLE_CELL_ELEMENTS[column.type]
				: null;
		if (!ElementClass) {
			captureError(new Error(`Unsupported table column type: ${column.type}`));
			return null;
		}
		return new ElementClass(this._rowRenderer(), column, submission[column.id]);
	}

	_rowRenderer(): ElementRenderer {
		return { id: this.id, readonly: this.readonly, mode: this.mode };
	}

	row(index: number, submission: FormSubmission) {
		const rowElt = document.createElement("tr");
		rowElt.dataset.index = String(index);
		rowElt.dataset.submission = JSON.stringify(submission);
		if (!this.renderer.readonly) rowElt.tabIndex = 0;

		this.schema.columns?.forEach((column) => {
			const cell = document.createElement("td");
			cell.className = COMPACT_COLUMN_TYPES.has(column.type)
				? STYLES.form.table.cell.compact.default
				: STYLES.form.table.cell.default;
			rowElt.appendChild(cell);

			const element = this._tableCellElement(column, submission);
			const content = element?.cell;
			cell.innerHTML =
				typeof content === "string" ? content : (content?.outerHTML ?? "");
		});
		if (!this.renderer.readonly) {
			const actionCell = rowElt.appendChild(document.createElement("td"));
			actionCell.className = STYLES.form.table.rowActionCell;
			actionCell.appendChild(this._rowActions(index));
		}

		return rowElt;
	}

	_rowActions(index: number) {
		const actions = document.createElement("div");
		actions.dataset.role = "row-actions";
		actions.dataset.index = String(index);
		actions.setAttribute("aria-label", "Row actions");
		actions.className = STYLES.form.table.rowActions;
		actions.hidden = true;

		for (const [role, icon, label] of ACTIONS) {
			const button = actions.appendChild(document.createElement("button"));
			button.type = "button";
			button.dataset.role = role;
			button.className = STYLES.form.table.actionButton;
			button.title = label;
			button.setAttribute("aria-label", label);
			if (role === "delete") button.dataset.kind = "delete";

			const iconElement = button.appendChild(document.createElement("span"));
			setIcon(iconElement, icon, "icon-sm");
		}

		actions.addEventListener("pointerenter", this._cancelHideActions);
		actions.addEventListener("pointerleave", this._scheduleHideActions);
		actions.addEventListener("focusin", this._cancelHideActions);
		actions.addEventListener("focusout", this._scheduleHideActions);

		return actions;
	}

	_rowPointerOver(e: PointerEvent) {
		if (e.pointerType && e.pointerType !== "mouse") return;
		if (performance.now() < this._suppressHoverUntil) return;
		if (this._actionsPinned) return;

		const row =
			e.target instanceof Element
				? e.target.closest<HTMLTableRowElement>("tr[data-index]")
				: null;
		if (!row) return;

		this._showActions(row);
	}

	_rowPointerDown(e: PointerEvent) {
		if (e.pointerType === "mouse") return;
		const target = e.target;
		if (
			!(target instanceof Element) ||
			target.closest("a, button, input, select, textarea, [data-role]")
		) {
			return;
		}

		const row = target.closest<HTMLTableRowElement>("tr[data-index]");
		if (!row) return;

		this._pendingTouchAction = {
			row,
			pointerId: e.pointerId,
			x: e.clientX,
			y: e.clientY,
			canceled: false,
		};
		document.addEventListener("pointermove", this._rowPointerMove, true);
		document.addEventListener("pointerup", this._rowPointerUp, true);
		document.addEventListener("pointercancel", this._rowPointerCancel, true);
	}

	_rowPointerMove(e: PointerEvent) {
		const pending = this._pendingTouchAction;
		if (!pending || pending.pointerId !== e.pointerId) return;

		const moved = Math.hypot(e.clientX - pending.x, e.clientY - pending.y);
		if (moved > TAP_MOVE_TOLERANCE) {
			pending.canceled = true;
			this._suppressTapUntil = performance.now() + TAP_SUPPRESSION_MS;
			this._hideActions();
		}
	}

	_rowPointerUp(e: PointerEvent) {
		const pending = this._pendingTouchAction;
		if (!pending || pending.pointerId !== e.pointerId) return;

		const hideActiveActions =
			!pending.canceled &&
			this._actionsOpen &&
			this._actionsPinned &&
			pending.row === this._activeRow;

		this._clearPendingTouchAction();
		if (!pending.canceled) {
			this._suppressTapUntil = performance.now() + TAP_SUPPRESSION_MS;
			if (hideActiveActions) {
				this._hideActions();
				return;
			}
			this._showActions(pending.row, { pinned: true });
		}
	}

	_rowPointerCancel(e: PointerEvent) {
		if (
			this._pendingTouchAction &&
			this._pendingTouchAction.pointerId !== e.pointerId
		) {
			return;
		}
		this._clearPendingTouchAction();
	}

	_rowClick(e: MouseEvent) {
		if (performance.now() < this._suppressTapUntil) return;
		const fineHover = window.matchMedia(
			"(hover: hover) and (pointer: fine)",
		).matches;
		if (fineHover) return;
		const target = e.target;
		if (
			!(target instanceof Element) ||
			target.closest("a, button, input, select, textarea, [data-role]")
		) {
			return;
		}

		const row = target.closest<HTMLTableRowElement>("tr[data-index]");
		if (!row) return;

		if (this._actionsOpen && this._actionsPinned && row === this._activeRow) {
			this._hideActions();
			return;
		}
		this._showActions(row, { pinned: true });
	}

	_clearPendingTouchAction() {
		this._pendingTouchAction = null;
		document.removeEventListener("pointermove", this._rowPointerMove, true);
		document.removeEventListener("pointerup", this._rowPointerUp, true);
		document.removeEventListener("pointercancel", this._rowPointerCancel, true);
	}

	_rowFocusIn(e: FocusEvent) {
		if (this._pendingTouchAction) return;

		const row =
			e.target instanceof Element
				? e.target.closest<HTMLTableRowElement>("tr[data-index]")
				: null;
		if (!row) return;

		this._showActions(row, { pinned: true });
	}

	_showActions(row: HTMLTableRowElement, { pinned = false } = {}) {
		if (this._form || !row || !this._edit?.contains(row)) return;

		this._cancelHideActions();
		this._activeRow = row;
		this._actionsPinned = pinned;

		const actions = row.querySelector<HTMLElement>("[data-role='row-actions']");
		if (!actions) return;
		if (this._actions && this._actions !== actions) {
			this._actions.hidden = true;
		}
		this._actions = actions;
		this._updateActionStates(row);
		actions.hidden = false;
		if (!this._actionsOpen) {
			this._actionsOpen = true;
			this._addActionsListeners();
		}
	}

	_updateActionStates(row: HTMLTableRowElement) {
		const index = Number.parseInt(row.dataset.index ?? "", 10);
		const length =
			tableRows(this.submission)?.length || this._tbody?.children.length || 0;
		if (Number.isNaN(index)) return;

		const states = {
			moveUp: index <= 0,
			moveDown: index >= length - 1,
		};
		for (const [role, disabled] of Object.entries(states)) {
			const button = this._actions?.querySelector<HTMLButtonElement>(
				`[data-role='${role}']`,
			);
			if (!button) continue;
			button.disabled = disabled;
			button.setAttribute("aria-disabled", disabled ? "true" : "false");
		}
	}

	_addActionsListeners() {
		if (this._actionsListenersAdded) return;

		document.addEventListener("pointerdown", this._documentPointerDown, true);
		document.addEventListener("keydown", this._documentKeyDown, true);
		this._actionsListenersAdded = true;
	}

	_removeActionsListeners() {
		if (!this._actionsListenersAdded) return;

		document.removeEventListener(
			"pointerdown",
			this._documentPointerDown,
			true,
		);
		document.removeEventListener("keydown", this._documentKeyDown, true);
		this._actionsListenersAdded = false;
	}

	_documentPointerDown(e: PointerEvent) {
		if (!(e.target instanceof Node)) return;
		if (this._actions?.contains(e.target)) return;
		if (this._activeRow?.contains(e.target)) return;

		this._hideActions();
	}

	_documentKeyDown(e: KeyboardEvent) {
		if (e.key === "Escape") this._hideActions();
	}

	_scheduleHideActions() {
		this._cancelHideActions();
		this._hideActionsTimer = window.setTimeout(() => {
			if (this._actionsPinned) return;
			if (this._actions?.matches(":hover")) return;
			if (this._activeRow?.matches(":hover")) return;
			if (this._actions?.contains(document.activeElement)) return;
			if (this._activeRow?.contains(document.activeElement)) return;

			this._hideActions();
		}, HOVER_HIDE_DELAY_MS);
	}

	_cancelHideActions() {
		if (this._hideActionsTimer) {
			window.clearTimeout(this._hideActionsTimer);
			this._hideActionsTimer = null;
		}
	}

	_hideActions() {
		this._cancelHideActions();
		if (this._actions) {
			this._actions.hidden = true;
		}
		this._removeActionsListeners();
		this._actionsOpen = false;
		this._actionsPinned = false;
		this._activeRow = null;
	}

	_scrollFormIntoView() {
		const form = this._form;
		if (!form) return;

		window.requestAnimationFrame(() => {
			if (!this._form || this._form !== form) return;
			const rect = form.getBoundingClientRect();
			const isVisible =
				rect.top >= 0 &&
				rect.left >= 0 &&
				rect.bottom <= window.innerHeight &&
				rect.right <= window.innerWidth;
			if (isVisible) return;

			const behavior = window.matchMedia("(prefers-reduced-motion: reduce)")
				.matches
				? "auto"
				: "smooth";
			form.scrollIntoView({
				behavior,
				block: "center",
				inline: "nearest",
			});
		});
	}

	async form(index?: string | null) {
		const hasIndex = index !== undefined && index !== null && index !== "";
		const submission = hasIndex
			? tableRows(this.submission)?.[Number(index)]
			: undefined;

		const form = document.createElement("form");
		form.className = STYLES.form.table.form;

		if (hasIndex) {
			form.dataset.index = index;
		}

		for (const column of this.schema.columns ?? []) {
			const element = await getFormElement(
				this._rowRenderer(),
				column,
				submission?.[column.id],
			);
			if (element.edit) form.appendChild(element.edit);
		}

		const buttons = form.appendChild(document.createElement("div"));
		buttons.className = STYLES.button.group;

		const cancel = buttons.appendChild(document.createElement("button"));
		cancel.className = STYLES.button.submit;
		cancel.dataset.kind = "cancel";
		cancel.dataset.role = "cancel";
		cancel.textContent = "Cancel";

		const submit = buttons.appendChild(document.createElement("button"));
		submit.className = STYLES.button.submit;
		submit.textContent = hasIndex ? "Save Changes" : "Add Row";
		submit.dataset.role = "validate";

		form.addEventListener("change", (e) => {
			e.stopPropagation();
		});

		form.addEventListener("updated", (e) => {
			e.stopPropagation();
		});
		return form;
	}

	destroy() {
		this._clearPendingTouchAction();
		this._hideActions();
		if (!this.renderer.readonly && this._tbody) {
			this._tbody.removeEventListener("pointerover", this._rowPointerOver);
			this._tbody.removeEventListener("pointerdown", this._rowPointerDown);
			this._tbody.removeEventListener("pointermove", this._rowPointerMove);
			this._tbody.removeEventListener("click", this._rowClick);
			this._tbody.removeEventListener("focusin", this._rowFocusIn);
			this._tbody.removeEventListener(
				"pointerleave",
				this._scheduleHideActions,
			);
			this._tbody.removeEventListener("focusout", this._scheduleHideActions);
		}
		if (!this.renderer.readonly && this._edit) {
			this._edit.removeEventListener("click", this._click);
		}
		this._actions = null;
		super.destroy();
	}
}
