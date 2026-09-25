import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser, useClock } from "../utility/js/environment.mjs";

function deferred() {
	let resolve;
	let reject;
	const promise = new Promise((yes, no) => {
		resolve = yes;
		reject = no;
	});
	return { promise, resolve, reject };
}

function rowHtml(key, name = "Original") {
	return (
		'<tr lp-entity data-key="' +
		key +
		'">' +
		'<td data-column="name" data-editable="true" data-edit-value="' +
		JSON.stringify(name).replaceAll('"', "&quot;") +
		'">' +
		name +
		"</td>" +
		'<td data-column="description" data-editable="true" data-edit-value="&quot;Description&quot;">Description</td>' +
		'<td data-column="flag" data-editable="true" data-edit-value="false">No</td></tr>'
	);
}

function response(html) {
	return {
		ok: true,
		html: new DOMParser().parseFromString(html, "text/html"),
	};
}

async function setup(t, { load, patch, transition, expectedErrors = [] } = {}) {
	let editor;
	let table;
	const errors = [];
	t.after(() => {
		editor?.destroy();
		table?.destroy();
		assert.deepEqual(errors, expectedErrors);
	});
	createBrowser(t, {
		html:
			'<main><button lp-show="table:TableEditor">Quick Edit</button>' +
			'<table id="table"><tbody data-widget="IndexTable" loaded>' +
			rowHtml("one") +
			rowHtml("two") +
			"</tbody></table></main>",
	});
	const { getFormElement } = await import(
		"../../src/script/elements/loader.mjs"
	);
	const { IndexTable } = await import(
		"../../src/script/widgets/tables/indexTable.mjs"
	);
	const fields = [];
	const requests = [];
	const mocks = {
		"../../src/script/elements/loader.mjs": {
			getFormElement: async (...args) => {
				if (load) await load(...args);
				const element = await getFormElement(...args);
				t.mock.method(element, "destroy");
				fields.push(element);
				return element;
			},
		},
		"../../src/script/shared/request.mjs": {
			request: {
				patch: (route, payload) => {
					requests.push({ route, payload });
					assert.ok(patch, "Unexpected PATCH");
					return patch(route, payload);
				},
			},
		},
		"../../src/script/shared/errors.mjs": {
			captureError: (error) => errors.push(error),
		},
	};
	if (transition) {
		mocks["../../src/script/shared/transitions.mjs"] = {
			withTransition: transition,
		};
	}
	const { TableEditor } = await esmock.strict(
		"../../src/script/widgets/tables/editor.mjs",
		mocks,
	);
	const view = {
		elt: document.querySelector("main"),
		mobile: false,
		addFlash() {},
	};
	const columns = [
		{ field: "name", schema: { type: "input", input: "text" } },
		{ field: "description", schema: { type: "input", input: "text" } },
		{ field: "flag", schema: { type: "checkbox" } },
	];
	const component = {
		elt: document.querySelector("table"),
		view,
		kind: "page",
		widgets: {},
		preload: () => columns,
		loadWidget: async (name) => component.widgets[name],
	};
	table = new IndexTable({
		component,
		view,
		target: document.querySelector("tbody"),
	});
	component.widgets.IndexTable = table;
	table.init();
	editor = new TableEditor({ component, view, visible: true });
	component.widgets.TableEditor = editor;
	await editor.init();
	return {
		editor,
		table,
		component,
		view,
		fields,
		requests,
		cell: (column = "name", key = "one") =>
			document.querySelector(
				`tr[data-key="${key}"] td[data-column="${column}"]`,
			),
	};
}

function close(editor) {
	editor.visible = false;
	editor.postreconcile();
}

async function open(editor) {
	editor.visible = true;
	await editor.prereconcile();
	editor.postreconcile();
}

/**
 * @source src/script/widgets/tables/editor.mjs::TableEditor
 * @matrix table-controls : quick-edit async-preparation
 */
