import { STYLES } from "styles";
import { captureError, ENDPOINTS, request, withTransition } from "../shared";
import { setIcon } from "../shared/icons";
import { areEqual } from "../shared/utilities";
import { BaseElement } from "./base/baseElement";
import { CheckboxElement } from "./checkbox";
import { InputElement } from "./input";
import { LinkElement } from "./link";
import { getFormElement } from "./loader";
import { primitives } from "./primitives";

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
];

/**
 * @testable true
 * @tests tests_e2e/005_pages/test_005b_page_submissions.py::test_table_submission_row_actions
 * @tests tests_e2e/005_pages/test_005b_page_submissions.py::test_table_submission_mobile_row_action_gestures
 * @tests tests_js/test_027_table_element_frontend.py::test_table_validation_uses_form_key_for_detached_preview
 * @features form-table
 * @dimensions row-actions reorder edit delete reload mobile touch-gesture detached-revision-preview validation-route
 */
export class TableElement extends BaseElement {
	constructor(renderer, schema, submission) {
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
			this._validate = ENDPOINTS.renderer.validateRow(
				this.renderer.form.key,
				this.schema.id,
			);
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

	changed(value) {
		if (areEqual(this.value, value)) return false;
		return true;
	}

	_setSubmission(value) {
		this.submission = value;
		if (this._input) {
			this._input.value = value?.rows ? JSON.stringify(value.rows) : "";
		}
	}

	updateSubmission(value) {
		this._hideActions();
		this._setSubmission(value);
		this._redrawRows();
	}

	_redrawRows() {
		const rows = this.submission?.rows || [];
		if (rows.length === 0) {
			this._tbody.innerHTML = "";
			this._container.dataset.visible = "false";
			return;
		}

		const existing = Array.from(this._tbody.children);

		for (let i = 0; i < rows.length; i++) {
			const serialized = JSON.stringify(rows[i]);
			if (i < existing.length) {
				if (existing[i].dataset.submission !== serialized) {
					existing[i].replaceWith(this.row(i, rows[i]));
				} else {
					existing[i].dataset.index = i;
					const actions = existing[i].querySelector(
						"[data-role='row-actions']",
					);
					if (actions) actions.dataset.index = i;
				}
			} else {
				this._tbody.appendChild(this.row(i, rows[i]));
			}
		}

		while (this._tbody.children.length > rows.length) {
			this._tbody.lastChild.remove();
		}

		this._container.dataset.visible = "true";
	}

	_redrawTable({ after = null, dispatchChange = false } = {}) {
		return withTransition(() => {
			this._hideActions();
			this._redrawRows();
			if (after) after();
			if (dispatchChange) {
				this._edit?.dispatchEvent(new Event("change", { bubbles: true }));
			}
		});
	}

	_commitRows(rows, { after = null } = {}) {
		const value = rows.length > 0 ? { rows } : null;
		this._suppressHoverUntil = performance.now() + HOVER_SUPPRESSION_MS;
		this._setSubmission(value);
		return this._redrawTable({ after, dispatchChange: true });
	}

	_removeForm() {
		this._form.remove();
		this._form = null;
		if (this._tbody.children.length === 0) {
			this._container.dataset.visible = "false";
		} else {
			this._container.dataset.visible = "true";
		}
	}

	_actionRow(e) {
		return e.target.closest("tr[data-index]") || this._activeRow;
	}

	_moveRow(index, direction) {
		const rows = [...(this.submission?.rows || [])];
		const newIndex = direction === "moveUp" ? index - 1 : index + 1;
		if (newIndex < 0 || newIndex >= rows.length) return;

		[rows[index], rows[newIndex]] = [rows[newIndex], rows[index]];
		this._commitRows(rows);
	}

	async _click(e) {
		e.stopPropagation();

		const role = e.target.closest("[data-role]")?.dataset.role;
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
			withTransition(async () => {
				this._container.dataset.visible = "false";
				this._form = await this.form();
				this._edit.appendChild(this._form);
			});
		} else if (role === "cancel") {
			withTransition(() => {
				this._removeForm();
			});
		} else if (role === "edit") {
			const index = this._actionRow(e)?.dataset.index;
			if (index === undefined) return;
			this._hideActions();
			withTransition(async () => {
				this._container.dataset.visible = "false";
				this._form = await this.form(index);
				this._edit.appendChild(this._form);
			}).then((success) => {
				if (success) this._scrollFormIntoView();
			});
		} else if (role === "delete") {
			const index = Number.parseInt(
				this._actionRow(e)?.dataset.index ?? "",
				10,
			);
			if (Number.isNaN(index) || !this.submission?.rows) return;

			const rows = this.submission.rows.filter(
				(_, rowIndex) => rowIndex !== index,
			);
			this._commitRows(rows);
		} else if (role === "moveUp" || role === "moveDown") {
			const index = Number.parseInt(
				this._actionRow(e)?.dataset.index ?? "",
				10,
			);
			if (Number.isNaN(index)) return;
			this._moveRow(index, role);
		} else if (role === "validate") {
			const button = e.target.closest("button");
			const form = this._form;
			if (!button || !form) return;

			const index = form.dataset.index;
			const formData = new FormData(form);
			button.disabled = true;
			try {
				const response = await request.get(this._validate, formData);
				if (!response.ok || this._form !== form) return;

				const row = response.row;
				const rows = [...(this.submission?.rows || [])];
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

		this._thead = table.appendChild(document.createElement("thead"));
		this._thead.className = "bg-base-bg";

		this.schema.columns.forEach((column) => {
			const headerCell = this._thead.appendChild(document.createElement("th"));
			headerCell.className = COMPACT_COLUMN_TYPES.has(column.type)
				? STYLES.form.table.cell.compact.th
				: STYLES.form.table.cell.th;

			const title = headerCell.appendChild(document.createElement("div"));
			title.className = STYLES.form.table.cell.title;

			const span = title.appendChild(document.createElement("span"));
			span.textContent = column.title;
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

		const rows = this.submission?.rows || [];
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
		this._edit.dataset.kind = this.renderer.kind;

		this._input = this._edit.appendChild(
			primitives.input({
				name: this.schema.id,
				type: "hidden",
				value: this.submission?.rows
					? JSON.stringify(this.submission.rows)
					: "",
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
			this._createButton.dataset.role = "create";
			this._createButton.className = `group-data-[mode=read]/element:hidden ${STYLES.form.icon}`;
			this._createButton.dataset.kind = "add";
			setIcon(
				this._createButton.appendChild(document.createElement("span")),
				"addRow",
				"icon-sm",
			);
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

	_tableCellElement(column, submission) {
		const ElementClass = TABLE_CELL_ELEMENTS[column.type];
		if (!ElementClass) {
			captureError(new Error(`Unsupported table column type: ${column.type}`));
			return null;
		}
		return new ElementClass(this, column, submission?.[column.id]);
	}

	row(index, submission) {
		const rowElt = document.createElement("tr");
		rowElt.dataset.index = index;
		rowElt.dataset.submission = JSON.stringify(submission);
		if (!this.renderer.readonly) rowElt.tabIndex = 0;

		this.schema.columns.forEach((column) => {
			const cell = document.createElement("td");
			cell.className = COMPACT_COLUMN_TYPES.has(column.type)
				? STYLES.form.table.cell.compact.default
				: STYLES.form.table.cell.default;
			rowElt.appendChild(cell);

			const element = this._tableCellElement(column, submission);
			const content = element.cell;
			cell.innerHTML = content ? content : "";
		});
		if (!this.renderer.readonly) {
			const actionCell = rowElt.appendChild(document.createElement("td"));
			actionCell.className = STYLES.form.table.rowActionCell;
			actionCell.appendChild(this._rowActions(index));
		}

		return rowElt;
	}

	_rowActions(index) {
		const actions = document.createElement("div");
		actions.dataset.role = "row-actions";
		actions.dataset.index = index;
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

	_rowPointerOver(e) {
		if (e.pointerType && e.pointerType !== "mouse") return;
		if (performance.now() < this._suppressHoverUntil) return;
		if (this._actionsPinned) return;

		const row = e.target.closest("tr[data-index]");
		if (!row) return;

		this._showActions(row);
	}

	_rowPointerDown(e) {
		if (e.pointerType === "mouse") return;
		if (e.target.closest("a, button, input, select, textarea, [data-role]")) {
			return;
		}

		const row = e.target.closest("tr[data-index]");
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

	_rowPointerMove(e) {
		const pending = this._pendingTouchAction;
		if (!pending || pending.pointerId !== e.pointerId) return;

		const moved = Math.hypot(e.clientX - pending.x, e.clientY - pending.y);
		if (moved > TAP_MOVE_TOLERANCE) {
			pending.canceled = true;
			this._suppressTapUntil = performance.now() + TAP_SUPPRESSION_MS;
			this._hideActions();
		}
	}

	_rowPointerUp(e) {
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

	_rowPointerCancel(e) {
		if (
			this._pendingTouchAction &&
			this._pendingTouchAction.pointerId !== e.pointerId
		) {
			return;
		}
		this._clearPendingTouchAction();
	}

	_rowClick(e) {
		if (performance.now() < this._suppressTapUntil) return;
		const fineHover = window.matchMedia(
			"(hover: hover) and (pointer: fine)",
		).matches;
		if (fineHover) return;
		if (e.target.closest("a, button, input, select, textarea, [data-role]")) {
			return;
		}

		const row = e.target.closest("tr[data-index]");
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

	_rowFocusIn(e) {
		if (this._pendingTouchAction) return;

		const row = e.target.closest("tr[data-index]");
		if (!row) return;

		this._showActions(row, { pinned: true });
	}

	_showActions(row, { pinned = false } = {}) {
		if (this._form || !row || !this._edit?.contains(row)) return;

		this._cancelHideActions();
		this._activeRow = row;
		this._actionsPinned = pinned;

		const actions = row.querySelector("[data-role='row-actions']");
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

	_updateActionStates(row) {
		const index = Number.parseInt(row.dataset.index ?? "", 10);
		const length =
			this.submission?.rows?.length || this._tbody?.children.length || 0;
		if (Number.isNaN(index)) return;

		const states = {
			moveUp: index <= 0,
			moveDown: index >= length - 1,
		};
		for (const [role, disabled] of Object.entries(states)) {
			const button = this._actions?.querySelector(`[data-role='${role}']`);
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

	_documentPointerDown(e) {
		if (this._actions?.contains(e.target)) return;
		if (this._activeRow?.contains(e.target)) return;

		this._hideActions();
	}

	_documentKeyDown(e) {
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

	async form(index) {
		const hasIndex = index !== undefined && index !== null && index !== "";
		const submission = hasIndex ? this.submission.rows[index] : {};

		const form = document.createElement("form");
		form.className = STYLES.form.table.form;

		if (hasIndex) {
			form.dataset.index = index;
		}

		for (const column of this.schema.columns) {
			const element = await getFormElement(
				this,
				column,
				submission?.[column.id],
			);
			form.appendChild(element.edit);
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
