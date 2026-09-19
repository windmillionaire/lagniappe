import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { incompatibleSchema } from "../../src/script/forms/representation.mjs";
import { createBrowser, installIndexedDB } from "../utility/js/environment.mjs";

async function loadFormWidget({
	FormController = class {},
	installMigrationNotice,
} = {}) {
	const mocks = {
		"../../src/script/forms/controller.mjs": { FormController },
	};
	if (installMigrationNotice) {
		mocks["../../src/script/forms/migrationNotice.mjs"] = {
			installMigrationNotice,
		};
	}
	return await esmock.strict(
		"../../src/script/widgets/base/formWidget.mjs",
		mocks,
	);
}

async function loadOfflineQueue({
	deleteOfflineMutations = async () => {},
	getOfflineMutations = async () => [],
	setOfflineMutation = async () => {},
	request = {},
} = {}) {
	return await esmock.strict("../../src/script/shared/offlineQueue.mjs", {
		"../../src/script/shared/offline.mjs": {
			deleteOfflineMutations,
			getOfflineMutations,
			setOfflineMutation,
		},
		"../../src/script/shared/request.mjs": { request },
	});
}

async function loadEditOwners({ loadRevisionPreview, request = {} } = {}) {
	const { EditReconciler } = await esmock.strict(
		"../../src/script/forms/revisions/reconciler.mjs",
		{
			"../../src/script/shared/errors.mjs": {
				captureError(error) {
					throw error;
				},
			},
			"../../src/script/shared/request.mjs": { request },
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => callback(),
			},
			"../../src/script/shared/utilities.mjs": {
				areEqual: (left, right) =>
					JSON.stringify(left) === JSON.stringify(right),
			},
			"../../src/script/forms/representation.mjs": { incompatibleSchema },
			"../../src/script/forms/revisions/modals.mjs": {
				FormRevisionModal: class {},
				WholeFormRevisionModal: class {},
			},
			"../../src/script/forms/revisions/preview.mjs": { loadRevisionPreview },
		},
	);
	const { EditWatcher } = await esmock.strict(
		"../../src/script/forms/revisions/watcher.mjs",
		{
			"../../src/script/shared/errors.mjs": {
				captureError(error) {
					throw error;
				},
			},
			"../../src/script/forms/revisions/reconciler.mjs": { EditReconciler },
		},
	);
	return { EditReconciler, EditWatcher };
}

async function loadCore(connectivity = { online: true, hidden: true }) {
	class ShellView {
		constructor(elt) {
			this.elt = elt;
			this.kind = elt.dataset.kind;
			this.key = elt.dataset.key;
			this.hash = elt.dataset.hash || elt.dataset.index;
			this.online = connectivity.online;
			this.hidden = connectivity.hidden;
			this.components = {};
			this._destroyed = false;
		}
	}
	const service = (name) => (view) => Promise.resolve(view[name] ?? null);
	const { default: Core } = await esmock.strict(
		"../../src/script/views/base/core.mjs",
		{
			"../../src/script/shared/connectivity.mjs": { connectivity },
			"../../src/script/shared/endpoints.mjs": { ENDPOINTS: {} },
			"../../src/script/shared/errors.mjs": {
				captureError(error) {
					throw error;
				},
			},
			"../../src/script/shared/request.mjs": { request: {} },
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => callback(),
			},
			"../../src/script/views/base/component.mjs": { default: class {} },
			"../../src/script/views/base/reconciliation.mjs": {
				collectRefreshTargets: () => [],
				reconcileChange() {},
				refreshCollectionComponents() {},
			},
			"../../src/script/views/base/services.mjs": {
				ensureDeferredOperations: service("DeferredOperations"),
				ensureEditWatcher: service("EditWatcher"),
				ensureEntityMenu: service("EntityMenu"),
				ensureModalClasses: service("ModalClasses"),
				ensureNotifications: service("Notifications"),
				ensureOfflineModal: service("offlineModal"),
				ensureOfflineQueue: service("offlineQueue"),
				ensurePollingCoordinator: service("PollingCoordinator"),
				ensureSearchBox: service("SearchBox"),
				ensureSubmissionManager: service("SubmissionManager"),
				ensureSyncManager: service("SyncManager"),
				initializeCoreServices() {},
			},
			"../../src/script/views/base/shell.mjs": { default: ShellView },
			"../../src/script/views/base/task.mjs": { Task: class {} },
		},
	);
	return Core;
}

async function loadPageTaskList() {
	return await esmock.strict("../../src/script/widgets/pageTaskList.mjs", {
		"../../src/script/elements/base/baseList.mjs": { BaseList: class {} },
	});
}

/** @matrix form-migration : informational-notice */
test("test_migration_notice_survives_form_replacement_and_discard", async (t) => {
	createBrowser(t);
	const modals = [];
	class Modal {
		constructor() {
			this.destroyed = 0;
			modals.push(this);
		}
		destroy() {
			this.destroyed += 1;
		}
	}
	const { installMigrationNotice } = await esmock.strict(
		"../../src/script/forms/migrationNotice.mjs",
		{ "../../src/script/shared/modal.mjs": { Modal } },
	);
	class FormController {
		async init() {}
		destroy() {}
	}
	const { FormWidget } = await loadFormWidget({
		FormController,
		installMigrationNotice,
	});
	const values = JSON.stringify([
		{ label: "Quantity", before: "invalid", after: "", reason: "invalid" },
	]);
	const makeTarget = (migrationNotice = values) => {
		const target = document.createElement("form");
		target.dataset.migrationNotice = migrationNotice;
		return target;
	};
	const mounted = makeTarget();
	document.body.append(mounted);
	const widget = new FormWidget({ target: mounted });
	widget.revisionSnapshot = () => "baseline";
	await widget.init();
	const original = widget.target;
	const banner = original.firstElementChild;
	assert.equal(banner.dataset.role, "migration-notice");

	const replacement = makeTarget();
	await widget.prepareReset({ nextTarget: replacement });
	assert.equal(original.firstElementChild, banner);
	assert.equal(modals[0].destroyed, 0);
	const newBanner = replacement.firstElementChild;
	widget.commitReset();
	assert.equal(widget.target, replacement);
	assert.equal(replacement.firstElementChild, newBanner);
	assert.equal(newBanner.dataset.role, "migration-notice");
	assert.equal(modals[0].destroyed, 1);
	assert.equal(modals[1].destroyed, 0);

	const discarded = makeTarget();
	await widget.prepareReset({ nextTarget: discarded });
	widget.discardPreparedReset();
	assert.equal(widget.target, replacement);
	assert.equal(replacement.firstElementChild, newBanner);
	assert.equal(modals[1].destroyed, 0);
	assert.equal(discarded.children.length, 0);
	assert.equal(modals[2].destroyed, 1);

	await widget.prepareReset({ nextTarget: makeTarget("[]") });
	widget.commitReset();
	assert.equal(widget.target.children.length, 0);
	assert.equal(modals[1].destroyed, 1);
	widget.destroy();
	assert.equal(modals[1].destroyed, 1);
});

