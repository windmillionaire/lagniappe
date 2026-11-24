import type { PersistedSyncRecord } from "../../types/sync.d.ts";

type ReplayIdentity = Pick<PersistedSyncRecord, "key" | "fingerprint">;
type ReplayOptions = { sync_id: string } & (
	| { remote: ReplayIdentity; offline?: ReplayIdentity | null }
	| { remote?: ReplayIdentity | null; offline: ReplayIdentity }
);

/** Sync-capable widgets that can run without a mounted view (offline replay). */
const HEADLESS_WIDGETS = {
	document: {
		load: () => import("./collaborative.ts"),
		name: "CollaborativeDocument",
	},
} as const;

function _headlessKind(sync_id: string) {
	if (sync_id.endsWith(":document")) return "document";
	return null;
}

/**
 *
 * Construct a sync-capable widget with no view or DOM chrome.
 * Caller runs init(), assigns remote/offlineRecord, then sync().
 */
export async function loadHeadlessWidget({
	sync_id,
	remote,
	offline,
}: ReplayOptions) {
	const kind = _headlessKind(sync_id);
	if (!kind) return null;

	const { load, name } = HEADLESS_WIDGETS[kind];
	const module = await load();
	const Widget = module[name];

	const target = document.createElement("div");
	target.setAttribute("lp-sync", sync_id);
	const identity = remote ?? offline;
	if (!identity) return null;
	const fingerprint = remote?.fingerprint ?? offline?.fingerprint;
	if (fingerprint) target.setAttribute("lp-fingerprint", fingerprint);
	const widget = new Widget({
		target,
		headless: true,
		view: null,
		readonly: true,
		key: identity.key,
	});
	return module.hasDocumentSyncId(widget) ? widget : null;
}
