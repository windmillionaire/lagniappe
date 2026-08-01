/*! Third-party licenses: /third-party-licenses.txt */
import { l as loadHeadlessWidget } from './core.js?v=b211475b';
import { E as ENDPOINTS } from './endpoints.js?v=b211475b';
import { getSyncRecord, getAllOfflineRecords, deleteSyncRecords, deleteSyncRecord, updateSyncRecord } from './offline.js?v=b211475b';
import { r as request } from './request.js?v=b211475b';
import { waitForAttribute } from './utilities.js?v=b211475b';
import './connectivity.js?v=b211475b';
import './errors.js?v=b211475b';
import './shell.js?v=b211475b';

/**
 * Coordinate Yjs document updates through the shared polling protocol.
 *
 * @testable infrastructure
 */
class SyncManager {
	constructor(view) {
		this.view = view;
		this._initialized = false;
		this._subscriptions = new Map();
		this._cursors = new Map();
		this._checkpointRetries = new Set();
		this._checkpointPollFirst = new Set();
		this._pendingParentTouches = new Set();
		this._activating = new Set();
		this._registerPromise = null;
		this._sendPromise = null;
		this._queuedSend = null;
		this.ready = Promise.resolve(this);
		this._syncSave = () => this.sendUpdates(true);
	}

	init() {
		if (this._initialized) return this;
		this._initialized = true;
		window.addEventListener("sync-save", this._syncSave);
		this.ready = this.register();
		return this;
	}

