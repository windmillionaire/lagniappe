OFFLINE_MUTATION_COUNT = """
async ({ minimum, exact }) => {
    const count = await new Promise((resolve) => {
        const request = indexedDB.open("offline-db", 5);
        request.onerror = () => resolve(0);
        request.onupgradeneeded = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains("sync")) {
                db.createObjectStore("sync", { keyPath: "sync_id" });
            }
            if (!db.objectStoreNames.contains("mutations")) {
                db.createObjectStore("mutations", { keyPath: "id" });
            }
        };
        request.onsuccess = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains("mutations")) {
                db.close();
                resolve(0);
                return;
            }
            const transaction = db.transaction("mutations", "readonly");
            const countRequest = transaction.objectStore("mutations").count();
            countRequest.onsuccess = () => resolve(countRequest.result);
            countRequest.onerror = () => resolve(0);
            transaction.oncomplete = () => db.close();
            transaction.onerror = () => {
                db.close();
                resolve(0);
            };
        };
    });
    return exact === null ? count >= minimum : count === exact;
}
"""


def wait_for_offline_mutations(user, *, minimum=None, exact=None):
    """Wait for the durable mutation queue, not a timing or network proxy."""
    user.page.wait_for_function(
        OFFLINE_MUTATION_COUNT,
        arg={"minimum": minimum, "exact": exact},
    )
