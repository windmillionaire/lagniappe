import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

const tick = () => new Promise((resolve) => setImmediate(resolve));

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

function createIndexedDB(t) {
	const state = { closeCount: 0, transactions: [] };
	const db = {
		close() {
			state.closeCount += 1;
		},
		transaction(storeNames, mode) {
			const tx = {
				abortCount: 0,
				error: null,
				mode,
				requests: [],
				storeNames,
				abort() {
					this.abortCount += 1;
				},
				objectStore(name) {
					if (state.executorError) throw state.executorError;
					return {
						delete: (key) => makeRequest("delete", { key, name }),
						get: (key) => makeRequest("get", { key, name }),
						getAll: () => makeRequest("getAll", { name }),
						put: (value) => makeRequest("put", { name, value }),
					};
				},
			};
			const makeRequest = (operation, details) => {
				const request = { operation, ...details };
				tx.requests.push(request);
				return request;
			};
			state.transactions.push(tx);
			return tx;
		},
	};
	const indexedDB = {
		open() {
			const request = { result: db };
			queueMicrotask(() => request.onsuccess?.());
			return request;
		},
	};
	replaceGlobal(t, "indexedDB", indexedDB);
	return { db, indexedDB, state };
}

async function waitForTransaction(state, index = 0) {
	for (let attempt = 0; attempt < 10; attempt += 1) {
		if (state.transactions[index]) return state.transactions[index];
		await tick();
	}
	throw new Error(`Transaction ${index} was not created`);
}

async function waitForRequests(tx, count) {
	for (let attempt = 0; attempt < 10; attempt += 1) {
		if (tx.requests.length >= count) return;
		await tick();
	}
	throw new Error(`Expected ${count} requests, received ${tx.requests.length}`);
}

/** @matrix offline sync : connection-lifecycle multi-delete readonly-result transaction-commit */
test("test_indexeddb_operations_resolve_only_after_transaction_commit", async (t) => {
	const { db, state } = createIndexedDB(t);
	const offline = await import("../../src/script/shared/offline.mjs");
	let writeSettled = false;
	const write = offline.setOfflineMutation({ id: "mutation-1" }).then(() => {
		writeSettled = true;
	});
	const writeTx = await waitForTransaction(state, 0);
	await waitForRequests(writeTx, 1);
	writeTx.requests[0].onsuccess?.();
	await tick();
	assert.equal(writeSettled, false);
	db.onversionchange?.();
	assert.equal(state.closeCount, 1);
	assert.equal(writeSettled, false);
	writeTx.oncomplete?.();
	await write;
	assert.equal(writeSettled, true);
	assert.equal(state.closeCount, 1);

	let readSettled = false;
	const read = offline.getOfflineMutations().then((value) => {
		readSettled = true;
		return value;
	});
	const readTx = await waitForTransaction(state, 1);
	await waitForRequests(readTx, 1);
	readTx.requests[0].result = [{ id: "mutation-1" }];
	readTx.requests[0].onsuccess?.();
	await tick();
	assert.equal(readSettled, false);
	readTx.oncomplete?.();
	assert.deepEqual(await read, [{ id: "mutation-1" }]);

	let deleteSettled = false;
	const deleted = offline.deleteOfflineMutations(["one", "two"]).then(() => {
		deleteSettled = true;
	});
	const deleteTx = await waitForTransaction(state, 2);
	await waitForRequests(deleteTx, 2);
	deleteTx.requests[0].onsuccess?.();
	await tick();
	assert.equal(deleteSettled, false);
	deleteTx.requests[1].onsuccess?.();
	await tick();
	assert.equal(deleteSettled, false);
	deleteTx.oncomplete?.();
	await deleted;
	assert.equal(deleteSettled, true);
});

