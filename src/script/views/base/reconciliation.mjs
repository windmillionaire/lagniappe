import { captureError } from "../../shared/errors";
import { request } from "../../shared/request";
import { clearRecentSearchResults } from "../../shared/utilities";

const COLLECTION_ONLY_CHANGE_TYPES = new Set(["delete", "star", "unstar"]);
const FORM_ALREADY_RECONCILED_CHANGE_TYPES = new Set([
	...COLLECTION_ONLY_CHANGE_TYPES,
	"entity-poll",
]);

const loadChangeDestination = async (view, destination) => {
	if (!destination) return null;
	const [componentId, widgetName] = destination.split(":");
	if (!componentId || !widgetName) return null;
	const component = view.getComponent(document.getElementById(componentId));
	return component ? await component.loadWidget(widgetName) : null;
};

const loadMountedCollectionOwners = async (view, keys) => {
	const requested = new Set(keys);
	const targets = new Set();
	for (const entity of view.elt.querySelectorAll("[lp-entity][data-key]")) {
		if (!requested.has(entity.dataset.key)) continue;
		const target = entity.parentElement?.closest?.("[data-widget]");
		if (target?.dataset.widget && !target.matches?.("form"))
			targets.add(target);
	}
	await Promise.all(
		Array.from(targets, async (target) => {
			await view.getComponent(target)?.loadWidget(target.dataset.widget);
		}),
	);
};

const removeDeletedEntity = (view, key) => {
	for (const element of view.elt.querySelectorAll("[data-key]")) {
		if (element.dataset.key !== key) continue;
		element._lp_component?.destroy?.();
		element.remove();
	}
};

export const reconcileChange = (view, change = {}) => {
	view._pendingChanges.push({ ...change });
	if (view._reconcilePromise) return view._reconcilePromise;

	view._reconcilePromise = (async () => {
		try {
			do {
				const changes = view._pendingChanges.splice(0);
				const fingerprint = view.elt.dataset.fingerprint || null;
				const destinationKeys = [];
				for (const item of changes) {
					if (item.type === "delete") clearRecentSearchResults();
					if (["star", "unstar"].includes(item.type)) {
						view._applyStarState(item);
					}
					const destination = await loadChangeDestination(
						view,
						item.destination,
					);
					if (
						destination?.key &&
						!COLLECTION_ONLY_CHANGE_TYPES.has(item.type)
					) {
						destinationKeys.push(destination.key);
					}
				}
				const keys = [
					...new Set(changes.map(({ key }) => key).filter(Boolean)),
				];
				if (keys.length) await loadMountedCollectionOwners(view, keys);
				for (const { key, type } of changes) {
					if (type === "delete" && key) removeDeletedEntity(view, key);
				}
				const formKeys = [
					...new Set([
						...changes
							.filter(
								({ type }) => !FORM_ALREADY_RECONCILED_CHANGE_TYPES.has(type),
							)
							.map(({ key }) => key)
							.filter(Boolean),
						...destinationKeys,
					]),
				];
				if (formKeys.length) {
					const watcher = await view.ensureEditWatcher();
					if (view.PollingCoordinator?.activePoll) watcher?.enqueue(formKeys);
					else await watcher?.invalidate(formKeys);
				}
				await view.refreshCollections(false, { fingerprint });
				await view.refreshSupplementalCollections(changes);
				for (const item of changes) await view.afterReconcileChange(item);
			} while (view._pendingChanges.length);
		} finally {
			view._reconcilePromise = null;
		}
	})();
	return view._reconcilePromise;
};

export const collectRefreshTargets = (_view, components) => {
	const targets = new Map();
	for (const component of components) {
		if (component.elt && !component.elt.isConnected) continue;
		for (const widget of Object.values(component.widgets)) {
			if (widget.refreshScope !== "collection") continue;
			if (!widget.refreshDescriptor || !widget.refreshDelta) continue;
			try {
				const descriptor = widget.refreshDescriptor();
				if (!descriptor) continue;
				const id = component.name;
				if (!id || targets.has(id)) continue;
				targets.set(id, { descriptor: { ...descriptor, id }, widget });
			} catch (error) {
				captureError(error);
			}
		}
	}
	return targets;
};

export const refreshCollectionComponents = async (
	view,
	components,
	{ fingerprint = view.elt.dataset.fingerprint || null } = {},
) => {
	const targets = collectRefreshTargets(view, components);
	const reconciled = new Set();
	let refreshedFingerprint = null;
	if (targets.size) {
		const response = await request.post("/refresh", {
			view: {
				key: view.key || null,
				hash: view.hash || null,
				index: view.elt.dataset.index || null,
				mode: view.elt.dataset.userMode || null,
				fingerprint,
			},
			targets: Array.from(targets.values(), ({ descriptor }) => descriptor),
		});
		if (response?.reload) {
			window.location.reload();
			return;
		}
		if (response?.ok && Array.isArray(response.targets)) {
			refreshedFingerprint = response.fingerprint || null;
			if (!response.targets.length && refreshedFingerprint) {
				for (const { widget } of targets.values()) reconciled.add(widget);
			}
			const results = new Map(
				response.targets.map((target) => [target.id, target]),
			);
			for (const [id, { widget }] of targets) {
				const result = results.get(id);
				if (!result || result.fallback) continue;
				try {
					await widget.refreshDelta(result);
					reconciled.add(widget);
				} catch (error) {
					captureError(error);
				}
			}
		}
	}
	await Promise.all(
		components.map(async (component) => {
			if (component.elt && !component.elt.isConnected) return;
			await component.refreshCollections(reconciled);
		}),
	);
	if (refreshedFingerprint) view.elt.dataset.fingerprint = refreshedFingerprint;
	await view.Notifications?.refresh?.();
};