/** @matrix offline : database-upgrade legacy-record-discard mutation-store */
test("test_offline_database_upgrade_discards_legacy_activity_records", async (t) => {
	createBrowser(t, { formData: "native" });
	const factory = installIndexedDB(t);
	const legacy = await new Promise((resolve, reject) => {
		const request = factory.open("offline-db", 3);
		request.onupgradeneeded = () => {
			request.result.createObjectStore("sync", { keyPath: "sync_id" });
			request.result.createObjectStore("activity", { keyPath: "id" });
		};
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error);
	});
	await new Promise((resolve, reject) => {
		const tx = legacy.transaction("activity", "readwrite");
		tx.objectStore("activity").put({ id: "legacy-unsent-command" });
		tx.oncomplete = resolve;
		tx.onerror = () => reject(tx.error);
	});
	legacy.close();
	const { getOfflineMutations } = await import(
		"../../src/script/shared/offline.mjs"
	);
	assert.deepEqual(await getOfflineMutations(), []);
	const upgraded = await new Promise((resolve, reject) => {
		const request = factory.open("offline-db", 5);
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error);
	});
	assert.equal(upgraded.objectStoreNames.contains("activity"), false);
	assert.equal(upgraded.objectStoreNames.contains("mutations"), true);
	upgraded.close();
});

/** @matrix deferred-jobs forms submission : deliberate-submit form-lock no-live-sync */
test("test_form_submit_is_guarded_only_by_durable_autofill_lock", async (t) => {
	createBrowser(t);
	const { FormWidget } = await loadFormWidget();
	const target = document.createElement("div");
	const widget = new FormWidget({
		target,
		view: {
			SyncManager: {
				sendUpdates() {
					throw new Error("form used live sync");
				},
			},
		},
	});
	assert.equal(widget.syncId, undefined);
	assert.equal(widget.syncData, undefined);
	assert.equal(await widget.prepareSubmit(), true);
	let delegatedOptions;
	widget.form = {
		_subForm: {
			async prepareSubmit(options) {
				delegatedOptions = options;
				return true;
			},
		},
	};
	const options = { route: "/pages/page-key/update" };
	assert.equal(await widget.prepareSubmit(options), true);
	assert.equal(delegatedOptions, options);

	const formTarget = document.createElement("form");
	const formWidget = new FormWidget({ target: formTarget });
	formWidget.form = {
		_subForm: {
			applyDirectUploads(data) {
				data.directUploadApplied = true;
				return data;
			},
		},
	};
	assert.equal(formWidget.formData.directUploadApplied, true);
	widget.lockDeferredOperation({ operation: "operation-1", revision: 3 });
	assert.equal(await widget.prepareSubmit(), false);
	widget.lockDeferredOperation({
		operation: "migration-1",
		revision: 0,
		scope: "form-change",
	});
	for (const node of [widget.target, widget.initialTarget]) {
		assert.equal(node.dataset.operationScope, "form-change");
	}
});

/** @matrix deferred-jobs : form-lock reload */
test("test_active_deferred_form_waits_for_root_operation_scan", async (t) => {
	createBrowser(t);
	const scans = [];
	let ensureCalls = 0;
	let releaseManager;
	const managerReady = new Promise((resolve) => {
		releaseManager = resolve;
	});
	class FormController {
		async init() {}
	}
	const { FormWidget } = await loadFormWidget({ FormController });
	const target = document.createElement("form");
	target.dataset.operation = "operation-1";
	document.body.append(target);
	const widget = new FormWidget({
		target,
		view: {
			ensureDeferredOperations() {
				ensureCalls += 1;
				return managerReady;
			},
		},
	});
	let initialized = false;
	const pending = widget._initForm().then(() => {
		initialized = true;
	});
	await new Promise((resolve) => setImmediate(resolve));
	assert.equal(ensureCalls, 1);
	assert.equal(initialized, false);
	releaseManager({
		scan(node) {
			scans.push(node);
		},
	});
	await pending;
	assert.deepEqual(scans, [widget.target]);
});

/** @matrix edited-entity-notice form-schema forms : latest-schema local-values no-schema-version-choice remote-added-values */
test("test_local_revision_uses_latest_schema_and_merges_submission_values", async (t) => {
	createBrowser(t);
	const { FormWidget } = await loadFormWidget();
	const target = document.createElement("form");
	const replacementTarget = document.createElement("form");
	replacementTarget.dataset.widget = "PageInfo";
	const responseDocument = document.implementation.createHTMLDocument("");
	responseDocument.body.append(replacementTarget);
	const widget = new FormWidget({
		target,
		name: "PageInfo",
		schema: [
			{ id: "retained", type: "input" },
			{ id: "removed", type: "input" },
		],
	});
	widget._applyQueuedFields = (targetNode, state) => {
		assert.equal(targetNode.dataset.widget, "PageInfo");
		assert.deepEqual(state.fields[0], ["name", "Local name"]);
	};
	const local = widget.buildLocalRevision(
		{
			html: responseDocument,
			schema: [
				{ id: "retained", type: "input" },
				{ id: "added", type: "input" },
			],
			submission: { retained: "Saved", added: "New saved value" },
		},
		{
			fields: [["name", "Local name"]],
			files: [],
			form_controls: [],
			renderer_submission: { retained: "Local", removed: "Old local value" },
		},
	);
	assert.deepEqual(local.response.submission, {
		retained: "Local",
		added: "New saved value",
	});
	assert.deepEqual(local.response.schema, [
		{ id: "retained", type: "input" },
		{ id: "added", type: "input" },
	]);
});

