import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import {
	compatibleField,
	incompatibleSchema,
} from "../../src/script/forms/representation.mjs";
import {
	needsMigration,
	repairConditions,
} from "../../src/script/views/builder/migrations.mjs";
import { createBrowser } from "../utility/js/environment.mjs";

/** @matrix form-migration : modify-panel draft-undo */
test("test_delete_element_commits_panel_and_model_changes_in_one_transition", async (t) => {
	createBrowser(t);
	const commits = [];
	const changes = [];
	let committing = false;
	const withTransition = (commit) => {
		if (committing) commit();
		else commits.push(commit);
	};
	const { default: Modify } = await esmock.strict(
		"../../src/script/views/builder/conditions/modify.mjs",
		{
			"../../src/script/shared/transitions.mjs": { withTransition },
		},
	);
	const change = (name) => {
		assert.equal(
			committing,
			true,
			`${name} changed the UI before the transition`,
		);
		changes.push(name);
	};
	const element = { schema: { id: "notes", type: "textarea" } };
	const builder = {
		elt: document.createElement("div"),
		selectedElement: element,
		savedField: () => element.schema,
		conversionCatalog: { types: [] },
		conditions: {
			close() {
				withTransition(() => change("close-options"));
			},
		},
		removeElement() {
			change("remove-element");
			this.selectedElement = null;
		},
		settings: {
			deselectItem() {
				change("deselect-settings");
			},
		},
		formSettings: {
			set visible(value) {
				assert.equal(value, true);
				change("show-form-settings");
			},
		},
	};
	const header = document.createElement("header");
	const help = document.createElement("button");
	help.dataset.role = "help";
	header.append(help);
	const target = document.createElement("section");
	const modify = Object.assign(Object.create(Modify.prototype), {
		builder,
		element,
		header,
		target,
		destroy() {},
		setTitle() {},
	});
	modify.init();
	const remove = [...target.querySelectorAll("button")].find(
		(button) => button.textContent === "Delete",
	);
	remove.click();
	assert.deepEqual(changes, [], "All visible changes must wait for one commit");
	assert.equal(commits.length, 1);
	committing = true;
	commits.shift()();
	assert.deepEqual(changes, [
		"close-options",
		"remove-element",
		"deselect-settings",
		"show-form-settings",
	]);
});

