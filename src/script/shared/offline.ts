import type {
	PersistedSyncRecord,
	SyncMention,
	SyncUpdate,
} from "../types/sync";

const DB_NAME = "offline-db";
const DB_VERSION = 5;
const SYNC_STORE = "sync";
const MUTATION_STORE = "mutations";

type StoreName = typeof SYNC_STORE | typeof MUTATION_STORE;

export interface StoredOfflineMutation extends Record<string, unknown> {
	id: string;
}

function openDB() {
	return new Promise<IDBDatabase>((resolve, reject) => {
		const request = indexedDB.open(DB_NAME, DB_VERSION);
		request.onerror = () => reject(request.error);
		request.onsuccess = () => resolve(request.result);
		request.onupgradeneeded = (event) => {
			const db = request.result;
			if (event.oldVersion < 2) {
				// The store fields were renamed sync_id (snake_case) to match the
				// wire format; nuke old v1 stores so the keyPath matches records.
				if (db.objectStoreNames.contains(SYNC_STORE)) {
					db.deleteObjectStore(SYNC_STORE);
				}
			}
			if (!db.objectStoreNames.contains(SYNC_STORE)) {
				db.createObjectStore(SYNC_STORE, { keyPath: "sync_id" });
			}

			if (db.objectStoreNames.contains("activity")) {
				db.deleteObjectStore("activity");
			}
			if (db.objectStoreNames.contains("submit")) {
				db.deleteObjectStore("submit");
			}
			if (!db.objectStoreNames.contains(MUTATION_STORE)) {
				db.createObjectStore(MUTATION_STORE, { keyPath: "id" });
			}
		};
	});
}

function withTransaction<T>(
	storeNames: StoreName | StoreName[],
	mode: IDBTransactionMode,
	executor: (transaction: IDBTransaction) => T | Promise<T>,
): Promise<T> {
	return openDB().then(
		(db) =>
			new Promise<T>((resolve, reject) => {
				let tx: IDBTransaction | null = null;
				let transactionComplete = false;
				let operationResult: { value: T } | null = null;
				let firstError: unknown = null;
				let settled = false;
				let databaseClosed = false;

				const closeDatabase = () => {
					if (databaseClosed) return;
					databaseClosed = true;
					db.onclose = null;
					db.close();
				};
				const rememberError = (error: unknown) => {
					firstError ||=
						error || tx?.error || new Error("IndexedDB transaction failed");
					return firstError;
				};
				const rejectOnce = (error: unknown) => {
					if (settled) return;
					settled = true;
					closeDatabase();
					reject(rememberError(error));
				};
				const resolveAfterCommit = () => {
					if (settled || !operationResult || !transactionComplete) return;
					settled = true;
					closeDatabase();
					resolve(operationResult.value);
				};
				const abortWithError = (error: unknown) => {
					rememberError(error);
					try {
						tx?.abort();
					} catch {
						// A transaction that already completed cannot be aborted. The
						// original executor error remains the useful failure.
					}
					rejectOnce(firstError);
				};

				db.onversionchange = closeDatabase;
				db.onclose = () => {
					rejectOnce(new Error("IndexedDB database closed unexpectedly"));
				};

				try {
					tx = db.transaction(storeNames, mode);
				} catch (e) {
					rejectOnce(e);
					return;
				}

				tx.oncomplete = () => {
					transactionComplete = true;
					resolveAfterCommit();
				};
				tx.onerror = (event) => {
					const target = event.target;
					const error = target && "error" in target ? target.error : null;
					rejectOnce(error || tx?.error);
				};
				tx.onabort = () => {
					rejectOnce(tx?.error || new Error("IndexedDB transaction aborted"));
				};

				let operation: T | Promise<T>;
				try {
					operation = executor(tx);
				} catch (e) {
					abortWithError(e);
					return;
				}
				Promise.resolve(operation).then((result) => {
					operationResult = { value: result };
					resolveAfterCommit();
				}, abortWithError);
			}),
	);
}

function promisify<T>(request: IDBRequest<T>): Promise<T> {
	return new Promise<T>((resolve, reject) => {
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error);
	});
}