/** @matrix offline : fingerprint immutable-command queue-submit */
test("test_offline_submit_record_keeps_originating_entity_fingerprint", async (t) => {
	createBrowser(t, {
		formData: "native",
		html: '<main lp-entity data-fingerprint="fingerprint-at-submit" data-modified="2026-07-22T10:00:00+00:00"><form lp-offline></form></main>',
	});
	let stored;
	const { OfflineQueue } = await loadOfflineQueue();
	const form = document.querySelector("form");
	const widget = {
		target: form,
		async offline() {
			return { id: "update:page:one", kind: "page", target_key: "page-one" };
		},
	};
	const manager = new OfflineQueue({ components: {}, elt: { dataset: {} } });
	manager._destinationWidget = async () => null;
	manager._store = async (record) => {
		stored = record;
	};
	manager._dispatch = async () => [];
	const data = new FormData();
	data.append("name", "Offline edit");
	await manager.queueSubmit(
		{ active: widget },
		data,
		"/pages/page-one/update",
		"PUT",
	);
	assert.equal(stored.fingerprint, "fingerprint-at-submit");
	assert.equal(stored.modified, "2026-07-22T10:00:00+00:00");
	assert.deepEqual(stored.fields[0], ["name", "Offline edit"]);
});

/** @matrix offline : reload renderer-snapshot replay-payload */
test("test_offline_submit_record_keeps_renderer_snapshot_out_of_replay_payload", async (t) => {
	createBrowser(t, {
		formData: "native",
		html: '<main lp-entity data-fingerprint="fingerprint-1" data-modified="2026-07-22T10:00:00+00:00"><form lp-offline></form></main>',
	});
	let stored;
	let replayed;
	const request = {
		async put(_route, data) {
			replayed = [...data.entries()];
			return { ok: true };
		},
	};
	const { OfflineQueue } = await loadOfflineQueue({ request });
	const rendererSubmission = {
		headline: "Queued headline",
		items: { rows: [{ note: "Queued row" }] },
	};
	const widget = {
		target: document.querySelector("form"),
		form: {
			renderer: { _packageSubmission: () => rendererSubmission },
		},
		async offline() {
			return { id: "update:page:one", kind: "page", target_key: "page-one" };
		},
	};
	const manager = new OfflineQueue({ components: {}, elt: { dataset: {} } });
	manager._destinationWidget = async () => null;
	manager._store = async (record) => {
		stored = record;
	};
	manager._dispatch = async () => [];
	const data = new FormData();
	data.append("headline", "Queued headline");
	await manager.queueSubmit(
		{ active: widget },
		data,
		"/pages/page-one/update",
		"PUT",
	);
	assert.deepEqual(stored.renderer_submission, rendererSubmission);
	await manager._send(stored);
	assert.deepEqual(replayed, [
		["headline", "Queued headline"],
		["offline", "True"],
		["offline-fingerprint", "fingerprint-1"],
	]);
});

function offlineRecord() {
	return {
		id: "update:page:one",
		action: "update",
		kind: "page",
		method: "PUT",
		route: "/pages/page-one/update",
		target_key: "page-one",
		fingerprint: "originating-fingerprint",
		modified: "2026-07-22T10:00:00+00:00",
		fields: [["name", "Queued name"]],
		files: [],
		created_at: 1,
	};
}

/** @matrix offline : conflict-durability dispatch fingerprint-precondition */
test("test_offline_replay_keeps_stale_submission_queued_for_reconciliation", async (t) => {
	createBrowser(t, { formData: "native" });
	const deleted = [];
	const phases = [];
	let payload;
	const request = {
		async put(_route, data, options) {
			payload = { values: [...data.entries()], options };
			return {
				ok: true,
				conflict: true,
				entities: [{ key: "page-one", fingerprint: "server-fingerprint" }],
			};
		},
	};
	const { OfflineQueue } = await loadOfflineQueue({
		deleteOfflineMutations: async (ids) => deleted.push(...ids),
		request,
	});
	const record = offlineRecord();
	const manager = new OfflineQueue({ online: true, components: {} });
	manager.records = [record];
	manager._dispatch = async ({ phase }) => phases.push(phase);
	assert.equal(await manager.replay(), 0);
	assert.deepEqual(deleted, []);
	assert.deepEqual(manager.records, [record]);
	assert.deepEqual(phases, ["conflict"]);
	assert.equal(record.conflictResponse.conflict, true);
	assert.equal(
		Object.fromEntries(payload.values)["offline-fingerprint"],
		"originating-fingerprint",
	);
	assert.equal(Object.fromEntries(payload.values).offline, "True");
	assert.equal(payload.options.acknowledgeEntities, false);
});

/** @pairs edited-entity-notice:replayed-response offline:replay-reconciliation */
test("test_offline_replay_polls_mounted_form_without_direct_acknowledgement", async (t) => {
	createBrowser(t, { formData: "native" });
	const events = [];
	let queue;
	const { OfflineQueue } = await loadOfflineQueue({
		deleteOfflineMutations: async (ids) => {
			events.push({ type: "delete", ids, remaining: queue.records.length });
		},
		request: {
			async put() {
				return { ok: true, entities: [{ key: "page-one" }] };
			},
		},
	});
	const mountedForm = {
		key: "page-one",
		target: { matches: (selector) => selector === "form[data-widget]" },
		handleOfflineQueue() {},
	};
	queue = new OfflineQueue({
		online: true,
		components: { info: { widgets: { PageInfo: mountedForm } } },
		async ensureEditWatcher() {
			return {
				async invalidate(key) {
					events.push({ type: "poll", key, remaining: queue.records.length });
				},
			};
		},
	});
	queue.records = [offlineRecord()];
	queue._dispatch = async ({ phase }, targets = []) => {
		events.push({
			type: phase,
			remaining: queue.recordsFor({ kind: "page" }).length,
			targets: targets.length,
		});
	};
	assert.equal(await queue.replay(), 1);
	assert.deepEqual(queue.records, []);
	assert.deepEqual(
		events.map(({ type }) => type),
		["delete", "replayed", "poll"],
	);
	assert.equal(events[1].remaining, 0);
	assert.equal(events[1].targets, 0);
	assert.equal(events[2].remaining, 0);
	assert.equal(events[2].key, "page-one");
});

