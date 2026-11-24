import { captureError } from "../../shared/errors.ts";
import { request } from "../../shared/request.ts";
import { clearRecentSearchResults } from "../../shared/storage.ts";
import type { LoadedWidget } from "../../types/widgets";
import type { PageTaskDelta } from "../../widgets/pageTaskList.ts";
import type ViewComponent from "./component.ts";
import type Core from "./core.ts";
import type {
	ComponentElement,
	ReconcileChange,
	RefreshOptions,
} from "./core.ts";

interface RefreshDescriptor {
	rows: { key?: string; hash: string; fingerprint: string }[];
}

interface RefreshDelta extends PageTaskDelta {
	id: string;
	fallback?: false;
}

interface CollectionRefreshResponse {
	targets: unknown;
	fingerprint: string | null;
	authorization: string | null;
	collection_revision: string | null;
}

type CollectionWidget = LoadedWidget & {
	refreshDescriptor(): RefreshDescriptor | null;
	refreshDelta(result: RefreshDelta): unknown;
	prepareRefreshDelta?(
		result: RefreshDelta,
	): Promise<RefreshCommit | null | undefined>;
};

interface CollectionRefreshTarget {
	descriptor: RefreshDescriptor & { id: string };
	widget: CollectionWidget;
}

type RefreshCommit = () => void;

function isCollectionWidget(widget: LoadedWidget): widget is CollectionWidget {
	return (
		widget.refreshScope === "collection" &&
		"refreshDescriptor" in widget &&
		typeof widget.refreshDescriptor === "function" &&
		"refreshDelta" in widget &&
		typeof widget.refreshDelta === "function"
	);
}

function isStringList(value: unknown): value is string[] {
	return (
		Array.isArray(value) && value.every((item) => typeof item === "string")
	);
}

function isRefreshDelta(value: unknown): value is RefreshDelta {
	if (
		value === null ||
		typeof value !== "object" ||
		!("id" in value) ||
		typeof value.id !== "string"
	)
		return false;
	if ("fallback" in value && value.fallback !== false) return false;
	if ("remove" in value && !isStringList(value.remove)) return false;
	if ("order" in value && !isStringList(value.order)) return false;
	if (
		"empty" in value &&
		value.empty !== null &&
		typeof value.empty !== "string"
	)
		return false;
	return (
		!("upsert" in value) ||
		(Array.isArray(value.upsert) &&
			value.upsert.every(
				(row: unknown) =>
					row !== null &&
					typeof row === "object" &&
					"key" in row &&
					typeof row.key === "string" &&
					"html" in row &&
					typeof row.html === "string",
			))
	);
}

const COLLECTION_ONLY_CHANGE_TYPES = new Set(["delete", "star", "unstar"]);
const FORM_ALREADY_RECONCILED_CHANGE_TYPES = new Set([
	...COLLECTION_ONLY_CHANGE_TYPES,
	"entity-poll",
]);

const loadChangeDestination = async (
	view: Core,
	destination: ReconcileChange["destination"],
) => {
	if (!destination) return null;
	const [componentId, widgetName] = destination.split(":");
	if (!componentId || !widgetName) return null;
	const component = view.getComponent(document.getElementById(componentId));
	return component ? await component.loadWidget(widgetName) : null;
};

const loadMountedCollectionOwners = async (view: Core, keys: string[]) => {
	const requested = new Set(keys);
	const targets = new Set<HTMLElement>();
	for (const entity of view.elt.querySelectorAll<HTMLElement>(
		"[lp-entity][data-key]",
	)) {
		if (!entity.dataset.key || !requested.has(entity.dataset.key)) continue;
		const target =
			entity.parentElement?.closest?.<HTMLElement>("[data-widget]");
		if (target?.dataset.widget && !target.matches?.("form"))
			targets.add(target);
	}
	await Promise.all(
		Array.from(targets, async (target) => {
			await view.getComponent(target)?.loadWidget(target.dataset.widget);
		}),
	);
};

const removeDeletedEntity = (view: Core, key: string) => {
	for (const element of view.elt.querySelectorAll<ComponentElement>(
		"[data-key]",
	)) {
		if (element.dataset.key !== key) continue;
		element._lp_component?.destroy?.();
		element.remove();
	}
};

