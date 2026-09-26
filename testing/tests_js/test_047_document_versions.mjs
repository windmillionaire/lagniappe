import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import * as Y from "yjs";
import { createBrowser } from "../utility/js/environment.mjs";

function snapshot(doc) {
	return Buffer.from(Y.encodeStateAsUpdate(doc)).toString("base64");
}

async function versions(request = {}) {
	return esmock.strict("../../src/script/elements/editor/versions.mjs", {
		"../../src/script/shared/request.mjs": { request },
		"../../src/script/elements/editor/editor.mjs": { previewEditor() {} },
	});
}

// @matrix editor sync : replacement offline-replay preview
test("test_replacement_detection_keeps_the_live_document_untouched", async (t) => {
	createBrowser(t);
	const { incomingReplacements } = await versions();
	const local = new Y.Doc();
	const remote = new Y.Doc();
	local.getText("test").insert(0, "Local draft");
	Y.applyUpdate(remote, Y.encodeStateAsUpdate(local));
	const vector = Y.encodeStateVector(local);
	remote
		.getMap("lagniappeReplacements")
		.set("replace-one", { key: "pin-one", name: "Before replacement" });
	remote.getText("test").delete(0, 11);
	const update = Buffer.from(Y.encodeStateAsUpdate(remote, vector)).toString(
		"base64",
	);
	for (const payload of [
		{ ydoc: snapshot(remote) },
		{ updates: [{ update }] },
	]) {
		assert.deepEqual(incomingReplacements(local, payload), [
			["replace-one", { key: "pin-one", name: "Before replacement" }],
		]);
		assert.equal(local.getText("test").toString(), "Local draft");
		assert.equal(local.getMap("lagniappeReplacements").size, 0);
		assert.deepEqual(
			incomingReplacements(local, payload, { ydoc: snapshot(remote) }),
			[],
		);
	}
	local.destroy();
	remote.destroy();
});

// @matrix editor sync : replacement recovery offline-replay
test("test_recovery_failure_preserves_draft_before_merge", async (t) => {
	createBrowser(t);
	const requests = [];
	let available = false;
	const { DocumentVersions } = await versions({
		post: async (url, payload) => {
			requests.push({ url, payload });
			return available
				? { ok: true, entry: { key: "recovery", name: payload.name } }
				: { ok: false, error: "Try again" };
		},
	});
	const local = new Y.Doc();
	const remote = new Y.Doc();
	remote
		.getMap("lagniappeReplacements")
		.set("replace", { key: "pin", name: "Previous" });
	const doc = {
		ydoc: local,
		key: "page",
		initialized: true,
		_dirty: true,
		headless: true,
		editor: {
			isEditable: true,
			setEditable(value) {
				this.isEditable = value;
			},
			getHTML: () => "<p>Unsent work</p>",
		},
	};
	const controller = new DocumentVersions(doc);
	assert.equal(await controller.beforeSync({ ydoc: snapshot(remote) }), false);
	assert.equal(local.getMap("lagniappeReplacements").size, 0);
	assert.equal(doc._dirty, true);
	assert.equal(doc.editor.isEditable, true);
	assert.equal(doc._versionBusy, false);
	available = true;
	assert.equal(await controller.beforeSync({ ydoc: snapshot(remote) }), true);
	assert.equal(
		requests[0].payload.recovery_id,
		requests[1].payload.recovery_id,
	);
	assert.equal(requests[0].payload.html, "<p>Unsent work</p>");
	assert.equal(requests[0].payload.name, "Recovered local edits");
	assert.equal(requests[0].url, "/assets/page/document/history/pin");
	doc.initialized = false;
	doc._dirty = false;
	doc.offlineRecord = { ydoc: snapshot(local), html: "<p>Offline draft</p>" };
	assert.equal(await controller.beforeSync({ ydoc: snapshot(remote) }), true);
	assert.equal(requests.at(-1).payload.html, "<p>Offline draft</p>");
	doc.initialized = true;
	doc._dirty = true;
	assert.equal(await controller.beforeSync({ ydoc: snapshot(remote) }), true);
	assert.deepEqual(
		requests.slice(-2).map(({ payload }) => payload.html),
		["<p>Offline draft</p>", "<p>Unsent work</p>"],
	);
	delete doc.offlineRecord;
	doc.initialized = false;
	doc._dirty = false;
	const count = requests.length;
	assert.equal(await controller.beforeSync({ ydoc: snapshot(remote) }), true);
	assert.equal(requests.length, count); // A fresh reader never makes recovery pins.
	local.destroy();
	remote.destroy();
});
