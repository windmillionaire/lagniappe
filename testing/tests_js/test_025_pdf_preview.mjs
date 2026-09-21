import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

async function loadPreview(t, getDocument = t.mock.fn()) {
	class PDFDataRangeTransport {}
	return await esmock.strict("../../src/script/widgets/filePdfPreview.mjs", {
		"pdfjs-dist": {
			getDocument,
			GlobalWorkerOptions: {},
			PDFDataRangeTransport,
		},
	});
}

/** @matrix file : loading-state pdf-preview view-transition */
test("test_pdf_preview_loading_does_not_block_widget_reconciliation", async (t) => {
	createBrowser(t, {
		html: `
			<section data-role="pdf-preview" data-url="/file.pdf" data-size="1024">
				<div data-role="pdf-status"></div>
			</section>
		`,
	});
	const pending = new Promise(() => {});
	const getDocument = t.mock.fn(() => ({ promise: pending }));
	const { PDFPreview } = await loadPreview(t, getDocument);
	const target = document.querySelector("[data-role='pdf-preview']");
	const preview = new PDFPreview({ target, visible: true });

	const result = preview.postreconcile();

	assert.equal(
		result,
		undefined,
		"PDF loading must not extend the view-transition callback",
	);
	assert.equal(preview._started, true, "PDF loading did not start");
	const status = target.querySelector("[data-role='pdf-status']");
	assert.equal(status.getAttribute("aria-label"), "Loading preview");
	assert.equal(status.dataset.visible, "true");
	assert.equal(target.getAttribute("aria-busy"), "true");
});

/** @matrix file : pdf-preview revisit view-transition */
test("test_pdf_preview_revisit_does_not_await_pending_rasterization", async (t) => {
	createBrowser(t);
	const { PDFPreview } = await loadPreview(t);
	const preview = new PDFPreview({
		target: document.createElement("section"),
		visible: true,
	});
	preview._started = true;
	preview._pages.set(1, { renderedWidth: 0 });
	preview._renderQueue = new Promise(() => {});

	const result = preview.postreconcile();

	assert.equal(
		result,
		undefined,
		"Pending rasterization must not extend the view-transition callback",
	);
	assert.equal(
		preview._rendering.has(1),
		true,
		"Current-page rasterization was not scheduled",
	);
	assert.equal(preview._rendering.size, 1, "Expected one current-page render");
});
