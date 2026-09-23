import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

async function setupSubmissionManager(t) {
	createBrowser(t, { formData: "native" });
	const capturedErrors = [];
	const captureError = t.mock.fn((...args) => capturedErrors.push(args));
	const request = {
		get: t.mock.fn(),
		post: t.mock.fn(),
		put: t.mock.fn(),
	};
	const withTransition = t.mock.fn(async (callback) => {
		await callback();
		return true;
	});
	const { SubmissionManager } = await esmock.strict(
		"../../src/script/views/base/submission.mjs",
		{
			"../../src/script/shared/errors.mjs": { captureError },
			"../../src/script/shared/request.mjs": { request },
			"../../src/script/shared/transitions.mjs": { withTransition },
		},
	);
	return { capturedErrors, SubmissionManager, request };
}

/**
 * @source src/script/views/base/submission.mjs::SubmissionManager
 * @pair submit:active-widget
 */
test("test_duplicate_autofill_start_keeps_draft_dirty", async (t) => {
	const { SubmissionManager, request } = await setupSubmissionManager(t);
	const messages = [];
	const widget = {
		target: document.body.appendChild(document.createElement("form")),
		revisionSnapshot: () => "draft",
		form: {
			clearUnsavedState() {
				assert.fail("Rejected start cleared the draft");
			},
		},
		lockDeferredOperation() {},
	};
	const component = {
		active: widget,
		showError: (message) => messages.push(message),
	};
	const tracked = [];
	const manager = new SubmissionManager({
		online: true,
		components: {},
		ensureDeferredOperations: async () => ({
			track: (key) => tracked.push(key),
		}),
	});
	request.put.mock.mockImplementation(async () => ({
		ok: false,
		already_running: true,
		deferred: true,
		operation: "existing",
		message: "Already running",
	}));
	await manager.update(component, new FormData(), "/task/update");
	await new Promise(setImmediate);
	assert.deepEqual(messages, ["Already running"]);
	assert.deepEqual(tracked, ["existing"]);
});

/**
 * @source src/script/views/base/submission.mjs::SubmissionManager
 * @pair submit:active-widget
 */
test("test_autofill_ack_preserves_edits_made_during_request", async (t) => {
	const { SubmissionManager, request } = await setupSubmissionManager(t);
	const form = document.body.appendChild(document.createElement("form"));
	let value = "Submitted";
	const widget = {
		target: form,
		initialTarget: form.cloneNode(true),
		revisionSnapshot: () => value,
		captureFormState: () => ({ renderer_submission: { title: value } }),
		form: {
			clearUnsavedState() {
				assert.fail("A newer edit must remain dirty");
			},
		},
		lockDeferredOperation() {},
	};
	const manager = new SubmissionManager({
		online: true,
		components: {},
		ensureDeferredOperations: async () => ({ track() {} }),
	});
	request.put.mock.mockImplementation(async () => {
		value = "Typed while waiting";
		return {
			ok: true,
			deferred: true,
			operation: "job",
			scope: "form-autofill",
			locked: true,
			form_revision: "saved",
			submission: { title: "Submitted" },
		};
	});
	await manager.update({ active: widget }, new FormData(), "/task/update");
	assert.equal(value, "Typed while waiting");
	assert.equal(widget.reviewState.revision, "saved");
	assert.deepEqual(widget._baselineSubmission, { title: "Submitted" });
	assert.equal(widget._revisionBaseline, "Submitted");
});

/**
 * @source src/script/views/base/submission.mjs::SubmissionManager
 * @pair submit:active-widget
 */
test("test_autofill_ack_does_not_decorate_new_active_widget", async (t) => {
	const { SubmissionManager, request } = await setupSubmissionManager(t);
	const form = document.body.appendChild(document.createElement("form"));
	const widget = { target: form, revisionSnapshot: () => "submitted" };
	const replacement = {
		lockDeferredOperation() {
			assert.fail("Decorated another form");
		},
		form: {
			clearUnsavedState() {
				assert.fail("Cleared another draft");
			},
		},
	};
	const component = { active: widget };
	const tracked = [];
	const manager = new SubmissionManager({
		online: true,
		components: {},
		ensureDeferredOperations: async () => ({
			track: (...args) => tracked.push(args),
		}),
	});
	request.put.mock.mockImplementation(async () => {
		component.active = replacement;
		return {
			ok: true,
			deferred: true,
			operation: "job",
			scope: "form-autofill",
			locked: true,
		};
	});
	await manager.update(component, new FormData(), "/task/update");
	assert.equal(tracked[0][0], "job");
	assert.equal(tracked[0][1].node, undefined);
});