/** @matrix form-migration : progress recovery */
test("test_builder_resumes_migration_polling_and_clears_completed_status", async (t) => {
	createBrowser(t);
	const { Header } = await import(
		"../../src/script/views/builder/panels/header.mjs"
	);
	let activeClock = null;
	for (const target of [globalThis, window]) {
		t.mock.method(target, "setTimeout", (callback, delay) =>
			activeClock.setTimeout(callback, delay),
		);
		t.mock.method(target, "clearTimeout", (id) => activeClock.clearTimeout(id));
	}
	t.mock.method(Date, "now", () => activeClock.now);

	for (const suspension of [
		"focused",
		"visible-blur",
		"focus",
		"offline",
		"background-load",
	]) {
		document.body.replaceChildren();
		let timerId = 0;
		activeClock = {
			now: 1000,
			timers: new Map(),
			setTimeout(callback, delay) {
				const id = ++timerId;
				this.timers.set(id, { callback, at: this.now + delay });
				return id;
			},
			clearTimeout(id) {
				this.timers.delete(id);
			},
		};
		let running = { operation: "job-1", status: "running" };
		const saved = {
			schema: [{ id: "quantity", type: "input", input: "text" }],
		};
		const finished = { ok: true, draft: saved, baseline: "generation-2" };
		let response = { ok: true, pending_change: running };
		let heldRefresh = null;
		let polls = 0;
		let refreshes = 0;
		let restored = 0;
		const connectivity = { online: true };
		const request = {
			async post(url, body) {
				assert.equal(url, "/l/poll", suspension);
				assert.equal(body.subscriptions.length, 1, suspension);
				assert.equal(body.subscriptions[0].key, running.operation, suspension);
				polls += 1;
				const revision = response.pending_change ? 1 : 2;
				return {
					ok: true,
					version: 1,
					results: body.subscriptions.map((item) => ({
						id: item.id,
						type: "operation",
						revision,
						poll_after_ms: 4000,
						status: item.revision === revision ? "unchanged" : "changed",
						...(item.revision === revision
							? {}
							: {
									payload: {
										key: item.key,
										revision,
										terminal: !response.pending_change,
									},
								}),
					})),
				};
			},
			async get(url) {
				assert.equal(url, "/forms/form-1/change", suspension);
				refreshes += 1;
				return heldRefresh ? await heldRefresh : response;
			},
		};
		const { PollingCoordinator } = await esmock.strict(
			"../../src/script/shared/polling.mjs",
			{
				"../../src/script/shared/endpoints.mjs": {
					ENDPOINTS: { poll: "/l/poll" },
				},
				"../../src/script/shared/errors.mjs": {
					captureError(error) {
						throw error;
					},
				},
				"../../src/script/shared/request.mjs": { request },
			},
		);
		const { FormChangeStatus } = await esmock.strict(
			"../../src/script/views/builder/changeStatus.mjs",
			{
				"../../src/script/shared/polling.mjs": { PollingCoordinator },
				"../../src/script/shared/request.mjs": { request },
			},
		);
		const { default: FormBuilder } = await esmock.strict(
			"../../src/script/views/builder/builder.mjs",
			{
				"../../src/script/shared/index.mjs": {
					captureError(error) {
						throw error;
					},
					connectivity,
					DeleteModal: class {},
					generateElementId: () => "generated",
					HelpModal: class {},
					OfflineModal: class {},
					request,
				},
				"../../src/script/views/builder/changeStatus.mjs": {
					FormChangeStatus,
				},
			},
		);
		const builder = Object.assign(Object.create(FormBuilder.prototype), {
			elt: document.createElement("div"),
			key: "form-1",
			online: true,
			hidden: suspension === "background-load",
			blurred: false,
			blurredAt: null,
			_independentDocuments: new Set(),
			draft: {
				dirty: false,
				saved,
				acknowledge(submitted, result) {
					assert.equal(submitted, saved, suspension);
					assert.equal(result, finished, suspension);
					this.baseline = result.baseline;
				},
			},
			async restoreDraft() {
				restored += 1;
				this.header.saved();
			},
		});
		for (const name of [
			"settings",
			"conditions",
			"components",
			"model",
			"formSettings",
		]) {
			builder[name] = { panel: document.createElement("div") };
		}
		const saveButton = document.createElement("button");
		const notification = document.createElement("div");
		document.body.append(notification);
		builder.header = Object.assign(Object.create(Header.prototype), {
			builder,
			saveButton,
			notification,
			_destroyed: false,
			_messageTimer: null,
			_savePromise: null,
		});
		builder.setPendingChange(running);
		builder.changeStatus.node.checkVisibility = () => true;
		const polling = builder.changeStatus.polling;
		const nextTimer = async () => {
			assert.ok(
				activeClock.timers.size,
				`Pending migration must schedule its next status check: ${suspension}`,
			);
			const [id, timer] = [...activeClock.timers].sort(
				(left, right) => left[1].at - right[1].at,
			)[0];
			activeClock.timers.delete(id);
			activeClock.now = timer.at;
			timer.callback();
			await polling.activePoll;
		};
		if (suspension !== "background-load") {
			await nextTimer();
			assert.equal(refreshes, 1, suspension);
			assert.equal(builder.pendingChange, running, suspension);
			assert.equal(
				activeClock.timers.size,
				1,
				`Running migration keeps polling on a timer: ${suspension}`,
			);
			if (["focused", "visible-blur"].includes(suspension)) {
				if (suspension === "visible-blur") {
					await builder.sync({
						hidden: true,
						blurred: true,
						blurredAt: activeClock.now,
					});
				}
				await nextTimer();
				assert.equal(
					refreshes,
					2,
					`Unchanged operation status keeps the visible builder polling: ${suspension}`,
				);
				response = finished;
				await nextTimer();
			} else {
				if (suspension === "offline") connectivity.online = false;
				await builder.sync({ hidden: suspension === "focus" });
				if (activeClock.timers.size) await nextTimer();
				assert.equal(
					refreshes,
					1,
					`Inactive builder must not refresh its schema: ${suspension}`,
				);
			}
		}
		if (!["focused", "visible-blur"].includes(suspension)) {
			assert.equal(activeClock.timers.size, 0, suspension);
			assert.equal(
				saveButton.getAttribute("aria-disabled"),
				"true",
				suspension,
			);
			response = finished;
			connectivity.online = true;
			await builder.sync({ hidden: false });
		}
		assert.equal(
			builder.pendingChange,
			null,
			`Completed migration stayed locked on return: ${suspension}`,
		);
		assert.equal(
			refreshes,
			["focused", "visible-blur"].includes(suspension)
				? 3
				: suspension === "background-load"
					? 1
					: 2,
			suspension,
		);
		assert.equal(builder.draft.baseline, "generation-2", suspension);
		assert.equal(restored, 1, suspension);
		assert.equal(notification.textContent, "Form update finished.", suspension);
		assert.equal(polling.subscriptions.size, 0, suspension);
		for (const name of [
			"settings",
			"conditions",
			"components",
			"model",
			"formSettings",
		]) {
			assert.equal(builder[name].panel.inert, false, `${suspension}:${name}`);
		}
		builder.draft.dirty = true;
		builder.header.unsaved();
		assert.equal(saveButton.getAttribute("aria-disabled"), "false", suspension);
		await nextTimer();
		assert.equal(notification.dataset.visible, "false", suspension);
		assert.equal(
			activeClock.timers.size,
			0,
			`Completed migration stopped polling: ${suspension}`,
		);
		await builder.sync({ hidden: false });

		running = { operation: "job-2", status: "queued" };
		response = { ok: true, pending_change: running };
		builder.setPendingChange(running);
		builder.changeStatus.node.checkVisibility = () => true;
		assert.equal(saveButton.getAttribute("aria-disabled"), "true", suspension);
		let releaseRefresh;
		heldRefresh = new Promise((resolve) => {
			releaseRefresh = resolve;
		});
		const previousRefreshes = refreshes;
		const oldCycle = nextTimer();
		for (
			let turns = 0;
			refreshes === previousRefreshes && turns < 20;
			turns += 1
		) {
			await Promise.resolve();
		}
		assert.equal(refreshes, previousRefreshes + 1, suspension);
		const staleResponse = response;
		await builder.sync({ hidden: true });
		response = finished;
		const returning = builder.sync({ hidden: false });
		heldRefresh = null;
		releaseRefresh(staleResponse);
		await returning;
		await oldCycle;
		assert.equal(
			builder.pendingChange,
			null,
			`Second migration stayed locked on return: ${suspension}`,
		);
		assert.equal(restored, 2, suspension);
		assert.equal(polling.subscriptions.size, 0, suspension);
		assert.ok(polls > 0, suspension);
		builder.changeStatus.destroy();
	}
});