/** @matrix offline sync : connection-lifecycle error-ownership transaction-abort */
test("test_indexeddb_abort_and_errors_reject_once_and_close_the_database", async (t) => {
	{
		const { state } = createIndexedDB(t);
		const offline = await import("../../src/script/shared/offline.mjs");
		const aborted = new Error("commit aborted");
		const pending = offline.setOfflineMutation({ id: "mutation-1" });
		const tx = await waitForTransaction(state);
		await waitForRequests(tx, 1);
		tx.requests[0].onsuccess?.();
		await tick();
		tx.error = aborted;
		tx.onabort?.();
		assert.equal(
			await pending.then(
				() => null,
				(error) => error,
			),
			aborted,
		);
		assert.equal(state.closeCount, 1);
	}
	{
		const { state } = createIndexedDB(t);
		const offline = await import("../../src/script/shared/offline.mjs");
		const requestError = new Error("request failed");
		const pending = offline.setOfflineMutation({ id: "mutation-2" });
		const tx = await waitForTransaction(state);
		await waitForRequests(tx, 1);
		tx.requests[0].error = requestError;
		tx.requests[0].onerror?.();
		tx.error = requestError;
		tx.onerror?.({ target: tx.requests[0] });
		tx.onabort?.();
		assert.equal(
			await pending.then(
				() => null,
				(error) => error,
			),
			requestError,
		);
		assert.equal(state.closeCount, 1);
	}
	{
		const { db, state } = createIndexedDB(t);
		const offline = await import("../../src/script/shared/offline.mjs");
		const pending = offline.getOfflineMutations();
		await waitForTransaction(state);
		db.onclose?.();
		const received = await pending.then(
			() => null,
			(error) => error,
		);
		assert.equal(received.message, "IndexedDB database closed unexpectedly");
		assert.equal(state.closeCount, 1);
	}
});

/** @matrix offline sync : error-ownership executor-error transaction-abort */
test("test_indexeddb_executor_failures_abort_and_preserve_the_original_error", async (t) => {
	for (const operation of ["set", "get"]) {
		const { state } = createIndexedDB(t);
		const offline = await import("../../src/script/shared/offline.mjs");
		const original = new Error(`${operation} executor`);
		state.executorError = original;
		const pending =
			operation === "set"
				? offline.setOfflineMutation({ id: "mutation-1" })
				: offline.getOfflineMutations();
		const observed = pending.then(
			() => null,
			(error) => error,
		);
		const tx = await waitForTransaction(state);
		assert.equal(await observed, original);
		assert.equal(tx.abortCount, 1);
		assert.equal(state.closeCount, 1);
	}
});

async function setupEditor(t) {
	createBrowser(t);
	const requests = { get: [], put: [] };
	let get = (...args) => {
		requests.get.push(args);
		return Promise.resolve({ ok: true, markup: "" });
	};
	let put = (...args) => {
		requests.put.push(args);
		return Promise.resolve({ ok: true });
	};
	const request = {
		get: (...args) => get(...args),
		put: (...args) => put(...args),
	};
	const { IndependentDocument } = await esmock.strict(
		"../../src/script/elements/editor/independent.mjs",
		{
			"../../src/script/generated/styles.mjs": {
				STYLES: {
					button: { submit: "submit" },
					editor: { container: "editor" },
					message: "message",
				},
			},
			"../../src/script/shared/errors.mjs": {
				captureError(error) {
					throw new Error(`Unexpected capture: ${error.message}`);
				},
			},
			"../../src/script/shared/request.mjs": { request },
			"../../src/script/elements/editor/editor.mjs": {
				independentEditor() {
					throw new Error("Editor factory was not stubbed");
				},
			},
			"../../src/script/elements/editor/toolbar.mjs": { Toolbar: class {} },
		},
	);
	const statusElement = () => {
		const element = document.createElement("div");
		element.hidden = false;
		return element;
	};
	const loadedContainer = () => {
		const container = document.createElement("div");
		container.setAttribute("loaded", "");
		return container;
	};
	const makeDocument = ({
		acknowledged = "<p>Saved</p>",
		current = acknowledged,
	} = {}) => {
		const owner = new IndependentDocument({
			endpoints: { getContent: "/content", save: "/save" },
			target: document.createElement("div"),
		});
		owner.container = loadedContainer();
		owner.status = statusElement();
		owner.statusMessage = statusElement();
		owner.retryButton = statusElement();
		owner.acknowledgedContent = acknowledged;
		owner.editor = { destroy() {}, getHTML: () => current };
		return {
			document: owner,
			setCurrent(value) {
				current = value;
			},
		};
	};
	return {
		IndependentDocument,
		makeDocument,
		requests,
		setGet(callback) {
			get = callback;
		},
		setPut(callback) {
			put = callback;
		},
		statusElement,
		loadedContainer,
	};
}