/** @matrix offline : conflict-rebase replay */
test("test_offline_replay_retries_a_conflict_rebased_by_the_form", async (t) => {
	createBrowser(t, { formData: "native" });
	const deleted = [];
	const phases = [];
	const fingerprints = [];
	const { OfflineQueue } = await loadOfflineQueue({
		deleteOfflineMutations: async (ids) => deleted.push(...ids),
		request: {
			async put(_route, data) {
				const fingerprint = data.get("offline-fingerprint");
				fingerprints.push(fingerprint);
				return fingerprint === "originating-fingerprint"
					? { ok: true, conflict: true }
					: { ok: true };
			},
		},
	});
	const record = offlineRecord();
	const queue = new OfflineQueue({ online: true, components: {} });
	queue.records = [record];
	queue._dispatch = async ({ phase, record: dispatched }) => {
		phases.push(phase);
		if (phase === "conflict") {
			await queue._store({ ...dispatched, fingerprint: "current-fingerprint" });
		}
	};
	assert.equal(await queue.replay(), 1);
	assert.deepEqual(fingerprints, [
		"originating-fingerprint",
		"current-fingerprint",
	]);
	assert.deepEqual(phases, ["conflict", "replayed"]);
	assert.deepEqual(deleted, [record.id]);
	assert.deepEqual(queue.records, []);
});

/** @matrix edited-entity-notice : active-state latest-schema local-values renderer-capability schema-only submission-choice whole-form-selection */
test("test_edit_watcher_separates_schema_and_renderer_value_changes", async (t) => {
	createBrowser(t);
	const events = [];
	const anchor = {
		dataset: {
			key: "page-one",
			fingerprint: "old",
			modified: "2026-07-22T10:00:00+00:00",
		},
	};
	const makeMarker = (widget) => {
		const button = { textContent: "", disabled: false };
		const message = { textContent: "" };
		const form = { _lp_widget: widget };
		const marker = {
			dataset: { visible: "false" },
			querySelector(selector) {
				return selector === "[data-role='edited-message']" ? message : button;
			},
			closest(selector) {
				if (selector === "[lp-entity]") return anchor;
				if (selector === "form[data-widget]") return form;
				return null;
			},
		};
		widget.target = { querySelector: () => marker };
		return marker;
	};
	const makeWidget = (
		schema,
		localSubmission,
		localSnapshot = "local-current",
	) => ({
		name: "PageInfo",
		schema,
		submission: Object.fromEntries(schema.map(({ id }) => [id, "baseline"])),
		unsavedState: true,
		form: { renderer: {}, _queued: false },
		revisionBaseline: "baseline",
		revisionSnapshot: () => "local-current",
		revisionCanReset: () => true,
		buildLocalRevision(response) {
			const submission = structuredClone(response.submission);
			const latestIds = new Set(response.schema.map(({ id }) => id));
			for (const { id } of this.schema) {
				if (latestIds.has(id) && Object.hasOwn(localSubmission ?? {}, id)) {
					submission[id] = structuredClone(localSubmission[id]);
				}
			}
			return {
				response: { ...response, snapshot: localSnapshot, submission },
			};
		},
		async applyLocalRevision(response, options) {
			const local = this.buildLocalRevision(response);
			events.push({
				type: "apply-schema",
				options,
				schema: response.schema,
				submission: local.response.submission,
			});
			this.schema = response.schema;
			this.submission = local.response.submission;
		},
		commitRevisionBaseline() {},
		async applyRevision() {},
	});
	const { EditWatcher } = await loadEditOwners({
		loadRevisionPreview(_widget, response) {
			return {
				name: "PageInfo",
				revisionSnapshot: () => response.snapshot,
				destroy() {},
			};
		},
	});
	const watcher = new EditWatcher({
		addFlash() {},
		components: {},
		elt: { addEventListener() {}, querySelectorAll: () => [] },
	});
	const stage = async (widget, response, details) => {
		const marker = makeMarker(widget);
		watcher._reconciler._state(marker).token = {};
		await watcher._reconciler._stageRevision(marker, widget, response, details);
		return { marker, state: watcher._reconciler._state(marker) };
	};

	const schema = await stage(
		makeWidget(
			[
				{ id: "retained", label: "Old label" },
				{ id: "removed", label: "Removed field" },
			],
			{ retained: "Local value", removed: "Local removed value" },
		),
		{
			schema: [
				{ id: "retained", label: "Updated label" },
				{ id: "added", label: "Added field" },
			],
			submission: { retained: "Saved value", added: "New saved value" },
			snapshot: "server-current",
		},
		{
			fingerprint: "schema-fingerprint",
			modified: "2026-07-22T10:00:00+00:00",
		},
	);
	assert.equal(
		events.some(({ type }) => type === "apply-schema"),
		false,
	);
	assert.equal(schema.state.submissionChoice, true);
	assert.equal(schema.state.mode, "review");

	const values = await stage(
		makeWidget([{ id: "same" }], { same: "local" }),
		{
			schema: [{ id: "same" }],
			submission: { same: "server" },
			snapshot: "server-newer",
		},
		{
			fingerprint: "submission-fingerprint",
			modified: "2026-07-22T11:00:00+00:00",
		},
	);
	assert.equal(values.state.submissionChoice, true);
	assert.equal(values.state.mode, "review");
	assert.equal(events.length, 0);

	const equivalent = await stage(
		makeWidget([{ id: "minutes" }], { minutes: "50" }, "canonical-50"),
		{
			schema: [{ id: "minutes" }],
			submission: { minutes: 50 },
			snapshot: "canonical-50",
		},
		{
			fingerprint: "type-equivalent-fingerprint",
			modified: "2026-07-22T11:10:00+00:00",
		},
	);
	assert.equal(equivalent.state.submissionChoice, false);
	assert.notEqual(equivalent.state.mode, "review");
	assert.equal(equivalent.marker.dataset.visible, "false");

	const activeWidget = makeWidget([{ id: "same" }], { same: "active-local" });
	activeWidget.unsavedState = false;
	activeWidget.visible = true;
	activeWidget.component = { active: activeWidget };
	const active = await stage(
		activeWidget,
		{
			schema: [{ id: "same" }],
			submission: { same: "active-server" },
			snapshot: "active-server-newer",
		},
		{
			fingerprint: "active-submission-fingerprint",
			modified: "2026-07-22T11:15:00+00:00",
		},
	);
	assert.equal(active.state.submissionChoice, true);
	assert.equal(active.state.mode, "review");
	assert.equal(active.marker.dataset.visible, "true");
	assert.equal(events.length, 0);

	const matching = await stage(
		makeWidget([{ id: "same" }], { same: "saved" }),
		{
			schema: [{ id: "same" }],
			submission: { same: "saved" },
			snapshot: "local-current",
		},
		{
			fingerprint: "matching-submission-fingerprint",
			modified: "2026-07-22T11:30:00+00:00",
		},
	);
	assert.equal(matching.state.submissionChoice, false);
	assert.notEqual(matching.state.mode, "review");
	assert.equal(matching.marker.dataset.visible, "false");

	const queuedWidget = makeWidget([{ id: "plain" }], { plain: "queued" });
	queuedWidget.form = { _queued: true };
	const queued = await stage(
		queuedWidget,
		{
			schema: [{ id: "plain" }],
			submission: { plain: "saved" },
			snapshot: "server-whole-form",
		},
		{
			fingerprint: "queued-fingerprint",
			modified: "2026-07-22T12:00:00+00:00",
			record: { id: "queued-mutation" },
		},
	);
	assert.equal(queued.state.mode, "whole-review");
	assert.equal(queued.state.submissionChoice, true);
});

