import { getFormElement } from "../elements/loader";
import { setIcon } from "../shared/icons";
import { request } from "../shared/request";
import { withTransition } from "../shared/utilities";

const SAVED_STATE_MS = 1200;

const ROUTES = {
	page: (key) => `/pages/${key}/patch`,
	task: (key) => `/tasks/${key}/patch`,
};

/**
 * @testable true
 * @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_quick_edit_updates_editable_cell
 * @tests tests_e2e/006_tasks/test_006c_task_index.py::test_task_index_quick_edit_keeps_revealed_completed_column_editable
 * @tests tests_e2e/007_categories/test_007a_category_index.py::test_category_index_quick_edit_renders_checkbox_cells
 * @pairs task-index:quick-edit
 * @pairs task-index:link-affordance
 * @pairs task-index:editable-cell
 * @pairs task-index:quick-edit task-index:column-visibility task-index:checkbox-cell
 * @pairs category-index:quick-edit category-index:checkbox-cell
 */
export class TableEditor {
	constructor(attributes) {
		Object.assign(this, attributes);

		this.rows = null;
		this.kind = this.kind || this.component.kind;
		this.columns = new Map(
			(this.component.preload("columns") || []).map((column) => [
				column.field,
				column,
			]),
		);
		this.activeEdit = null;
		this.checkboxEdits = new Map();
	}

	async init() {
		this.rows = await this.component.loadWidget("IndexTable");

		this.rows.target.addEventListener("click", (e) => this._click(e));
		this.rows.target.addEventListener("change", (e) => this._change(e));
		this.rows.target.addEventListener("keydown", (e) => this._keydown(e));
	}

	_parseValue(cell) {
		try {
			return JSON.parse(cell.dataset.editValue ?? "null");
		} catch {
			return null;
		}
	}

	_column(cell) {
		return this.columns.get(cell.dataset.column);
	}

	_schema(cell) {
		const column = this._column(cell);
		if (!column?.schema) return null;

		return {
			id: column.field,
			title: column.title,
			...column.schema,
		};
	}

	_route(cell) {
		const route = ROUTES[this.kind];
		const key = cell.closest("tr[data-key]")?.dataset.key;
		return route && key ? route(key) : null;
	}

	_editRenderer() {
		return {
			readonly: false,
			kind: this.kind,
			id: "quick-edit",
			mode: "edit",
			cellEditing: true,
			form: { target: this.rows.target },
		};
	}

	_control(root) {
		for (const selector of [
			"input:not([type='hidden']):not([disabled])",
			"textarea:not([disabled])",
			"select:not([disabled])",
		]) {
			if (root.matches?.(selector)) return root;
			const control = root.querySelector(selector);
			if (control) return control;
		}
		return null;
	}

	_editableCells() {
		return Array.from(
			this.rows.target.querySelectorAll('td[data-editable="true"]'),
		).filter((candidate) => this._schema(candidate) && this._route(candidate));
	}

	_isCheckboxCell(cell) {
		return this._schema(cell)?.type === "checkbox";
	}

	_changed(edit) {
		if (typeof edit.element.changed === "function") {
			return edit.element.changed(edit.value);
		}
		return edit.element.value !== edit.value;
	}

	_renderValue(cell, html, { saved = false } = {}) {
		const wrapper = document.createElement("div");
		wrapper.dataset.editing = "false";
		wrapper.dataset.role = "quick-edit-result";

		const row = wrapper.appendChild(document.createElement("div"));
		row.dataset.role = "quick-edit-value";

		if (saved) {
			const icon = row.appendChild(document.createElement("span"));
			setIcon(icon, "check", "text-saved-default");
			icon.dataset.role = "quick-edit-saved";
		}

		const content = row.appendChild(document.createElement("div"));
		content.dataset.role = "quick-edit-content";
		content.innerHTML = html;

		cell.replaceChildren(wrapper);
	}

	_clearError(cell) {
		cell.querySelector("[data-role='quick-edit-error']")?.remove();
	}