/** @matrix form-migration : saved-job progress reload recovery */
test("test_migration_status_uses_notification_and_keeps_save_disabled", async (t) => {
	createBrowser(t);
	const { Header } = await import(
		"../../src/script/views/builder/panels/header.mjs"
	);
	class PollingCoordinator {
		init() {
			return this;
		}

		subscribe() {
			return () => {};
		}

		destroy() {}
	}
	const { FormChangeStatus } = await esmock.strict(
		"../../src/script/views/builder/changeStatus.mjs",
		{
			"../../src/script/shared/polling.mjs": { PollingCoordinator },
			"../../src/script/shared/request.mjs": { request: {} },
		},
	);
	const builder = { draft: { dirty: true }, key: "form-1" };
	for (const name of [
		"settings",
		"conditions",
		"components",
		"model",
		"formSettings",
	]) {
		builder[name] = { panel: document.createElement("div") };
	}
	const saveButton = document.createElement("button");
	const notification = document.createElement("div");
	document.body.append(notification);
	builder.header = Object.assign(Object.create(Header.prototype), {
		builder,
		saveButton,
		notification,
		_destroyed: false,
		_messageTimer: null,
		_savePromise: null,
	});
	const header = builder.header;
	const status = new FormChangeStatus(builder);
	const running = {
		operation: "job-1",
		status: "running",
		can_cancel: true,
	};
	status.show(running);
	assert.equal(header.notification.children[0], status.node);
	assert.equal(
		header.notification.textContent,
		"Schema migration in progress, Save temporarily disabled",
	);
	assert.equal(header.notification.dataset.visible, "true");
	assert.equal(header.saveButton.getAttribute("aria-disabled"), "true");
	header.saved();
	header.unsaved();
	assert.equal(header.notification.children[0], status.node);
	assert.equal(header.notification.dataset.visible, "true");
	assert.equal(header.saveButton.getAttribute("aria-disabled"), "true");
	assert.equal(await header.saveForm(), false);
	status.show({ ...running, status: "failed", error: "Try again" });
	assert.equal(status.node.children.length, 3);
	assert.equal(status.node.children[2].textContent, "Retry");
	assert.match(status.node.textContent, /keeps answers already updated/);
	assert.match(
		status.node.textContent,
		/Save will be available when the update finishes/,
	);
	assert.ok(!header.notification.textContent.includes("Cancel"));
	status.show({
		...running,
		status: "failed",
		error: "Quantity must be a number.",
		failed_entity: {
			name: "Checklist",
			kind: "Task",
			url: "/tasks/checklist",
		},
	});
	const link = status.node.children[1].children[0];
	assert.equal(link.textContent, "Checklist");
	assert.equal(link.getAttribute("href"), "/tasks/checklist");
	assert.match(status.node.textContent, /Affected Task/);
	status.show({ ...running, status: "failed" });
	assert.ok(!status.node.textContent.includes("Checklist"));
	status.show(null);
	header.unsaved();
	assert.equal(header.notification.dataset.visible, "false");
	assert.equal(header.saveButton.getAttribute("aria-disabled"), "false");
	status.destroy();
});