/** @matrix edited-entity-notice forms : mixed-submission per-field-selection saved-default */
test("test_edit_watcher_reconciles_independent_field_selections", async (t) => {
	createBrowser(t);
	const applied = [];
	const widget = {
		target: null,
		async applyRevision(response) {
			applied.push({ kind: "server", response });
		},
		async applyLocalRevision(response, options) {
			applied.push({ kind: "selected", response, options });
		},
	};
	const form = { _lp_widget: widget };
	const marker = {
		dataset: { visible: "true" },
		querySelector(selector) {
			return selector === "[data-role='edited-message']"
				? { textContent: "" }
				: { textContent: "", disabled: false };
		},
		closest: (selector) => (selector === "form[data-widget]" ? form : null),
	};
	widget.target = { querySelector: () => marker };
	const { EditWatcher } = await loadEditOwners({
		loadRevisionPreview() {},
	});
	const watcher = new EditWatcher({
		components: {},
		elt: { addEventListener() {}, querySelectorAll: () => [] },
	});
	const state = watcher._reconciler._state(marker);
	state.response = {
		submission: { first: "Saved first", second: "Saved second" },
	};
	state.remoteSnapshot = "saved-snapshot";
	await watcher.resolveRevision(marker, {
		localResponse: {
			submission: { first: "Local first", second: "Local second" },
		},
		selections: { first: "local", second: "server" },
	});
	assert.equal(applied.length, 1);
	assert.equal(applied[0].kind, "selected");
	assert.deepEqual(applied[0].options.selectedSubmission, {
		first: "Local first",
		second: "Saved second",
	});
	assert.equal(applied[0].options.remoteSnapshot, "saved-snapshot");
	assert.equal(applied[0].options.markUnsaved, true);
});

/** @matrix deferred-jobs edited-entity-notice : active-operation form-lock reload */
test("test_edit_watcher_restores_active_autofill_without_form_sync", async (t) => {
	createBrowser(t);
	const locked = [];
	const tracked = [];
	let ensureCalls = 0;
	const widget = {
		_deferredOperation: null,
		target: { dataset: {} },
		lockDeferredOperation(descriptor) {
			this._deferredOperation = descriptor.operation;
			locked.push(descriptor);
			return true;
		},
	};
	const form = { dataset: { widget: "PageInfo" }, _lp_widget: widget };
	const marker = {
		closest: (selector) => (selector === "form[data-widget]" ? form : null),
	};
	const operations = {
		track(operation, options) {
			tracked.push({ operation, options });
		},
	};
	const view = {
		ensureDeferredOperations() {
			ensureCalls += 1;
			return Promise.resolve(operations);
		},
	};
	const { EditWatcher } = await loadEditOwners({ loadRevisionPreview() {} });
	const watcher = new EditWatcher(view);
	await watcher._lockEntity(
		{ markers: new Set([marker]) },
		{ operation: "operation-2", revision: 5, locked: true },
	);
	assert.equal(locked.length, 1);
	assert.equal(locked[0].operation, "operation-2");
	assert.equal(ensureCalls, 1);
	assert.equal(tracked[0].options.node, widget.target);
	await watcher._lockEntity(
		{ markers: new Set([marker]) },
		{
			operation: "migration-1",
			revision: 0,
			scope: "form-change",
			locked: true,
		},
	);
	assert.equal(locked[1].scope, "form-change");
	delete form._lp_widget;
	await watcher._lockEntity(
		{ markers: new Set([marker]) },
		{
			operation: "migration-2",
			revision: 0,
			scope: "form-change",
			locked: true,
		},
	);
	assert.equal(form.dataset.operationScope, "form-change");
	assert.equal(tracked[2].options.node, form);
});

