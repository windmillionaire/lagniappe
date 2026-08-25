/*! Third-party licenses: /third-party-licenses.txt */
import { STYLES } from './styles.js?v=b4b0f2eb';
import { s as setIcon } from './icons.js?v=b4b0f2eb';
import { j as areEqual } from './foundation.js?v=b4b0f2eb';
import { B as BaseElement } from './baseElement.js?v=b4b0f2eb';
import { p as primitives } from './primitives.js?v=b4b0f2eb';
import './connectivity.js?v=b4b0f2eb';

/**
 * @testable true
 * @tests tests_js/test_032_todo_element_frontend.py::test_todo_value_normalization_and_history_reset
 * @features form-todo
 * @dimensions normalization checked-state
 */
const normalizeTodoValue = (value, { resetChecked = false } = {}) => {
	if (!value || !Array.isArray(value.items)) return null;

	const items = value.items
		.filter((item) => item && typeof item.text === "string")
		.map((item) => ({
			text: item.text.trim(),
			checked: resetChecked ? false : item.checked === true,
		}))
		.filter((item) => item.text);

	return items.length > 0 ? { items } : null;
};

/**
 * @testable true
 * @tests tests_js/test_032_todo_element_frontend.py::test_todo_value_normalization_and_history_reset
 * @tests tests_js/test_032_todo_element_frontend.py::test_todo_keyboard_commit_contract
 * @tests tests_e2e/006_tasks/test_006h_task_todo_lists.py::test_task_todo_list_editing_and_history_restore
 * @features form-todo
 * @dimensions add edit rename delete check keyboard history-fill reset default-persistence
 */
class TodoElement extends BaseElement {
	constructor(renderer, schema, submission) {
		super(renderer, schema, normalizeTodoValue(submission));
		this._input = null;
		this._editing = false;
		this._draftVisible = false;
		this._draft = "";
		this._renamingIndex = null;
		this._renameValue = "";
		this._historyValue = null;
		this._historyOnFill = null;

		this._click = this._click.bind(this);
		this._change = this._change.bind(this);
		this._inputEvent = this._inputEvent.bind(this);
		this._keydown = this._keydown.bind(this);
	}

	get historyFillPersistsDefault() {
		return false;
	}

	get value() {
		return normalizeTodoValue({ items: this._payloadItems() });
	}

	get mode() {
		return this._editing ? "edit" : "read";
	}

	changed(value) {
		return !areEqual(this.value, normalizeTodoValue(value));
	}

	_items() {
		return (this.submission?.items || []).map((item) => ({ ...item }));
	}

	_payloadItems() {
		const items = this._items();
		if (this._renamingIndex !== null && items[this._renamingIndex]) {
			const text = this._renameValue.trim();
			if (text) items[this._renamingIndex].text = text;
		}
		if (this._editing && this._draftVisible) {
			const text = this._draft.trim();
			if (text) items.push({ text, checked: false });
		}
		return items;
	}

	_setSubmission(value) {
		this.submission = normalizeTodoValue(value);
		this._syncInput();
	}

	_syncInput() {
		if (!this._input) return;
		const value = this.value;
		this._input.value = value ? JSON.stringify(value) : "";
	}

	_notifyChange() {
		this._input?.dispatchEvent(new Event("change", { bubbles: true }));
	}

	_commitItems(items, { notify = true, render = true } = {}) {
		this._setSubmission({ items });
		if (render) this._render();
		if (notify) this._notifyChange();
	}

	_focus(role, { select = false } = {}) {
		queueMicrotask(() => {
			const input = this._elt?.querySelector(`[data-role='${role}']`);
			if (!input) return;
			input.focus();
			if (select) input.select();
		});
	}

	/**
	 * @testable true
	 * @tests tests_js/test_032_todo_element_frontend.py::test_todo_title_actions_use_table_style_semantics
	 * @features form-todo
	 * @dimensions title-actions
	 */
	_button({ role, icon, label, kind = null, header = false }) {
		const button = document.createElement("button");
		button.type = "button";
		button.dataset.role = role;
		if (kind) button.dataset.kind = kind;
		button.ariaLabel = label;
		button.title = label;
		button.className = header
			? STYLES.form.icon
			: STYLES.form.table.actionButton;
		setIcon(
			button.appendChild(document.createElement("span")),
			icon,
			"icon-sm",
		);
		return button;
	}

	_checkbox(item, index, { disabled = false } = {}) {
		const checkbox = primitives.checkbox({
			checked: item.checked,
			disabled,
		});
		const input = checkbox.querySelector("input");
		input.dataset.role = "todo-check";
		input.dataset.index = index;
		input.ariaLabel = `${item.checked ? "Uncheck" : "Check"} ${item.text}`;
		return checkbox;
	}

