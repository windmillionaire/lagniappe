import assert from "node:assert/strict";
import { test } from "node:test";
import { createBrowser } from "../utility/js/environment.mjs";

function installCssStyleSheetStub() {
	globalThis.CSSStyleSheet = class {
		constructor() {
			this.rulesText = "";
		}
		replaceSync(text) {
			this.rulesText = text;
		}
	};
	Object.defineProperty(document, "adoptedStyleSheets", {
		value: [],
		writable: true,
		configurable: true,
	});
}

test("test_task_table_editor_temporarily_reveals_completed_and_shows_header_status", async (t) => {
	createBrowser(t, {
		url: "https://lagniappe.test/tasks/index",
		html: `
			<div lp-view data-index="tasks" data-kind="task">
				<nav data-role="page-header">
					<span data-role="title">Active Tasks</span>
					<div data-role="actions">
						<button type="button"
						        lp-show="table:TableEditor"
						        aria-label="Edit table"
						        title="Edit table"></button>
					</div>
				</nav>
				<table id="table" data-kind="task">
					<thead>
						<tr data-role="column-header">
							<th data-column="completed">Completed</th>
							<th data-column="name">Name</th>
							<th data-column="due_date">Due Date</th>
						</tr>
						<tr data-widget="TableVisibility" data-visible="false"></tr>
					</thead>
					<tbody data-widget="IndexTable" loaded>
						<tr lp-entity data-key="task-1">
							<td data-column="completed" data-editable="true" data-edit-value="false">No</td>
							<td data-column="name" data-editable="true" data-edit-value="&quot;Inspect hive&quot;">Inspect hive</td>
							<td data-column="due_date" data-editable="true" data-edit-value="&quot;2026-09-01&quot;">Sep 1</td>
						</tr>
					</tbody>
				</table>
			</div>
		`,
	});
	installCssStyleSheetStub();

	const { TableVisibilityState } = await import(
		"../../src/script/widgets/tables/visibilityState.ts"
	);
	const { TableVisibility } = await import(
		"../../src/script/widgets/tables/visibility.ts"
	);
	const { TableEditor } = await import(
		"../../src/script/widgets/tables/editor.ts"
	);

	const root = document.querySelector("[lp-view]");
	const tableElt = document.querySelector("#table");
	const tbody = tableElt.querySelector("tbody");
	const columns = [
		{ field: "completed", title: "Completed", schema: { type: "checkbox" } },
		{ field: "name", title: "Name", selected: true, schema: { type: "input" } },
		{
			field: "due_date",
			title: "Due Date",
			selected: true,
			schema: { type: "input", input: "date" },
		},
	];
	const component = {
		elt: tableElt,
		kind: "task",
		widgets: {},
		preload(key) {
			if (key === "columns") return columns;
			if (key === "selected") return ["name", "due_date"];
			return null;
		},
		async loadWidget(name) {
			if (name === "IndexTable") return { target: tbody };
			return null;
		},
	};
	const view = { elt: root, hash: "tasks-index" };

	const visibilityState = new TableVisibilityState({
		component,
		view,
		selected: ["name", "due_date"],
		columns,
	}).init();
	view.TableVisibilityState = visibilityState;

	const visibility = new TableVisibility({
		component,
		view,
		target: tableElt.querySelector("[data-widget='TableVisibility']"),
		kind: "task",
	});
	visibility.init();
	component.widgets.TableVisibility = visibility;

	const editor = new TableEditor({
		component,
		view,
		kind: "task",
		visible: false,
	});
	component.widgets.TableEditor = editor;

	try {
		await editor.init();
		const editBtn = root.querySelector("button[lp-show='table:TableEditor']");
		const completedCheckbox = () =>
			tableElt.querySelector(
				"[data-widget='TableVisibility'] input[name='completed']",
			);

		// Initially, Completed is hidden by default.
		assert.deepEqual(visibilityState.visibleColumns, ["name", "due_date"]);
		assert.equal(completedCheckbox().checked, false);
		const savedBefore = localStorage.getItem("columns-tasks-index");

		// Entering Edit table temporarily reveals Completed without mutating localStorage.
		editor.visible = true;
		await editor.prereconcile();
		editor.postreconcile();

		assert.deepEqual(visibilityState.visibleColumns, [
			"completed",
			"name",
			"due_date",
		]);
		assert.equal(completedCheckbox().checked, true);
		assert.equal(
			localStorage.getItem("columns-tasks-index"),
			savedBefore,
			"Temporary Completed reveal must not overwrite saved column prefs",
		);
		assert.ok(
			tbody.querySelector("td[data-column='completed'] input[type='checkbox']"),
			"Completed column should mount live checkboxes in edit mode",
		);
		assert.equal(editBtn.getAttribute("aria-label"), "Done editing table");
		assert.ok(
			root.querySelector(
				"[data-role='actions'] [data-role='table-edit-status']",
			),
			"Edit mode should show inline status pill inside header actions",
		);

		// Exiting Edit table hides Completed again and removes the status pill.
		editor.visible = false;
		await editor.prereconcile();
		editor.postreconcile();

		assert.deepEqual(visibilityState.visibleColumns, ["name", "due_date"]);
		assert.equal(completedCheckbox().checked, false);
		assert.equal(editBtn.getAttribute("aria-label"), "Edit table");
		assert.equal(root.querySelector("[data-role='table-edit-status']"), null);

		// If the user explicitly enabled Completed in column visibility, exiting edit keeps it visible.
		visibilityState.toggle("completed", true);
		assert.deepEqual(visibilityState.visibleColumns, [
			"completed",
			"name",
			"due_date",
		]);
		editor.visible = true;
		await editor.prereconcile();
		editor.postreconcile();
		editor.visible = false;
		await editor.prereconcile();
		editor.postreconcile();
		assert.deepEqual(visibilityState.visibleColumns, [
			"completed",
			"name",
			"due_date",
		]);
	} finally {
		editor.destroy();
		visibility.destroy();
		visibilityState.destroy();
	}
});