async function loadToolbar() {
	return await esmock.strict("../../src/script/elements/editor/toolbar.mjs", {
		"../../src/script/generated/styles.mjs": { STYLES: {} },
		"../../src/script/shared/transitions.mjs": {
			withTransition: (callback) => callback(),
		},
		"../../src/script/shared/utilities.mjs": {
			debounce: (callback) => Object.assign(callback, { cancel() {} }),
		},
		"../../src/script/elements/editor/config.mjs": {
			TOOLBAR_MENUS: {},
			TOOLBAR_TOOLS: [],
		},
		"../../src/script/elements/editor/dropdowns.mjs": {
			toolbarDropdown() {},
		},
		"../../src/script/elements/editor/options/markdownPaste.mjs": {
			MarkdownPastePrompt: class {},
		},
		"../../src/script/elements/editor/options/registry.mjs": {
			FORM_REGISTRY: {},
			OPTION_REGISTRY: {},
		},
		"../../src/script/elements/editor/users.mjs": { UserManager: class {} },
	});
}

/** @matrix editor html-field : listener-teardown builder-save */
test("test_editor_teardown_releases_toolbar_before_editor_view", async (t) => {
	const env = await setupEditor(t);
	const { document: owner } = env.makeDocument();
	let editorDestroyed = false;
	const order = [];
	owner.editor.destroy = () => {
		editorDestroyed = true;
		order.push("editor");
	};
	owner.toolbar = {
		destroy() {
			assert.equal(editorDestroyed, false);
			order.push("toolbar");
		},
	};
	owner.destroy();
	owner.destroy();
	assert.deepEqual(order, ["toolbar", "editor"]);

	const { Toolbar } = await loadToolbar();
	const removed = [];
	const events = [];
	let cancellations = 0;
	const toolbar = {
		_destroyed: false,
		editor: {
			get view() {
				throw new Error("Destroyed editor view accessed");
			},
			off(event) {
				events.push(event);
			},
		},
		editorDom: { removeEventListener: (event) => removed.push(event) },
		forms: {},
		editorState: { cancel: () => cancellations++ },
		toggleForm: { cancel: () => cancellations++ },
	};
	Toolbar.prototype.destroy.call(toolbar);
	Toolbar.prototype.destroy.call(toolbar);
	assert.deepEqual(events, ["transaction"]);
	assert.deepEqual(removed, ["click", "keydown", "editor-link-edit"]);
	assert.equal(cancellations, 2);
});

