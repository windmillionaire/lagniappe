import assert from "node:assert/strict";
import { test } from "node:test";
import {
	toggleCode,
	toggleUnderline,
} from "../../src/script/elements/editor/options/menuItems.mjs";
import { createBrowser } from "../utility/js/environment.mjs";

/** @matrix editor : dropdown-rerender menu-active-state */
test("test_editor_menu_item_serializes_current_active_state", (t) => {
	createBrowser(t);
	const item = new toggleUnderline({});
	item.init({
		icon: "underline",
		name: "underline",
		title: "Underline",
	});

	assert.match(item.html, /data-active="false"/);
	assert.doesNotMatch(item.html, /title="Underline"/);
	item.enable();
	assert.match(item.html, /data-active="true"/);
	item.disable();
	assert.match(item.html, /data-active="false"/);

	const renderedButton = document.createElement("button");
	renderedButton.dataset.active = "false";
	item.button = renderedButton;
	item.enable();
	assert.match(item.html, /data-active="true"/);
});

/** @matrix editor : inline-code toggle */
test("test_editor_inline_code_menu_item_toggles_from_local_active_state", (t) => {
	createBrowser(t);
	const calls = [];
	const chain = {
		focus() {
			calls.push("focus");
			return this;
		},
		toggleCode() {
			calls.push("toggleCode");
			return this;
		},
		unsetCode() {
			calls.push("unsetCode");
			return this;
		},
		run() {
			calls.push("run");
			return true;
		},
	};
	const toolbar = {
		editor: {
			chain: () => chain,
		},
	};
	const item = new toggleCode(toolbar);
	item.command = "toggleCode";
	item.name = "code";

	item._onClick(item.button);
	assert.deepEqual(calls, ["focus", "toggleCode", "run"]);
	assert.equal(item.active, true);
	assert.equal(item.button.dataset.active, "true");

	calls.length = 0;
	item._onClick(item.button);
	assert.deepEqual(calls, ["focus", "unsetCode", "run"]);
	assert.equal(item.active, false);
	assert.equal(item.button.dataset.active, "false");
});
