import assert from "node:assert/strict";
import { test } from "node:test";
import { getFormElement } from "../../src/script/elements/loader.mjs";

/** @pair forms:invalid-schema */
test("test_unknown_form_element_reports_schema_type", async () => {
	await assert.rejects(
		getFormElement(null, { type: "unsupported-field" }, null),
		{
			message: "Unknown form element type: unsupported-field",
		},
		"Unsupported form element did not report its schema type",
	);
});
