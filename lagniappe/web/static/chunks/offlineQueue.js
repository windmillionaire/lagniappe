/*! Third-party licenses: /third-party-licenses.txt */
import { getOfflineMutations, deleteOfflineMutations, setOfflineMutation } from './offline.js?v=b881d5e5';
import { r as request } from './foundation.js?v=b881d5e5';
import './connectivity.js?v=b881d5e5';

const REPLAY_RESULT = Object.freeze({
	BLOCKED: "blocked",
	COMPLETED: "completed",
	REBASED: "rebased",
});

/**
 * @testable false
 * @covered-by src/script/shared/offlineQueue.mjs::OfflineQueue
 * @reason private queue id helper exercised through queued offline mutations
 */
function createId() {
	if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
	return `offline-mutation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * @testable false
 * @covered-by src/script/shared/offlineQueue.mjs::OfflineQueue
 * @reason private response helper used by optimistic offline rendering
 */
function elementResponse(element) {
	const html = document.implementation.createHTMLDocument("");
	if (element) html.body.appendChild(element);
	return {
		ok: true,
		html,
	};
}

/**
 * @testable false
 * @covered-by src/script/shared/offlineQueue.mjs::OfflineQueue
 * @reason private IndexedDB serialization helper owned by offline queue behavior
 */
function serializeFormData(data) {
	const fields = [];
	const files = [];

	for (const [name, value] of data.entries()) {
		if (value instanceof File) {
			if (value.size > 0 && value.name) {
				files.push({
					name,
					file: value,
					filename: value.name,
					type: value.type,
				});
			}
		} else {
			fields.push([name, value]);
		}
	}

	return { fields, files };
}

/**
 * @testable false
 * @covered-by src/script/shared/offlineQueue.mjs::OfflineQueue
 * @reason private request payload rehydration helper owned by replay behavior
 */
function formDataFromRecord(record) {
	const data = new FormData();
	for (const [name, value] of record.fields || []) {
		data.append(name, value);
	}
	for (const file of record.files || []) {
		data.append(file.name, file.file, file.filename);
	}
	if (record.method !== "DELETE") {
		data.set("offline", "True");
		if (record.fingerprint) {
			data.set("offline-fingerprint", record.fingerprint);
		}
	}
	return data;
}

/**
 * @testable false
 * @covered-by src/script/shared/offlineQueue.mjs::OfflineQueue
 * @reason private queued-record field lookup used by optimistic renderers
 */
function field(record, name) {
	return (record.fields || []).find(([key]) => key === name)?.[1] || "";
}

/**
 * @testable infrastructure
 */
class OfflineQueue {
	constructor(view) {
		this.view = view;
		this.records = [];
		this._replaying = false;
	}

	async init() {
		this.records = await getOfflineMutations();
	}

	get widgets() {
		return Object.values(this.view.components).flatMap((component) => {
			return Object.values(component.widgets);
		});
	}

	get targets() {
		return this.widgets.filter(
			(widget) => typeof widget.handleOfflineQueue === "function",
		);
	}

	async _dispatch(context, targets = this.targets) {
		return Promise.all(
			[...new Set(targets)].filter(Boolean).map(async (target) => {
				if (typeof target === "function") return target(context);
				return target.handleOfflineQueue?.(context);
			}),
		);
	}

	_responseFromResults(results) {
		return results.find((result) => {
			return result && typeof result === "object" && "ok" in result;
		});
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_offline_submit_record_keeps_originating_entity_fingerprint
	 * @tests tests_js/test_028_form_state_split.py::test_offline_submit_record_keeps_renderer_snapshot_out_of_replay_payload
	 * @matrix offline : fingerprint immutable-command queue-submit renderer-snapshot
	 */
	async queueSubmit(component, data, route, method = "POST") {
		const widget = component.active;
		const target = widget?.target;
		if (!target?.hasAttribute("lp-offline")) return null;
		if (typeof widget.offline !== "function") return null;

		await this._destinationWidget(component);

		const action = method === "POST" ? "create" : "update";
		const partial = await widget.offline({
			action,
			queue: this,
			component,
			data,
			method,
			route,
			widget,
		});
		if (!partial) return null;
		const fingerprint =
			partial.fingerprint ??
			target.closest?.("[lp-entity]")?.dataset?.fingerprint ??
			this.view.elt?.dataset?.fingerprint ??
			null;
		const modified =
			partial.modified ??
			target.closest?.("[lp-entity]")?.dataset?.modified ??
			this.view.elt?.dataset?.modified ??
			null;
		const rendererSubmission =
			partial.renderer_submission ??
			widget.form?.renderer?._packageSubmission?.() ??
			null;
		const formControls = Array.from(
			target.querySelectorAll?.("[data-combobox-id]") || [],
		)
			.filter((control) => !control.closest?.(".form-element"))
			.map((control) => {
				const combobox = control._lp_combobox;
				if (!combobox?.name) return null;
				const options = (combobox.options || []).filter((option) =>
					combobox.values?.has(option.id),
				);
				return { name: combobox.name, options };
			})
			.filter(Boolean);

		const result = await this.queue({
			action,
			method,
			route,
			data,
			...partial,
			fingerprint,
			modified,
			renderer_submission: rendererSubmission,
			form_controls: formControls,
		});

		return result.response
			? { ...result.response, queued: true }
			: { ok: true, queued: true };
	}

	async _destinationWidget(component) {
		const destination = component.active?.target?.dataset.destination;
		if (!destination) return null;

		const [componentId, widgetName] = destination.split(":");
		if (!widgetName) return null;

		const componentElt =
			componentId === component.name
				? component.elt
				: document.getElementById(componentId);
		const destinationComponent = this.view.getComponent(componentElt);
		if (!destinationComponent) return null;

		return (
			destinationComponent.widgets[widgetName] ||
			(await destinationComponent.loadWidget(widgetName))
		);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_offline_replay_polls_mounted_form_without_direct_acknowledgement
	 * @tests tests_js/test_028_form_state_split.py::test_offline_replay_keeps_stale_submission_queued_for_reconciliation
	 * @tests tests_js/test_045_offline_queue.py::test_offline_replay_blocks_later_records_after_the_oldest_record_fails
	 * @tests tests_js/test_045_offline_queue.py::test_offline_replay_returns_the_completed_prefix_and_retries_the_oldest_record
	 * @tests tests_js/test_045_offline_queue.py::test_offline_replay_retries_rebased_record_before_later_record
	 * @tests tests_js/test_045_offline_queue.py::test_offline_replay_releases_ownership_after_handler_errors
	 * @tests tests_js/test_028_form_state_split.py::test_offline_replay_retries_a_conflict_rebased_by_the_form
	 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_replay_reconciles_after_reload
	 * @matrix offline : conflict-durability conflict-rebase dispatch queue-preserved queue-submit reload replay replay-order replay-reconciliation retry-boundary
	 * @pair edited-entity-notice:replayed-response
	 */
	async replay() {
		if (!this.view.online || this._replaying) return 0;

		this._replaying = true;
		let completed = 0;

		try {
			for (const record of this._sortedRecords()) {
				let current = record;
				while (current) {
					const result = await this._replayRecord(current);
					if (result.state === REPLAY_RESULT.REBASED) {
						current = result.record;
						continue;
					}
					if (result.state === REPLAY_RESULT.BLOCKED) return completed;
					if (result.state === REPLAY_RESULT.COMPLETED) {
						completed += 1;
						break;
					}
					throw new TypeError(`Unknown replay result: ${result.state}`);
				}
			}
		} finally {
			this._replaying = false;
		}

		return completed;
	}

	/**
	 * @testable false
	 * @covered-by src/script/shared/offlineQueue.mjs::OfflineQueue.replay
	 * @reason one-record replay outcomes are exercised through the ordered queue boundary
	 */
	async _replayRecord(record) {
		const response = await this._send(record);
		if (response?.conflict) {
			const attemptedFingerprint = record.fingerprint;
			record.conflictResponse = response;
			await this._dispatch({
				phase: "conflict",
				queue: this,
				record,
				response,
			});
			const rebased = this.records.find((queued) => queued.id === record.id);
			if (!rebased || rebased.fingerprint === attemptedFingerprint) {
				return { state: REPLAY_RESULT.BLOCKED };
			}
			return { state: REPLAY_RESULT.REBASED, record: rebased };
		}
		if (!response?.ok || response.error) {
			return { state: REPLAY_RESULT.BLOCKED };
		}

		await deleteOfflineMutations([record.id]);
		this.records = this.records.filter((queued) => queued.id !== record.id);
		const targets = this.targets;
		const mountedUpdateTargets =
			record.method === "PUT"
				? this._mountedUpdateTargets(record, targets)
				: [];
		this._finalize(record, response);
		await this._dispatch(
			{
				phase: "replayed",
				queue: this,
				record,
				response,
			},
			targets.filter((target) => !mountedUpdateTargets.includes(target)),
		);
		if (record.method === "PUT") {
			await this._pollMountedUpdate(record, mountedUpdateTargets);
		}
		return { state: REPLAY_RESULT.COMPLETED };
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_offline_replay_polls_mounted_form_without_direct_acknowledgement
	 * @tests tests_e2e/005_pages/test_005i_page_info_offline.py::test_page_info_replay_reconciles_after_reload
	 * @pairs edited-entity-notice:replayed-response offline:replay-reconciliation
	 */
	_mountedUpdateTargets(record, targets = this.targets) {
		return targets.filter(
			(target) =>
				target?.key === record.target_key &&
				target.target?.matches?.("form[data-widget]"),
		);
	}

	async _pollMountedUpdate(
		record,
		targets = this._mountedUpdateTargets(record),
	) {
		if (!targets.length) return;
		const watcher =
			this.view.EditWatcher || (await this.view.ensureEditWatcher?.());
		await watcher?.invalidate?.(record.target_key);
	}

	async rebaseSubmit(record, widget, { fingerprint, modified } = {}) {
		if (!record?.id || !widget) return null;
		const data = widget.component?.formData ?? widget.formData;
		if (!(data instanceof FormData)) return null;

		const serialized = serializeFormData(data);
		const currentFileNames = new Set(serialized.files.map((file) => file.name));
		serialized.files.push(
			...(record.files || []).filter(
				(file) => !currentFileNames.has(file.name),
			),
		);
		const rebased = {
			...record,
			fingerprint: fingerprint || record.fingerprint || null,
			modified: modified || record.modified || null,
			renderer_submission:
				widget.form?.renderer?._packageSubmission?.() ??
				record.renderer_submission ??
				null,
			fields: serialized.fields,
			files: serialized.files,
		};
		delete rebased.conflictResponse;

		await this._store(rebased);
		await this._dispatch({
			phase: "queued",
			queue: this,
			record: rebased,
		});
		return rebased;
	}

	async queue(record) {
		const queued = this._queuedRecord(record);
		await this._store(queued);
		const results = await this._dispatch({
			phase: "queued",
			queue: this,
			record: queued,
		});
		return {
			record: queued,
			response: this._responseFromResults(results),
		};
	}

	_queuedRecord(record) {
		const id = record.id || createId();
		const serialized = record.data
			? serializeFormData(record.data)
			: {
					fields: record.fields || [],
					files: record.files || [],
				};
		return {
			id,
			action:
				record.action || (record.method === "DELETE" ? "delete" : "submit"),
			kind: record.kind,
			method: record.method || "POST",
			route: record.route,
			client_key:
				record.client_key ||
				(record.action === "create" ? `offline:${id}` : null),
			target_key: record.target_key,
			fingerprint: record.fingerprint || null,
			modified: record.modified || null,
			renderer_submission: record.renderer_submission ?? null,
			form_controls: record.form_controls || [],
			fields: serialized.fields,
			files: serialized.files,
			created_at: record.created_at || Date.now(),
		};
	}

	response(element) {
		return elementResponse(element);
	}

	field(record, name) {
		return field(record, name);
	}

	recordsFor({ kind = null, action = null } = {}) {
		return this._sortedRecords().filter((record) => {
			if (kind && record.kind !== kind) return false;
			if (action && record.action !== action) return false;
			return true;
		});
	}

	async cancel(match) {
		const records = this.records.filter((record) => {
			return this._recordMatches(record, match);
		});
		if (records.length === 0) return [];

		await deleteOfflineMutations(records.map((record) => record.id));
		const ids = new Set(records.map((record) => record.id));
		this.records = this.records.filter((record) => !ids.has(record.id));
		await Promise.all(
			records.map((record) => {
				return this._dispatch({
					phase: "cancelled",
					queue: this,
					record,
				});
			}),
		);
		return records;
	}

	_recordMatches(record, match) {
		if (typeof match === "function") return match(record);
		if (typeof match === "string") {
			return [record.id, record.client_key, record.target_key].includes(match);
		}
		if (!match || typeof match !== "object") return false;

		return Object.entries(match).every(([key, value]) => record[key] === value);
	}

	async _store(record) {
		await setOfflineMutation(record);
		this.records = [
			...this.records.filter((existing) => existing.id !== record.id),
			record,
		];
	}

	_sortedRecords() {
		return [...this.records].sort((a, b) => a.created_at - b.created_at);
	}

	/**
	 * @testable true
	 * @tests tests_js/test_028_form_state_split.py::test_offline_replay_keeps_stale_submission_queued_for_reconciliation
	 * @tests tests_js/test_028_form_state_split.py::test_offline_submit_record_keeps_renderer_snapshot_out_of_replay_payload
	 * @matrix offline : fingerprint-precondition reload replay-payload
	 */
	async _send(record) {
		if (record.method === "DELETE") return request.delete(record.route);

		const data = formDataFromRecord(record);
		if (record.method === "PUT") {
			return request.put(record.route, data, { acknowledgeEntities: false });
		}
		return request.post(record.route, data);
	}

	_finalize(record, response) {
		const key =
			record.action === "create" ? record.client_key : record.target_key;
		if (!key) return;
		const current = document.querySelector(`[data-key="${key}"]`);

		if (record.action === "create") {
			const replacement = response.html?.querySelector("li,[lp-entity]");
			if (current && replacement) current.replaceWith(replacement);
			else if (current && response.removed) current.remove();
			return;
		}

		if (["complete", "delete"].includes(record.action) && current) {
			current.remove();
		}
	}
}

export { OfflineQueue };
