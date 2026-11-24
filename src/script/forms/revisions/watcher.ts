import { captureError } from "../../shared/errors.ts";
import type { PollingCoordinator, PollResult } from "../../shared/polling.ts";
import type { EntityRevision } from "../../types/api";
import type {
	FormRevisionChoice,
	FormRevisionConflict,
	FormRevisionReviewOptions,
} from "../../types/forms";
import type { FormWidget } from "../../widgets/base/formWidget.ts";
import {
	type DeferredCompletion,
	EditReconciler,
	type MarkerRevision,
	type ReconcilerView,
	type RevisionForm,
	type RevisionMarker,
} from "./reconciler.ts";

interface WatchComponent {
	elt?: HTMLElement | null;
	visible?: boolean;
	widgets?: Record<string, unknown>;
}

export interface EditWatcherView extends ReconcilerView {
	elt: HTMLElement;
	key?: string | null;
	online?: boolean;
	hidden?: boolean;
	components?: Record<string, WatchComponent>;
	PollingCoordinator?: Pick<
		PollingCoordinator,
		"subscribe" | "trigger" | "enqueue" | "acknowledge"
	> | null;
}

interface WatchedEntity {
	key: string;
	fingerprint: string;
	modified: string | null;
	anchors: Set<HTMLElement>;
	markers: Set<RevisionMarker>;
}

type FormLockPayload = Extract<
	PollResult<"form-lock">,
	{ status: "changed" }
>["payload"];
type FormLock = Extract<FormLockPayload, { locked: true }> & {
	blocks_edit?: boolean;
};

/**
 * View-scoped detector for committed edits to forms represented by
 * lp-edited-marker descendants.
 *
 */
export class EditWatcher {
	declare readonly view: EditWatcherView;
	declare readonly _unsubscribers: Map<string, () => void>;
	declare readonly _markerRevisions: WeakMap<RevisionMarker, MarkerRevision>;
	declare readonly _latestRevisions: Map<
		string,
		MarkerRevision & { fingerprint: string }
	>;
	declare readonly _deferredCompletions: Map<string, Set<string>>;
	declare readonly _reconciler: EditReconciler;
	declare readonly _click: (event: MouseEvent) => Promise<void>;
	declare _destroyed: boolean;

	constructor(view: EditWatcherView) {
		this.view = view;
		this._unsubscribers = new Map();
		this._markerRevisions = new WeakMap();
		this._latestRevisions = new Map();
		this._deferredCompletions = new Map();
		this._destroyed = false;
		this._reconciler = new EditReconciler(view, {
			recordMarkerRevision: (marker, revision) => {
				this._markerRevisions.set(marker, revision);
			},
			ownedDeferredCompletion: (marker, widget) =>
				this._ownedDeferredCompletion(marker, widget),
			forgetDeferredCompletion: (completion) =>
				this._forgetDeferredCompletion(completion),
		});

		this._click = (event) => this._reconciler.handleClick(event);
		this._entityUpdated = this._entityUpdated.bind(this);
		this.check = this.check.bind(this);
	}

	init() {
		this.view.elt.addEventListener("click", this._click);
		window.addEventListener("entity-updated", this._entityUpdated);
		if (this.view.key && this.view.elt.dataset.fingerprint) {
			this._latestRevisions.set(this.view.key, {
				fingerprint: this.view.elt.dataset.fingerprint,
				modified: this.view.elt.dataset.modified ?? null,
			});
		}
		for (const component of Object.values(this.view.components ?? {})) {
			for (const widget of Object.values(component.widgets ?? {})) {
				if (
					widget &&
					typeof widget === "object" &&
					"_offlineConflict" in widget &&
					widget._offlineConflict
				) {
					const form = widget as FormWidget & {
						_offlineConflict: FormRevisionConflict;
					};
					void this.stageConflict(form, form._offlineConflict);
				}
			}
		}
		this.resume();
	}

	get entities() {
		return this._entities();
	}