export const reconcileChange = (
	view: Core,
	change: ReconcileChange = {},
): Promise<void> => {
	view._pendingChanges.push({ ...change });
	if (view._reconcilePromise) return view._reconcilePromise;

	view._reconcilePromise = (async () => {
		try {
			do {
				const changes = view._pendingChanges.splice(0);
				const fingerprint = view.elt.dataset.fingerprint || null;
				const destinationKeys: string[] = [];
				for (const item of changes) {
					if (item.type === "delete") clearRecentSearchResults();
					if (item.type === "star" || item.type === "unstar") {
						view._applyStarState(item);
					}
					const destination = await loadChangeDestination(
						view,
						item.destination,
					);
					if (
						destination?.key &&
						!COLLECTION_ONLY_CHANGE_TYPES.has(item.type ?? "")
					) {
						destinationKeys.push(destination.key);
					}
				}
				const keys = [
					...new Set(changes.flatMap(({ key }) => (key ? [key] : []))),
				];
				if (keys.length) await loadMountedCollectionOwners(view, keys);
				const deletedKeys = changes.flatMap(({ key, type }) =>
					type === "delete" && key ? [key] : [],
				);
				const formKeys = [
					...new Set([
						...changes
							.filter(
								({ type }) =>
									!FORM_ALREADY_RECONCILED_CHANGE_TYPES.has(type ?? ""),
							)
							.flatMap(({ key }) => (key ? [key] : [])),
						...destinationKeys,
					]),
				];
				if (formKeys.length) {
					const watcher = await view.ensureEditWatcher();
					if (view.PollingCoordinator?.activePoll) watcher?.enqueue(formKeys);
					else await watcher?.invalidate(formKeys);
				}
				await view.refreshCollections(false, {
					fingerprint,
					beforeCommit: () => {
						deletedKeys.forEach((key) => {
							removeDeletedEntity(view, key);
						});
					},
				});
				await view.refreshSupplementalCollections(changes);
				for (const item of changes) await view.afterReconcileChange(item);
			} while (view._pendingChanges.length);
		} finally {
			view._reconcilePromise = null;
		}
	})();
	return view._reconcilePromise;
};

export const collectRefreshTargets = (
	_view: Core,
	components: ViewComponent[],
) => {
	const targets = new Map<string, CollectionRefreshTarget>();
	for (const component of components) {
		if (component.elt && !component.elt.isConnected) continue;
		for (const widget of Object.values(component.widgets)) {
			if (!isCollectionWidget(widget)) continue;
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
	view: Core,
	components: ViewComponent[],
	{
		fingerprint = view.elt.dataset.fingerprint || null,
		deferCommit = false,
	}: RefreshOptions = {},
): Promise<RefreshCommit | null | undefined> => {
	const targets = collectRefreshTargets(view, components);
	const reconciled = new Set<LoadedWidget>();
	const commits: (RefreshCommit | null | undefined)[] = [];
	let refreshedFingerprint = null;
	let refreshedAuthorization = null;
	let collectionRevision = null;
	if (targets.size) {
		const response = await request.post<CollectionRefreshResponse>(
			"/l/refresh",
			{
				view: {
					key: view.key || null,
					hash: view.hash || null,
					index: view.elt.dataset.index || null,
					mode: view.elt.dataset.userMode || null,
					fingerprint,
					authorization: view.elt.dataset.authorization || null,
					collection_revision: view.elt.dataset.collectionRevision || null,
				},
				targets: Array.from(targets.values(), ({ descriptor }) => descriptor),
			},
		);
		if (response?.reload) {
			window.location.reload();
			return;
		}
		if (response?.ok && Array.isArray(response.targets)) {
			refreshedFingerprint = response.fingerprint || null;
			refreshedAuthorization = response.authorization || null;
			collectionRevision = response.collection_revision || null;
			if (!response.targets.length && refreshedFingerprint) {
				for (const { widget } of targets.values()) reconciled.add(widget);
			}
			const results = new Map(
				response.targets
					.filter(isRefreshDelta)
					.map((target) => [target.id, target]),
			);
			for (const [id, { widget }] of targets) {
				const result = results.get(id);
				if (!result || result.fallback) continue;
				try {
					if (deferCommit && widget.prepareRefreshDelta) {
						commits.push(await widget.prepareRefreshDelta(result));
					} else if (deferCommit) {
						commits.push(() => {
							const pending = widget.refreshDelta(result);
							if (pending instanceof Promise) void pending.catch(captureError);
						});
					} else {
						await widget.refreshDelta(result);
					}
					reconciled.add(widget);
				} catch (error) {
					captureError(error);
				}
			}
		}
	}
	if (deferCommit) {
		const prepared = await Promise.all(
			components.map(async (component) => {
				if (component.elt && !component.elt.isConnected) return [];
				return await component.prepareCollectionRefresh(reconciled);
			}),
		);
		commits.push(...prepared.flat());
		return () => {
			commits
				.filter((commit) => commit != null)
				.forEach((commit) => {
					commit();
				});
			if (refreshedFingerprint) {
				view.elt.dataset.fingerprint = refreshedFingerprint;
			}
			if (refreshedAuthorization)
				view.elt.dataset.authorization = refreshedAuthorization;
			if (collectionRevision)
				view.elt.dataset.collectionRevision = collectionRevision;
		};
	}

	await Promise.all(
		components.map(async (component) => {
			if (component.elt && !component.elt.isConnected) return;
			await component.refreshCollections(reconciled);
		}),
	);
	if (refreshedFingerprint) view.elt.dataset.fingerprint = refreshedFingerprint;
	if (refreshedAuthorization)
		view.elt.dataset.authorization = refreshedAuthorization;
	if (collectionRevision)
		view.elt.dataset.collectionRevision = collectionRevision;
	return null;
};
