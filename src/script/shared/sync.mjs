import { loadHeadlessWidget } from "../widgets/loader";
import { ENDPOINTS } from "./endpoints";
import {
	deleteSyncRecord,
	deleteSyncRecords,
	getAllOfflineRecords,
	getSyncRecord,
	updateSyncRecord,
} from "./offline";
import { EVENTS } from "./protocol";
import { request } from "./request";
import { waitForAttribute } from "./utilities";

/**
 * SyncManager — view-scoped sync coordinator.
 *
 * Wires the syncable widgets on the page to the /register, /sync, /state,
 * and /deregister endpoints. The flow is:
 *
 *   • register() — at view start, send every widget's (sync_id, fingerprint)
 *     plus any offline records. Widgets that drifted come back in the
 *     response; we merge offline edits into them and ship the result.
 *   • sendUpdates(save) — poll loop (every 2s) that batches each widget's
 *     syncData (or saveData on explicit save) and posts to /sync.
 *   • receiveUpdate(event) — service worker push handler; routes the update
 *     to the right widget and lets it apply.
 *   • deregister() — best-effort cleanup on tab hide / unload / offline.
 *
 * Widget contract (anything in `component.widgets` that opts in):
 *   syncId, fingerprint, component, initialized,
 *   syncData (incremental payload or null),
 *   saveData (full save payload or null),
 *   async sync() — consumes `remote` / `update` / `offlineRecord` slots set by
 *   the manager and clears them when done.
 *
 * @testable infrastructure
 */