/** @matrix form-migration : schema-only stable-identity conditions */
test("test_schema_changes_and_condition_repairs_are_local", () => {
	const before = [{ id: "a", type: "input", input: "text", title: "Old" }];
	assert.equal(needsMigration(before, [{ ...before[0], title: "New" }]), false);
	assert.equal(
		needsMigration(before, [{ ...before[0], input: "number" }]),
		true,
	);
	assert.equal(needsMigration(before, []), true);
	assert.equal(needsMigration([], before), false);
	const schema = [
		{
			id: "choice",
			type: "select",
			options: [{ value: "yes", label: "Yes" }],
		},
		{
			id: "note",
			type: "textarea",
			visibility: [
				{ id: "choice", type: "radio", value: "yes" },
				{ id: "gone", value: "missing" },
			],
		},
	];
	assert.equal(repairConditions(schema), 1);
	assert.deepEqual(schema[1].visibility, [
		{ id: "choice", type: "select", value: "yes" },
	]);
});

/** @matrix form-migration : stale-input representation-aware */
test("test_incompatible_local_values_require_review", () => {
	const text = { id: "quantity", type: "input", input: "text" };
	assert.equal(compatibleField(text, { ...text, title: "New label" }), true);
	assert.equal(compatibleField(text, { ...text, input: "number" }), false);
	assert.equal(incompatibleSchema([text], []), true);
	assert.equal(
		incompatibleSchema([text], [text, { id: "extra", type: "textarea" }]),
		false,
	);
	const table = { id: "items", type: "table", columns: [text] };
	assert.equal(
		compatibleField(table, {
			...table,
			columns: [{ ...text, input: "number" }],
		}),
		false,
	);
});