	_itemRow(item, index) {
		const row = document.createElement("li");
		row.className = STYLES.form.todo.row;
		row.dataset.index = index;
		row.appendChild(
			this._checkbox(item, index, {
				disabled: this.readonly || this._editing,
			}),
		);

		if (this._editing && this._renamingIndex === index) {
			const input = row.appendChild(document.createElement("input"));
			input.type = "text";
			input.autocomplete = "off";
			input.dataset.role = "todo-rename-input";
			input.dataset.index = index;
			input.value = this._renameValue;
			input.className = STYLES.form.todo.inlineInput;
			input.ariaLabel = `Rename ${item.text}`;
		} else if (this._editing) {
			const text = row.appendChild(document.createElement("button"));
			text.type = "button";
			text.dataset.role = "todo-rename";
			text.dataset.index = index;
			text.textContent = item.text;
			text.className = STYLES.form.todo.text;
			text.ariaLabel = `Rename ${item.text}`;
		} else {
			const text = row.appendChild(document.createElement("span"));
			text.textContent = item.text;
			text.className = `${STYLES.form.todo.text} ${
				item.checked ? STYLES.form.todo.completeText : ""
			}`.trim();
		}

		if (this._editing) {
			const actions = row.appendChild(document.createElement("div"));
			actions.className = STYLES.form.todo.actions;
			actions.appendChild(
				this._button({
					role: "todo-remove",
					icon: "remove",
					label: `Remove ${item.text}`,
					kind: "delete",
				}),
			);
		}
		return row;
	}

	_draftRow() {
		const row = document.createElement("li");
		row.className = STYLES.form.todo.row;
		row.dataset.role = "todo-draft-row";
		row.appendChild(
			this._checkbox({ text: "new todo", checked: false }, "draft", {
				disabled: true,
			}),
		);

		const input = row.appendChild(document.createElement("input"));
		input.type = "text";
		input.autocomplete = "off";
		input.dataset.role = "todo-draft";
		input.value = this._draft;
		input.className = STYLES.form.todo.inlineInput;
		input.placeholder = "Add a todo…";
		input.ariaLabel = `Add item to ${this.label}`;

		const actions = row.appendChild(document.createElement("div"));
		actions.className = STYLES.form.todo.actions;
		actions.append(
			this._button({
				role: "todo-dismiss-draft",
				icon: "remove",
				label: "Dismiss new todo",
				kind: "delete",
			}),
			this._button({
				role: "todo-commit-draft",
				icon: "success",
				label: "Add todo",
			}),
		);
		return row;
	}

	_render() {
		if (!this._elt) return;

		this._elt.dataset.mode = this.mode;
		this._elt.replaceChildren(this._input);
		const label = this._elt.appendChild(
			primitives.label({
				label: this.label,
				tag: "h3",
				styles: { label: STYLES.label.row },
			}),
		);

		if (!this.readonly) {
			const controls = label;
			if (this._editing) {
				controls.appendChild(
					this._button({
						role: "todo-done",
						icon: "success",
						label: `Done editing ${this.label}`,
						kind: "success",
						header: true,
					}),
				);
			} else {
				const historyButton = super.historyFillButton(
					this._historyValue,
					this._historyOnFill,
				);
				if (historyButton) controls.appendChild(historyButton);
				controls.appendChild(
					this._button({
						role: "todo-edit",
						icon: this.hasSubmission ? "edit" : "addRow",
						label: this.hasSubmission
							? `Edit ${this.label}`
							: `Add to ${this.label}`,
						kind: this.hasSubmission ? null : "add",
						header: true,
					}),
				);
			}
		}

		const items = this._items();
		if (items.length > 0 || (this._editing && this._draftVisible)) {
			const list = this._elt.appendChild(document.createElement("ul"));
			list.className = STYLES.form.todo.list;
			items.forEach((item, index) => {
				list.appendChild(this._itemRow(item, index));
			});
			if (this._editing && this._draftVisible) {
				list.appendChild(this._draftRow());
			}
		} else if (this.readonly && this.showEmptyFields) {
			this._elt.appendChild(this.readonlyPlaceholder());
		}

		this._syncInput();
	}

	_enterEdit() {
		this._editing = true;
		this._draftVisible = true;
		this._draft = "";
		this._renamingIndex = null;
		this._render();
		this._focus("todo-draft");
	}

	_commitDraft({ continueEditing = true } = {}) {
		this._commitRename({ render: false });
		const text = this._draft.trim();
		const items = this._items();
		if (text) items.push({ text, checked: false });

		this._draft = "";
		this._draftVisible = continueEditing;
		this._renamingIndex = null;
		this._commitItems(items, { notify: Boolean(text) });
		if (continueEditing) this._focus("todo-draft");
		return Boolean(text);
	}

	_commitRename({ render = true } = {}) {
		if (this._renamingIndex === null) return false;
		const items = this._items();
		const item = items[this._renamingIndex];
		const text = this._renameValue.trim();
		const changed = Boolean(item && text && text !== item.text);
		if (changed) item.text = text;

		this._renamingIndex = null;
		this._renameValue = "";
		this._commitItems(items, { notify: changed, render });
		return changed;
	}