test("test_table_editor_close_discards_late_input_and_checkbox_fields", async (t) => {
	const gate = deferred();
	const { editor, cell, fields } = await setup(t, { load: () => gate.promise });
	const opening = editor._open(cell());
	const checkboxes = editor.refreshCheckboxes();
	close(editor);
	gate.resolve();
	await Promise.all([opening, checkboxes]);
	assert.equal(document.querySelectorAll("td input").length, 0);
	assert.equal(cell().textContent, "Original");
	assert.equal(editor.activeEdit, null);
	assert.equal(editor.checkboxEdits.size, 0);
	assert.equal(fields.length, 3);
	for (const field of fields) assert.equal(field.destroy.mock.callCount(), 1);
	await open(editor);
	await editor._open(cell());
	assert.equal(cell().querySelector("input").value, "Original");
});

/**
 * @source src/script/widgets/tables/editor.mjs::TableEditor
 * @matrix table-controls : quick-edit async-preparation teardown
 */
test("test_table_editor_rechecks_ownership_in_queued_commits", async (t) => {
	const queued = [];
	const queuedOpen = deferred();
	const queuedCheckboxes = deferred();
	const { editor, cell, fields } = await setup(t, {
		transition: (commit, { label }) => {
			const gate = deferred();
			queued.push(() => {
				commit();
				gate.resolve();
			});
			if (label.endsWith("open-cell")) queuedOpen.resolve();
			else queuedCheckboxes.resolve();
			return gate.promise;
		},
	});
	const opening = editor._open(cell());
	const checkboxes = editor.refreshCheckboxes();
	await Promise.all([queuedOpen.promise, queuedCheckboxes.promise]);
	close(editor);
	await open(editor);
	for (const commit of queued) commit();
	await Promise.all([opening, checkboxes]);
	assert.equal(cell().querySelector("input"), null);
	assert.equal(document.querySelectorAll("input[type=checkbox]").length, 2);
	assert.equal(editor.activeEdit, null);
	for (const field of fields.slice(0, 3))
		assert.equal(field.destroy.mock.callCount(), 1);
});

/**
 * @source src/script/widgets/tables/editor.mjs::TableEditor
 * @matrix table-controls : quick-edit async-preparation
 */
test("test_table_editor_latest_cell_open_owns_the_only_editor", async (t) => {
	const first = deferred();
	const second = deferred();
	const { editor, cell, fields } = await setup(t, {
		load: (_renderer, schema) =>
			schema.id === "name" ? first.promise : second.promise,
	});
	const openingFirst = editor._open(cell());
	const openingSecond = editor._open(cell("description"));
	second.resolve();
	await openingSecond;
	first.resolve();
	await openingFirst;
	assert.equal(document.querySelectorAll("td input").length, 1);
	assert.equal(
		cell("description").querySelector("input"),
		document.activeElement,
	);
	assert.equal(cell().textContent, "Original");
	const discarded = fields.find((field) => field.schema.id === "name");
	assert.equal(discarded.destroy.mock.callCount(), 1);
});

/**
 * @source src/script/widgets/tables/editor.mjs::TableEditor
 * @matrix table-controls : quick-edit async-preparation teardown
 */
test("test_table_checkbox_batches_release_superseded_and_failed_fields", async (t) => {
	const gate = deferred();
	const failure = new Error("Field import failed");
	let fail = false;
	let attempt = 0;
	const { editor, fields } = await setup(t, {
		load: async () => {
			await gate.promise;
			if (fail && attempt++ === 0) throw failure;
		},
		expectedErrors: [failure],
	});
	const first = editor.refreshCheckboxes();
	const second = editor.refreshCheckboxes();
	gate.resolve();
	await Promise.all([first, second]);
	assert.equal(document.querySelectorAll("input[type=checkbox]").length, 2);
	close(editor);
	assert.equal(fields.length, 4);
	for (const field of fields) assert.equal(field.destroy.mock.callCount(), 1);
	fail = true;
	editor.visible = true;
	await editor.refreshCheckboxes();
	assert.equal(document.querySelectorAll("input[type=checkbox]").length, 0);
	for (const field of fields) assert.equal(field.destroy.mock.callCount(), 1);
});

