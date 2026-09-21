import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { incompatibleSchema } from "../../src/script/forms/representation.mjs";

const areEqual = (left, right) =>
	JSON.stringify(left) === JSON.stringify(right);

function replaceGlobal(t, name, value) {
	const descriptor = Object.getOwnPropertyDescriptor(globalThis, name);
	Object.defineProperty(globalThis, name, {
		configurable: true,
		writable: true,
		value,
	});
	t.after(() => {
		if (descriptor) Object.defineProperty(globalThis, name, descriptor);
		else delete globalThis[name];
	});
}

async function loadEditOwners({
	loadRevisionPreview,
	request = {},
	withTransition = async (callback) => callback(),
} = {}) {
	const { EditReconciler } = await esmock.strict(
		"../../src/script/forms/revisions/reconciler.mjs",
		{
			"../../src/script/shared/errors.mjs": {
				captureError(error) {
					throw error;
				},
			},
			"../../src/script/shared/request.mjs": { request },
			"../../src/script/shared/transitions.mjs": { withTransition },
			"../../src/script/shared/utilities.mjs": { areEqual },
			"../../src/script/forms/representation.mjs": { incompatibleSchema },
			"../../src/script/forms/revisions/modals.mjs": {
				FormRevisionModal: class {},
				WholeFormRevisionModal: class {},
			},
			"../../src/script/forms/revisions/preview.mjs": {
				loadRevisionPreview,
			},
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

/** @matrix forms unsaved-state : change input non-sync reset success */
test("test_base_form_tracks_unsaved_state_without_sync", async () => {
	const listeners = new Map();
	const target = {
		addEventListener(type, listener) {
			listeners.set(type, listener);
		},
		removeEventListener(type) {
			listeners.delete(type);
		},
		hasAttribute: () => false,
		querySelector: () => null,
	};
	const widget = {
		target,
		submitButton: { disabled: false },
		readonly: false,
		schema: [],
		submission: {},
		messages: { submit: "Save", submitting: "Saving", submitted: "Saved" },
		unsavedState: false,
	};
	const { FormController } = await esmock.strict(
		"../../src/script/forms/controller.mjs",
		{
			"../../src/script/elements/primitives.mjs": {
				primitives: { error: () => ({}) },
			},
			"../../src/script/shared/icons.mjs": { createIcon: () => ({}) },
			"../../src/script/shared/transitions.mjs": {
				withTransition: (callback) => callback(),
			},
			"../../src/script/shared/utilities.mjs": { showBriefly() {} },
			"../../src/script/forms/controls/loader.mjs": {
				initFormControls: async () => [],
			},
			"../../src/script/forms/renderer.mjs": { FormRenderer: class {} },
		},
	);
	const form = new FormController(widget);
	form.setSubmitButton = (state) => {
		form.lastState = state;
	};
	form.hideError = () => {};
	form._initUnsavedState();
	assert.equal(listeners.has("input"), true);
	assert.equal(listeners.has("change"), true);
	listeners.get("input")({
		target: { disabled: false, matches: () => true },
	});
	assert.equal(widget.unsavedState, true);
	assert.equal(form.lastState.icon, "builder.unsaved");
	form.success();
	assert.equal(widget.unsavedState, false);
	listeners.get("change")({
		target: { disabled: false, matches: () => true },
	});
	listeners.get("reset")();
	await Promise.resolve();
	assert.equal(widget.unsavedState, false);
});

/** @matrix edited-entity-notice forms : canonicalization formdata repeated-values revision-only-state */
test("test_form_revision_snapshot_is_canonical_and_memory_only", async () => {
	class FakeFormData {
		constructor(entries = []) {
			this.values = entries;
		}
		entries() {
			return this.values[Symbol.iterator]();
		}
	}
	const target = {
		cloneNode() {
			return this;
		},
		getAttribute: () => null,
		setAttribute() {},
	};
	const { FormWidget } = await esmock.strict(
		"../../src/script/widgets/base/formWidget.mjs",
		{
			"../../src/script/forms/controller.mjs": { FormController: class {} },
			"../../src/script/forms/migrationNotice.mjs": {
				installMigrationNotice() {},
			},
			"../../src/script/forms/representation.mjs": {
				compatibleField: () => true,
			},
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => callback(),
			},
		},
	);
	const widget = new FormWidget({ target });
	Object.defineProperty(widget, "formData", {
		configurable: true,
		get: () =>
			new FakeFormData([
				["category", "second"],
				["name", "Example"],
				["category", "first"],
			]),
	});
	Object.defineProperty(widget, "revisionEntries", {
		get: () => [["__revision-owner", "true"]],
	});
	const first = widget.revisionSnapshot();
	Object.defineProperty(widget, "formData", {
		configurable: true,
		get: () =>
			new FakeFormData([
				["category", "first"],
				["category", "second"],
				["name", "Example"],
			]),
	});
	const second = widget.revisionSnapshot();
	assert.equal(first, second);
	widget.commitRevisionBaseline();
	assert.equal(widget.revisionBaseline, second);
	assert.equal(Boolean(target.dataset?.revisionFingerprint), false);
});

/**
 * @matrix edited-entity-notice : acknowledgement acknowledgement-no-probe active-state batching clean-state comparison entity-ancestor focused-state overlap-follow-up per-form reload-fallback subscription-lifecycle targeted-reset transition visibility
 */
test("test_edit_watcher_compares_and_resets_each_form_independently", async (t) => {
	const events = [];
	const focusedElement = {};
	const anchor = {
		dataset: {
			key: "entity-key",
			fingerprint: "old",
			modified: "2026-07-22T10:00:00+00:00",
		},
	};
	const makeMarker = (route, widget) => {
		const button = { disabled: false, textContent: "Reset form" };
		const message = { textContent: "This form changed elsewhere." };
		const form = { dataset: { widget: widget.name }, _lp_widget: widget };
		const marker = {
			dataset: { visible: "false", editedRoute: route },
			querySelector(selector) {
				return selector === "[data-role='edited-message']" ? message : button;
			},
			closest(selector) {
				if (selector === "[lp-entity]") return anchor;
				if (selector === "form[data-widget]") return form;
				return null;
			},
		};
		button.closest = (selector) =>
			selector === "[lp-edited-marker]" ? marker : null;
		widget.target = {
			querySelector: () => marker,
			contains: (element) =>
				widget.focused === true && element === focusedElement,
		};
		return { marker, button };
	};
	const widget = (name, snapshot) => ({
		name,
		revisionBaseline: name === "FormA" ? "same" : "old",
		revisionSnapshot: () => snapshot,
		revisionCanReset: () => true,
		buildLocalRevision: (response) => ({
			response: { ...response, remote: name === "FormA" ? "local-a" : "old" },
		}),
		commitRevisionBaseline() {
			events.push({ type: `commit-${name.at(-1).toLowerCase()}` });
		},
		async applyRevision(response) {
			events.push({ type: `apply-${name.at(-1).toLowerCase()}`, response });
		},
	});
	const widgetA = widget("FormA", "local-dirty");
	const widgetB = Object.assign(widget("FormB", "old"), { unsavedState: true });
	const widgetC = Object.assign(widget("FormC", "old"), { focused: true });
	widgetA.component = { active: null, visible: false };
	widgetA.visible = false;
	for (const current of [widgetB, widgetC]) {
		current.component = { active: current, visible: true };
		current.visible = true;
	}
	const { marker: markerA } = makeMarker("/form-a", widgetA);
	const { marker: markerB, button: buttonB } = makeMarker("/form-b", widgetB);
	const { marker: markerC } = makeMarker("/form-c", widgetC);
	const markers = [markerA, markerB, markerC];
	const pollSubscriptions = new Map();
	const pollTriggers = [];
	const view = {
		key: "root-key",
		online: true,
		hidden: false,
		elt: {
			dataset: anchor.dataset,
			addEventListener() {},
			removeEventListener() {},
			querySelectorAll: (selector) =>
				selector === "[lp-edited-marker]" ? markers : [],
		},
		addFlash(marker) {
			events.push({ type: "flash", marker });
		},
		PollingCoordinator: {
			subscribe(descriptor, hooks) {
				pollSubscriptions.set(descriptor.id, { descriptor, hooks });
				return () => pollSubscriptions.delete(descriptor.id);
			},
			acknowledge(id, revision) {
				const subscription = pollSubscriptions.get(id);
				if (subscription) subscription.descriptor.revision = revision;
			},
			async trigger(ids) {
				pollTriggers.push(ids);
				for (const id of ids) {
					const subscription = pollSubscriptions.get(id);
					if (!subscription) continue;
					await subscription.hooks.onResult(
						subscription.descriptor.type === "entity"
							? {
									status: "changed",
									revision: "new",
									payload: {
										fingerprint: "new",
										modified: "2026-07-22T11:00:00+00:00",
									},
								}
							: { status: "unchanged", revision: "unlocked" },
					);
				}
				return [];
			},
		},
	};
	replaceGlobal(t, "document", { activeElement: focusedElement });
	replaceGlobal(t, "window", {
		addEventListener() {},
		removeEventListener() {},
		location: {
			reload() {
				events.push({ type: "reload" });
			},
		},
	});
	const request = {
		async get(url, _params, options) {
			events.push({ type: "form-request", url, options });
			return { ok: true, remote: url === "/form-a" ? "same" : "new" };
		},
	};
	const { EditWatcher } = await loadEditOwners({
		request,
		withTransition(callback) {
			events.push({ type: "transition" });
			return callback();
		},
		loadRevisionPreview(current, response) {
			return {
				name: current.name,
				revisionSnapshot: () => response.remote,
				destroy() {},
			};
		},
	});
	const watcher = new EditWatcher(view);
	await watcher.check();
	assert.equal(pollSubscriptions.size, 2);
	assert.equal(pollTriggers[0].length, 2);
	assert.equal(markerA.dataset.visible, "false");
	assert.equal(
		events.some(({ type }) => type === "apply-a"),
		false,
	);
	assert.equal(markerB.dataset.visible, "true");
	assert.equal(markerC.dataset.visible, "true");
	assert.equal(
		events.some(({ type }) => type === "apply-c"),
		false,
	);
	assert.equal(anchor.dataset.fingerprint, "new");
	const probes = events.filter(({ type }) => type === "form-request");
	assert.equal(probes.length, 2);
	assert.equal(
		probes.some(({ url }) => url === "/form-a"),
		false,
	);
	assert.equal(
		probes.some(({ options }) => options.acknowledgeEntities !== false),
		false,
	);
	assert.equal(
		events.some(({ type }) => type === "reload"),
		false,
	);

	widgetA.component.active = widgetA;
	widgetA.component.visible = true;
	widgetA.visible = true;
	await watcher.reconcileSubscriptions();
	assert.equal(
		events.filter(
			({ type, url }) => type === "form-request" && url === "/form-a",
		).length,
		1,
	);
	assert.equal(markerA.dataset.visible, "false");
	assert.equal(
		events.some(({ type }) => type === "apply-a"),
		false,
	);

	const probesBefore = events.filter(
		({ type }) => type === "form-request",
	).length;
	const scheduled = t.mock.method(globalThis, "setTimeout", () => 0);
	watcher.acknowledge({ key: "entity-key", fingerprint: "new" });
	assert.equal(
		scheduled.mock.callCount(),
		0,
		"Unchanged local acknowledgement scheduled revalidation",
	);
	watcher.acknowledge({ key: "entity-key", fingerprint: "acknowledged" });
	assert.equal(
		scheduled.mock.callCount(),
		0,
		"Local acknowledgement scheduled revalidation",
	);
	scheduled.mock.restore();
	assert.equal(anchor.dataset.fingerprint, "acknowledged");
	assert.equal(markerB.dataset.visible, "true");
	assert.equal(
		events.filter(({ type }) => type === "form-request").length,
		probesBefore,
	);
	markers.splice(0);
	watcher.acknowledge({ key: "root-key", fingerprint: "newer" });
	assert.equal(view.elt.dataset.fingerprint, "newer");

	watcher._reconciler._state(markerB).mode = "reset";
	await watcher._click({ target: { closest: () => buttonB } });
	assert.equal(
		events.some(({ type }) => type === "apply-b"),
		true,
	);
	assert.equal(
		events.some(({ type }) => type === "reload"),
		false,
	);
	watcher._reconciler._state(markerB).mode = "reload";
	await watcher._click({ target: { closest: () => buttonB } });
	assert.equal(events.filter(({ type }) => type === "reload").length, 1);
	const triggersBefore = pollTriggers.length;
	markers.push(markerA, markerB, markerC);
	await watcher.check();
	assert.equal(pollTriggers.length, triggersBefore + 1);
});

/** @matrix edited-entity-notice : clean-state coalescing overlap-follow-up */
test("test_edit_watcher_coalesces_overlapping_revision_probes", async (t) => {
	const requests = [];
	const applications = [];
	const anchor = {
		dataset: {
			key: "entity-key",
			fingerprint: "old",
			modified: "2026-07-22T10:00:00+00:00",
		},
	};
	const button = { textContent: "", disabled: false };
	const message = { textContent: "" };
	const widget = {
		name: "FormA",
		visible: false,
		unsavedState: false,
		form: { _queued: false },
		revisionBaseline: "old",
		revisionCanReset: () => true,
		revisionSnapshot: () => "old",
		buildLocalRevision: (response) => ({
			response: { ...response, snapshot: "old" },
		}),
		commitRevisionBaseline() {},
		async applyRevision(response) {
			applications.push(response);
		},
	};
	widget.component = { active: null };
	const form = { dataset: { widget: "FormA" }, _lp_widget: widget };
	const marker = {
		isConnected: true,
		dataset: { visible: "false", editedRoute: "/form-a" },
		querySelector: (selector) =>
			selector === "[data-role='edited-message']" ? message : button,
		closest(selector) {
			if (selector === "[lp-entity]") return anchor;
			if (selector === "form[data-widget]") return form;
			return null;
		},
	};
	widget.target = { querySelector: () => marker, contains: () => false };
	replaceGlobal(t, "document", { activeElement: null });
	replaceGlobal(t, "window", {
		addEventListener() {},
		removeEventListener() {},
	});
	const request = {
		get(url, _params, options) {
			return new Promise((resolve) => requests.push({ url, options, resolve }));
		},
	};
	const { EditWatcher } = await loadEditOwners({
		request,
		loadRevisionPreview(_current, response) {
			return {
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
	const first = watcher._reconciler.probe(
		marker,
		"fingerprint-one",
		"2026-07-22T11:00:00+00:00",
	);
	const duplicate = watcher._reconciler.probe(
		marker,
		"fingerprint-one",
		"2026-07-22T11:00:00+00:00",
	);
	const followup = watcher._reconciler.probe(
		marker,
		"fingerprint-two",
		"2026-07-22T12:00:00+00:00",
	);
	assert.equal(requests.length, 1);
	requests[0].resolve({ ok: true, snapshot: "saved-one" });
	while (requests.length < 2) {
		await new Promise((resolve) => setImmediate(resolve));
	}
	requests[1].resolve({ ok: true, unchanged: true });
	await Promise.all([first, duplicate, followup]);
	assert.equal(requests.length, 2);
	assert.equal(
		requests.some(({ options }) => options.acknowledgeEntities !== false),
		false,
	);
	assert.equal(applications.length, 1);
	assert.equal(applications[0].snapshot, "saved-one");
	assert.equal(
		watcher._markerRevisions.get(marker)?.fingerprint,
		"fingerprint-two",
	);
});

/** @pair edited-entity-notice:unchanged-form */
/** @source src/script/forms/revisions/reconciler.mjs::EditReconciler */
test("test_metadata_only_revision_preserves_clean_and_dirty_forms", async (t) => {
	replaceGlobal(t, "document", { activeElement: null });
	const { EditReconciler } = await loadEditOwners({
		loadRevisionPreview: async (_widget, response) => ({
			revisionSnapshot: () => response.snapshot,
			destroy() {},
		}),
	});
	for (const dirty of [false, true]) {
		for (const schema of [[], [{ id: "title" }]]) {
			let replacements = 0;
			const marker = {
				dataset: { visible: "true" },
				querySelector: () => null,
				closest: () => ({
					dataset: { fingerprint: "old", modified: "before" },
				}),
			};
			const widget = {
				schema,
				submission: { title: "saved" },
				revisionBaseline: "saved",
				revisionCanReset: () => true,
				revisionSnapshot: () => (dirty ? "draft" : "saved"),
				buildLocalRevision: (response) => ({
					response: { ...response, snapshot: "draft" },
				}),
				async applyRevision() {
					replacements += 1;
				},
				unsavedState: dirty,
				visible: true,
				form: schema.length ? { renderer: {} } : {},
				target: { contains: () => true },
			};
			widget.component = { active: widget };
			const reconciler = new EditReconciler({ addFlash() {} });
			await reconciler._stageRevision(
				marker,
				widget,
				{ schema, submission: { title: "saved" }, snapshot: "saved" },
				{ fingerprint: "image-updated", modified: "after" },
			);
			assert.equal(replacements, 0, "Metadata-only update replaced the form");
			assert.equal(marker.dataset.visible, "false");
			assert.equal(widget.unsavedState, dirty);
			assert.equal(widget.revisionSnapshot(), dirty ? "draft" : "saved");
			await reconciler._stageRevision(
				marker,
				widget,
				{ schema, submission: { title: "remote" }, snapshot: "remote" },
				{ fingerprint: "concurrent-edit", modified: "later" },
			);
			assert.equal(replacements, 0, "Concurrent edit replaced an active form");
			assert.equal(marker.dataset.visible, "true");
		}
	}
});