/**
 * @matrix edited-entity-notice : active-state dirty-state owned-deferred-completion
 * @pair deferred-jobs:owned-deferred-completion
 */
test("test_owned_deferred_completion_replaces_clean_active_form", async (t) => {
	createBrowser(t);
	const applications = [];
	const mountedMarkers = [];
	function formCase({ unsaved = false, entityKey = "page-one" } = {}) {
		const anchor = {
			dataset: {
				key: entityKey,
				fingerprint: "old-fingerprint",
				modified: "2026-07-22T10:00:00+00:00",
			},
		};
		const widget = {
			name: "PageInfo",
			_deferredOperation: "operation-one",
			unsavedState: unsaved,
			visible: true,
			form: { _queued: false },
			revisionBaseline: "local",
			revisionCanReset: () => true,
			revisionSnapshot: () => "local",
			buildLocalRevision: (response) => ({
				response: { ...response, snapshot: "local" },
			}),
			commitRevisionBaseline() {},
			async applyRevision(response) {
				applications.push({ widget, response });
			},
		};
		widget.component = {
			active: widget,
			visible: true,
			elt: { parentElement: null },
		};
		const form = { dataset: { widget: "PageInfo" }, _lp_widget: widget };
		const marker = {
			isConnected: true,
			dataset: {
				visible: "false",
				editedRoute: "/pages/page-one/info/replace",
			},
			querySelector(selector) {
				return selector === "[data-role='edited-message']"
					? { textContent: "" }
					: { textContent: "", disabled: false };
			},
			closest(selector) {
				if (selector === "[lp-entity]") return anchor;
				if (selector === "form[data-widget]") return form;
				return null;
			},
		};
		widget.target = { querySelector: () => marker, contains: () => true };
		return { marker, widget };
	}
	const { EditWatcher } = await loadEditOwners({
		loadRevisionPreview(_widget, response) {
			return {
				revisionSnapshot: () => response.snapshot,
				destroy() {},
			};
		},
		request: {
			async get() {
				return { ok: true, snapshot: "saved" };
			},
		},
	});
	const watcher = new EditWatcher({
		addFlash() {},
		components: {},
		elt: { addEventListener() {}, querySelectorAll: () => mountedMarkers },
	});

	const clean = formCase({ entityKey: "task-one" });
	watcher.expectDeferredCompletion("page-one", "operation-one");
	await watcher._reconciler.probe(
		clean.marker,
		"saved-fingerprint",
		"2026-07-22T11:00:00+00:00",
	);
	assert.equal(applications.length, 1);
	assert.equal(clean.marker.dataset.visible, "false");
	assert.equal(watcher._deferredCompletions.has("page-one"), false);

	const staged = formCase({ entityKey: "task-two" });
	mountedMarkers.push(staged.marker);
	await watcher.receiveEntityResult("task-two", {
		status: "changed",
		payload: {
			fingerprint: "saved-fingerprint",
			modified: "2026-07-22T11:00:00+00:00",
		},
	});
	assert.equal(applications.length, 1);
	assert.equal(staged.marker.dataset.visible, "true");
	watcher.expectDeferredCompletion("page-one", "operation-one");
	await watcher.receiveEntityResult("task-two", {
		status: "unchanged",
		revision: "saved-fingerprint",
	});
	assert.equal(applications.length, 2);
	assert.equal(staged.marker.dataset.visible, "false");
	assert.equal(watcher._deferredCompletions.has("page-one"), false);

	const dirty = formCase({ unsaved: true, entityKey: "task-one" });
	watcher.expectDeferredCompletion("page-one", "operation-one");
	await watcher._reconciler.probe(
		dirty.marker,
		"newer-fingerprint",
		"2026-07-22T12:00:00+00:00",
	);
	assert.equal(applications.length, 2);
	assert.equal(dirty.marker.dataset.visible, "true");
	assert.equal(watcher._reconciler._state(dirty.marker).mode, "reset");
});

/**
 * @matrix offline : background-replay dirty-form-preservation
 * @matrix polling : catch-up nonblocking
 */
test("test_visibility_sync_stages_remote_form_edits_without_waiting_for_offline_replay", async (t) => {
	createBrowser(t);
	const events = [];
	const Core = await loadCore();
	const root = document.createElement("main");
	root.dataset.kind = "page";
	root.dataset.key = "page-1";
	root.dataset.fingerprint = "stale-root";
	document.body.append(root);
	const view = new Core(root);
	let resolveReplay;
	const replayReady = new Promise((resolve) => {
		resolveReplay = resolve;
	});
	view.offlineQueue = {
		async replay() {
			events.push("replay");
			await replayReady;
			return 1;
		},
	};
	view.DeferredOperations = { nudge: () => events.push("nudge") };
	view.PollingCoordinator = {
		async catchUp() {
			events.push("catch-up");
		},
	};
	view.EditWatcher = {
		async resume() {
			events.push("watcher");
			root.dataset.fingerprint = "checked-root";
		},
	};
	view.SyncManager = {
		async register() {
			events.push("register");
		},
	};
	view.refresh = async (navigation, options) => {
		events.push(`refresh:${navigation}:${options?.fingerprint}`);
	};
	const outcome = await Promise.race([
		view.sync({ hidden: false }).then(() => "synced"),
		new Promise((resolve) => setTimeout(() => resolve("blocked"), 50)),
	]);
	assert.equal(outcome, "synced");
	assert.equal(view.replayReady, view._offlineReplayTask);
	assert.deepEqual(events.slice(0, 3), ["watcher", "register", "catch-up"]);
	while (!events.includes("replay")) await new Promise(setImmediate);
	resolveReplay();
	await view.replayReady;
	assert.equal(events.at(-1), "refresh:undefined:undefined");
});