	_showError(cell, message) {
		cell.dataset.editState = "error";

		let error = cell.querySelector("[data-role='quick-edit-error']");
		if (!error) {
			error = document.createElement("p");
			error.dataset.role = "quick-edit-error";
			cell.appendChild(error);
		}
		error.textContent = message || "Could not save this value.";
		this._control(cell)?.focus();
	}

	_editableCell(target) {
		const cell = target.closest("td");
		if (!this.visible || cell?.dataset.editable !== "true") return null;
		if (!this._schema(cell) || !this._route(cell)) return null;
		return cell;
	}

	async _openCheckboxes() {
		this._cleanupCheckboxEdits();

		await Promise.all(
			this._editableCells()
				.filter((cell) => this._isCheckboxCell(cell))
				.map((cell) => this._openCheckbox(cell)),
		);
	}

	async refreshCheckboxes() {
		if (this.visible) await this._openCheckboxes();
	}

	async _openCheckbox(cell) {
		if (this.checkboxEdits.has(cell)) return;

		const schema = this._schema(cell);
		const value = this._parseValue(cell);
		const element = await getFormElement(this._editRenderer(), schema, value);
		const editor = element.cell;
		if (!editor) {
			element.destroy();
			return;
		}

		this.checkboxEdits.set(cell, {
			before: cell.innerHTML,
			cell,
			column: this._column(cell),
			element,
			value,
		});
		cell.dataset.editState = "editing";
		cell.replaceChildren(editor);
	}

	_cleanupCheckboxEdits() {
		this.checkboxEdits.forEach((edit, cell) => {
			if (cell.isConnected) return;
			edit.element.destroy();
			this.checkboxEdits.delete(cell);
		});
	}

	_cancelCheckbox(cell) {
		const edit = this.checkboxEdits.get(cell);
		if (!edit) return;

		if (cell.isConnected) {
			cell.innerHTML = edit.before;
			delete cell.dataset.editState;
		}
		edit.element.destroy();
		this.checkboxEdits.delete(cell);
	}

	_cancelCheckboxes() {
		Array.from(this.checkboxEdits.keys()).forEach((cell) => {
			this._cancelCheckbox(cell);
		});
	}

	async _click(e) {
		if (!this.visible) return;

		e.stopPropagation();

		const cell = this._editableCell(e.target);
		if (!cell) return;

		if (this._isCheckboxCell(cell)) return;
		if (this.activeEdit?.cell === cell) return;

		e.preventDefault();
		await this._open(cell);
	}

	async _change(e) {
		if (!this.visible) return;

		const cell = this._editableCell(e.target);
		if (!cell || !this._isCheckboxCell(cell)) return;

		e.stopPropagation();
		if (!this.checkboxEdits.has(cell)) return;

		if (
			this.activeEdit &&
			this.activeEdit.cell !== cell &&
			!(await this._commit(this.activeEdit.cell))
		) {
			const control = this._control(cell);
			const edit = this.checkboxEdits.get(cell);
			if (control) control.checked = edit.value === true;
			return;
		}

		await this._commitCheckbox(cell);
	}

	async _open(cell) {
		if (this.activeEdit?.cell === cell) return;
		if (this._isCheckboxCell(cell)) return;

		if (this.activeEdit && !(await this._commit(this.activeEdit.cell))) {
			return;
		}

		const schema = this._schema(cell);
		const value = this._parseValue(cell);
		const element = await getFormElement(this._editRenderer(), schema, value);
		const editor = element.cell;
		if (!editor) {
			element.destroy();
			return;
		}

		await withTransition(async () => {
			cell.dataset.editState = "editing";
			this.activeEdit = {
				before: cell.innerHTML,
				cell,
				column: this._column(cell),
				element,
				value,
			};
			cell.replaceChildren(editor);
		});

		const control = this._control(editor);
		control?.focus({ preventScroll: true });
	}

