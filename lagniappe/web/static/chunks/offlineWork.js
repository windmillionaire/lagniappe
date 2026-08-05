/*! Third-party licenses: /third-party-licenses.txt */
/**
 * Inspect persisted offline work without loading either manager into the Core
 * startup closure. Database enumeration avoids opening or creating storage for
 * users who have never used offline behavior.
 *
 * @testable false
 * @covered-by src/script/views/base/services.mjs::initializeCoreServices
 * @reason lazy capability probe controls manager loading without changing queue semantics
 */
const inspectOfflineWork = async (view) => {
	const fallback = {
		mutations: Boolean(view.elt.querySelector("[lp-offline]")),
		sync: Boolean(view.elt.querySelector("[lp-sync]")),
	};
	if (!globalThis.indexedDB) return { mutations: false, sync: false };
	if (typeof globalThis.indexedDB.databases !== "function") return fallback;

	try {
		const databases = await globalThis.indexedDB.databases();
		if (!databases.some(({ name }) => name === "offline-db")) {
			return { mutations: false, sync: false };
		}
		const { getAllOfflineRecords } = await import('./offline.js?v=bfd37afb');
		const records = await getAllOfflineRecords();
		return {
			mutations: Boolean(records.mutations?.length),
			sync: Boolean(records.sync?.length),
		};
	} catch (error) {
		view.reportStartupError(error, view.elt, "offline-work-inspection");
		return fallback;
	}
};

export { inspectOfflineWork };
