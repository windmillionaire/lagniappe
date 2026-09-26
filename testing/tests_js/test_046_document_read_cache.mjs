import assert from "node:assert/strict";
import { test } from "node:test";
import * as Y from "yjs";
import { DocumentReadCache } from "../../src/script/elements/editor/readCache.mjs";

function cacheStorage(t) {
	const previous = { caches: globalThis.caches, location: globalThis.location };
	const stores = new Map();
	globalThis.location = { origin: "https://example.test" };
	globalThis.caches = {
		async open(name) {
			if (!stores.has(name)) {
				const entries = new Map();
				stores.set(name, {
					async match(key) {
						return entries.get(key)?.clone();
					},
					async put(key, response) {
						entries.set(key, response.clone());
					},
					async delete(key) {
						return entries.delete(key);
					},
				});
			}
			return stores.get(name);
		},
		async delete(name) {
			return stores.delete(name);
		},
	};
	t.after(() => Object.assign(globalThis, previous));
}

/** @matrix offline sync : cached-read delta empty-content persistence */
test("test_document_reads_retain_snapshots_and_deltas_without_pending_work", async (t) => {
	cacheStorage(t);
	const cache = new DocumentReadCache("alice:permissions", "page:document");
	await cache.accept({
		mode: "snapshot",
		markup: "<p>Original</p>",
		fingerprint: "one",
	});
	assert.equal((await cache.read()).markup, "<p>Original</p>");
	const document = new Y.Doc();
	t.after(() => document.destroy());
	const updates = [];
	document.on("update", (update) =>
		updates.push({ update: Buffer.from(update).toString("base64") }),
	);
	document.getText("content").insert(0, "First");
	await cache.accept({
		mode: "snapshot",
		ydoc: Buffer.from(Y.encodeStateAsUpdate(document)).toString("base64"),
	});
	document.getText("content").insert(5, " second");
	const firstWrite = cache.accept({ mode: "delta", updates: updates.slice(1) });
	document.getText("content").insert(12, " third");
	const secondWrite = cache.accept({
		mode: "delta",
		updates: updates.slice(2),
	});
	await Promise.all([firstWrite, secondWrite]);
	const retained = await new DocumentReadCache(
		"alice:permissions",
		"page:document",
	).read();
	const restored = new Y.Doc();
	t.after(() => restored.destroy());
	Y.applyUpdate(restored, Buffer.from(retained.ydoc, "base64"));
	for (const update of retained.updates)
		Y.applyUpdate(restored, Buffer.from(update.update, "base64"));
	assert.equal(restored.getText("content").toString(), "First second third");
	assert.equal(retained.updates.length, 1, "deltas stay compact");
	await cache.accept({ mode: "snapshot", markup: "", ydoc: null, updates: [] });
	assert.deepEqual(await cache.read(), {
		mode: "snapshot",
		markup: "",
		ydoc: null,
		updates: [],
	});
	await cache.accept({
		mode: "delta",
		users: [{ hash: "other" }],
		updates: [],
	});
	assert.equal(
		(await cache.read()).markup,
		"",
		"presence does not replace content",
	);
});

/** @matrix offline sync : cached-read invalidation storage-failure user-scope */
test("test_document_read_cache_is_scoped_best_effort_and_invalidatable", async (t) => {
	cacheStorage(t);
	const cache = new DocumentReadCache("alice:permissions", "page:document");
	const snapshot = { mode: "snapshot", markup: "Private content" };
	await cache.accept(snapshot);
	assert.equal(
		await new DocumentReadCache("bob:permissions", "page:document").read(),
		null,
	);
	assert.equal(
		await new DocumentReadCache(
			"alice:new-permissions",
			"page:document",
		).read(),
		null,
	);
	await cache.clear();
	assert.equal(await cache.read(), null);
	await cache.accept(snapshot);
	await caches.delete("response-cache");
	await cache.accept(snapshot); // Late completion must not recreate the cache.
	assert.equal(
		await new DocumentReadCache("alice:permissions", "page:document").read(),
		null,
	);
	globalThis.caches.open = async () => {
		throw new Error("Storage disabled");
	};
	const disabled = new DocumentReadCache("alice:permissions", "page:document");
	await disabled.accept(snapshot);
	assert.equal(await disabled.read(), null);
	await disabled.clear();
});