/** @matrix collections forms reconnect-refresh : explicit-collection-scope form-exclusion */
test("test_component_refresh_only_loads_collection_widgets", async (t) => {
	createBrowser(t);
	const events = [];
	const { default: ViewComponent } = await import(
		"../../src/script/views/base/component.mjs"
	);
	const clean = {
		route: "/clean",
		refreshScope: "collection",
		async refresh() {
			events.push("refresh:clean");
		},
	};
	const dirty = {
		route: "/dirty",
		unsavedState: true,
		async refresh() {
			events.push("refresh:dirty");
		},
	};
	const queued = {
		route: "/queued",
		form: { _queued: true },
		async refresh() {
			events.push("refresh:queued");
		},
	};
	const staged = {
		route: "/staged",
		target: { querySelector: () => ({}) },
		async refresh() {
			events.push("refresh:staged");
		},
	};
	const component = Object.create(ViewComponent.prototype);
	component.widgets = { clean, dirty, queued, staged };
	component.view = {
		async load(_component, route) {
			events.push(`load:${route}`);
			return { updated: true };
		},
	};
	await component.refreshCollections();
	assert.deepEqual(events, ["load:/clean", "refresh:clean"]);
});

/** @matrix tasks : active-form-preservation dirty-form-preservation stale-widget */
test("test_task_list_refresh_preserves_rows_with_local_form_state", async () => {
	const { PageTaskList } = await loadPageTaskList();
	const removed = {
		remove() {
			throw new Error("Dirty row was discarded");
		},
	};
	const replaced = {
		replaceWith() {
			throw new Error("Queued row was discarded");
		},
	};
	const active = {
		replaceWith() {
			throw new Error("Active form row was replaced");
		},
	};
	const activeReplacement = {
		querySelector: (selector) =>
			selector === "[data-widget='TaskForm']" ? {} : null,
	};
	let incompatibleReplaced = false;
	const incompatible = {
		replaceWith(node) {
			incompatibleReplaced = node;
		},
	};
	const incompatibleReplacement = {
		dataset: { open: "false" },
		querySelector: () => null,
	};
	let incompatibleDestroyed = false;
	let hiddenReplaced = false;
	const hidden = {
		replaceWith() {
			hiddenReplaced = true;
		},
	};
	const activeWidget = { name: "TaskForm", visible: true, unsavedState: false };
	const incompatibleWidget = {
		name: "TaskForm",
		visible: true,
		unsavedState: false,
	};
	const hiddenWidget = { visible: false, unsavedState: false };
	const components = new Map([
		[removed, { widgets: { TaskForm: { unsavedState: true } } }],
		[replaced, { widgets: { TaskForm: { form: { _queued: true } } } }],
		[active, { active: activeWidget, widgets: { TaskForm: activeWidget } }],
		[
			incompatible,
			{
				active: incompatibleWidget,
				open: "TaskForm",
				widgets: { TaskForm: incompatibleWidget },
				destroy() {
					incompatibleDestroyed = true;
				},
			},
		],
		[
			hidden,
			{
				active: hiddenWidget,
				widgets: { TaskForm: hiddenWidget },
				destroy() {},
			},
		],
	]);
	const list = Object.create(PageTaskList.prototype);
	list.component = { active: null };
	list.view = { getComponent: (node) => components.get(node) };
	list.target = { setAttribute() {} };
	list._updated = [];
	list._removed = [removed];
	list._replaced = [
		{ from: replaced, to: {} },
		{ from: active, to: activeReplacement },
		{ from: incompatible, to: incompatibleReplacement },
		{ from: hidden, to: {} },
	];
	list._added = [];
	list._created = [];
	list._setListVisibility = () => {};
	list._moveTaskIfNecessary = () => {};
	Object.defineProperty(list, "activeCount", { value: 1 });
	Object.defineProperty(list, "completedCount", { value: 0 });
	await list.prereconcile();
	list.postreconcile();
	assert.deepEqual(list._removed, []);
	assert.deepEqual(list._replaced, []);
	assert.equal(hiddenReplaced, true);
	assert.equal(incompatibleReplaced, incompatibleReplacement);
	assert.equal(incompatibleDestroyed, true);
	assert.equal(incompatibleReplacement.dataset.open, "false");
});

/** @matrix tasks : create dedupe refresh */
test("test_task_list_reconcile_deduplicates_created_row_already_added_by_refresh", async () => {
	const { PageTaskList } = await loadPageTaskList();
	const rows = [];
	const flashes = [];
	const refreshRow = { dataset: { key: "task-key", completed: "false" } };
	const createdRow = { dataset: { key: "task-key", completed: "false" } };
	const activeTasks = {
		contains: (row) => rows.includes(row),
		prepend: (row) => rows.unshift(row),
	};
	const completedTasks = {
		contains: () => false,
		prepend() {
			throw new Error("Active task entered completed tasks");
		},
	};
	const list = Object.create(PageTaskList.prototype);
	list.component = { active: null };
	list.view = {
		addFlash: (row) => flashes.push(row),
		getComponent() {
			throw new Error("Duplicate created row was initialized");
		},
	};
	list.target = { querySelectorAll: () => rows, setAttribute() {} };
	Object.defineProperties(list, {
		activeTasks: { value: activeTasks },
		completedTasks: { value: completedTasks },
		activeCount: { value: 0 },
		completedCount: { value: 0 },
	});
	list._updated = [];
	list._removed = [];
	list._replaced = [];
	list._added = [refreshRow];
	list._created = [createdRow];
	list._setListVisibility = () => {};
	await list.prereconcile();
	list.postreconcile();
	assert.deepEqual(rows, [refreshRow]);
	assert.deepEqual(flashes, [refreshRow]);
	assert.deepEqual(list._added, []);
	assert.deepEqual(list._created, []);
});

