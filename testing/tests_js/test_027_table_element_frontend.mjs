import assert from "node:assert/strict";
import { test } from "node:test";
import { createBrowser } from "../utility/js/environment.mjs";

/** @matrix form-table : detached-revision-preview validation-route */
test("test_table_validation_uses_form_key_for_detached_preview", async (t) => {
	createBrowser(t);
	const { TableElement } = await import("../../src/script/elements/table.mjs");
	const renderer = {
		form: {
			key: "page-key",
			target: {
				closest() {
					throw new Error("Detached preview must not depend on DOM ancestry");
				},
			},
		},
		readonly: false,
	};
	const table = new TableElement(renderer, { id: "contacts" }, null);

	assert.equal(
		table._validate,
		"/forms/page-key/validate-row/contacts",
		"Table validation did not use the form key",
	);
});

/** @pair form-table:touch-gesture */
test("test_table_touch_movement_threshold_distinguishes_tap_from_swipe", async (t) => {
	createBrowser(t, {
		html: `
			<div id="table-edit">
				<table><tbody>
					<tr data-index="0">
						<td>Contact</td>
						<td data-role="row-actions" hidden></td>
					</tr>
				</tbody></table>
			</div>
		`,
	});
	const activeDocumentListeners = new Map();
	const addEventListener = document.addEventListener.bind(document);
	const removeEventListener = document.removeEventListener.bind(document);
	t.mock.method(document, "addEventListener", (type, handler, options) => {
		if (!activeDocumentListeners.has(type)) {
			activeDocumentListeners.set(type, new Set());
		}
		activeDocumentListeners.get(type).add(handler);
		return addEventListener(type, handler, options);
	});
	t.mock.method(document, "removeEventListener", (type, handler, options) => {
		activeDocumentListeners.get(type)?.delete(handler);
		if (activeDocumentListeners.get(type)?.size === 0) {
			activeDocumentListeners.delete(type);
		}
		return removeEventListener(type, handler, options);
	});
	const { TableElement } = await import("../../src/script/elements/table.mjs");
	const renderer = { form: { key: "page-key" }, readonly: false };
	const table = new TableElement(renderer, { id: "contacts" }, null);
	table._edit = document.querySelector("#table-edit");
	table._tbody = table._edit.querySelector("tbody");
	const row = table._tbody.querySelector("tr");
	const target = row.querySelector("td:not([data-role])");
	const touch = (pointerId, clientX, clientY) => ({
		pointerType: "touch",
		pointerId,
		clientX,
		clientY,
		target,
	});
	const shown = [];
	let hidden = 0;
	const showActions = table._showActions;
	const hideActions = table._hideActions;
	t.mock.method(table, "_showActions", function (...args) {
		shown.push(args);
		return showActions.call(this, ...args);
	});
	t.mock.method(table, "_hideActions", function (...args) {
		hidden += 1;
		return hideActions.call(this, ...args);
	});

	table._rowPointerDown(touch(1, 100, 100));
	table._rowPointerMove(touch(1, 108, 100));
	table._rowPointerUp(touch(1, 108, 100));

	assert.equal(shown.length, 1, "Tap tolerance did not show row actions");
	assert.equal(shown[0][0], row);
	assert.equal(shown[0][1].pinned, true);
	assert.equal(table._actionsOpen, true);
	assert.equal(table._actionsPinned, true);
	for (const type of ["pointermove", "pointerup", "pointercancel"]) {
		assert.equal(
			activeDocumentListeners.has(type),
			false,
			`Completed tap retained temporary ${type} listener`,
		);
	}
	assert.equal(table._pendingTouchAction, null);

	table._rowPointerDown(touch(2, 100, 100));
	table._rowPointerMove(touch(2, 109, 100));
	table._rowPointerUp(touch(2, 109, 100));

	assert.equal(
		shown.length,
		1,
		"Movement beyond the tap tolerance showed row actions",
	);
	assert.equal(
		hidden,
		1,
		"A swipe did not hide active row actions exactly once",
	);
	assert.equal(table._actionsOpen, false);
	assert.equal(table._pendingTouchAction, null);
	assert.equal(
		activeDocumentListeners.size,
		0,
		"Canceled gesture retained document listeners",
	);
});