/** @matrix form-migration : stale-input queued-conflict explicit-review */
test("test_projected_matching_values_do_not_discard_incompatible_drafts", async (t) => {
	createBrowser(t);
	const { FormWidget } = await import(
		"../../src/script/widgets/base/formWidget.mjs"
	);
	const { EditReconciler } = await esmock.strict(
		"../../src/script/forms/revisions/reconciler.mjs",
		{
			"../../src/script/forms/revisions/preview.mjs": {
				loadRevisionPreview: async (_widget, response) => ({
					revisionSnapshot: () => JSON.stringify(response.submission),
					destroy() {},
				}),
			},
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (commit) => commit(),
			},
		},
	);
	for (const change of ["convert", "remove"]) {
		for (const mode of ["dirty", "queued", "clean"]) {
			const scenario = `${change}-${mode}`;
			const before = [
				{ id: "quantity", type: "input", input: "text" },
				{ id: "note", type: "textarea" },
			];
			const after =
				change === "remove"
					? [before[1]]
					: [{ ...before[0], input: "number" }, before[1]];
			const saved =
				change === "remove" ? { note: "Keep" } : { quantity: 9, note: "Keep" };
			const local = {
				quantity: mode === "clean" ? "009" : "unfinished",
				note: "Keep",
			};
			let applied = 0;
			const cancelled = [];
			const button = { textContent: "" };
			const message = { textContent: "" };
			const widget = new FormWidget({
				name: "TaskForm",
				schema: before,
				submission: { quantity: "009", note: "Keep" },
				target: { cloneNode: () => ({}) },
			});
			const marker = {
				dataset: { visible: "false" },
				querySelector: (selector) =>
					selector.includes("edited-message") ? message : button,
				closest: (selector) =>
					selector === "form[data-widget]"
						? { _lp_widget: widget }
						: { dataset: { fingerprint: "before", modified: "old" } },
			};
			widget.target.querySelector = () => marker;
			widget.form = { renderer: {}, _queued: mode === "queued" };
			widget.unsavedState = mode === "dirty";
			widget.visible = true;
			widget.component = { active: widget };
			widget._revisionBaseline = "baseline";
			widget.revisionSnapshot = () => JSON.stringify(local);
			widget.revisionCanReset = () => true;
			widget.captureFormState = () => ({ renderer_submission: local });
			widget._applyQueuedFields = () => {};
			widget.prepareRevision = async (result) => () => {
				applied += 1;
				widget.schema = result.schema;
			};
			const reconciler = new EditReconciler({
				offlineQueue: {
					cancel: async (id) => cancelled.push(id),
				},
			});
			const result = { ok: true, schema: after, submission: saved };
			assert.deepEqual(
				widget.buildLocalRevision(result).response.submission,
				saved,
				scenario,
			);
			const record = mode === "queued" ? { id: "queued-answer" } : null;
			await reconciler._stageRevision(marker, widget, result, {
				fingerprint: "after",
				modified: "new",
				record,
			});
			if (mode === "clean") {
				assert.equal(applied, 1, scenario);
				assert.equal(marker.dataset.visible, "false", scenario);
				continue;
			}
			assert.equal(
				applied,
				0,
				`An incompatible draft was discarded before review: ${scenario}`,
			);
			assert.deepEqual(
				cancelled,
				[],
				`A queued value was cancelled before review: ${scenario}`,
			);
			assert.equal(marker.dataset.visible, "true", scenario);
			assert.equal(button.textContent, "Review values", scenario);
			assert.equal(
				widget.captureFormState().renderer_submission.quantity,
				"unfinished",
				scenario,
			);
			assert.equal(widget.schema, before, scenario);
			await reconciler.resolveRevision(marker, "server");
			assert.equal(applied, 1, scenario);
			assert.deepEqual(
				cancelled,
				mode === "queued" ? [record.id] : [],
				scenario,
			);
			assert.equal(marker.dataset.visible, "false", scenario);
		}
	}
});