	_componentVisible(component?: WatchComponent | null) {
		if (component?.visible !== true) return false;
		let ancestor =
			component.elt?.parentElement?.closest?.<HTMLElement>("[lp-component]");
		while (ancestor) {
			if (ancestor.dataset.visible === "false") return false;
			ancestor =
				ancestor.parentElement?.closest?.<HTMLElement>("[lp-component]");
		}
		return true;
	}

	_markerActive(marker: RevisionMarker) {
		const widget =
			marker.closest?.<RevisionForm>("form[data-widget]")?._lp_widget;
		return Boolean(
			widget &&
				widget.component?.active === widget &&
				this._componentVisible(widget.component) &&
				widget.visible === true,
		);
	}

	_markerRevision(marker: RevisionMarker, anchor: HTMLElement) {
		let revision = this._markerRevisions.get(marker);
		if (!revision) {
			revision = {
				fingerprint: anchor.dataset.fingerprint ?? null,
				modified: anchor.dataset.modified ?? null,
			};
			this._markerRevisions.set(marker, revision);
		}
		return revision;
	}

	_entities({ activeOnly = true } = {}) {
		const entities = new Map<string, WatchedEntity>();
		const markers =
			this.view.elt.querySelectorAll<RevisionMarker>("[lp-edited-marker]");

		for (const marker of markers) {
			const anchor = marker.closest<HTMLElement>("[lp-entity]");
			const key = anchor?.dataset.key;
			const revision = anchor ? this._markerRevision(marker, anchor) : null;
			const fingerprint = revision?.fingerprint;
			if (!anchor || !key || !revision || !fingerprint) {
				captureError(
					new Error("Edited marker has no fingerprinted entity anchor"),
					marker,
				);
				continue;
			}
			if (activeOnly && !this._markerActive(marker)) continue;

			const entity = entities.get(key) ?? {
				key,
				fingerprint,
				modified: revision.modified,
				anchors: new Set(),
				markers: new Set(),
			};
			entity.anchors.add(anchor);
			entity.markers.add(marker);
			entities.set(key, entity);
		}

		return entities;
	}

	expectDeferredCompletion(key: string | null, operation: string) {
		if (!key || !operation) return false;
		const operations = this._deferredCompletions.get(key) ?? new Set();
		operations.add(operation);
		this._deferredCompletions.set(key, operations);
		return true;
	}

	_ownedDeferredCompletion(
		marker: RevisionMarker,
		widget?: FormWidget,
	): DeferredCompletion | null {
		const key = marker.closest?.<HTMLElement>("[lp-entity]")?.dataset?.key;
		const operation = widget?._deferredOperation;
		if (!key || !operation) return null;

		if (this._deferredCompletions.get(key)?.has(operation)) {
			return { key, operation };
		}

		for (const [ownerKey, operations] of this._deferredCompletions) {
			if (operations.has(operation)) return { key: ownerKey, operation };
		}
		return null;
	}

	_forgetDeferredCompletion(completion: DeferredCompletion | null) {
		if (!completion) return;
		const operations = this._deferredCompletions.get(completion.key);
		operations?.delete(completion.operation);
		if (!operations?.size) this._deferredCompletions.delete(completion.key);
	}

	async _probeEntity(
		key: string,
		fingerprint: string,
		modified: string | null = null,
	) {
		const entity = this.entities.get(key);
		if (!entity) return;
		const revision = { fingerprint, modified };
		const stale = Array.from(entity.markers).filter((marker) => {
			const current = this._markerRevisions.get(marker);
			return (
				current?.fingerprint !== fingerprint ||
				(Boolean(modified) && current?.modified !== modified) ||
				Boolean(
					this._ownedDeferredCompletion(
						marker,
						marker.closest?.<RevisionForm>("form[data-widget]")?._lp_widget,
					),
				)
			);
		});
		await Promise.all(
			stale.map((marker) =>
				this._reconciler.probe(marker, fingerprint, modified),
			),
		);
		const latest = this._latestRevisions.get(key);
		const anchorRevision = latest?.fingerprint ? latest : revision;
		for (const anchor of entity.anchors) {
			anchor.dataset.fingerprint = anchorRevision.fingerprint;
			if (anchorRevision.modified) {
				anchor.dataset.modified = anchorRevision.modified;
			}
		}
	}