/**
 * @source src/script/widgets/tables/editor.mjs::TableEditor
 * @matrix table-controls : quick-edit pending-save
 */
test("test_table_save_after_close_preserves_newer_edit_and_focus", async (t) => {
	let gate;
	const { editor, cell, requests } = await setup(t, {
		patch: () => gate.promise,
	});
	for (const successful of [true, false]) {
		await open(editor);
		await editor._open(cell());
		cell().querySelector("input").value = successful
			? "Accepted"
			: "Rejected attempt";
		gate = deferred();
		const saving = editor._commit(cell());
		close(editor);
		await open(editor);
		await editor._open(cell("description"));
		const newerInput = cell("description").querySelector("input");
		newerInput.value = "Unsaved newer draft";
		gate.resolve(
			successful ? response("Accepted") : { ok: false, error: "Save rejected" },
		);
		assert.equal(await saving, successful);
		assert.equal(editor.activeEdit.cell, cell("description"));
		assert.equal(document.activeElement, newerInput);
		assert.equal(newerInput.value, "Unsaved newer draft");
		assert.equal(cell().hasAttribute("inert"), false);
		if (successful) assert.equal(cell().dataset.editValue, '"Accepted"');
		else
			assert.equal(
				cell().querySelector("[role=alert]").textContent,
				"Save rejected",
			);
		close(editor);
	}
	assert.equal(requests.length, 2);
});

/**
 * @source src/script/widgets/tables/editor.mjs::TableEditor
 * @matrix table-controls : quick-edit pending-save
 */
test("test_table_pending_save_is_shared_and_blocks_same_cell_reentry", async (t) => {
	const gate = deferred();
	const { editor, cell, requests } = await setup(t, {
		patch: () => gate.promise,
	});
	await editor._open(cell());
	cell().querySelector("input").value = "Submitted snapshot";
	const first = editor._commit(cell());
	const second = editor._commit(cell());
	assert.equal(requests.length, 1);
	assert.equal(cell().getAttribute("aria-busy"), "true");
	assert.equal(cell().hasAttribute("inert"), true);
	cell().querySelector("input").value = "Later programmatic change";
	assert.equal(requests[0].payload.value, "Submitted snapshot");
	close(editor);
	editor.visible = true;
	await editor._open(cell());
	assert.equal(cell().querySelector("input"), null);
	gate.resolve(response("Submitted snapshot"));
	assert.deepEqual(await Promise.all([first, second]), [true, true]);
	await editor._open(cell());
	assert.equal(cell().querySelector("input").value, "Submitted snapshot");
});

/**
 * @source src/script/widgets/tables/editor.mjs::TableEditor
 * @matrix table-controls : quick-edit pending-save
 */
test("test_table_save_failure_keeps_current_draft_and_allows_retry", async (t) => {
	const failure = new Error("Network failed");
	let attempt = 0;
	const { editor, cell, requests } = await setup(t, {
		patch: async () => {
			if (attempt++ === 0) throw failure;
			return response("Retried draft");
		},
		expectedErrors: [failure],
	});
	await editor._open(cell());
	const input = cell().querySelector("input");
	input.value = "Retried draft";
	assert.equal(await editor._commit(cell()), false);
	assert.equal(cell().querySelector("input"), input);
	assert.equal(input.value, "Retried draft");
	assert.equal(cell().hasAttribute("inert"), false);
	assert.match(
		cell().querySelector("[role=alert]").textContent,
		/Could not save/,
	);
	assert.equal(await editor._commit(cell()), true);
	assert.equal(requests.length, 2);
	assert.equal(cell().querySelector("input"), null);
	assert.equal(cell().dataset.editValue, '"Retried draft"');
});

/**
 * @source src/script/widgets/tables/editor.mjs::TableEditor
 * @matrix table-controls : quick-edit pending-save
 */