/** @matrix editor html-field : authoritative-content error-reporting initial-load retry */
test("test_independent_editor_failed_load_stays_inert_and_retries", async (t) => {
	const env = await setupEditor(t);
	const owner = new env.IndependentDocument({
		endpoints: { getContent: "/content", save: "/save" },
		target: document.createElement("div"),
	});
	owner.container = env.loadedContainer();
	owner.container.removeAttribute("loaded");
	owner.status = env.statusElement();
	owner.statusMessage = env.statusElement();
	owner.retryButton = env.statusElement();
	owner._publishLoadedContent = async (html) => {
		owner.published = html;
		owner.container.setAttribute("loaded", "");
	};
	const responses = [
		{ ok: false, error: "Load failed" },
		{ ok: true, markup: "  <p>Authoritative</p>  " },
	];
	env.setGet((...args) => {
		env.requests.get.push(args);
		return Promise.resolve(responses.shift());
	});
	assert.equal(await owner.load(), false);
	assert.equal(owner.container.hasAttribute("loaded"), false);
	assert.equal(owner.acknowledgedContent, null);
	assert.equal(owner._statusScope, "load");
	assert.equal(owner.retryButton.hidden, false);
	owner._retryFailedOperation();
	await owner.ready;
	assert.equal(owner.published, "<p>Authoritative</p>");
	assert.equal(owner.acknowledgedContent, "<p>Authoritative</p>");
	assert.equal(owner.container.hasAttribute("loaded"), true);
	assert.equal(owner.status.hidden, true);
	assert.equal(
		env.requests.get.every(
			([, , options]) => options.replaceErrorPage === false,
		),
		true,
	);
});

/** @matrix editor html-field : error-reporting retry server-acknowledgement */
test("test_independent_editor_failed_save_stays_dirty_and_retries", async (t) => {
	const env = await setupEditor(t);
	const { document: owner, setCurrent } = env.makeDocument();
	setCurrent("<p>Changed</p>");
	const responses = [{ ok: false, error: "Save failed" }, { ok: true }];
	env.setPut((...args) => {
		env.requests.put.push(args);
		return Promise.resolve(responses.shift());
	});
	assert.equal(await owner.flush(), false);
	assert.equal(owner.acknowledgedContent, "<p>Saved</p>");
	assert.equal(owner.dirtyContent, "<p>Changed</p>");
	assert.equal(owner._statusScope, "save");
	assert.equal(await owner.flush(), true);
	assert.equal(owner.acknowledgedContent, "<p>Changed</p>");
	assert.equal(owner.dirtyContent, null);
	assert.equal(env.requests.put.length, 2);
	assert.equal(
		env.requests.put.every(
			([, , options]) => options.replaceErrorPage === false,
		),
		true,
	);
});

/** @matrix editor html-field : concurrent-edit keepalive serialized-save server-acknowledgement */
test("test_independent_editor_serializes_inflight_edits_and_acknowledges_in_order", async (t) => {
	const env = await setupEditor(t);
	const { document: owner, setCurrent } = env.makeDocument();
	const releases = [];
	env.setPut((...args) => {
		env.requests.put.push(args);
		return new Promise((resolve) => releases.push(resolve));
	});
	setCurrent("<p>A</p>");
	const saving = owner.flush({ keepalive: true });
	await tick();
	assert.equal(env.requests.put.length, 1);
	assert.equal(env.requests.put[0][1].html, "<p>A</p>");
	setCurrent("<p>B</p>");
	releases[0]({ ok: true });
	await tick();
	assert.equal(owner.acknowledgedContent, "<p>A</p>");
	assert.equal(env.requests.put.length, 2);
	assert.equal(env.requests.put[1][1].html, "<p>B</p>");
	assert.equal(
		env.requests.put.every(([, , options]) => options.keepalive === true),
		true,
	);
	releases[1]({ ok: true });
	assert.equal(await saving, true);
	assert.equal(owner.acknowledgedContent, "<p>B</p>");
	assert.equal(owner.dirtyContent, null);
	setCurrent(`<p>${"x".repeat(70 * 1024)}</p>`);
	env.setPut((...args) => {
		env.requests.put.push(args);
		return Promise.resolve({ ok: true });
	});
	assert.equal(await owner.flush({ keepalive: true }), true);
	assert.equal(env.requests.put.at(-1)[2].keepalive, false);
});