export class SyncManager {
	constructor(view) {
		this.view = view;
		this.token = view.fcmToken;

		this._registered = false;
		this._initialized = false;
		this._timeout = null;
		this._registeredIds = new Set();
		this._sendPromise = null;
		this._queuedSend = null;

		this.receiveUpdate = this.receiveUpdate.bind(this);
		this._poll = this._poll.bind(this);
		this._syncSave = () => this.sendUpdates(true);
		this.register = this.register.bind(this);
		this.deregister = this.deregister.bind(this);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_destroy_removes_sync_listeners
	 * @pair sync:lifecycle-listeners
	 */
	init() {
		if (this._initialized) return;
		this._initialized = true;
		this.register();

		window.addEventListener(EVENTS.SYNC_UPDATE, this.receiveUpdate);
		window.addEventListener("sync-save", this._syncSave);
	}

	// ------------------------------------------------------------------
	// Widget discovery
	// ------------------------------------------------------------------

	/** Live snapshot of every initialized document widget keyed by sync_id. */
	get widgets() {
		const entries = [];
		for (const component of Object.values(this.view.components)) {
			for (const widget of Object.values(component.widgets)) {
				if (widget.syncId && widget.initialized) {
					entries.push([widget.syncId, widget]);
				}
			}
		}
		return Object.fromEntries(entries);
	}

	/** Compact descriptor of a widget for the wire format. */
	_descriptor(widget) {
		return {
			key: widget.component.key,
			sync_id: widget.syncId,
			fingerprint: widget.fingerprint,
		};
	}

	// ------------------------------------------------------------------
	// Single-widget state fetch (called from widget.init())
	// ------------------------------------------------------------------

	/**
	 * @testable true
	 * @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_presence_appears_and_clears
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_state_without_token_fetches_without_registering
	 * @pair sync:state-registration
	 * @pair sync:state-only
	 * @pair sync:deregistration
	 * @pair sync:presence
	 */
	async state(widget) {
		const offline = await getSyncRecord(widget.syncId);
		if (offline) widget.offlineRecord = offline;

		if (!this.view.online) return null;

		const remote = await request.post(ENDPOINTS.state, {
			...(this.token ? { token: this.token } : {}),
			sync_id: widget.syncId,
			key: widget.component.key,
			fingerprint: widget.fingerprint,
		});

		if (remote?.ok === false) return null;
		if (this.token) {
			this._registeredIds.add(widget.syncId);
			if (offline) await deleteSyncRecord(widget.syncId);
		}
		return remote;
	}

	// ------------------------------------------------------------------
	// Registration / deregistration
	// ------------------------------------------------------------------

	/**
	 * @testable true
	 * @tests tests_e2e/010_sync/test_010a_document_sync.py::test_two_users_see_document_edits_without_reload
	 * @tests tests_js/test_028_form_state_split.py::test_document_sync_registration_discards_legacy_form_patch_records
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_hidden_view_does_not_register
	 * @features sync
	 * @dimensions document collaboration document-only legacy-form-patch-cleanup hidden-view
	 */
	async register() {
		if (!this.token || !this.view.online || this.view.hidden) return;
		if (this._timeout) {
			clearTimeout(this._timeout);
			this._timeout = null;
		}
		this._registered = true;

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
		const offlineDescriptors = offline.map(({ key, sync_id, fingerprint }) => ({
			key,
			sync_id,
			fingerprint,
		}));

		const active = Object.values(this.widgets).map((w) => this._descriptor(w));
		const response = await request.post(ENDPOINTS.register, {
			token: this.token,
			active,
			offline: offlineDescriptors,
		});

		await this._reconcile(offline, response?.modified ?? []);
		this._trackRegisteredIds();
		this._timeout = setTimeout(this._poll, 2000);
	}

	/**
	 * @testable true
	 * @tests tests_e2e/010_sync/test_010a_document_sync.py::test_document_presence_appears_and_clears
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_deregister_keeps_unload_sync_and_cleanup_keepalive
	 * @features sync
	 * @dimensions document deregistration stale-sessions presence keepalive
	 */
	async deregister() {
		if (this._timeout) clearTimeout(this._timeout);
		this._timeout = null;
		if (!this.token) return;

		if (!this.view.online) {
			await this.sendUpdates(true, null, { keepalive: true });
			return;
		}

		const sync_ids = [...this._registeredIds];
		this._registeredIds.clear();
		this._registered = false;

		await this.sendUpdates(true, null, { keepalive: true });

		if (sync_ids.length) {
			await request.post(
				ENDPOINTS.deregister,
				{ token: this.token, sync_ids },
				{ keepalive: true },
			);
		}

		if (this._timeout) clearTimeout(this._timeout);
		this._timeout = null;
		this._registeredIds.clear();
	}

	_trackRegisteredIds() {
		for (const sync_id of Object.keys(this.widgets)) {
			this._registeredIds.add(sync_id);
		}
	}

	async _waitForWidgetInitialized(widget) {
		if (widget.initialized) return;
		const target = widget.container ?? widget.target;
		if (!target) return;
		await waitForAttribute(target, "initialized");
	}

	/**
	 * @testable true
	 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_document_edits_replay_in_order
	 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_failed_offline_replay_keeps_queue_and_retries
	 * @tests tests_e2e/010_sync/test_010c_offline_replay.py::test_offline_replay_does_not_duplicate_after_reload
	 * @features sync
	 * @dimensions offline-replay replay-error queue-preserved retry
	 *
	 * Reconcile everything that needs attention after /register:
	 *   - widgets the server flagged as drifted (`modified`),
	 *   - offline records the client still has (`offlineRecords`).
	 *
	 * Both lists key on sync_id, so we union them and walk once. Mounted
	 * widgets and headless stand-ins (see `loadHeadlessWidget`) share the
	 * same path: assign remote/offlineRecord slots, `sync()`, then `saveData`.
	 *
	 * Offline records are deleted only after the replay batch is accepted by
	 * /sync, so a transient server/network failure can be retried.
	 */
	async _reconcile(offlineRecords, modified) {
		if (!modified.length && !offlineRecords.length) return;

		const widgets = this.widgets;
		const work = new Map();
		for (const m of modified) work.set(m.sync_id, { remote: m, offline: null });
		for (const o of offlineRecords) {
			const entry = work.get(o.sync_id) ?? { remote: null, offline: null };
			entry.offline = o;
			work.set(o.sync_id, entry);
		}

		const replays = [];
		const headless = [];

		for (const [sync_id, { remote, offline }] of work) {
			let widget = widgets[sync_id];
			let destroy = false;

			if (!widget) {
				widget = await loadHeadlessWidget({ sync_id, remote, offline });
				if (!widget) continue;
				destroy = true;
				await widget.init();
				await this._waitForWidgetInitialized(widget);
			}

			widget.remote = remote;
			widget.offlineRecord = offline;
			await widget.sync();

			const saveData = widget.saveData;
			if (saveData) {
				replays.push({
					key:
						widget.component?.key ?? widget.key ?? remote?.key ?? offline?.key,
					sync_id,
					fingerprint: widget.fingerprint,
					...saveData,
					save: true,
				});
			} else if (offline?.save) {
				replays.push({
					...offline,
					key: widget.component?.key ?? widget.key ?? offline.key,
					sync_id,
					fingerprint: widget.fingerprint ?? offline.fingerprint,
					save: true,
				});
			}

			if (destroy) headless.push(widget);
		}

		const response = replays.length
			? await this.sendUpdates(false, replays)
			: null;
		const replayAccepted = response?.ok !== false;
		if (offlineRecords.length && replayAccepted) {
			await deleteSyncRecords(offlineRecords.map((o) => o.sync_id));
		}
		for (const w of headless) w.destroy();
	}

	// ------------------------------------------------------------------
	// Outgoing updates
	// ------------------------------------------------------------------

	_poll() {
		this.sendUpdates(false);
	}

	_tokenlessSaveBatch(batch) {
		return batch.filter(
			(update) =>
				update.save === true &&
				update.sync_id?.endsWith(":document") &&
				Object.hasOwn(update, "html"),
		);
	}

	/** Collect each active widget's payload, tagged with the save intent. */
	_collect(save, { documentOnly = false } = {}) {
		const batch = [];
		for (const widget of Object.values(this.widgets)) {
			if (documentOnly && !widget.syncId?.endsWith(":document")) continue;
			const payload = save ? widget.saveData : widget.syncData;
			if (!payload) continue;
			batch.push({ ...this._descriptor(widget), ...payload, save });
		}
		return batch;
	}

	/**
	 * @testable true
	 * @tests tests_e2e/001_site/test_001d_offline.py::test_offline_prevents_sync_requests
	 * @features offline
	 * @dimensions sync-queue reconnect
	 */
	async _sendUpdatesNow(
		save = false,
		updates = null,
		{ keepalive = false } = {},
	) {
		if (!this.token && !save && !updates) return;
		if (this._timeout) {
			clearTimeout(this._timeout);
			this._timeout = null;
		}

		let batch = updates ?? this._collect(save, { documentOnly: !this.token });
		if (!this.token) batch = this._tokenlessSaveBatch(batch);

		if (!batch.length) {
			if (this._registered) this._timeout = setTimeout(this._poll, 2000);
			return;
		}

		let response = null;
		if (this.view.online) {
			response = await request.post(
				ENDPOINTS.sync,
				{ ...(this.token ? { token: this.token } : {}), updates: batch },
				{ keepalive },
			);
		} else if (this.token) {
			for (const update of batch) await updateSyncRecord(update);
		}

		if (this.token) this._trackRegisteredIds();
		if (this._registered) this._timeout = setTimeout(this._poll, 2000);
		return response;
	}

	/**
	 * @testable true
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_send_updates_queues_save_behind_in_flight_sync_without_keepalive
	 * @tests tests_js/test_010_sync_manager_frontend.py::test_tokenless_document_save_posts_without_registering
	 * @features sync
	 * @dimensions request-queue keepalive tokenless-save document registration-exclusion
	 */
	async sendUpdates(save = false, updates = null, options = {}) {
		if (!this.token && !save && !updates) return;

		if (this._sendPromise) {
			if (updates) {
				await this._sendPromise;
				return this.sendUpdates(save, updates, options);
			}

			this._queuedSend = {
				save: Boolean(this._queuedSend?.save || save),
				keepalive: Boolean(this._queuedSend?.keepalive || options.keepalive),
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

	// ------------------------------------------------------------------
	// Incoming push updates
	// ------------------------------------------------------------------

	/**
	 * @testable true
	 * @tests tests_e2e/010_sync/test_010a_document_sync.py::test_two_users_see_document_edits_without_reload
	 * @features sync
	 * @dimensions document collaboration
	 */
	async receiveUpdate(event) {
		const update = event.detail?.update;
		if (!update) return;

		const widget = this.widgets[update.sync_id];
		if (!widget) return;

		if (update.fetch) {
			widget.remote = await this.state(widget);
		} else {
			widget.update = update;
		}

		await widget.sync();
	}
	destroy() {
		if (this._timeout) clearTimeout(this._timeout);
		this._timeout = null;
		window.removeEventListener(EVENTS.SYNC_UPDATE, this.receiveUpdate);
		window.removeEventListener("sync-save", this._syncSave);
		this._initialized = false;
	}
}
