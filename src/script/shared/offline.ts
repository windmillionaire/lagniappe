const DB_NAME = "offline-db";
const DB_VERSION = 5;
const SYNC_STORE = "sync";
const MUTATION_STORE = "mutations";

function openDB() {
	return new Promise((resolve, reject) => {
		const request = indexedDB.open(DB_NAME, DB_VERSION);
		request.onerror = () => reject(request.error);
		request.onsuccess = () => resolve(request.result);
		request.onupgradeneeded = (event) => {
			const db = event.target.result;
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

function withTransaction(storeNames, mode, executor) {
	return openDB().then(
		(db) =>
			new Promise((resolve, reject) => {
				let tx = null;
				let operationComplete = false;
				let transactionComplete = false;
				let operationResult;
				let firstError = null;
				let settled = false;
				let databaseClosed = false;

				const closeDatabase = () => {
					if (databaseClosed) return;
					databaseClosed = true;
					db.onclose = null;
					db.close();
				};
				const rememberError = (error) => {
					firstError ||=
						error || tx?.error || new Error("IndexedDB transaction failed");
					return firstError;
				};
				const rejectOnce = (error) => {
					if (settled) return;
					settled = true;
					closeDatabase();
					reject(rememberError(error));
				};
				const resolveAfterCommit = () => {
					if (settled || !operationComplete || !transactionComplete) return;
					settled = true;
					closeDatabase();
					resolve(operationResult);
				};
				const abortWithError = (error) => {
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
					rejectOnce(event.target?.error || tx.error);
				};
				tx.onabort = () => {
					rejectOnce(tx.error || new Error("IndexedDB transaction aborted"));
				};

				let operation;
				try {
					operation = executor(tx);
				} catch (e) {
					abortWithError(e);
					return;
				}
				Promise.resolve(operation).then((result) => {
					operationResult = result;
					operationComplete = true;
					resolveAfterCommit();
				}, abortWithError);
			}),
	);
}

function promisify(request) {
	return new Promise((resolve, reject) => {
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error);
	});
}

export function updateSyncRecord(record) {
	const timestamp = Date.now();
	return withTransaction(SYNC_STORE, "readwrite", async (tx) => {
		const store = tx.objectStore(SYNC_STORE);
		const existing = await promisify(store.get(record.sync_id));
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

export function getSyncRecord(sync_id) {
	return withTransaction([SYNC_STORE], "readonly", async (tx) => {
		const record = await promisify(tx.objectStore(SYNC_STORE).get(sync_id));
		return record ?? null;
	});
}

export function getAllOfflineRecords() {
	return withTransaction(
		[SYNC_STORE, MUTATION_STORE],
		"readonly",
		async (tx) => {
			const sync = await promisify(tx.objectStore(SYNC_STORE).getAll());
			const mutations = await promisify(
				tx.objectStore(MUTATION_STORE).getAll(),
			);
			return { sync, mutations };
		},
	);
}

export function deleteSyncRecord(sync_id) {
	return withTransaction(SYNC_STORE, "readwrite", async (tx) => {
		await promisify(tx.objectStore(SYNC_STORE).delete(sync_id));
	});
}

export function deleteSyncRecords(sync_ids) {
	if (!sync_ids?.length) return Promise.resolve();
	return withTransaction(SYNC_STORE, "readwrite", async (tx) => {
		const store = tx.objectStore(SYNC_STORE);
		await Promise.all(sync_ids.map((id) => promisify(store.delete(id))));
	});
}

export function setOfflineMutation(record) {
	return withTransaction(MUTATION_STORE, "readwrite", async (tx) => {
		await promisify(tx.objectStore(MUTATION_STORE).put(record));
	});
}

export function getOfflineMutations() {
	return withTransaction(MUTATION_STORE, "readonly", async (tx) => {
		return await promisify(tx.objectStore(MUTATION_STORE).getAll());
	});
}

export function deleteOfflineMutations(ids) {
	if (!ids?.length) return Promise.resolve();
	return withTransaction(MUTATION_STORE, "readwrite", async (tx) => {
		const store = tx.objectStore(MUTATION_STORE);
		await Promise.all(ids.map((id) => promisify(store.delete(id))));
	});
}
