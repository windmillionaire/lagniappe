import assert from "node:assert/strict";
import { test } from "node:test";
import { STYLES } from "../../src/script/generated/styles.mjs";
import { CONFIG } from "../../src/script/views/builder/config.mjs";
import { createBrowser } from "../utility/js/environment.mjs";

async function createTodo(t, overrides = {}) {
	createBrowser(t);
	const module = await import("../../src/script/elements/todo.mjs");
	const todo = new module.TodoElement(
		{ readonly: false, historyFillEnabled: true },
		{ id: "checklist", title: "Checklist", type: "todo" },
		null,
	);
	Object.assign(todo, overrides);
	return { ...module, todo };
}

/** @matrix form-todo : checked-state history-fill normalization */
test("test_todo_value_normalization_and_history_reset", async (t) => {
	const { normalizeTodoValue, todo } = await createTodo(t, {
		_editing: true,
		_draftVisible: true,
		_draft: "pending",
		_renamingIndex: 0,
	});
	const input = {
		items: [
			{ text: "  First  ", checked: true },
			{ text: "", checked: true },
			{ text: "Second", checked: false },
		],
	};
	assert.deepEqual(normalizeTodoValue(input), {
		items: [
			{ text: "First", checked: true },
			{ text: "Second", checked: false },
		],
	});
	let rendered = 0;
	let changed = 0;
	t.mock.method(todo, "_render", () => {
		rendered += 1;
	});
	t.mock.method(todo, "_notifyChange", () => {
		changed += 1;
	});

	assert.equal(todo.fillFromHistory(input), true);
	assert.equal(rendered, 1, "History fill did not redraw exactly once");
	assert.equal(changed, 1, "History fill did not publish exactly one change");
	assert.equal(
		todo.submission.items.some((item) => item.checked),
		false,
		"History fill retained a completed checkbox",
	);
	assert.equal(todo._editing, false);
	assert.equal(todo._draftVisible, false);
	assert.equal(todo._renamingIndex, null);
});

/** @pair form-todo:keyboard */
test("test_todo_keyboard_commit_contract", async (t) => {
	const { TodoElement, todo } = await createTodo(t);
	let commits = 0;
	t.mock.method(todo, "_commitDraft", () => {
		commits += 1;
	});
	const event = (key, shiftKey = false) => ({
		key,
		shiftKey,
		target: { dataset: { role: "todo-draft" } },
		prevented: false,
		preventDefault() {
			this.prevented = true;
		},
	});

	const enter = event("Enter");
	todo._keydown(enter);
	const tab = event("Tab");
	todo._keydown(tab);
	const reverseTab = event("Tab", true);
	todo._keydown(reverseTab);
	assert.equal(enter.prevented, true);
	assert.equal(tab.prevented, true);
	assert.equal(commits, 2, "Enter and forward Tab did not commit the draft");
	assert.equal(
		reverseTab.prevented,
		false,
		"Shift+Tab did not remain an escape path",
	);

	const list = new TodoElement(
		{ readonly: false },
		{ id: "checklist", title: "Checklist", type: "todo" },
		{ items: [{ text: "Before", checked: true }] },
	);
	Object.assign(list, {
		_draft: "New item",
		_draftVisible: true,
		_editing: true,
		_renamingIndex: 0,
		_renameValue: "After",
	});
	t.mock.method(list, "_render", () => {});
	t.mock.method(list, "_notifyChange", () => {});
	t.mock.method(list, "_focus", () => {});
	list._commitDraft();
	assert.deepEqual(list.submission, {
		items: [
			{ text: "After", checked: true },
			{ text: "New item", checked: false },
		],
	});
});

/** @pair form-todo:title-actions */
test("test_todo_title_actions_use_table_style_semantics", async (t) => {
	const { todo } = await createTodo(t);
	todo._elt = document.createElement("div");
	todo._input = document.createElement("input");
	todo._historyValue = { items: [{ text: "Earlier", checked: false }] };
	todo._render();
	let controls = todo._elt.querySelectorAll("h3 > button");
	const add = [...controls].find((child) => child.dataset.role === "todo-edit");
	const history = [...controls].find(
		(child) => child.dataset.role === "history-fill",
	);
	assert.deepEqual(
		[...controls].map((child) => child.dataset.role),
		["history-fill", "todo-edit"],
		"Todo title actions were ordered incorrectly",
	);
	assert.equal(add?.className, STYLES.form.icon);
	assert.equal(add?.dataset.kind, "add");
	assert.equal(history?.className, STYLES.form.icon);
	assert.equal(history?.dataset.kind, undefined);

	todo._editing = true;
	todo._render();
	controls = todo._elt.querySelectorAll("h3 > button");
	const done = [...controls].find(
		(child) => child.dataset.role === "todo-done",
	);
	assert.equal(done?.className, STYLES.form.icon);
	assert.equal(done?.dataset.kind, "success");

	const remove = todo._button({
		role: "todo-remove",
		icon: "remove",
		label: "Remove item",
		kind: "delete",
	});
	assert.equal(remove.className, STYLES.form.table.actionButton);
});

/** @pair forms:components */
test("test_todo_builder_registration_is_task_only", () => {
	const taskTodo = CONFIG.FORM_COMPONENTS.find(({ type }) => type === "todo");
	const pageTodo = CONFIG.PAGE_COMPONENTS.find(({ type }) => type === "todo");
	assert.deepEqual(taskTodo, {
		type: "todo",
		label: "Todo List",
		icon: "checklist",
	});
	assert.equal(pageTodo, undefined, "Page palette exposed task-only Todo");
	assert.equal(CONFIG.PRESENTATION_DEFAULTS.todo.title, "Todo List");
	assert.equal(CONFIG.DEFAULT_SETTINGS.todo.includes("title"), true);
});