	async receiveEntityResult(key: string, result: PollResult<"entity">) {
		if (!key || !result) return;
		if (result.status === "unavailable") {
			for (const marker of this.entities.get(key)?.markers ?? []) {
				this._reconciler.fallback(marker);
			}
			return;
		}
		// Task jobs can name their parent page as the operation owner. Probe
		// mounted markers so their exact operation lock can match that completion
		// even when the task's saved revision arrived before terminal status.
		if (result.status === "unchanged" && this._deferredCompletions.size) {
			const revision = this._latestRevisions.get(key) ?? {
				fingerprint: result.revision ?? null,
				modified: null,
			};
			if (revision.fingerprint) {
				await this._probeEntity(key, revision.fingerprint, revision.modified);
			}
			return;
		}
		if (result.status !== "changed" || !result.payload?.fingerprint) return;
		const revision = {
			fingerprint: result.payload.fingerprint,
			modified: result.payload.modified ?? null,
		};
		this._latestRevisions.set(key, revision);
		await this._probeEntity(key, revision.fingerprint, revision.modified);
	}

	async _lockEntity(entity: WatchedEntity | undefined, descriptor: FormLock) {
		if (!entity || !descriptor?.operation) return;
		const forms = new Set<RevisionForm>();
		for (const marker of entity.markers ?? []) {
			const form = marker.closest<RevisionForm>("form[data-widget]");
			if (form) forms.add(form);
		}
		for (const anchor of entity.anchors ?? []) {
			for (const form of anchor.querySelectorAll?.<RevisionForm>(
				"form[data-widget='PageInfo'], form[data-widget='TaskForm']",
			) ?? []) {
				forms.add(form);
			}
		}

		const tracked = [];
		for (const form of forms) {
			if (
				form.dataset.deferredLock !== "form" &&
				!["PageInfo", "TaskForm"].includes(form.dataset.widget ?? "")
			)
				continue;

			const widget = form._lp_widget;
			if (widget?._deferredOperation !== descriptor.operation) {
				widget?.lockDeferredOperation?.(descriptor);
			}
			if (!widget) {
				form.dataset.operation = descriptor.operation;
				form.dataset.operationRevision = String(descriptor.revision ?? 0);
				form.dataset.operationScope = descriptor.scope || "";
				if (
					descriptor.blocks_edit === true ||
					descriptor.scope === "form-change"
				)
					form.dataset.deferredLock = "form";
				else delete form.dataset.deferredLock;
			}
			tracked.push({
				revision: descriptor.revision ?? 0,
				node: widget?.target ?? form,
			});
		}

		if (!tracked.length) return;
		const operations =
			this.view.DeferredOperations ||
			(await this.view.ensureDeferredOperations?.());
		for (const options of tracked) {
			operations?.track(descriptor.operation, options);
		}
	}

	_syncSubscriptions() {
		const mounted = this.entities;
		const active = new Set<string>();
		for (const entity of mounted.values()) {
			const entityId = `edit:${entity.key}`;
			const lockId = `lock:${entity.key}`;
			active.add(lockId);
			if (entity.key !== this.view.key) active.add(entityId);
			if (entity.key !== this.view.key && !this._unsubscribers.has(entityId)) {
				this._unsubscribers.set(
					entityId,
					this.view.PollingCoordinator?.subscribe(
						{
							id: entityId,
							type: "entity",
							key: entity.key,
							revision: entity.fingerprint,
						},
						{
							mode: "periodic",
							initial: "scheduled",
							onResult: (result) =>
								this.receiveEntityResult(entity.key, result),
						},
					) ?? (() => {}),
				);
			}
			if (!this._unsubscribers.has(lockId)) {
				this._unsubscribers.set(
					lockId,
					this.view.PollingCoordinator?.subscribe(
						{
							id: lockId,
							type: "form-lock",
							key: entity.key,
							revision: "unlocked",
						},
						{
							mode: "periodic",
							initial: "scheduled",
							onResult: async (result) => {
								if (result.status !== "changed") return;
								if (result.payload?.locked) {
									await this._lockEntity(
										this.entities.get(entity.key),
										result.payload,
									);
								} else if (
									Array.from(this.entities.get(entity.key)?.markers ?? []).some(
										(marker) =>
											marker
												.closest?.("form[data-widget]")
												?.hasAttribute("data-deferred-lock"),
									)
								) {
									await this.view.reconcileChange?.({
										type: "poll",
										key: entity.key,
									});
								}
							},
						},
					) ?? (() => {}),
				);
			}
		}
		for (const [id, unsubscribe] of this._unsubscribers) {
			if (active.has(id)) continue;
			unsubscribe();
			this._unsubscribers.delete(id);
		}
		return mounted;
	}

