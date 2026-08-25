const DB_NAME = "offline-db";
const DB_VERSION = 5;
const SYNC_STORE = "sync";
const MUTATION_STORE = "mutations";

/**
 * @testable true
 * @tests tests_js/test_028_form_state_split.py::test_offline_database_upgrade_discards_legacy_activity_records
 * @matrix offline : database-upgrade legacy-record-discard mutation-store
 */
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

/**
 * @testable true
 * @tests tests_js/test_045_browser_persistence.py::test_indexeddb_operations_resolve_only_after_transaction_commit
 * @tests tests_js/test_045_browser_persistence.py::test_indexeddb_abort_and_errors_reject_once_and_close_the_database
 * @tests tests_js/test_045_browser_persistence.py::test_indexeddb_executor_failures_abort_and_preserve_the_original_error
 * @matrix offline sync : connection-lifecycle error-ownership executor-error multi-delete readonly-result transaction-abort transaction-commit
 */
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

				/**
				 * @testable false
				 * @covered-by src/script/shared/offline.mjs::withTransaction
				 * @reason connection closure is private transaction settlement plumbing
				 */
				const closeDatabase = () => {
					if (databaseClosed) return;
					databaseClosed = true;
					db.onclose = null;
					db.close();
				};
				/**
				 * @testable false
				 * @covered-by src/script/shared/offline.mjs::withTransaction
				 * @reason first-error retention is private transaction settlement plumbing
				 */
				const rememberError = (error) => {
					firstError ||=
						error || tx?.error || new Error("IndexedDB transaction failed");
					return firstError;
				};
				/**
				 * @testable false
				 * @covered-by src/script/shared/offline.mjs::withTransaction
				 * @reason rejection ownership is private transaction settlement plumbing
				 */
				const rejectOnce = (error) => {
					if (settled) return;
					settled = true;
					closeDatabase();
					reject(rememberError(error));
				};
				/**
				 * @testable false
				 * @covered-by src/script/shared/offline.mjs::withTransaction
				 * @reason commit gating is private transaction settlement plumbing
				 */
				const resolveAfterCommit = () => {
					if (settled || !operationComplete || !transactionComplete) return;
					settled = true;
					closeDatabase();
					resolve(operationResult);
				};
				/**
				 * @testable false
				 * @covered-by src/script/shared/offline.mjs::withTransaction
				 * @reason executor abort handling is private transaction settlement plumbing
				 */
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

/**
 * @testable false
 * @covered-by src/script/shared/offline.mjs::updateSyncRecord
 * @covered-by src/script/shared/offline.mjs::getAllOfflineRecords
 * @reason request promisification is private IndexedDB plumbing
 */
function promisify(request) {
	return new Promise((resolve, reject) => {
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error);
	});
}

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_failed_offline_replay_keeps_queue_and_retries
 * @matrix sync : offline-replay queue-preserved replay-order
 */
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

/**
 * @testable false
 * @covered-by src/script/shared/sync.mjs::SyncManager.state
 * @reason single-record lookup is owned by the widget state sync path
 */
export function getSyncRecord(sync_id) {
	return withTransaction([SYNC_STORE], "readonly", async (tx) => {
		const record = await promisify(tx.objectStore(SYNC_STORE).get(sync_id));
		return record ?? null;
	});
}

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_failed_offline_replay_keeps_queue_and_retries
 * @matrix sync : offline-replay queue-preserved replay-order
 */
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

/**
 * @testable false
 * @covered-by src/script/shared/sync.mjs::SyncManager._reconcile
 * @reason single-record deletion is owned by successful state reconciliation
 */
export function deleteSyncRecord(sync_id) {
	return withTransaction(SYNC_STORE, "readwrite", async (tx) => {
		await promisify(tx.objectStore(SYNC_STORE).delete(sync_id));
	});
}

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
 * @matrix sync : offline-replay queue-clear
 */
export function deleteSyncRecords(sync_ids) {
	if (!sync_ids?.length) return Promise.resolve();
	return withTransaction(SYNC_STORE, "readwrite", async (tx) => {
		const store = tx.objectStore(SYNC_STORE);
		await Promise.all(sync_ids.map((id) => promisify(store.delete(id))));
	});
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_create_mutations_persist_after_reload
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
 * @matrix offline : queue-create queue-submit reload
 */
export function setOfflineMutation(record) {
	return withTransaction(MUTATION_STORE, "readwrite", async (tx) => {
		await promisify(tx.objectStore(MUTATION_STORE).put(record));
	});
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_reload_uses_server_state_until_replay
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_mutations_replay_when_online
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
 * @matrix offline : durable-queue queue-submit replay server-first
 */
export function getOfflineMutations() {
	return withTransaction(MUTATION_STORE, "readonly", async (tx) => {
		return await promisify(tx.objectStore(MUTATION_STORE).getAll());
	});
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_mutations_replay_when_online
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
 * @matrix offline : notification queue-clear replay
 */
export function deleteOfflineMutations(ids) {
	if (!ids?.length) return Promise.resolve();
	return withTransaction(MUTATION_STORE, "readwrite", async (tx) => {
		const store = tx.objectStore(MUTATION_STORE);
		await Promise.all(ids.map((id) => promisify(store.delete(id))));
	});
}