test("test_table_checkbox_save_can_finish_with_editor_closed_or_reopened", async (t) => {
	let gate;
	const { editor, cell } = await setup(t, { patch: () => gate.promise });
	for (const reopen of [false, true]) {
		await open(editor);
		const checkbox = cell("flag").querySelector("input");
		checkbox.checked = !checkbox.checked;
		const value = checkbox.checked;
		gate = deferred();
		const saving = editor._commitCheckbox(cell("flag"));
		close(editor);
		if (reopen) {
			await open(editor);
			assert.equal(cell("flag").querySelector("input"), null);
		}
		gate.resolve(response(value ? "Yes" : "No"));
		assert.equal(await saving, true);
		assert.equal(cell("flag").dataset.editValue, JSON.stringify(value));
		if (reopen) {
			await editor.refreshCheckboxes();
			assert.equal(cell("flag").querySelector("input").checked, value);
		} else {
			assert.equal(cell("flag").querySelector("input"), null);
			assert.equal(cell("flag").textContent, value ? "Yes" : "No");
		}
		close(editor);
		assert.equal(
			cell("flag").querySelector("[data-role=quick-edit-saved]"),
			null,
		);
	}
});

/**
 * @source src/script/widgets/tables/editor.mjs::TableEditor
 * @matrix table-controls : quick-edit pending-save teardown
 */
test("test_table_saved_timers_cannot_clear_newer_save_or_survive_destroy", async (t) => {
	const { editor, cell } = await setup(t, {
		patch: async () => response("Saved"),
	});
	const clock = useClock(t);
	await editor._open(cell());
	cell().querySelector("input").value = "First";
	await editor._commit(cell());
	clock.tick(600);
	await editor._open(cell());
	cell().querySelector("input").value = "Second";
	await editor._commit(cell());
	clock.tick(600);
	assert.equal(cell().dataset.editState, "saved");
	assert.ok(cell().querySelector("[data-role=quick-edit-saved]"));
	clock.tick(600);
	assert.equal(cell().dataset.editState, undefined);
	assert.equal(cell().querySelector("[data-role=quick-edit-saved]"), null);
	await editor._open(cell());
	cell().querySelector("input").value = "Third";
	await editor._commit(cell());
	editor.destroy();
	const afterDestroy = cell().outerHTML;
	clock.tick(5000);
	assert.equal(cell().outerHTML, afterDestroy);
	assert.equal(cell().querySelector("[data-role=quick-edit-saved]"), null);
});

/**
 * @source src/script/widgets/tables/indexTable.mjs::IndexTable.refresh
 * @source src/script/widgets/tables/indexTable.mjs::IndexTable.refreshDelta
 * @matrix table-controls : quick-edit row-replacement teardown
 */
test("test_table_refresh_releases_replaced_and_removed_edits", async (t) => {
	const { editor, table, cell, fields } = await setup(t);
	for (const delta of [true, false]) {
		table.target.innerHTML = rowHtml("one") + rowHtml("two");
		await open(editor);
		await editor._open(cell());
		const owned = fields.filter(
			(field) => field.destroy.mock.callCount() === 0,
		);
		assert.equal(owned.length, 3);
		if (delta) {
			table.refreshDelta({
				remove: ["two"],
				upsert: [{ key: "one", html: rowHtml("one", "Refreshed") }],
				order: ["one"],
			});
		} else {
			table.refresh(
				response(
					`<table><tbody>${rowHtml("one", "Refreshed")}</tbody></table>`,
				),
			);
		}
		for (const field of owned) assert.equal(field.destroy.mock.callCount(), 1);
		await editor.refreshCheckboxes();
		assert.equal(cell().textContent, "Refreshed");
		assert.equal(editor.activeEdit, null);
		assert.equal(document.querySelectorAll("input[type=checkbox]").length, 1);
		assert.equal(cell("name", "two"), null);
		close(editor);
	}
});