	async _keydown(e) {
		if (!this.activeEdit) return;
		if (!["Enter", "Escape", "Tab"].includes(e.key)) return;

		const { cell } = this.activeEdit;
		if (!cell.contains(e.target)) return;

		e.preventDefault();
		e.stopPropagation();

		if (e.key === "Escape") {
			this._cancel(cell);
			return;
		}

		const committed = await this._commit(cell);
		if (committed && e.key === "Tab") await this._focusNext(cell, e.shiftKey);
	}

	_nextEditableCell(cell, reverse = false) {
		const cells = this._editableCells();
		const index = cells.indexOf(cell);
		if (index < 0) return null;

		const offset = reverse ? -1 : 1;
		return cells[index + offset] || null;
	}

	async _focusNext(cell, reverse = false) {
		const next = this._nextEditableCell(cell, reverse);
		next?.focus?.();
		if (!next) return;
		if (this._isCheckboxCell(next)) {
			this._control(next)?.focus({ preventScroll: true });
			return;
		}
		await this._open(next);
	}

	_cancel(cell) {
		if (!this.activeEdit || this.activeEdit.cell !== cell) return;

		cell.innerHTML = this.activeEdit.before;
		delete cell.dataset.editState;
		this.activeEdit.element.destroy();
		this.activeEdit = null;
	}

	async _commit(cell) {
		if (!this.activeEdit || this.activeEdit.cell !== cell) return false;

		const edit = this.activeEdit;
		const value = edit.element.value;
		if (!this._changed(edit)) {
			this._cancel(cell);
			return true;
		}

		cell.dataset.editState = "saving";
		this._clearError(cell);
		const response = await request.patch(this._route(cell), {
			schema_id: edit.element.schema.id,
			value,
			column: edit.column,
		});

		if (!response?.ok) {
			this._showError(cell, response?.error);
			return false;
		}

		this._renderValue(cell, response.html?.body?.innerHTML ?? "", {
			saved: true,
		});
		cell.dataset.editValue = JSON.stringify(value);
		cell.dataset.editState = "saved";
		edit.element.destroy();
		this.activeEdit = null;

		setTimeout(() => {
			if (cell.dataset.editState !== "saved") return;
			delete cell.dataset.editState;
			cell.querySelector("[data-role='quick-edit-saved']")?.remove();
		}, SAVED_STATE_MS);

		return true;
	}

	async _commitCheckbox(cell) {
		const edit = this.checkboxEdits.get(cell);
		if (!edit) return true;

		const value = edit.element.value;
		if (!this._changed(edit)) {
			cell.dataset.editState = "editing";
			this._clearError(cell);
			return true;
		}

		cell.dataset.editState = "saving";
		this._clearError(cell);
		const response = await request.patch(this._route(cell), {
			schema_id: edit.element.schema.id,
			value,
			column: edit.column,
		});

		if (!response?.ok) {
			this._showError(cell, response?.error);
			return false;
		}

		edit.before = response.html?.body?.innerHTML ?? edit.before;
		edit.value = value;
		cell.dataset.editValue = JSON.stringify(value);
		cell.dataset.editState = "saved";

		setTimeout(() => {
			if (cell.dataset.editState === "saved") {
				cell.dataset.editState = "editing";
			}
		}, SAVED_STATE_MS);

		return true;
	}

	async postreconcile() {
		const visibility = this.component.active;
		const preserveForVisibility =
			!this.visible &&
			this.rows.target.dataset.editing === "true" &&
			visibility?.name === "TableVisibility";
		if (preserveForVisibility) {
			this.visible = true;
			visibility.preserveEditor?.(this);
		}

		if (!this.visible && this.activeEdit) this._cancel(this.activeEdit.cell);
		if (!this.visible) {
			this._cancelCheckboxes();
		}

		this.rows.target.dataset.editing = this.visible ? "true" : "false";
		this.view.elt
			.querySelectorAll('button[lp-show="table:TableEditor"]')
			.forEach((button) => {
				button.dataset.editing = this.visible ? "true" : "false";
				button.setAttribute("aria-pressed", this.visible ? "true" : "false");
			});

		if (this.visible) await this._openCheckboxes();
	}
}
