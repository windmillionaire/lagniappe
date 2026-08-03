import { EditReconciler } from "./editReconciler";
import { captureError } from "./errors";

/**
 * View-scoped detector for committed edits to forms represented by
 * lp-edited-marker descendants.
 *
 * @testable true
 * @tests tests_js/test_024_edit_watcher.py::test_edit_watcher_compares_and_resets_each_form_independently
 * @tests tests_js/test_028_form_state_split.py::test_owned_deferred_completion_replaces_clean_active_form
 * @tests tests_e2e/004_projects/test_004b_info.py::test_project_revision_notice_only_resets_changed_form
 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_replay_reconciles_after_reload
 * @features edited-entity-notice deferred-jobs polling
 * @dimensions entity-ancestor batching per-form acknowledgement acknowledgement-no-probe active-state visibility subscription-lifecycle owned-deferred-completion freshness
 * @pairs edited-entity-notice:entity-ancestor edited-entity-notice:batching
 * @pairs edited-entity-notice:per-form edited-entity-notice:acknowledgement
 * @pairs edited-entity-notice:acknowledgement-no-probe
 * @pairs edited-entity-notice:active-state
 * @pairs edited-entity-notice:visibility edited-entity-notice:subscription-lifecycle
 * @pairs edited-entity-notice:owned-deferred-completion deferred-jobs:owned-deferred-completion
 * @pairs polling:freshness
 */
export class EditWatcher {
	constructor(view) {
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
				if (widget._offlineConflict) {
					this.stageConflict(widget, widget._offlineConflict);
				}
			}
		}
		this.resume();
	}

	get entities() {
		return this._entities();
	}

	_componentVisible(component) {
		if (component?.visible !== true) return false;
		let ancestor = component.elt?.parentElement?.closest?.("[lp-component]");
		while (ancestor) {
			if (ancestor.dataset.visible === "false") return false;
			ancestor = ancestor.parentElement?.closest?.("[lp-component]");
		}
		return true;
	}

	_markerActive(marker) {
		const widget = marker.closest?.("form[data-widget]")?._lp_widget;
		return Boolean(
			widget &&
				widget.component?.active === widget &&
				this._componentVisible(widget.component) &&
				widget.visible === true,
		);
	}

	_markerRevision(marker, anchor) {
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
		const entities = new Map();
		const markers = this.view.elt.querySelectorAll("[lp-edited-marker]");

		for (const marker of markers) {
			const anchor = marker.closest("[lp-entity]");
			const key = anchor?.dataset.key;
			const revision = anchor ? this._markerRevision(marker, anchor) : null;
			const fingerprint = revision?.fingerprint;
			if (!anchor || !key || !fingerprint) {
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

	expectDeferredCompletion(key, operation) {
		if (!key || !operation) return false;
		const operations = this._deferredCompletions.get(key) ?? new Set();
		operations.add(operation);
		this._deferredCompletions.set(key, operations);
		return true;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_owned_deferred_completion_replaces_clean_active_form
	 * @pair deferred-jobs:owned-deferred-completion
	 * @pair edited-entity-notice:owned-deferred-completion
	 */
	_ownedDeferredCompletion(marker, widget) {
		const key = marker.closest?.("[lp-entity]")?.dataset?.key;
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

	_forgetDeferredCompletion(completion) {
		if (!completion) return;
		const operations = this._deferredCompletions.get(completion.key);
		operations?.delete(completion.operation);
		if (!operations?.size) this._deferredCompletions.delete(completion.key);
	}

	async _probeEntity(key, fingerprint, modified = null) {
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
						marker.closest?.("form[data-widget]")?._lp_widget,
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

	async receiveEntityResult(key, result) {
		if (!key || !result) return;
		if (result.status === "unavailable") {
			for (const marker of this.entities.get(key)?.markers ?? []) {
				this._reconciler.fallback(marker);
			}
			return;
		}
		if (result.status === "unchanged" && this._deferredCompletions.has(key)) {
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

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_edit_watcher_restores_active_autofill_without_form_sync
	 * @tests tests_e2e/005_pages/test_005h_page_autofill.py::test_page_autofill_runs_deferred_with_attached_file_context
	 * @features edited-entity-notice deferred-jobs
	 * @dimensions active-operation reload form-lock
	 */
	async _lockEntity(entity, descriptor) {
		if (!entity || !descriptor?.operation) return;
		const forms = new Set();
		for (const marker of entity.markers ?? []) {
			const form = marker.closest("form[data-widget]");
			if (form) forms.add(form);
		}
		for (const anchor of entity.anchors ?? []) {
			for (const form of anchor.querySelectorAll?.(
				"form[data-widget='PageInfo'], form[data-widget='TaskForm']",
			) ?? []) {
				forms.add(form);
			}
		}

		const tracked = [];
		for (const form of forms) {
			if (
				form.dataset.deferredLock !== "form" &&
				!["PageInfo", "TaskForm"].includes(form.dataset.widget)
			)
				continue;

			const widget = form._lp_widget;
			if (widget?._deferredOperation !== descriptor.operation) {
				widget?.lockDeferredOperation?.(descriptor);
			}
			if (!widget) {
				form.dataset.operation = descriptor.operation;
				form.dataset.operationRevision = String(
					Number(descriptor.revision) || 0,
				);
				form.dataset.deferredLock = "form";
			}
			tracked.push({
				revision: Number(descriptor.revision) || 0,
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
		const active = new Set();
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

	check(keys = null, options = {}) {
		const mounted = this._syncSubscriptions();
		const requested = keys === null ? [...mounted.keys()] : Array.from(keys);
		const ids = requested.flatMap((key) => [
			key === this.view.key ? `view:entity:${key}` : `edit:${key}`,
			`lock:${key}`,
		]);
		return this.view.PollingCoordinator?.trigger(ids, options);
	}

	enqueue(keys = null) {
		const mounted = this._syncSubscriptions();
		const requested = keys === null ? [...mounted.keys()] : Array.from(keys);
		const ids = requested.flatMap((key) => [
			key === this.view.key ? `view:entity:${key}` : `edit:${key}`,
			`lock:${key}`,
		]);
		this.view.PollingCoordinator?.enqueue(ids);
	}

	invalidate(keys) {
		const requested = keys
			? (Array.isArray(keys) ? keys : [keys]).filter(Boolean)
			: null;
		return this.check(requested, { fresh: true });
	}

	acknowledge({ key, fingerprint, modified = null } = {}) {
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

	stageConflict(widget, conflict = {}) {
		return this._reconciler.stageConflict(widget, conflict);
	}

	resolveRevision(marker, choice) {
		return this._reconciler.resolveRevision(marker, choice);
	}

	_entityUpdated(event) {
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
