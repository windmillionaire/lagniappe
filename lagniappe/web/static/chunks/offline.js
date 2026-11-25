/*! Third-party licenses: /third-party-licenses.txt */
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
      const db = request.result;
      if (event.oldVersion < 2) {
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
    (db) => new Promise((resolve, reject) => {
      let tx = null;
      let transactionComplete = false;
      let operationResult = null;
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
        firstError ||= error || tx?.error || new Error("IndexedDB transaction failed");
        return firstError;
      };
      const rejectOnce = (error) => {
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
      const abortWithError = (error) => {
        rememberError(error);
        try {
          tx?.abort();
        } catch {
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
      let operation;
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
    })
  );
}
function promisify(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
function isStoredRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function isStoredMutation(value) {
  return isStoredRecord(value) && typeof value.id === "string";
}
function isOptionalText(value) {
  return value === void 0 || value === null || typeof value === "string";
}
function isStoredMention(value) {
  return isStoredRecord(value) && typeof value.occurrence_id === "string" && typeof value.recipient === "string" && typeof value.display_name === "string";
}
function isStoredSyncRecord(value) {
  return isStoredRecord(value) && typeof value.sync_id === "string" && typeof value.key === "string" && isOptionalText(value.update) && isOptionalText(value.ydoc) && isOptionalText(value.html) && isOptionalText(value.generation) && isOptionalText(value.presence_digest) && isOptionalText(value.fingerprint) && (value.revision === void 0 || value.revision === null || typeof value.revision === "number") && (value.mentions === void 0 || value.mentions === null || Array.isArray(value.mentions) && value.mentions.every(isStoredMention)) && (value.touch_parent === void 0 || typeof value.touch_parent === "boolean") && (value.save === void 0 || typeof value.save === "boolean") && (value.timestamp === void 0 || typeof value.timestamp === "number");
}
function updateSyncRecord(record) {
  const timestamp = Date.now();
  return withTransaction(SYNC_STORE, "readwrite", async (tx) => {
    const store = tx.objectStore(SYNC_STORE);
    const stored = await promisify(store.get(record.sync_id));
    const existing = isStoredRecord(stored) ? stored : null;
    const merged = existing ? {
      ...existing,
      ...record,
      save: existing.save || record.save,
      timestamp
    } : { ...record, timestamp };
    if (existing && !Object.hasOwn(record, "html")) delete merged.html;
    if (existing && !Object.hasOwn(record, "mentions")) delete merged.mentions;
    await promisify(store.put(merged));
  });
}
function getSyncRecord(sync_id) {
  return withTransaction([SYNC_STORE], "readonly", async (tx) => {
    const record = await promisify(
      tx.objectStore(SYNC_STORE).get(sync_id)
    );
    return isStoredSyncRecord(record) ? record : null;
  });
}
function getAllOfflineRecords() {
  return withTransaction(
    [SYNC_STORE, MUTATION_STORE],
    "readonly",
    async (tx) => {
      const sync = await promisify(
        tx.objectStore(SYNC_STORE).getAll()
      );
      const mutations = await promisify(
        tx.objectStore(MUTATION_STORE).getAll()
      );
      return {
        sync: sync.filter(isStoredSyncRecord),
        mutations: mutations.filter(isStoredMutation)
      };
    }
  );
}
function deleteSyncRecord(sync_id) {
  return withTransaction(SYNC_STORE, "readwrite", async (tx) => {
    await promisify(tx.objectStore(SYNC_STORE).delete(sync_id));
  });
}
function deleteSyncRecords(sync_ids) {
  if (!sync_ids?.length) return Promise.resolve();
  return withTransaction(SYNC_STORE, "readwrite", async (tx) => {
    const store = tx.objectStore(SYNC_STORE);
    await Promise.all(sync_ids.map((id) => promisify(store.delete(id))));
  });
}
function setOfflineMutation(record) {
  return withTransaction(MUTATION_STORE, "readwrite", async (tx) => {
    await promisify(tx.objectStore(MUTATION_STORE).put(record));
  });
}
function getOfflineMutations() {
  return withTransaction(MUTATION_STORE, "readonly", async (tx) => {
    const records = await promisify(
      tx.objectStore(MUTATION_STORE).getAll()
    );
    return records.filter(isStoredMutation);
  });
}
function deleteOfflineMutations(ids) {
  if (!ids?.length) return Promise.resolve();
  return withTransaction(MUTATION_STORE, "readwrite", async (tx) => {
    const store = tx.objectStore(MUTATION_STORE);
    await Promise.all(ids.map((id) => promisify(store.delete(id))));
  });
}

export { deleteOfflineMutations, deleteSyncRecord, deleteSyncRecords, getAllOfflineRecords, getOfflineMutations, getSyncRecord, setOfflineMutation, updateSyncRecord };