function isStoredRecord(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isStoredMutation(value: unknown): value is StoredOfflineMutation {
	return isStoredRecord(value) && typeof value.id === "string";
}

function isOptionalText(value: unknown) {
	return value === undefined || value === null || typeof value === "string";
}

function isStoredMention(value: unknown): value is SyncMention {
	return (
		isStoredRecord(value) &&
		typeof value.occurrence_id === "string" &&
		typeof value.recipient === "string" &&
		typeof value.display_name === "string"
	);
}

function isStoredSyncRecord(value: unknown): value is PersistedSyncRecord {
	return (
		isStoredRecord(value) &&
		typeof value.sync_id === "string" &&
		typeof value.key === "string" &&
		isOptionalText(value.update) &&
		isOptionalText(value.ydoc) &&
		isOptionalText(value.html) &&
		isOptionalText(value.generation) &&
		isOptionalText(value.presence_digest) &&
		isOptionalText(value.fingerprint) &&
		(value.revision === undefined ||
			value.revision === null ||
			typeof value.revision === "number") &&
		(value.mentions === undefined ||
			value.mentions === null ||
			(Array.isArray(value.mentions) &&
				value.mentions.every(isStoredMention))) &&
		(value.touch_parent === undefined ||
			typeof value.touch_parent === "boolean") &&
		(value.save === undefined || typeof value.save === "boolean") &&
		(value.timestamp === undefined || typeof value.timestamp === "number")
	);
}

export function updateSyncRecord(record: SyncUpdate) {
	const timestamp = Date.now();
	return withTransaction(SYNC_STORE, "readwrite", async (tx) => {
		const store = tx.objectStore(SYNC_STORE);
		const stored = await promisify<unknown>(store.get(record.sync_id));
		const existing = isStoredRecord(stored) ? stored : null;
		const merged = existing
			? {
					...existing,
					...record,
					save: existing.save || record.save,
					timestamp,
				}
			: { ...record, timestamp };
		if (existing && !Object.hasOwn(record, "html")) delete merged.html;
		if (existing && !Object.hasOwn(record, "mentions")) delete merged.mentions;
		await promisify(store.put(merged));
	});
}

export function getSyncRecord(sync_id: string) {
	return withTransaction([SYNC_STORE], "readonly", async (tx) => {
		const record = await promisify<unknown>(
			tx.objectStore(SYNC_STORE).get(sync_id),
		);
		return isStoredSyncRecord(record) ? record : null;
	});
}

export function getAllOfflineRecords() {
	return withTransaction(
		[SYNC_STORE, MUTATION_STORE],
		"readonly",
		async (tx) => {
			const sync = await promisify<unknown[]>(
				tx.objectStore(SYNC_STORE).getAll(),
			);
			const mutations = await promisify<unknown[]>(
				tx.objectStore(MUTATION_STORE).getAll(),
			);
			return {
				sync: sync.filter(isStoredSyncRecord),
				mutations: mutations.filter(isStoredMutation),
			};
		},
	);
}

export function deleteSyncRecord(sync_id: string) {
	return withTransaction(SYNC_STORE, "readwrite", async (tx) => {
		await promisify(tx.objectStore(SYNC_STORE).delete(sync_id));
	});
}

export function deleteSyncRecords(sync_ids?: readonly string[] | null) {
	if (!sync_ids?.length) return Promise.resolve();
	return withTransaction(SYNC_STORE, "readwrite", async (tx) => {
		const store = tx.objectStore(SYNC_STORE);
		await Promise.all(sync_ids.map((id) => promisify(store.delete(id))));
	});
}

export function setOfflineMutation<T extends { id: string }>(record: T) {
	return withTransaction(MUTATION_STORE, "readwrite", async (tx) => {
		await promisify(tx.objectStore(MUTATION_STORE).put(record));
	});
}

export function getOfflineMutations() {
	return withTransaction(MUTATION_STORE, "readonly", async (tx) => {
		const records = await promisify<unknown[]>(
			tx.objectStore(MUTATION_STORE).getAll(),
		);
		return records.filter(isStoredMutation);
	});
}

export function deleteOfflineMutations(ids?: readonly string[] | null) {
	if (!ids?.length) return Promise.resolve();
	return withTransaction(MUTATION_STORE, "readwrite", async (tx) => {
		const store = tx.objectStore(MUTATION_STORE);
		await Promise.all(ids.map((id) => promisify(store.delete(id))));
	});
}