/**
 * @source src/script/widgets/tables/indexTable.mjs::IndexTable.refreshDelta
 * @matrix table-controls : quick-edit row-replacement teardown
 */
test("test_table_refresh_rejects_pending_fields_and_save_results", async (t) => {
	const loading = deferred();
	const saving = deferred();
	const { editor, table, cell } = await setup(t, {
		load: (_renderer, schema) =>
			schema.type === "input" ? loading.promise : undefined,
		patch: () => saving.promise,
	});
	const opening = editor._open(cell());
	const replace = (name) =>
		table.refreshDelta({
			upsert: [{ key: "one", html: rowHtml("one", name) }],
			order: ["one", "two"],
		});
	replace("Replacement");
	loading.resolve();
	await opening;
	assert.equal(cell().querySelector("input"), null);
	await editor._open(cell());
	cell().querySelector("input").value = "Obsolete save";
	const pending = editor._commit(cell());
	replace("Authoritative row");
	saving.resolve(response("Obsolete save"));
	assert.equal(await pending, false);
	assert.equal(cell().textContent, "Authoritative row");
	assert.equal(cell().dataset.editValue, '"Authoritative row"');
	assert.equal(cell().querySelector("[data-role=quick-edit-saved]"), null);
	await editor.refreshCheckboxes();
});

/**
 * @source src/script/widgets/tables/indexTable.mjs::IndexTable.refreshDelta
 * @matrix table-controls : quick-edit row-replacement teardown
 */
test("test_table_refresh_preserves_edits_in_unchanged_rows", async (t) => {
	const { editor, table, cell } = await setup(t);
	await open(editor);
	await editor._open(cell());
	const input = cell().querySelector("input");
	const checkbox = cell("flag").querySelector("input");
	input.value = "Keep this draft";
	table.refreshDelta({
		upsert: [{ key: "two", html: rowHtml("two", "Changed elsewhere") }],
		order: ["one", "two"],
	});
	await editor.refreshCheckboxes();
	assert.equal(cell().querySelector("input"), input);
	assert.equal(input.value, "Keep this draft");
	assert.equal(editor.activeEdit.cell, cell());
	assert.equal(cell("flag").querySelector("input"), checkbox);
	assert.equal(cell("name", "two").textContent, "Changed elsewhere");
});

/**
 * @matrix table-controls : quick-edit teardown
 */
test("test_table_editor_destroy_releases_fields_listeners_and_pending_work", async (t) => {
	const gate = deferred();
	const { editor, table, cell, fields } = await setup(t, {
		patch: () => gate.promise,
	});
	const remove = t.mock.method(table.target, "removeEventListener");
	await open(editor);
	await editor._open(cell());
	cell().querySelector("input").value = "Pending";
	const pending = editor._commit(cell());
	editor.destroy();
	editor.destroy();
	const afterDestroy = table.target.innerHTML;
	gate.resolve(response("Too late"));
	assert.equal(await pending, false);
	assert.equal(table.target.innerHTML, afterDestroy);
	assert.equal(table.target.querySelector("input"), null);
	assert.deepEqual(
		remove.mock.calls.map(({ arguments: args }) => args[0]).sort(),
		["change", "click", "keydown"],
	);
	for (const field of fields) assert.equal(field.destroy.mock.callCount(), 1);
	await editor.init();
	await editor._open(cell());
	assert.equal(table.target.querySelector("input"), null);
});

/**
 * @source src/script/widgets/tables/editor.mjs::TableEditor.releaseRows
 * @source src/script/widgets/tables/indexTable.mjs::IndexTable.refreshDelta
 * @matrix table-controls : quick-edit row-replacement teardown
 */