function createComponentElement(component) {
	return {
		_lp_component: component,
		closest(selector) {
			return selector === "[lp-component]" ? this : null;
		},
		dataset: {},
		hasAttribute(name) {
			return name === "lp-component";
		},
		id: "tools",
		matches() {
			return false;
		},
		setAttribute() {},
	};
}

function createSubmitEvent({ detail = {}, form, submitter }) {
	return {
		detail,
		preventDefault() {},
		stopPropagation() {},
		submitter,
		target: form,
	};
}

/** @matrix submit : direct-upload-navigation stale-widget */
test("test_submit_abandons_stale_widget_after_async_prepare", async (t) => {
	const { capturedErrors, SubmissionManager } = await setupSubmissionManager(t);
	const events = [];
	const submitter = { dataset: { role: "organize" }, disabled: false };
	const component = {
		active: null,
		get route() {
			return this.active?.route || "/component-route";
		},
		showError(message) {
			events.push(`error:${message}`);
		},
		widgets: {},
	};
	const componentElement = createComponentElement(component);
	const submitForm = {
		isConnected: true,
		closest(selector) {
			return selector === "[lp-component]" ? componentElement : null;
		},
	};
	let formDataReads = 0;
	const widget = {
		form: { syncOfflineState: () => false },
		get formData() {
			formDataReads += 1;
			throw new Error("stale widget formData was read");
		},
		async prepareSubmit() {
			assert.equal(submitter.disabled, true);
			events.push("prepare");
			component.active = null;
			submitForm.isConnected = false;
			widget.target.isConnected = false;
			return true;
		},
		route: "/tools/organize",
		target: {
			isConnected: true,
			hasAttribute: (name) => name === "lp-create",
		},
	};
	component.active = widget;
	const view = {
		components: {},
		getComponent: () => component,
		online: true,
		operationId: () => "operation-1",
	};
	const manager = new SubmissionManager(view);
	const create = t.mock.method(manager, "create", () => {});
	const update = t.mock.method(manager, "update", () => {});
	const event = createSubmitEvent({ form: submitForm, submitter });
	event.preventDefault = () => events.push("prevent");
	event.stopPropagation = () => events.push("stop");

	await manager.submit(event);

	assert.deepEqual(events, ["prevent", "stop", "prepare"]);
	assert.equal(formDataReads, 0);
	assert.equal(create.mock.callCount(), 0);
	assert.equal(update.mock.callCount(), 0);
	assert.equal(submitter.disabled, false);
	assert.equal(capturedErrors.length, 0);
});

/** @matrix submit : direct-upload-error stale-widget */
test("test_submit_does_not_show_upload_error_after_stale_prepare", async (t) => {
	const { capturedErrors, SubmissionManager } = await setupSubmissionManager(t);
	const events = [];
	const submitter = { dataset: { role: "organize" }, disabled: false };
	const component = {
		active: null,
		get route() {
			return this.active?.route || "/component-route";
		},
		showError(message) {
			events.push(`error:${message}`);
		},
		widgets: {},
	};
	const componentElement = createComponentElement(component);
	const submitForm = {
		isConnected: true,
		closest: (selector) =>
			selector === "[lp-component]" ? componentElement : null,
	};
	const widget = {
		form: { syncOfflineState: () => false },
		async prepareSubmit() {
			events.push("prepare");
			component.active = null;
			submitForm.isConnected = false;
			widget.target.isConnected = false;
			throw new Error("upload failed");
		},
		route: "/tools/organize",
		target: {
			isConnected: true,
			hasAttribute: (name) => name === "lp-create",
		},
	};
	component.active = widget;
	const manager = new SubmissionManager({
		components: {},
		getComponent: () => component,
		online: true,
		operationId: () => "operation-1",
	});
	const event = createSubmitEvent({ form: submitForm, submitter });
	event.preventDefault = () => events.push("prevent");
	event.stopPropagation = () => events.push("stop");

	await manager.submit(event);

	assert.deepEqual(events, ["prevent", "stop", "prepare"]);
	assert.equal(submitter.disabled, false);
	assert.equal(capturedErrors.length, 0);
});

