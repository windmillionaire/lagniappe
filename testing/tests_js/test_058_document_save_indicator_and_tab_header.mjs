import assert from "node:assert/strict";
import { test } from "node:test";
import * as Y from "yjs";
import { createBrowser, useClock } from "../utility/js/environment.mjs";

test("test_document_toolbar_save_status_transitions_and_draft_omission", async (t) => {
	createBrowser(t, { url: "https://lagniappe.test/pages/page-1" });

	const { Toolbar } = await import(
		"../../src/script/elements/editor/toolbar.ts"
	);

	const makeStubEditor = () => {
		const dom = document.createElement("div");
		return {
			isDestroyed: false,
			view: { dom },
			storage: { editorPaste: {} },
			on() {},
			off() {},
			state: {
				selection: {
					empty: true,
					$from: { marks: () => [], parent: { attrs: {} } },
				},
				storedMarks: null,
			},
			getAttributes: () => ({}),
			isActive: () => false,
		};
	};

	const container = document.createElement("div");
	const toolbar = new Toolbar({
		editor: makeStubEditor(),
		container,
		kind: "page",
		target: document.createElement("div"),
	});
	toolbar.init();
	try {
		const status = toolbar.element.querySelector("[data-role='save-status']");
		assert.ok(status, "Persistent document toolbar should include save status");
		assert.equal(status.hidden, true);
		assert.equal(status.dataset.saveState, "idle");

		toolbar.setSaveState("dirty");
		assert.equal(status.hidden, false);
		assert.equal(status.textContent, "Unsaved");

		toolbar.setSaveState("saving");
		assert.equal(status.textContent, "Saving…");

		toolbar.setSaveState("saved");
		assert.equal(status.dataset.saveState, "saved");
		assert.equal(status.querySelector("[data-icon='check']") !== null, true);
		assert.ok(status.textContent.includes("Saved"));

		toolbar.setSaveState("offline");
		assert.equal(status.dataset.saveState, "offline");
		assert.equal(status.querySelector("[data-icon='offline']") !== null, true);
		assert.ok(status.textContent.includes("Saved offline"));
		assert.ok(
			status.querySelector(".hidden.sm\\:inline"),
			"Offline prefix should collapse on mobile screens",
		);

		toolbar.setSaveState("error");
		assert.ok(status.textContent.includes("Retrying…"));

		toolbar.setSaveState("idle");
		assert.equal(status.hidden, true);
	} finally {
		toolbar.destroy();
	}

	const draftToolbar = new Toolbar({
		editor: makeStubEditor(),
		container: document.createElement("div"),
		kind: "form",
		draftOnly: true,
		target: document.createElement("div"),
	});
	draftToolbar.init();
	try {
		assert.equal(
			draftToolbar.element.querySelector("[data-role='save-status']"),
			null,
			"Ephemeral draft editors must not show collaborative save status",
		);
	} finally {
		draftToolbar.destroy();
	}
});

test("test_collaborative_document_schedules_idle_save_and_updates_save_state", async (t) => {
	createBrowser(t, { url: "https://lagniappe.test/pages/page-1" });
	const clock = useClock(t);

	const { CollaborativeDocument, IDLE_SAVE_DELAY_MS } = await import(
		"../../src/script/elements/editor/collaborative.ts"
	);

	const target = document.createElement("div");
	target.setAttribute("lp-sync", "doc-sync-1");
	document.body.appendChild(target);
	const doc = new CollaborativeDocument({
		target,
		key: "page-1",
		kind: "page",
		headless: false,
		readonly: false,
	});

	const states = [];
	doc.toolbar = {
		setSaveState(state) {
			states.push(state);
		},
		destroy() {},
	};
	doc.initialized = true;

	let saveEvents = 0;
	const onSave = () => {
		saveEvents += 1;
	};
	window.addEventListener("sync-save", onSave);

	try {
		// Attach the same update handler as _initEditor without mounting full ProseMirror.
		doc.ydoc.on("update", (update, origin) => {
			if (origin !== "remote" && !doc._applyingRemote) {
				doc.updateQueue.push(update);
				if (doc.initialized) {
					doc._dirty = true;
					doc.setSaveState("dirty");
					doc._scheduleIdleSave();
				}
			}
		});

		doc.ydoc.getText("default").insert(0, "Hello");
		assert.equal(doc._dirty, true);
		assert.equal(states.at(-1), "dirty");

		// Typing again before IDLE_SAVE_DELAY_MS resets the timer.
		clock.tick(IDLE_SAVE_DELAY_MS - 500);
		assert.equal(saveEvents, 0);
		doc.ydoc.getText("default").insert(5, " world");

		clock.tick(IDLE_SAVE_DELAY_MS - 500);
		assert.equal(saveEvents, 0);
		clock.tick(500);
		assert.equal(saveEvents, 1, "Idle pause should dispatch sync-save");

		// Persisting baseline clears dirty and reports saved.
		doc.updateQueue.length = 0;
		doc.commitSavedBaseline("snap-1");
		assert.equal(doc._dirty, false);
		assert.equal(states.at(-1), "saved");

		// Remote updates must not mark dirty or schedule saves.
		const other = new Y.Doc();
		other.getText("default").insert(0, "Remote");
		Y.applyUpdate(doc.ydoc, Y.encodeStateAsUpdate(other), "remote");
		clock.tick(IDLE_SAVE_DELAY_MS + 100);
		assert.equal(saveEvents, 1);
		assert.equal(states.at(-1), "saved");
	} finally {
		window.removeEventListener("sync-save", onSave);
		doc.destroy();
	}
});