	async reconcileSubscriptions() {
		const mounted = this._syncSubscriptions();
		await Promise.all(
			Array.from(mounted.values(), async (entity) => {
				const latest = this._latestRevisions.get(entity.key);
				if (!latest) return;
				await this._probeEntity(
					entity.key,
					latest.fingerprint,
					latest.modified,
				);
			}),
		);
		return mounted;
	}

	check(
		keys: Iterable<string> | null = null,
		options: { fresh?: boolean } = {},
	) {
		const mounted = this._syncSubscriptions();
		const requested = keys === null ? [...mounted.keys()] : Array.from(keys);
		const ids = requested.flatMap((key) => [
			key === this.view.key ? `view:entity:${key}` : `edit:${key}`,
			`lock:${key}`,
		]);
		return this.view.PollingCoordinator?.trigger(ids, options);
	}

	enqueue(keys: Iterable<string> | null = null) {
		const mounted = this._syncSubscriptions();
		const requested = keys === null ? [...mounted.keys()] : Array.from(keys);
		const ids = requested.flatMap((key) => [
			key === this.view.key ? `view:entity:${key}` : `edit:${key}`,
			`lock:${key}`,
		]);
		this.view.PollingCoordinator?.enqueue(ids);
	}

	invalidate(keys?: string | string[] | null) {
		const requested = keys
			? (Array.isArray(keys) ? keys : [keys]).filter(Boolean)
			: null;
		return this.check(requested, { fresh: true });
	}

	acknowledge({
		key,
		fingerprint,
		modified = null,
	}: Partial<EntityRevision> = {}) {
		if (!key || !fingerprint) return;
		this._latestRevisions.set(key, { fingerprint, modified });
		if (this.view.key === key) {
			this.view.elt.dataset.fingerprint = fingerprint;
			if (modified) this.view.elt.dataset.modified = modified;
		}
		this.view.PollingCoordinator?.acknowledge(`edit:${key}`, fingerprint);
		this.view.PollingCoordinator?.acknowledge(
			`view:entity:${key}`,
			fingerprint,
		);

		const entity = this.entities.get(key);
		if (!entity) return;
		for (const anchor of entity.anchors) {
			anchor.dataset.fingerprint = fingerprint;
			if (modified) anchor.dataset.modified = modified;
		}
		for (const marker of entity.markers) {
			this._markerRevisions.set(marker, { fingerprint, modified });
		}
	}

	pause() {}

	resume() {
		if (this._destroyed || !this.view.online || this.view.hidden) return;
		return this.reconcileSubscriptions();
	}

	stageConflict(widget: FormWidget, conflict: FormRevisionConflict = {}) {
		return this._reconciler.stageConflict(widget, conflict);
	}

	openConflictReview(
		widget: FormWidget,
		options: FormRevisionReviewOptions = {},
	) {
		return this._reconciler.openConflictReview(widget, options);
	}

	resolveRevision(marker: RevisionMarker, choice: FormRevisionChoice) {
		return this._reconciler.resolveRevision(marker, choice);
	}

	_entityUpdated(event: CustomEvent<EntityRevision>) {
		this.acknowledge(event.detail);
	}

	destroy() {
		this._destroyed = true;
		for (const unsubscribe of this._unsubscribers.values()) unsubscribe();
		this._unsubscribers.clear();
		this._deferredCompletions.clear();
		this.view.elt.removeEventListener("click", this._click);
		window.removeEventListener("entity-updated", this._entityUpdated);
	}
}
