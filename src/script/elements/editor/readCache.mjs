import { mergeUpdates } from "yjs";
import {
	base64ToUint8Array,
	uint8ArrayToBase64,
} from "../../shared/utilities.mjs";

/**
 * Retain server document reads separately from pending offline edits. Sharing
 * the response cache also shares logout/permission/build invalidation and
 * quota eviction. A retained handle cannot recreate a deleted cache.
 *
 * @testable true
 * @tests tests_js/test_046_document_read_cache.mjs::test_document_reads_retain_snapshots_and_deltas_without_pending_work
 * @tests tests_js/test_046_document_read_cache.mjs::test_document_read_cache_is_scoped_best_effort_and_invalidatable
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_read_document_survives_offline_reload_without_saving
 * @matrix offline sync : cached-read delta empty-content invalidation persistence reload save-guard storage-failure user-scope
 */
export class DocumentReadCache {
	constructor(scope, syncId) {
		this.key =
			scope && syncId
				? new URL(
						`/offline-document/${encodeURIComponent(scope)}/${encodeURIComponent(syncId)}`,
						globalThis.location.origin,
					).href
				: null;
		this.cache = this.key
			? Promise.resolve()
					.then(() => globalThis.caches?.open("response-cache"))
					.catch(() => null)
			: Promise.resolve(null);
		this.pending = Promise.resolve();
	}

	async read() {
		await this.pending;
		try {
			const cache = await this.cache;
			const response = await cache?.match(this.key);
			return response ? await response.json() : null;
		} catch {
			return null;
		}
	}

	accept(payload) {
		// Presence-only deltas don't change the retained content.
		if (payload?.mode !== "snapshot" && !payload?.updates?.length)
			return this.pending;
		return this._queue(async (cache) => {
			const previous =
				payload.mode === "snapshot"
					? payload
					: await (await cache.match(this.key))?.json();
			if (!previous) return;
			const updates = [
				...(previous.updates ?? []),
				...(previous === payload ? [] : (payload.updates ?? [])),
			]
				.filter((item) => item.update)
				.map((item) => base64ToUint8Array(item.update));
			const snapshot = {
				mode: "snapshot",
				ydoc: previous.ydoc ?? null,
				markup: previous.markup ?? null,
				fingerprint: payload.fingerprint ?? previous.fingerprint,
				updates: updates.length
					? [{ update: uint8ArrayToBase64(mergeUpdates(updates)) }]
					: [],
			};
			await cache.put(
				this.key,
				new Response(JSON.stringify(snapshot), {
					headers: { "Content-Type": "application/json" },
				}),
			);
		});
	}

	clear() {
		return this._queue((cache) => cache.delete(this.key));
	}

	_queue(operation) {
		this.pending = this.pending
			.then(async () => {
				const cache = await this.cache;
				if (cache) await operation(cache);
			})
			.catch(() => undefined); // Storage availability never blocks online use.
		return this.pending;
	}
}