	get widgets() {
		const entries = [];
		for (const component of Object.values(this.view.components ?? {})) {
			for (const widget of Object.values(component.widgets ?? {})) {
				if (widget.syncId) {
					entries.push([widget.syncId, widget]);
				}
			}
		}
		return Object.fromEntries(entries);
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

	_widgetVisible(widget) {
		return Boolean(
			widget?.component?.active === widget &&
				this._componentVisible(widget.component) &&
				widget.visible === true,
		);
	}

	_descriptor(widget) {
		const protocol =
			this.view.PollingCoordinator?.get(`document:${widget.syncId}`) ??
			this._cursors.get(widget.syncId);
		return {
			key: widget.component?.key ?? widget.key,
			sync_id: widget.syncId,
			fingerprint: widget.fingerprint,
			generation: protocol?.generation ?? null,
			revision: Number(protocol?.revision) || 0,
		};
	}

	_rememberCursor(syncId, patch = null) {
		const active = this.view.PollingCoordinator?.get(`document:${syncId}`);
		const current = this._cursors.get(syncId) ?? {};
		const source = { ...current, ...active, ...patch };
		this._cursors.set(syncId, {
			generation: source.generation ?? null,
			revision: Number(source.revision) || 0,
		});
	}

	_subscribe(widget, { force = false } = {}) {
		if (!widget?.syncId || this._subscriptions.has(widget.syncId)) return;
		if (!force && !this._widgetVisible(widget)) return;
		const id = `document:${widget.syncId}`;
		const descriptor = {
			id,
			type: "document",
			...this._descriptor(widget),
		};
		const unsubscribe = this.view.PollingCoordinator?.subscribe(descriptor, {
			beforePoll: () => {
				const current = this.widgets[widget.syncId] ?? widget;
				if (
					!this._widgetVisible(current) &&
					!this._activating.has(widget.syncId)
				)
					return;
				return this.sendUpdates(
					this._checkpointRetries.has(widget.syncId) &&
						!this._checkpointPollFirst.has(widget.syncId),
				);
			},
			onResult: async (result) => {
				const current = this.widgets[widget.syncId] ?? widget;
				if (
					!this._widgetVisible(current) &&
					!this._activating.has(widget.syncId)
				)
					return false;
				this._rememberCursor(widget.syncId);
				if (result.status !== "changed" || !result.payload) return;
				// state() consumes its forced result directly, so its cursor is
				// safe to accept while the editor's async create event is still
				// completing. Any later result must wait for the mounted widget.
				if (!current.initialized) return this._activating.has(widget.syncId);
				current.remote = result.payload;
				await current.sync();
				if (
					!current.readonly &&
					(result.payload.checkpoint_required ||
						this._checkpointRetries.has(widget.syncId))
				) {
					this._checkpointPollFirst.delete(widget.syncId);
					await this.sendUpdates(true);
				}
			},
		});
		if (unsubscribe) {
			this._subscriptions.set(widget.syncId, unsubscribe);
			this._rememberCursor(widget.syncId, descriptor);
		}
	}

	/**
	 * @testable true
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_sync_manager_uses_polling_subscriptions
	 * @tests tests_js/test_029_core_startup.py::test_collaborative_document_renders_before_initial_state
	 * @pairs sync:editor-readiness sync:state-only sync:offline-replay polling:document
	 */
	async state(widget) {
		await this.ready;
		const offline = await getSyncRecord(widget.syncId);
		if (offline) widget.offlineRecord = offline;
		if (!this.view.online) return null;
		this._activating.add(widget.syncId);
		try {
			this._subscribe(widget, { force: true });
			const results = await this.view.PollingCoordinator?.trigger(
				`document:${widget.syncId}`,
			);
			return results?.find(
				(result) => result.id === `document:${widget.syncId}`,
			)?.payload;
		} finally {
			this._activating.delete(widget.syncId);
		}
	}

	register() {
		if (this._registerPromise) return this._registerPromise;
		const pending = this._register();
		this._registerPromise = pending;
		const complete = () => {
			if (this._registerPromise === pending) this._registerPromise = null;
		};
		void pending.then(complete, complete);
		return pending;
	}

	async _register() {
		const { sync: allOffline } = await getAllOfflineRecords();
		const offline = allOffline.filter(({ sync_id }) =>
			sync_id?.endsWith(":document"),
		);
		const obsolete = allOffline.filter(
			({ sync_id }) => !sync_id?.endsWith(":document"),
		);
		if (obsolete.length) {
			await deleteSyncRecords(obsolete.map(({ sync_id }) => sync_id));
		}
		for (const widget of Object.values(this.widgets)) this._subscribe(widget);
		if (offline.length) await this._reconcile(offline);
	}

	/**
	 * Keep document presence and its fast polling cadence scoped to the active,
	 * visible document widget.
	 *
	 * @testable true
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_sync_manager_uses_polling_subscriptions
	 * @features sync polling
	 * @dimensions active-widget visibility presence lifecycle
	 * @pairs sync:active-widget sync:visibility
	 * @pairs polling:active-widget polling:visibility
	 */
	async reconcileSubscriptions() {
		if (!this.view.online || this.view.hidden) return;
		const widgets = this.widgets;
		const active = new Map(
			Object.entries(widgets).filter(([, widget]) =>
				this._widgetVisible(widget),
			),
		);
		const closing = [...this._subscriptions.keys()].filter(
			(syncId) => !active.has(syncId) && !this._activating.has(syncId),
		);
		if (closing.length) {
			await this.sendUpdates(true, null, { touchSyncIds: closing });
			for (const syncId of closing) {
				this._rememberCursor(syncId);
				this._subscriptions.get(syncId)?.();
				this._subscriptions.delete(syncId);
			}
			await this.view.PollingCoordinator?.closeDocuments(closing);
		}
		for (const widget of active.values()) this._subscribe(widget);
	}

	async deregister() {
		const syncIds = [...this._subscriptions.keys()];
		await this.sendUpdates(true, null, {
			keepalive: true,
			touchSyncIds: syncIds,
		});
		for (const syncId of syncIds) this._rememberCursor(syncId);
		for (const unsubscribe of this._subscriptions.values()) unsubscribe();
		this._subscriptions.clear();
		await this.view.PollingCoordinator?.closeDocuments(syncIds);
	}

	async _waitForWidgetInitialized(widget) {
		if (widget.initialized) return;
		const target = widget.container ?? widget.target;
		if (target) await waitForAttribute(target, "initialized");
	}

	/**
	 * Fetch the authoritative state newer than an offline record's base cursor.
	 *
	 * @testable true
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_sync_manager_uses_polling_subscriptions
	 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_headless_offline_replay_merges_concurrent_remote_edits
	 * @pairs sync:offline-replay sync:headless sync:merge
	 * @pairs polling:document polling:current-state polling:cursor
	 */
	async _pollOfflineState(offline) {
		const id = `replay:${offline.sync_id}`;
		const unsubscribe = this.view.PollingCoordinator?.subscribe({
			id,
			type: "document",
			key: offline.key,
			sync_id: offline.sync_id,
			fingerprint: offline.fingerprint,
			generation: offline.generation ?? null,
			revision: Number(offline.revision) || 0,
		});
		if (!unsubscribe) return null;

		try {
			const results = await this.view.PollingCoordinator.trigger(id);
			const result = results?.find((candidate) => candidate.id === id);
			if (
				!result ||
				!["changed", "unchanged"].includes(result.status) ||
				(result.status === "changed" && !result.payload)
			) {
				return null;
			}
			const descriptor = this.view.PollingCoordinator.get(id);
			if (!descriptor?.generation) return null;
			const cursor = {
				generation: descriptor.generation,
				revision: Number(descriptor.revision) || 0,
			};
			this._rememberCursor(offline.sync_id, cursor);
			return { cursor, payload: result.payload ?? null };
		} finally {
			unsubscribe();
		}
	}

	/**
	 * @testable true
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_sync_manager_uses_polling_subscriptions
	 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_headless_offline_replay_merges_concurrent_remote_edits
	 * @pairs sync:offline-replay sync:headless sync:merge sync:queue-clear
	 */
	async _reconcile(offlineRecords) {
		const replays = [];
		const headless = [];
		try {
			for (const offline of offlineRecords) {
				if (
					offline.touch_parent &&
					!offline.update &&
					!offline.ydoc &&
					!Object.hasOwn(offline, "html")
				) {
					replays.push({
						key: offline.key,
						sync_id: offline.sync_id,
						fingerprint: offline.fingerprint,
						generation: offline.generation ?? null,
						revision: Number(offline.revision) || 0,
						save: true,
						touch_parent: true,
					});
					continue;
				}
				let widget = this.widgets[offline.sync_id];
				if (!widget) {
					widget = await loadHeadlessWidget({
						sync_id: offline.sync_id,
						offline,
					});
					if (!widget) continue;
					headless.push(widget);
					await widget.init();
					await this._waitForWidgetInitialized(widget);
				}

				const current = await this._pollOfflineState(offline);
				if (!current) continue;
				widget.remote = current.payload;
				widget.offlineRecord = offline;
				await widget.sync();

				const saveData = widget.saveData;
				if (!saveData) {
					if (offline.touch_parent) {
						replays.push({
							key: widget.component?.key ?? widget.key ?? offline.key,
							sync_id: offline.sync_id,
							fingerprint: widget.fingerprint ?? offline.fingerprint,
							...current.cursor,
							save: true,
							touch_parent: true,
						});
					} else {
						await deleteSyncRecord(offline.sync_id);
					}
					continue;
				}
				replays.push({
					key: widget.component?.key ?? widget.key ?? offline.key,
					sync_id: offline.sync_id,
					fingerprint: widget.fingerprint ?? offline.fingerprint,
					...current.cursor,
					...saveData,
					save: true,
					touch_parent: true,
				});
			}
			if (replays.length) await this.sendUpdates(false, replays);
		} finally {
			for (const widget of headless) {
				widget.destroy();
			}
			await this.view.PollingCoordinator?.closeDocuments(
				headless.map((widget) => widget.syncId),
			);
		}
	}

	_collect(save, { touchSyncIds = [] } = {}) {
		const batch = [];
		const touches = new Set(touchSyncIds);
		const included = new Set();
		for (const widget of Object.values(this.widgets)) {
			const payload = save ? widget.saveData : widget.syncData;
			if (!payload) continue;
			const update = { ...this._descriptor(widget), ...payload, save };
			if (save && touches.has(widget.syncId)) update.touch_parent = true;
			batch.push(update);
			included.add(widget.syncId);
		}
		if (save) {
			for (const syncId of touches) {
				if (included.has(syncId) || !this._pendingParentTouches.has(syncId))
					continue;
				const widget = this.widgets[syncId];
				if (!widget) continue;
				batch.push({
					...this._descriptor(widget),
					save: true,
					touch_parent: true,
				});
			}
		}
		return batch;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_sync_manager_uses_polling_subscriptions
	 * @features sync
	 * @dimensions checkpoint persistence dirty-state
	 */
	async _sendUpdatesNow(
		save = false,
		updates = null,
		{ keepalive = false, touchSyncIds = [] } = {},
	) {
		const batch = updates ?? this._collect(save, { touchSyncIds });
		if (!batch.length) return null;
		if (!this.view.online) {
			for (const update of batch) await updateSyncRecord(update);
			return null;
		}
		const response = await request.post(
			ENDPOINTS.sync,
			{
				client_id: this.view.PollingCoordinator?.clientId,
				updates: batch,
			},
			{ keepalive },
		);
		if (response?.ok === false) {
			for (const update of batch) {
				await updateSyncRecord(update);
				this._checkpointRetries.add(update.sync_id);
				this._checkpointPollFirst.delete(update.sync_id);
			}
			return response;
		}
		const submitted = new Map(batch.map((update) => [update.sync_id, update]));
		for (const acknowledgement of response?.updates ?? []) {
			const update = submitted.get(acknowledgement.sync_id);
			if (acknowledgement.checkpoint_accepted) {
				const cursor = {
					generation: acknowledgement.generation,
					revision: acknowledgement.revision,
				};
				this.view.PollingCoordinator?.update(
					`document:${acknowledgement.sync_id}`,
					cursor,
				);
				this._rememberCursor(acknowledgement.sync_id, cursor);
				this._checkpointRetries.delete(acknowledgement.sync_id);
				this._checkpointPollFirst.delete(acknowledgement.sync_id);
			}
			if (acknowledgement.checkpoint_persisted) {
				if (update?.save && update.ydoc) {
					const widget = this.widgets[acknowledgement.sync_id];
					if (widget?.commitSavedBaseline) {
						widget.commitSavedBaseline(update.ydoc);
					} else if (widget) {
						widget.snapshot = update.ydoc;
					}
				}
				if (acknowledgement.entity_touched) {
					this._pendingParentTouches.delete(acknowledgement.sync_id);
				} else {
					this._pendingParentTouches.add(acknowledgement.sync_id);
				}
				await deleteSyncRecord(acknowledgement.sync_id);
			} else if (acknowledgement.entity_touched) {
				this._pendingParentTouches.delete(acknowledgement.sync_id);
				await deleteSyncRecord(acknowledgement.sync_id);
			} else if (update?.save) {
				this._checkpointRetries.add(acknowledgement.sync_id);
				this._checkpointPollFirst.add(acknowledgement.sync_id);
				await updateSyncRecord(update);
			}
		}
		return response;
	}

	async sendUpdates(save = false, updates = null, options = {}) {
		if (this._sendPromise) {
			if (updates) {
				await this._sendPromise;
				return this.sendUpdates(save, updates, options);
			}
			this._queuedSend = {
				save: Boolean(this._queuedSend?.save || save),
				keepalive: Boolean(this._queuedSend?.keepalive || options.keepalive),
				touchSyncIds: new Set([
					...(this._queuedSend?.touchSyncIds ?? []),
					...(options.touchSyncIds ?? []),
				]),
			};
			return this._sendPromise;
		}
		this._sendPromise = (async () => {
			let response = await this._sendUpdatesNow(save, updates, options);
			while (this._queuedSend) {
				const queued = this._queuedSend;
				this._queuedSend = null;
				response = await this._sendUpdatesNow(queued.save, null, {
					keepalive: queued.keepalive,
					touchSyncIds: queued.touchSyncIds,
				});
			}
			return response;
		})();
		try {
			return await this._sendPromise;
		} finally {
			this._sendPromise = null;
		}
	}

	destroy() {
		for (const unsubscribe of this._subscriptions.values()) unsubscribe();
		this._subscriptions.clear();
		this._cursors.clear();
		this._checkpointRetries.clear();
		this._checkpointPollFirst.clear();
		this._pendingParentTouches.clear();
		this._activating.clear();
		this._registerPromise = null;
		window.removeEventListener("sync-save", this._syncSave);
		this._initialized = false;
	}
}

export { SyncManager };