test("test_table_refresh_releases_rows_already_removed_by_the_view", async (t) => {
	const { editor, table, cell } = await setup(t);
	await open(editor);
	await editor._open(cell());
	const oldField = editor.activeEdit.element;
	cell().querySelector("input").value = "Removed draft";
	// Deletion reconciliation removes the entity before committing row deltas.
	cell().closest("tr").remove();
	table.refreshDelta({ remove: ["one"], order: ["two"] });
	await editor.refreshCheckboxes();
	await editor._open(cell("name", "two"));
	assert.equal(oldField.destroy.mock.callCount(), 1);
	assert.equal(cell("name", "two").querySelector("input").value, "Original");
	assert.equal(editor.activeEdit.cell, cell("name", "two"));
});

/**
 * @source src/script/widgets/tables/editor.mjs::TableEditor
 * @matrix table-controls : quick-edit async-preparation teardown
 */
test("test_table_editor_destroy_during_init_or_field_load_cannot_attach", async (t) => {
	const gate = deferred();
	const { editor, table, cell, component, fields } = await setup(t, {
		load: () => gate.promise,
	});
	const opening = editor._open(cell());
	editor.destroy();
	gate.resolve();
	await opening;
	assert.equal(cell().querySelector("input"), null);
	assert.equal(fields[0].destroy.mock.callCount(), 1);
	const rows = deferred();
	component.loadWidget = () => rows.promise;
	const late = new editor.constructor({
		component,
		view: component.view,
		visible: true,
	});
	const add = t.mock.method(table.target, "addEventListener");
	const initialization = late.init();
	late.destroy();
	rows.resolve(table);
	await initialization;
	assert.equal(add.mock.callCount(), 0);
});

/**
 * @matrix table-controls : persistence sorting teardown
 */
test("test_table_sorting_destroy_removes_controls_and_rejects_queued_toggles", async (t) => {
	createBrowser(t);
	const queued = [];
	const { TableSorting } = await esmock.strict(
		"../../src/script/widgets/tables/sorting.mjs",
		{
			"../../src/script/shared/transitions.mjs": {
				withTransition: (commit) => {
					const gate = deferred();
					queued.push(() => {
						commit();
						gate.resolve();
					});
					return gate.promise;
				},
			},
		},
	);
	for (const mobile of [false, true]) {
		document.body.innerHTML =
			'<main><table><thead><tr><th data-column="name" data-ordering="lexical">' +
			'<button data-toggle="filter">Sort</button></th></tr><tr data-widget="TableSorting"></tr></thead>' +
			"<tbody>" +
			rowHtml("one") +
			"</tbody></table>" +
			'<div id="mobile-controls"><div data-column="name"><button data-toggle="filter">Sort</button></div></div></main>';
		const view = {
			elt: document.querySelector("main"),
			hash: "sort-test",
			mobile,
		};
		const component = {
			elt: document.querySelector("table"),
			preload: () => [],
		};
		const attributes = {
			view,
			component,
			target: document.querySelector("[data-widget=TableSorting]"),
		};
		const sorting = new TableSorting(attributes);
		sorting.init();
		const saved = JSON.stringify({
			lastReorderColumn: "name",
			sorts: { name: { value: "asc" } },
		});
		sessionStorage.setItem("sorts-sort-test", saved);
		assert.equal(document.querySelectorAll("[data-sorts]").length, 1);
		view.elt.dispatchEvent(
			new CustomEvent("toggle-column-filter", { detail: { column: "name" } }),
		);
		assert.equal(queued.length, 1);
		sorting.destroy();
		sorting.destroy();
		queued.shift()();
		view.elt.dispatchEvent(
			new CustomEvent("toggle-column-filter", { detail: { column: "name" } }),
		);
		sorting.init();
		sorting.reset();
		sorting.refreshRows();
		assert.equal(queued.length, 0);
		assert.equal(document.querySelectorAll("[data-sorts]").length, 0);
		assert.equal(sessionStorage.getItem("sorts-sort-test"), saved);
		const replacement = new TableSorting(attributes);
		replacement.init();
		assert.equal(document.querySelectorAll("[data-sorts]").length, 1);
		assert.equal(document.querySelector('input[value="asc"]').checked, true);
		replacement.destroy();
	}
});