	_done() {
		this._commitRename({ render: false });
		const text = this._draftVisible ? this._draft.trim() : "";
		if (text) {
			const items = this._items();
			items.push({ text, checked: false });
			this._setSubmission({ items });
			this._notifyChange();
		}
		this._draft = "";
		this._draftVisible = false;
		this._editing = false;
		this._render();
	}

	_click(event) {
		const target = event.target.closest("[data-role]");
		if (!target || !this._elt.contains(target)) return;
		const role = target.dataset.role;
		const handled = new Set([
			"todo-edit",
			"todo-done",
			"todo-commit-draft",
			"todo-dismiss-draft",
			"todo-remove",
			"todo-rename",
		]);
		if (!handled.has(role)) return;

		event.preventDefault();
		event.stopPropagation();
		if (role === "todo-edit") {
			this._enterEdit();
		} else if (role === "todo-done") {
			this._done();
		} else if (role === "todo-commit-draft") {
			this._commitDraft();
		} else if (role === "todo-dismiss-draft") {
			const hadDraft = Boolean(this._draft.trim());
			this._draft = "";
			this._draftVisible = false;
			this._syncInput();
			this._render();
			if (hadDraft) this._notifyChange();
		} else if (role === "todo-remove") {
			this._commitRename({ render: false });
			const index = Number.parseInt(
				target.closest("[data-index]")?.dataset.index ?? "",
				10,
			);
			if (Number.isNaN(index)) return;
			const items = this._items().filter((_, itemIndex) => itemIndex !== index);
			this._renamingIndex = null;
			this._commitItems(items);
		} else if (role === "todo-rename") {
			this._commitRename({ render: false });
			const index = Number.parseInt(target.dataset.index ?? "", 10);
			const item = this._items()[index];
			if (!item) return;
			this._renamingIndex = index;
			this._renameValue = item.text;
			this._render();
			this._focus("todo-rename-input", { select: true });
		}
	}

	_change(event) {
		const checkbox = event.target.closest("[data-role='todo-check']");
		if (!checkbox || this._editing || this.readonly) return;
		const index = Number.parseInt(checkbox.dataset.index ?? "", 10);
		const items = this._items();
		if (Number.isNaN(index) || !items[index]) return;
		items[index].checked = checkbox.checked;
		this._setSubmission({ items });
	}

	_inputEvent(event) {
		if (event.target.dataset.role === "todo-draft") {
			this._draft = event.target.value;
			this._syncInput();
		} else if (event.target.dataset.role === "todo-rename-input") {
			this._renameValue = event.target.value;
			this._syncInput();
		}
	}

	_keydown(event) {
		const role = event.target.dataset.role;
		if (role === "todo-draft") {
			if (event.key === "Enter" || (event.key === "Tab" && !event.shiftKey)) {
				event.preventDefault();
				this._commitDraft();
			} else if (event.key === "Escape") {
				event.preventDefault();
				this._draft = "";
				this._draftVisible = false;
				this._render();
			}
		} else if (role === "todo-rename-input") {
			if (event.key === "Enter" || (event.key === "Tab" && !event.shiftKey)) {
				event.preventDefault();
				this._commitRename();
				this._focus("todo-draft");
			} else if (event.key === "Escape") {
				event.preventDefault();
				this._renamingIndex = null;
				this._renameValue = "";
				this._render();
			}
		}
	}

	fillFromHistory(value) {
		const restored = normalizeTodoValue(value, { resetChecked: true });
		if (!restored) return false;
		this._editing = false;
		this._draftVisible = false;
		this._draft = "";
		this._renamingIndex = null;
		this._setSubmission(restored);
		this._render();
		this._notifyChange();
		return true;
	}

	addHistoryFill(value, onFill = null) {
		this._historyValue = normalizeTodoValue(value, { resetChecked: true });
		this._historyOnFill = onFill;
		this._render();
		return Boolean(this._elt?.querySelector("[data-role='history-fill']"));
	}

	updateSubmission(value) {
		this._editing = false;
		this._draftVisible = false;
		this._draft = "";
		this._renamingIndex = null;
		this._setSubmission(value);
		this._render();
	}

	create() {
		const elt = document.createElement("div");
		elt.id = this.id;
		elt.className = `${STYLES.form.todo.container} form-element group/element`;
		elt.dataset.kind = this.renderer.kind;
		elt._lp_element = this;

		this._elt = elt;
		this._input = document.createElement("input");
		this._input.type = "hidden";
		this._input.name = this.schema.id;

		elt.addEventListener("click", this._click);
		elt.addEventListener("change", this._change);
		elt.addEventListener("input", this._inputEvent);
		elt.addEventListener("keydown", this._keydown);
		this._render();
		return elt;
	}

	destroy() {
		if (this._elt) {
			this._elt.removeEventListener("click", this._click);
			this._elt.removeEventListener("change", this._change);
			this._elt.removeEventListener("input", this._inputEvent);
			this._elt.removeEventListener("keydown", this._keydown);
		}
		this._input = null;
		super.destroy();
	}
}

export { TodoElement, normalizeTodoValue };