/** @pair submit:missing-form-data */
test("test_submit_stops_before_appending_when_form_data_is_missing", async (t) => {
	const { capturedErrors, SubmissionManager } = await setupSubmissionManager(t);
	const componentElement = createComponentElement(null);
	const submitForm = {
		isConnected: true,
		closest: (selector) =>
			selector === "[lp-component]" ? componentElement : null,
	};
	const submitter = { dataset: {}, disabled: false };
	const widget = {
		form: { syncOfflineState: () => false },
		target: { isConnected: true, hasAttribute: () => false },
	};
	const component = {
		active: widget,
		formData: undefined,
		widgets: {},
	};
	componentElement._lp_component = component;
	const manager = new SubmissionManager({
		components: {},
		getComponent: () => component,
		online: true,
	});
	const create = t.mock.method(manager, "create", () => {});
	const update = t.mock.method(manager, "update", () => {});

	await manager.submit(
		createSubmitEvent({
			detail: { update: true },
			form: submitForm,
			submitter,
		}),
	);

	assert.equal(capturedErrors.length, 1);
	assert.equal(capturedErrors[0][0]?.message, "No form data found");
	assert.equal(create.mock.callCount(), 0);
	assert.equal(update.mock.callCount(), 0);
	assert.equal(submitter.disabled, false);
});

/** @matrix submit : active-widget route-override */
test("test_submit_uses_explicit_action_route_over_active_widget_route", async (t) => {
	const { SubmissionManager } = await setupSubmissionManager(t);
	const componentElement = createComponentElement(null);
	const submitForm = {
		isConnected: true,
		closest: (selector) =>
			selector === "[lp-component]" ? componentElement : null,
	};
	const submitter = {
		dataset: { role: "complete-toggle" },
		disabled: false,
	};
	const widget = {
		form: { syncOfflineState: () => false },
		route: "/tasks/task/history",
		target: { isConnected: true, hasAttribute: () => false },
	};
	const component = {
		active: widget,
		formData: new FormData(),
		route: widget.route,
		widgets: {},
	};
	componentElement._lp_component = component;
	const manager = new SubmissionManager({
		components: {},
		getComponent: () => component,
		online: true,
	});
	const update = t.mock.method(manager, "update", () => {});

	await manager.submit(
		createSubmitEvent({
			detail: {
				update: true,
				role: "complete-toggle",
				route: "/tasks/task/update",
			},
			form: submitForm,
			submitter,
		}),
	);

	assert.equal(update.mock.callCount(), 1);
	assert.equal(update.mock.calls[0].arguments[2], "/tasks/task/update");
});

/** @matrix deferred-jobs submit : background deferred-create destination-row */
test("test_deferred_background_create_does_not_decorate_source_form", async (t) => {
	const { SubmissionManager } = await setupSubmissionManager(t);
	const tracked = [];
	const created = [];
	const source = { dataset: {} };
	const component = {
		active: { target: source },
		async created(response) {
			created.push(response.html);
		},
	};
	const manager = new SubmissionManager({
		components: {},
		async ensureDeferredOperations() {
			return {
				track(key, options) {
					tracked.push([key, options.node]);
				},
			};
		},
		async ensureNotifications() {
			return { upsertNotification() {} };
		},
	});

	await manager._deferredCreated(
		{
			background: true,
			deferred: true,
			html: "<table><tr></tr></table>",
			notification: "<li></li>",
			operation: "operation-1",
		},
		component,
	);

	assert.deepEqual(tracked, [["operation-1", null]]);
	assert.deepEqual(created, ["<table><tr></tr></table>"]);
});
