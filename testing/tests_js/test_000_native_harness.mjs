import assert from "node:assert/strict";
import {
	mkdtempSync,
	readFileSync,
	rmSync,
	statSync,
	unlinkSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";
import {
	createBrowser,
	installIndexedDB,
	mockFetch,
	useClock,
} from "../utility/js/environment.mjs";

test("test_browser_forms_events_and_storage_use_one_dom", (t) => {
	createBrowser(t, { html: '<form><input name="title" value="hello"></form>' });
	const form = document.querySelector("form");
	assert.equal(new FormData(form).get("title"), "hello");
	let observed;
	form.addEventListener("changed", (event) => {
		observed = event.detail;
	});
	form.dispatchEvent(new CustomEvent("changed", { detail: { title: "next" } }));
	assert.deepEqual(observed, { title: "next" });
	localStorage.setItem("example", "value");
	assert.equal(window.localStorage.getItem("example"), "value");
	assert.equal(
		new File(["content"], "example.txt") instanceof window.File,
		true,
	);
});

test("test_indexeddb_commits_binary_payloads_and_aborts_changes", async (t) => {
	createBrowser(t, { formData: "native" });
	const factory = installIndexedDB(t);
	assert.equal(window.indexedDB, factory);
	const storage = await import("../../src/script/shared/offline.mjs");
	const file = new File(["payload"], "upload.txt", { type: "text/plain" });
	await storage.setOfflineMutation({
		id: "kept",
		files: [{ file, filename: file.name }],
	});
	const rows = await storage.getOfflineMutations();
	assert.equal(await rows[0].files[0].file.text(), "payload");
	assert.equal(rows[0].files[0].filename, "upload.txt");
	const db = await new Promise((resolve, reject) => {
		const open = factory.open("offline-db");
		open.onsuccess = () => resolve(open.result);
		open.onerror = () => reject(open.error);
	});
	const transaction = db.transaction("mutations", "readwrite");
	const aborted = new Promise((resolve) => {
		transaction.onabort = resolve;
	});
	transaction.objectStore("mutations").put({ id: "aborted" });
	transaction.abort();
	await aborted;
	db.close();
	assert.deepEqual(
		(await storage.getOfflineMutations()).map(({ id }) => id),
		["kept"],
	);
	await storage.deleteOfflineMutations(["kept"]);
	assert.deepEqual(await storage.getOfflineMutations(), []);
});

test("test_fetch_records_requests_and_handles_errors_and_cancellation", async (t) => {
	createBrowser(t);
	const network = mockFetch(t, ({ url }) => {
		if (url.pathname === "/ok") return Response.json({ saved: true });
		if (url.pathname === "/error") throw new TypeError("offline");
		if (url.pathname === "/wait") return new Promise(() => {});
	});
	assert.deepEqual(
		await (await window.fetch("/ok", { method: "POST" })).json(),
		{ saved: true },
	);
	assert.equal(network.calls[0].method, "POST");
	assert.equal(network.calls[0].url.href, "https://lagniappe.test/ok");
	assert.equal((await fetch(new window.URL("/ok", window.location))).ok, true);
	const request = new Request("https://lagniappe.test/ok", {
		method: "POST",
		body: "payload",
	});
	assert.equal((await fetch(request)).ok, true);
	assert.equal(network.calls.at(-1).method, "POST");
	assert.equal(await network.calls.at(-1).input.text(), "payload");
	await assert.rejects(fetch("/error"), /offline/);
	const controller = new AbortController();
	const pending = fetch("/wait", { signal: controller.signal });
	controller.abort();
	await assert.rejects(pending, { name: "AbortError" });
});

test("test_request_parses_server_html_through_mocked_fetch", async (t) => {
	createBrowser(t);
	const network = mockFetch(t, ({ url, method }) => {
		if (url.pathname === "/example" && method === "GET") {
			return new Response('<p data-role="result">Saved</p>', {
				headers: { "content-type": "text/html" },
			});
		}
	});
	const { request } = await import("../../src/script/shared/request.mjs");
	const response = await request.get("/example");
	assert.equal(response.ok, true);
	assert.equal(response.html.querySelector("p").textContent, "Saved");
	assert.equal(network.calls.length, 1);
});

test("test_clock_coordinates_global_and_window_timers", (t) => {
	createBrowser(t);
	const clock = useClock(t, { now: 100 });
	const observed = [];
	setTimeout(() => observed.push(Date.now()), 10);
	window.setTimeout(() => observed.push(window.Date.now()), 20);
	clock.tick(20);
	assert.deepEqual(observed, [120, 120]);
});

test("test_unmocked_queue_graph_imports_with_browser_environment", async (t) => {
	createBrowser(t);
	installIndexedDB(t);
	const { OfflineQueue } = await import(
		"../../src/script/shared/offlineQueue.mjs"
	);
	const queue = new OfflineQueue({ online: false, components: {} });
	await queue.init();
	assert.deepEqual(queue.records, []);
	assert.equal(await queue.replay(), 0);
});

/** @pair style-build:runtime-parity */
test("test_registry_generation_is_idempotent_and_repairs_missing_outputs", async () => {
	const { generateStyleModules, STYLE_PIPELINE } = await import(
		"../../build/utility.mjs"
	);
	const root = mkdtempSync(join(tmpdir(), "lagniappe-registries-"));
	const cwd = process.cwd();
	try {
		process.chdir(root);
		generateStyleModules();
		const file = join(root, STYLE_PIPELINE.registry.javascript_styles);
		const before = statSync(file).mtimeMs;
		const source = readFileSync(file, "utf8");
		generateStyleModules();
		assert.equal(statSync(file).mtimeMs, before);
		unlinkSync(file);
		generateStyleModules();
		assert.equal(readFileSync(file, "utf8"), source);
		const { STYLES } = await import(pathToFileURL(file));
		assert.equal(typeof STYLES.button.submit, "string");
		assert.ok(
			readFileSync(STYLE_PIPELINE.registry.python_styles, "utf8").includes(
				JSON.stringify(STYLES.button.submit),
			),
		);
	} finally {
		process.chdir(cwd);
		rmSync(root, { recursive: true, force: true });
	}
});

test("test_generated_styles_and_icons_render_a_real_button", async (t) => {
	createBrowser(t);
	const { buttons } = await import("../../src/script/elements/buttons.mjs");
	const { STYLES } = await import("../../src/script/generated/styles.mjs");
	const button = buttons.default({ text: "Create page", icon: "page" });
	assert.equal(button.className, STYLES.button.submit);
	assert.equal(
		button.querySelector('[data-icon="page"] .icon-glyph').textContent,
		"draft",
	);
	assert.ok(button.textContent.includes("Create page"));
});