/** @pair tasks:initial-render */
test("test_task_list_initial_reconciliation_publishes_list_visibility", async () => {
	const { PageTaskList } = await loadPageTaskList();
	const attributes = new Set();
	const activeTasks = { dataset: {}, querySelector: () => null };
	const completedTasks = { dataset: {} };
	const completedHeader = { dataset: {} };
	const list = Object.create(PageTaskList.prototype);
	list.target = {
		hasAttribute: (name) => attributes.has(name),
		setAttribute: (name) => attributes.add(name),
	};
	list.component = { active: list };
	list._removed = [];
	list._added = [];
	list._preparedReplacements = [];
	list._preparedCreated = [];
	Object.defineProperties(list, {
		activeTasks: { value: activeTasks },
		completedTasks: { value: completedTasks },
		completedHeader: { value: completedHeader },
		activeCount: { value: 1 },
		completedCount: { value: 0 },
	});
	list.postreconcile();
	assert.equal(attributes.has("loaded"), true);
	assert.equal(activeTasks.dataset.visible, "true");
	assert.equal(completedHeader.dataset.visible, "false");
});

/** @matrix tasks : active-widget complete route-override */
test("test_task_completion_keeps_component_update_route_when_history_is_active", async (t) => {
	createBrowser(t);
	const { PageTaskList } = await loadPageTaskList();
	let submitted;
	const submitter = document.createElement("button");
	submitter.dataset.role = "complete-toggle";
	submitter.addEventListener("submit", (event) => {
		submitted = event;
	});
	const task = {
		active: { name: "TaskHistory", route: "/tasks/task/history" },
		disable() {},
		elt: { dataset: { route: "/tasks/task/update" } },
	};
	const list = Object.create(PageTaskList.prototype);
	list.target = { contains: () => true };
	list.view = { getComponent: () => task };
	list._click({
		target: { closest: () => submitter },
		preventDefault() {},
		stopPropagation() {},
	});
	assert.equal(submitted.type, "submit");
	assert.equal(submitted.detail.route, "/tasks/task/update");
	assert.equal(submitted.detail.role, "complete-toggle");
	assert.equal(submitted.detail.update, true);
});

/** @matrix tasks : completed-only create-close empty-state */
test("test_task_list_empty_marker_requires_closed_create_form_and_no_tasks", async () => {
	const { PageTaskList } = await loadPageTaskList();
	const marker = { dataset: {} };
	const activeTasks = {
		dataset: {},
		querySelector: (selector) =>
			selector === "[data-role='empty']" ? marker : null,
	};
	const completedHeader = { dataset: {} };
	const completedTasks = { dataset: {} };
	const list = Object.create(PageTaskList.prototype);
	let activeCount = 0;
	let completedCount = 0;
	list.target = {
		dataset: { ifEmpty: "CreateTask" },
		hasAttribute: (name) => name === "loaded",
	};
	list._isEmpty = true;
	list._created = [];
	list.component = { active: { name: "CreateTask" }, widgets: {} };
	Object.defineProperties(list, {
		activeTasks: { value: activeTasks },
		completedTasks: { value: completedTasks },
		completedHeader: { value: completedHeader },
		activeCount: { get: () => activeCount },
		completedCount: { get: () => completedCount },
	});
	assert.equal(list.ifEmpty, "CreateTask");
	list.component.widgets.CreateTask = {
		visible: false,
		target: { dataset: { visible: "true" } },
	};
	assert.equal(list.ifEmpty, false);
	list._setListVisibility();
	assert.equal(marker.dataset.visible, "false");
	assert.equal(activeTasks.dataset.visible, "false");
	list.component.active = list;
	list._setListVisibility();
	assert.equal(marker.dataset.visible, "true");
	assert.equal(activeTasks.dataset.visible, "true");
	completedCount = 1;
	list._setListVisibility();
	assert.equal(marker.dataset.visible, "false");
	assert.equal(activeTasks.dataset.visible, "false");
	assert.equal(completedHeader.dataset.visible, "true");
	completedCount = 0;
	activeCount = 1;
	list._setListVisibility();
	assert.equal(marker.dataset.visible, "false");
	assert.equal(activeTasks.dataset.visible, "true");
});

/** @pair tasks:detached-structure */
test("test_task_list_reconciliation_rejects_incomplete_structure", async () => {
	const { PageTaskList } = await loadPageTaskList();
	const list = Object.create(PageTaskList.prototype);
	list._isEmpty = false;
	list._updated = [{ stale: true }];
	list.target = {
		hasAttribute: (name) => name === "loaded",
		querySelector: () => null,
	};
	list.updated({
		html: {
			querySelector(selector) {
				if (selector === "[data-role='active-tasks']")
					return { role: "active" };
				if (selector === "[data-role='completed-header']")
					return { role: "header" };
				return null;
			},
		},
	});
	assert.deepEqual(list._updated, []);
	assert.equal(list._isEmpty, false);
	list._setListVisibility();
});

/** @matrix forms : clear direct-fields input textarea */
test("test_direct_form_controls_clear_inputs_and_textareas", async (t) => {
	createBrowser(t);
	const { BaseElement } = await import(
		"../../src/script/elements/base/baseElement.mjs"
	);
	const root = document.createElement("div");
	const label = document.createElement("label");
	label.dataset.role = "label";
	root.append(label);
	class DirectElement extends BaseElement {
		get edit() {
			return root;
		}
	}
	const direct = new DirectElement(
		{ mode: "edit", readonly: false, showEmptyFields: false },
		{ id: "name", type: "input" },
		null,
	);
	let clearCalls = 0;
	direct.clear = () => {
		clearCalls += 1;
	};
	assert.equal(direct.elt._lp_element, direct);
	const { FormWidget } = await loadFormWidget();
	const widget = new FormWidget({
		readonly: false,
		target: document.createElement("form"),
	});
	widget.form = { renderer: null };
	const role = document.createElement("button");
	role.dataset.role = "clear";
	root.append(role);
	widget._click({
		preventDefault() {},
		stopPropagation() {},
		target: role,
	});
	assert.equal(clearCalls, 1);

	const { TextareaElement } = await import(
		"../../src/script/elements/textarea.mjs"
	);
	const control = document.createElement("textarea");
	control.value = "Project description";
	const textarea = new TextareaElement(
		{ readonly: false },
		{ id: "description", type: "textarea" },
		"Project description",
	);
	const edit = document.createElement("div");
	edit.append(control);
	textarea._edit = edit;
	textarea.clear();
	assert.equal(textarea.submission, null);
	assert.equal(control.value, "");
});
