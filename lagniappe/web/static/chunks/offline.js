/*! Third-party licenses: /third-party-licenses.txt */
const DB_NAME = "offline-db";
const DB_VERSION = 5;
const SYNC_STORE = "sync";
const MUTATION_STORE = "mutations";

/**
 * @testable true
 * @tests tests_js/test_028_form_state_split.py::test_offline_database_upgrade_discards_legacy_activity_records
 * @features offline
 * @dimensions database-upgrade legacy-record-discard mutation-store
 */
function openDB() {
	return new Promise((resolve, reject) => {
		const request = indexedDB.open(DB_NAME, DB_VERSION);
		request.onerror = () => reject(request.error);
		request.onsuccess = () => {
			const db = request.result;
			db.onversionchange = () => db.close();
			resolve(db);
		};
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
 * @testable false
 * @covered-by src/script/shared/offline.mjs::updateSyncRecord
 * @covered-by src/script/shared/offline.mjs::getAllOfflineRecords
 * @reason transaction wrapper is exercised through the offline record API
 */
function withTransaction(storeNames, mode, executor) {
	return openDB().then(
		(db) =>
			new Promise((resolve, reject) => {
				const tx = db.transaction(storeNames, mode);
				tx.oncomplete = () => db.close();
				tx.onerror = () => {
					db.close();
					reject(tx.error);
				};
				try {
					executor(tx, resolve, reject);
				} catch (e) {
					reject(e);
				}
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
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_replay_does_not_duplicate_after_reload
 * @features sync
 * @dimensions offline-replay replay-order queue-preserved dedupe reload
 */
function updateSyncRecord(record) {
	const timestamp = Date.now();
	return withTransaction(
		SYNC_STORE,
		"readwrite",
		async (tx, resolve, reject) => {
			const store = tx.objectStore(SYNC_STORE);
			try {
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
				if (existing && !Object.hasOwn(record, "mentions"))
					delete merged.mentions;
				await promisify(store.put(merged));
				resolve();
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable false
 * @covered-by src/script/shared/sync.mjs::SyncManager.state
 * @reason single-record lookup is owned by the widget state sync path
 */
function getSyncRecord(sync_id) {
	return withTransaction(
		[SYNC_STORE],
		"readonly",
		async (tx, resolve, reject) => {
			try {
				const record = await promisify(tx.objectStore(SYNC_STORE).get(sync_id));
				resolve(record ?? null);
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_failed_offline_replay_keeps_queue_and_retries
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_replay_does_not_duplicate_after_reload
 * @features sync
 * @dimensions offline-replay replay-order queue-preserved dedupe reload
 */
function getAllOfflineRecords() {
	return withTransaction(
		[SYNC_STORE, MUTATION_STORE],
		"readonly",
		async (tx, resolve, reject) => {
			try {
				const sync = await promisify(tx.objectStore(SYNC_STORE).getAll());
				const mutations = await promisify(
					tx.objectStore(MUTATION_STORE).getAll(),
				);
				resolve({ sync, mutations });
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable false
 * @covered-by src/script/shared/sync.mjs::SyncManager._reconcile
 * @reason single-record deletion is owned by successful state reconciliation
 */
function deleteSyncRecord(sync_id) {
	return withTransaction(
		SYNC_STORE,
		"readwrite",
		async (tx, resolve, reject) => {
			try {
				await promisify(tx.objectStore(SYNC_STORE).delete(sync_id));
				resolve();
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_replay_does_not_duplicate_after_reload
 * @features sync
 * @dimensions offline-replay queue-clear dedupe
 */
function deleteSyncRecords(sync_ids) {
	if (!sync_ids?.length) return Promise.resolve();
	return withTransaction(
		SYNC_STORE,
		"readwrite",
		async (tx, resolve, reject) => {
			try {
				const store = tx.objectStore(SYNC_STORE);
				await Promise.all(sync_ids.map((id) => promisify(store.delete(id))));
				resolve();
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_create_mutations_persist_after_reload
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
 * @pairs offline:queue-create offline:queue-submit offline:reload
 */
function setOfflineMutation(record) {
	return withTransaction(
		MUTATION_STORE,
		"readwrite",
		async (tx, resolve, reject) => {
			try {
				await promisify(tx.objectStore(MUTATION_STORE).put(record));
				resolve();
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_reload_uses_server_state_until_replay
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_mutations_replay_when_online
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
 * @features offline
 * @dimensions durable-queue server-first replay queue-submit
 */
function getOfflineMutations() {
	return withTransaction(
		MUTATION_STORE,
		"readonly",
		async (tx, resolve, reject) => {
			try {
				const records = await promisify(
					tx.objectStore(MUTATION_STORE).getAll(),
				);
				resolve(records);
			} catch (e) {
				reject(e);
			}
		},
	);
}

/**
 * @testable true
 * @tests tests_e2e/002_home/test_002i_home_activity.py::test_offline_home_mutations_replay_when_online
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_lp_offline_submit_replays_and_notifies
 * @pairs offline:replay offline:queue-clear offline:notification
 */
function deleteOfflineMutations(ids) {
	if (!ids?.length) return Promise.resolve();
	return withTransaction(
		MUTATION_STORE,
		"readwrite",
		async (tx, resolve, reject) => {
			try {
				const store = tx.objectStore(MUTATION_STORE);
				await Promise.all(ids.map((id) => promisify(store.delete(id))));
				resolve();
			} catch (e) {
				reject(e);
			}
		},
	);
}

export { deleteOfflineMutations, deleteSyncRecord, deleteSyncRecords, getAllOfflineRecords, getOfflineMutations, getSyncRecord, setOfflineMutation, updateSyncRecord };
