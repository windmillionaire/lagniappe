"""Node-backed checks for the task-form to-do list element."""


# @pairs form-todo:normalization form-todo:history-fill form-todo:checked-state
def test_todo_value_normalization_and_history_reset(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class BaseElement {}
const context = { BaseElement };
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/todo.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace(
  "export const normalizeTodoValue =",
  "const normalizeTodoValue =",
);
source = source.replace("export class TodoElement", "class TodoElement");
source += `
globalThis.normalizeTodoValue = normalizeTodoValue;
globalThis.TodoElement = TodoElement;
`;
vm.runInContext(source, context);

const input = {
  items: [
    { text: "  First  ", checked: true },
    { text: "", checked: true },
    { text: "Second", checked: false },
  ],
};
const normalized = context.normalizeTodoValue(input);
if (JSON.stringify(normalized) !== JSON.stringify({
  items: [
    { text: "First", checked: true },
    { text: "Second", checked: false },
  ],
})) {
  throw new Error(`Unexpected normalized value: ${JSON.stringify(normalized)}`);
}

const todo = Object.create(context.TodoElement.prototype);
Object.assign(todo, {
  submission: null,
  _input: null,
  _editing: true,
  _draftVisible: true,
  _draft: "pending",
  _renamingIndex: 0,
});
let rendered = 0;
let changed = 0;
todo._render = () => { rendered += 1; };
todo._notifyChange = () => { changed += 1; };

const filled = todo.fillFromHistory(input);
if (!filled || rendered !== 1 || changed !== 1) {
  throw new Error("History fill did not redraw and publish one change");
}
if (todo.historyFillPersistsDefault !== false) {
  throw new Error("To-do history fill must not become a repeating default");
}
if (todo.submission.items.some((item) => item.checked)) {
  throw new Error("History fill retained a completed checkbox");
}
if (todo._editing || todo._draftVisible || todo._renamingIndex !== null) {
  throw new Error("History fill did not return the list to normal mode");
}
'''
    )


# @pair form-todo:keyboard
def test_todo_keyboard_commit_contract(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

class BaseElement {}
const context = { BaseElement };
vm.createContext(context);
let source = fs.readFileSync("src/script/elements/todo.mjs", "utf8");
source = source.replace(/^import .*$/gm, "");
source = source.replace(
  "export const normalizeTodoValue =",
  "const normalizeTodoValue =",
);
source = source.replace("export class TodoElement", "class TodoElement");
source += "\nglobalThis.TodoElement = TodoElement;";
vm.runInContext(source, context);

const todo = Object.create(context.TodoElement.prototype);
let commits = 0;
todo._commitDraft = () => { commits += 1; };

const event = (key, shiftKey = false) => ({
  key,
  shiftKey,
  target: { dataset: { role: "todo-draft" } },
  prevented: false,
  preventDefault() { this.prevented = true; },
});

const enter = event("Enter");
todo._keydown(enter);
const tab = event("Tab");
todo._keydown(tab);
const reverseTab = event("Tab", true);
todo._keydown(reverseTab);

if (!enter.prevented || !tab.prevented || commits !== 2) {
  throw new Error("Enter and forward Tab must commit the current draft");
}
if (reverseTab.prevented) {
  throw new Error("Shift+Tab must remain an escape path from the list");
}

const list = Object.create(context.TodoElement.prototype);
Object.assign(list, {
  submission: { items: [{ text: "Before", checked: true }] },
  _input: null,
  _draft: "New item",
  _draftVisible: true,
  _renamingIndex: 0,
  _renameValue: "After",
});
list._render = () => {};
list._notifyChange = () => {};
list._focus = () => {};
list._commitDraft();
if (JSON.stringify(list.submission) !== JSON.stringify({
  items: [
    { text: "After", checked: true },
    { text: "New item", checked: false },
  ],
})) {
  throw new Error("Committing a draft lost the active item rename");
}
'''
    )


# @pair forms:components
def test_todo_builder_registration_is_task_only(run_node):
    run_node(
        r'''
const fs = require("node:fs");
const vm = require("node:vm");

const context = {};
vm.createContext(context);
let source = fs.readFileSync("src/script/config/builder.mjs", "utf8");
source = source.replace("const CONFIG =", "globalThis.CONFIG =");
source = source.replace("export { CONFIG };", "");
vm.runInContext(source, context);

const taskTodo = context.CONFIG.FORM_COMPONENTS.find(({ type }) => type === "todo");
const pageTodo = context.CONFIG.PAGE_COMPONENTS.find(({ type }) => type === "todo");
if (!taskTodo || taskTodo.label !== "To-do List" || taskTodo.icon !== "checklist") {
  throw new Error("Task builder palette is missing the to-do list component");
}
if (pageTodo) {
  throw new Error("Page builder palette exposed the task-only to-do list");
}
if (context.CONFIG.PRESENTATION_DEFAULTS.todo.title !== "To-do List") {
  throw new Error("To-do presentation defaults are missing");
}
if (!context.CONFIG.DEFAULT_SETTINGS.todo.includes("title")) {
  throw new Error("To-do builder settings are missing title editing");
}
'''
    )
