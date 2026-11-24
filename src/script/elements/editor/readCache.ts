import { mergeUpdates } from "yjs";
import {
	base64ToUint8Array,
	uint8ArrayToBase64,
} from "../../shared/utilities.ts";

import type { DocumentState } from "../../types/sync.d.ts";

type CachedSnapshot = Extract<DocumentState, { mode: "snapshot" }>;

/**
 * Retain server document reads separately from pending offline edits. Sharing
 * the response cache also shares logout/permission/build invalidation and
 * quota eviction. A retained handle cannot recreate a deleted cache.
 *
 */
export class DocumentReadCache {
	declare key: string | null;
	declare cache: Promise<Cache | null | undefined>;
	declare pending: Promise<void>;
	constructor(scope: string | undefined, syncId: string | null) {
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

	async read(): Promise<CachedSnapshot | null> {
		await this.pending;
		try {
			const cache = await this.cache;
			if (!this.key || !cache) return null;
			const response = await cache.match(this.key);
			return response ? ((await response.json()) as CachedSnapshot) : null;
		} catch {
			return null;
		}
	}

	accept(payload: DocumentState | null | undefined) {
		// Presence-only deltas don't change the retained content.
		if (payload?.mode !== "snapshot" && !payload?.updates?.length)
			return this.pending;
		return this._queue(async (cache, key) => {
			const previous: CachedSnapshot | null | undefined =
				payload.mode === "snapshot"
					? payload
					: await (await cache.match(key))?.json();
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
				key,
				new Response(JSON.stringify(snapshot), {
					headers: { "Content-Type": "application/json" },
				}),
			);
		});
	}

	clear() {
		return this._queue((cache, key) => cache.delete(key));
	}

	_queue(operation: (cache: Cache, key: string) => Promise<unknown>) {
		this.pending = this.pending
			.then(async () => {
				const cache = await this.cache;
				if (cache && this.key) await operation(cache, this.key);
			})
			.catch(() => undefined); // Storage availability never blocks online use.
		return this.pending;
	}
}
