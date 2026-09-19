import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { ENDPOINTS } from "../../src/script/shared/endpoints.mjs";
import { createBrowser } from "../utility/js/environment.mjs";

/** @pair form-html:error-reporting */
test("test_html_element_reports_request_failure_without_masking_original", async (t) => {
	createBrowser(t);
	const original = new Error("HTML request failed");
	const captured = [];
	const captureError = t.mock.fn((...args) => captured.push(args));
	const get = t.mock.fn(async () => {
		throw original;
	});
	const { HtmlElement } = await esmock.strict(
		"../../src/script/elements/html.mjs",
		{
			"../../src/script/shared/index.mjs": {
				captureError,
				ENDPOINTS,
				request: { get },
			},
		},
	);
	const target = document.createElement("div");
	const element = new HtmlElement(
		{ form: { key: "form-1", target } },
		{ id: "instructions" },
		null,
	);

	assert.equal(
		await element._getHtml(),
		"",
		"Failed HTML request returned content",
	);
	assert.equal(get.mock.callCount(), 1);
	assert.equal(
		get.mock.calls[0].arguments[0],
		"/assets/form-1/html/instructions",
	);
	assert.equal(captured.length, 1, "Request failure was not reported once");
	assert.equal(captured[0][0], original, "Original request failure was masked");
	assert.equal(
		captured[0][1],
		target,
		"Form target was not attached to the error report",
	);
	assert.equal(
		captured[0][2]?.schema,
		element.schema,
		"Field schema was not attached to the error report",
	);
});