test("test_sync_manager_parent_touch_on_blur_does_not_stick_in_saving_state", async (t) => {
	createBrowser(t, { url: "https://lagniappe.test/pages/page-1" });
	const esmock = (await import("esmock")).default;

	const states = [];
	const widget = {
		syncId: "page-1:document",
		key: "page-1",
		initialized: true,
		visible: true,
		saveData: null,
		syncData: null,
		setSaveState(state) {
			states.push(state);
		},
	};
	const view = {
		online: true,
		hidden: false,
		connectivityGeneration: 0,
		components: {
			document: { active: widget, visible: true, widgets: { doc: widget } },
		},
		PollingCoordinator: {
			clientId: "client-1",
			get: () => null,
			update() {},
			closeDocuments: async () => {},
		},
	};

	const { SyncManager } = await esmock.strict(
		"../../src/script/shared/sync.ts",
		{
			"../../src/script/shared/request.ts": {
				request: {
					post: async () => ({
						ok: true,
						updates: [
							{
								sync_id: "page-1:document",
								checkpoint_persisted: false,
								entity_touched: true,
							},
						],
					}),
				},
			},
			"../../src/script/shared/offline.ts": {
				deleteSyncRecord: async () => {},
				deleteSyncRecords: async () => {},
				getAllOfflineRecords: async () => ({ sync: [] }),
				getSyncRecord: async () => null,
				updateSyncRecord: async () => {},
			},
		},
	);

	const manager = new SyncManager(view);
	manager._pendingParentTouches.add("page-1:document");
	await manager.sendUpdates(true, null, {
		keepalive: true,
		touchSyncIds: ["page-1:document"],
	});

	assert.deepEqual(
		states,
		[],
		"Parent-touch-only blur flushes must not transition the indicator to Saving…",
	);
	assert.equal(manager._pendingParentTouches.has("page-1:document"), false);
});

test("test_builder_select_model_avoids_native_select_arrow", async (t) => {
	createBrowser(t, { url: "https://lagniappe.test/forms/1" });

	const { ModelElement } = await import(
		"../../src/script/views/builder/panels/model.ts"
	);

	const selectModel = ModelElement.select({
		id: "queen-seen",
		type: "select",
		title: "Queen Seen",
		placeholder: "select an option...",
	});
	assert.equal(
		selectModel.querySelector("select"),
		null,
		"Builder edit-mode select preview should not render a native <select>",
	);
	const input = selectModel.querySelector("input[disabled]");
	assert.ok(input);
	assert.equal(input.placeholder, "select an option...");
	assert.ok(selectModel.querySelector("[data-icon='dropdown']"));

	const internalLink = ModelElement.link({
		id: "linked-page",
		type: "link",
		title: "Linked Page",
		location: "page",
	});
	assert.equal(internalLink.querySelector("select"), null);
	assert.ok(internalLink.querySelector("input[disabled]"));
	assert.ok(internalLink.querySelector("[data-icon='search']"));
});
