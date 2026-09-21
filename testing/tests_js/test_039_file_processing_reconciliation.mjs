import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";

function replaceGlobal(t, name, value) {
	const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
	Object.defineProperty(globalThis, name, {
		configurable: true,
		writable: true,
		value,
	});
	t.after(() => {
		if (descriptor) Object.defineProperty(globalThis, name, descriptor);
		else delete globalThis[name];
	});
}

/** @matrix file : authoritative-remount extract reload text-tab */
test("test_file_info_extract_completion_requests_one_reload_notice", async (t) => {
	const events = [];
	let hasTextTab = false;
	class FormWidget {
		updated() {
			events.push("base-updated");
		}
		async postreconcile() {
			events.push("base-postreconcile");
		}
		setEntityMetadata() {
			events.push("metadata");
		}
	}
	replaceGlobal(t, "document", {
		getElementById: (id) => (id === "text" && hasTextTab ? {} : null),
	});
	const { FileInfo } = await esmock.strict(
		"../../src/script/widgets/fileInfo.mjs",
		{
			"../../src/script/elements/input.mjs": { InputElement: class {} },
			"../../src/script/elements/primitives.mjs": { primitives: {} },
			"../../src/script/elements/sectionToggle.mjs": { SectionToggle: {} },
			"../../src/script/elements/textarea.mjs": { TextareaElement: class {} },
			"../../src/script/generated/styles.mjs": {
				STYLES: { label: { default: "" } },
			},
			"../../src/script/shared/icons.mjs": { setIcon() {} },
			"../../src/script/widgets/base/formWidget.mjs": { FormWidget },
		},
	);
	let notices = 0;
	const info = Object.create(FileInfo.prototype);
	info._refreshExtractOnReconcile = false;
	info.view = {
		showExtractReloadNotice() {
			notices += 1;
		},
	};
	const response = {
		html: {
			querySelector: () => ({
				dataset: {
					options: JSON.stringify({
						extract: {
							complete: true,
							status: "Text extraction complete.",
						},
					}),
				},
			}),
		},
	};
	info.updated(response);
	assert.equal(info._refreshExtractOnReconcile, true);
	await info.postreconcile();
	await info.postreconcile();
	assert.equal(notices, 1);
	assert.equal(info._refreshExtractOnReconcile, false);
	hasTextTab = true;
	info.updated(response);
	await info.postreconcile();
	assert.equal(notices, 1, "mounted text tab does not request reload");
	hasTextTab = false;
	info.updated({ html: { querySelector: () => null } });
	await info.postreconcile();
	assert.equal(
		notices,
		1,
		"missing options do not reuse stale extraction state",
	);
	assert.equal(events.filter((event) => event === "base-updated").length, 3);
	assert.equal(
		events.filter((event) => event === "base-postreconcile").length,
		4,
	);
	assert.equal(events.filter((event) => event === "metadata").length, 4);
});

/** @matrix file : authoritative-remount extract reload text-tab */
test("test_file_view_shows_extract_reload_only_for_matching_unmounted_text", async (t) => {
	let reloads = 0;
	replaceGlobal(t, "window", {
		location: {
			reload() {
				reloads += 1;
			},
		},
	});
	const { default: FileView } = await esmock.strict(
		"../../src/script/views/file.mjs",
		{
			"../../src/script/views/base/entity.mjs": { default: class {} },
		},
	);
	const notice = { dataset: { visible: "false" } };
	let hasTextTab = false;
	const flashes = [];
	const view = Object.create(FileView.prototype);
	view.key = "file-key";
	view.elt = {
		querySelector(selector) {
			if (selector === "#text") return hasTextTab ? {} : null;
			if (selector === "[data-role='extract-reload']") return notice;
			return null;
		},
	};
	view.addFlash = (node) => flashes.push(node);
	view.afterReconcileChange({ type: "entity-poll", key: "file-key" });
	view.afterReconcileChange({ type: "extract-complete", key: "other-file" });
	assert.deepEqual([notice.dataset.visible, flashes.length], ["false", 0]);
	hasTextTab = true;
	view.afterReconcileChange({ type: "extract-complete", key: "file-key" });
	assert.deepEqual([notice.dataset.visible, flashes.length], ["false", 0]);
	hasTextTab = false;
	view.afterReconcileChange({ type: "extract-complete", key: "file-key" });
	assert.equal(notice.dataset.visible, "true");
	assert.equal(flashes[0], notice);
	view._reloadAfterExtract({ target: { closest: () => null } });
	view._reloadAfterExtract({ target: { closest: () => ({}) } });
	assert.equal(reloads, 1);
});
