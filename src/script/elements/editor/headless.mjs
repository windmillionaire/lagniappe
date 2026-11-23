/** Sync-capable widgets that can run without a mounted view (offline replay). */
const HEADLESS_WIDGETS = {
	document: {
		load: () => import("./collaborative.mjs"),
		name: "CollaborativeDocument",
	},
};

function _headlessKind(sync_id) {
	if (sync_id.endsWith(":document")) return "document";
	return null;
}

/**
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