/** @matrix editor html-field : intentional-clear server-acknowledgement */
test("test_independent_editor_saves_intentional_clear", async (t) => {
	const env = await setupEditor(t);
	const { document: owner, setCurrent } = env.makeDocument();
	setCurrent("<p><br></p>");
	env.setPut((...args) => {
		env.requests.put.push(args);
		return Promise.resolve({ ok: true });
	});
	assert.equal(await owner.flush(), true);
	assert.equal(env.requests.put.length, 1);
	assert.equal(env.requests.put[0][1].html, "");
	assert.equal(owner.acknowledgedContent, "");
	owner.destroy();
	await tick();
	assert.equal(env.requests.put.length, 1);
});

function emptyClass() {
	return class {};
}

async function loadBuilder(connectivity) {
	return await esmock.strict("../../src/script/views/builder/builder.mjs", {
		"../../src/script/elements/combobox/search.mjs": {
			SearchBox: emptyClass(),
		},
		"../../src/script/elements/entityMenu.mjs": { EntityMenu: emptyClass() },
		"../../src/script/shared/directUpload.mjs": { directUpload() {} },
		"../../src/script/shared/index.mjs": {
			captureError() {},
			connectivity,
			DeleteModal: emptyClass(),
			generateElementId: (type) => `${type}-1`,
			HelpModal: emptyClass(),
			OfflineModal: emptyClass(),
			request: {},
		},
		"../../src/script/shared/transitions.mjs": {
			withTransition: (callback) => callback(),
		},
		"../../src/script/views/builder/changeStatus.mjs": {
			FormChangeStatus: emptyClass(),
		},
		"../../src/script/views/builder/conditions/loader.mjs": {
			loadCondition: async () => null,
		},
		"../../src/script/views/builder/draft.mjs": { BuilderDraft: emptyClass() },
		"../../src/script/views/builder/migrations.mjs": {
			fieldKind: () => null,
			needsMigration: () => false,
			repairConditions() {},
		},
		"../../src/script/views/builder/panels/components.mjs": {
			ComponentsPanel: emptyClass(),
		},
		"../../src/script/views/builder/panels/condition.mjs": {
			ConditionPanel: emptyClass(),
		},
		"../../src/script/views/builder/panels/elementSettings.mjs": {
			ElementSettings: emptyClass(),
		},
		"../../src/script/views/builder/panels/formSettings.mjs": {
			FormSettings: emptyClass(),
		},
		"../../src/script/views/builder/panels/header.mjs": {
			Header: emptyClass(),
		},
		"../../src/script/views/builder/panels/model.mjs": {
			ModelElement: {},
			ModelPanel: emptyClass(),
		},
	});
}

/** @matrix editor html-field : teardown */
test("test_builder_owns_independent_editor_lifecycle_flushes", async (t) => {
	createBrowser(t);
	const connectivity = { online: true };
	const { default: FormBuilder } = await loadBuilder(connectivity);
	const calls = [];
	const editor = {
		async flush(options) {
			calls.push(options);
			return true;
		},
	};
	const builder = {
		_independentDocuments: new Set(),
		hidden: false,
		online: true,
		offline() {},
		flushIndependentDocuments: FormBuilder.prototype.flushIndependentDocuments,
	};
	FormBuilder.prototype.registerIndependentDocument.call(builder, editor);
	await FormBuilder.prototype.sync.call(builder, { hidden: true });
	assert.equal(calls.length, 1);
	assert.equal(calls[0].keepalive, true);
	connectivity.online = false;
	await FormBuilder.prototype.sync.call(builder, { hidden: true });
	assert.equal(calls.length, 1);
	connectivity.online = true;
	await FormBuilder.prototype.sync.call(builder, { hidden: false });
	assert.equal(calls.length, 2);
	assert.equal(calls[1].keepalive, false);
	FormBuilder.prototype.unregisterIndependentDocument.call(builder, editor);
	await FormBuilder.prototype.sync.call(builder, { hidden: true });
	assert.equal(calls.length, 2);
});
