/** Sync-capable widgets that can run without a mounted view (offline replay). */
const HEADLESS_WIDGETS = {
	document: {
		load: () => import("./collaborative"),
		name: "CollaborativeDocument",
	},
};

/**
 * @testable false
 * @covered-by src/script/elements/editor/headless.mjs::loadHeadlessWidget
 * @reason helper owned by the headless sync widget loader
 */
function _headlessKind(sync_id) {
	if (sync_id.endsWith(":document")) return "document";
	return null;
}

/**
 * @testable true
 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_headless_offline_replay_merges_concurrent_remote_edits
 * @matrix sync : concurrency document headless-widget offline-replay
 *
 * Construct a sync-capable widget with no view or DOM chrome.
 * Caller runs init(), assigns remote/offlineRecord, then sync().
 */
export async function loadHeadlessWidget({ sync_id, remote, offline }) {
	const kind = _headlessKind(sync_id);
	if (!kind) return null;

	const { load, name } = HEADLESS_WIDGETS[kind];
	const module = await load();
	const Widget = module[name];

	const target = document.createElement("div");
	target.setAttribute("lp-sync", sync_id);
	const fingerprint = remote?.fingerprint ?? offline?.fingerprint;
	if (fingerprint) target.setAttribute("lp-fingerprint", fingerprint);
	return new Widget({
		target,
		headless: true,
		view: null,
		readonly: true,
		key: remote?.key ?? offline?.key,
	});
}
