import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser, mockFetch } from "../utility/js/environment.mjs";

const formHTML = `<form data-widget="TaskForm"><input name="title" value="My draft"><button data-role="autofill-submit">Autofill</button><button data-role="save">Update</button><div lp-edited-marker data-edited-route="/tasks/task/replace"><span data-role="edited-message"></span><span data-role="form-operation"></span><button type="button" data-role="edited-reset">Review</button><button type="button" data-role="autofill-cancel">Cancel</button><button type="button" data-role="autofill-retry">Retry</button></div></form>`;

function widgetFixture() {
	const target = document.querySelector("form");
	const widget = {
		target,
		unsavedState: true,
		component: {},
		view: {},
		reviewState: { revision: "launch" },
	};
	target._lp_widget = widget;
	target.dataset.formState = JSON.stringify(widget.reviewState);
	return widget;
}

/**
 * @source src/script/forms/reviewBar.mjs::renderReviewBar
 * @pair forms:submission-choice
 */
test("test_review_bar_keeps_answers_editable_and_prioritizes_new_operation", async (t) => {
	createBrowser(t, { html: formHTML });
	const { renderReviewBar } = await import(
		"../../src/script/forms/reviewBar.mjs"
	);
	const widget = widgetFixture();
	widget.reviewState.reviews = [{ operation: "prior" }];
	widget.reviewState.migration = { schema: [] };
	renderReviewBar(widget, {
		key: "job",
		type: "autofill",
		status: "running",
		phase_label: "Generating",
		elapsed_seconds: 12,
		terminal: false,
		can_cancel: true,
	});
	assert.equal(widget.target.querySelector("input").disabled, false);
	assert.equal(widget.target.querySelector("input").value, "My draft");
	assert.equal(widget.target.querySelector("[data-role=save]").disabled, false);
	assert.equal(
		widget.target.querySelector("[data-role=autofill-submit]").disabled,
		true,
	);
	assert.equal(widget.unsavedState, true);
	assert.equal(
		widget.target.querySelector("[data-role=edited-message]").textContent,
		"This form's fields have changed.",
	);
	assert.match(
		widget.target.querySelector("[data-role=form-operation]").textContent,
		/running.*12s/,
	);
	assert.equal(
		widget.target.querySelector("[data-role=autofill-cancel]").hidden,
		false,
	);
	renderReviewBar(widget, {
		key: "job",
		type: "autofill",
		status: "cancelled",
		terminal: true,
	});
	assert.equal(
		widget.target.querySelector("[data-role=autofill-submit]").disabled,
		false,
	);
	assert.equal(
		widget.target.querySelector("[data-role=autofill-cancel]").hidden,
		true,
	);
	assert.equal(
		widget.target.querySelector("[data-role=edited-reset]").hidden,
		false,
	);
});

/**
 * @source src/script/forms/reviewBar.mjs::renderReviewBar
 * @pair forms:autofill-completion-review
 */
test("test_new_autofill_hides_prior_completion_until_its_own_review_arrives", async (t) => {
	createBrowser(t, { html: formHTML });
	const { renderReviewBar } = await import(
		"../../src/script/forms/reviewBar.mjs"
	);
	const widget = widgetFixture();
	const marker = widget.target.querySelector("[lp-edited-marker]");
	const message = marker.querySelector("[data-role='edited-message']");
	const progress = marker.querySelector("[data-role='form-operation']");
	const review = marker.querySelector("[data-role='edited-reset']");
	widget.reviewState.reviews = [{ operation: "old-job" }];
	renderReviewBar(widget, {
		key: "new-job",
		type: "autofill",
		status: "running",
		phase_label: "Preparing inputs",
		elapsed_seconds: 3,
		terminal: false,
		can_cancel: true,
	});
	assert.equal(message.hidden, true);
	assert.equal(review.hidden, true);
	assert.match(progress.textContent, /running.*Preparing inputs/);
	renderReviewBar(widget, {
		key: "new-job",
		type: "autofill",
		status: "succeeded",
		terminal: true,
	});
	assert.equal(message.hidden, true);
	assert.equal(review.hidden, true);
	assert.match(progress.textContent, /Loading values to review/);
	widget.reviewState.reviews = [{ operation: "new-job" }];
	renderReviewBar(widget);
	assert.equal(message.textContent, "Autofill is complete.");
	assert.equal(review.hidden, false);
	assert.equal(progress.hidden, true);
});

/**
 * @source src/script/forms/reviewBar.mjs::renderReviewBar
 * @pair forms:autofill-completion-review
 */
test("test_review_bar_keeps_success_visible_until_review_arrives", async (t) => {
	createBrowser(t, { html: formHTML });
	const { renderReviewBar } = await import(
		"../../src/script/forms/reviewBar.mjs"
	);
	const widget = widgetFixture();
	renderReviewBar(widget, {
		key: "job",
		type: "autofill",
		status: "succeeded",
		terminal: true,
	});
	const marker = widget.target.querySelector("[lp-edited-marker]");
	assert.equal(marker.dataset.visible, "true");
	assert.match(
		marker.querySelector("[data-role='form-operation']").textContent,
		/Loading values to review/,
	);
	marker._lp_edited_state = { response: {} };
	renderReviewBar(widget);
	assert.equal(
		marker.querySelector("[data-role='edited-message']").textContent,
		"Another user has edited this form.",
	);
	assert.equal(
		marker.querySelector("[data-role='form-operation']").hidden,
		true,
	);
	assert.equal(marker.dataset.visible, "true");
	widget.reviewState.reviews = [{ operation: "job" }];
	renderReviewBar(widget);
	assert.match(
		marker.querySelector("[data-role='edited-message']").textContent,
		/Autofill is complete/,
	);
	assert.equal(
		marker.querySelector("[data-role='form-operation']").hidden,
		true,
	);
	widget._reviewedOperations = new Set(["job"]);
	widget.reviewState.reviews = [];
	renderReviewBar(widget);
	assert.equal(
		marker.querySelector("[data-role='edited-message']").textContent,
		"Another user has edited this form.",
	);
	marker._lp_edited_state.response = null;
	renderReviewBar(widget);
	assert.equal(marker.dataset.visible, "false");
	assert.equal(
		marker.querySelector("[data-role='form-operation']").hidden,
		true,
	);
});

/**
 * @source src/script/forms/reviewBar.mjs::renderReviewBar
 * @pair forms:autofill-completion-review
 */
test("test_remote_edit_notice_keeps_running_autofill_visible", async (t) => {
	createBrowser(t, { html: formHTML });
	const { renderReviewBar } = await import(
		"../../src/script/forms/reviewBar.mjs"
	);
	const widget = widgetFixture();
	const marker = widget.target.querySelector("[lp-edited-marker]");
	const message = marker.querySelector("[data-role='edited-message']");
	const progress = marker.querySelector("[data-role='form-operation']");
	const review = marker.querySelector("[data-role='edited-reset']");
	const cancel = marker.querySelector("[data-role='autofill-cancel']");
	widget.reviewState.reviews = [{ operation: "old-job" }];
	marker._lp_edited_state = { response: { conflict: true } };
	renderReviewBar(widget, {
		key: "new-job",
		type: "autofill",
		status: "running",
		phase_label: "Preparing inputs",
		elapsed_seconds: 3,
		terminal: false,
		can_cancel: true,
	});
	assert.equal(message.textContent, "Another user has edited this form.");
	assert.equal(message.hidden, false);
	assert.equal(progress.hidden, false);
	assert.match(progress.textContent, /Autofill is running.*Preparing inputs/);
	assert.equal(review.hidden, false);
	assert.equal(cancel.hidden, false);
	marker._lp_edited_state.response = null;
	renderReviewBar(widget);
	assert.equal(message.hidden, true);
	assert.equal(progress.hidden, false);
	assert.match(progress.textContent, /Autofill is running.*Preparing inputs/);
	assert.equal(review.hidden, true);
});

/**
 * @pair ai:autofill
 */
test("test_review_bar_cancel_uses_operation_identity", async (t) => {
	createBrowser(t, { html: formHTML });
	let sent;
	const finished = new Promise((resolve) =>
		mockFetch(t, ({ url, init }) => {
			sent = { url: url.pathname, id: init.body.get("operation-id") };
			resolve();
			return Response.json({
				status: {
					key: "job",
					type: "autofill",
					status: "cancelled",
					terminal: true,
				},
			});
		}),
	);
	const { installReviewBar } = await import(
		"../../src/script/forms/reviewBar.mjs"
	);
	const widget = widgetFixture();
	widget.target.dataset.formState = JSON.stringify({
		revision: "launch",
		operation: {
			key: "job",
			operation_id: "request-1",
			type: "autofill",
			status: "running",
			terminal: false,
			can_cancel: true,
		},
	});
	installReviewBar(widget);
	const cancel = widget.target.querySelector("[data-role=autofill-cancel]");
	cancel.click();
	assert.equal(cancel.disabled, true);
	assert.equal(cancel.textContent, "Cancelling…");
	assert.equal(
		widget.target.querySelector("[data-role=form-operation]").textContent,
		"Cancellation requested…",
	);
	await finished;
	await new Promise(setImmediate);
	assert.deepEqual(sent, {
		url: "/tools/operations/job/cancel",
		id: "request-1",
	});
	assert.equal(widget.target.querySelector("input").value, "My draft");
	assert.equal(widget.reviewState.operation.status, "cancelled");
	widget._migrationNotice.destroy();
});

/**
 * @source src/script/forms/reviewBar.mjs::installReviewBar
 * @pair ai:autofill
 */
test("test_retry_button_shows_pending_feedback_until_submission_settles", async (t) => {
	createBrowser(t, { html: formHTML });
	const { installReviewBar } = await import(
		"../../src/script/forms/reviewBar.mjs"
	);
	const widget = widgetFixture();
	widget.target.dataset.formState = JSON.stringify({
		revision: "launch",
		retry_operation: "old-job",
		operation: {
			key: "old-job",
			type: "autofill",
			status: "cancelled",
			terminal: true,
		},
	});
	let settle;
	let submissions = 0;
	widget.target.addEventListener("submit", (event) => {
		event.preventDefault();
		submissions += 1;
		settle = event.detail.onSettled;
	});
	installReviewBar(widget);
	const retry = widget.target.querySelector("[data-role=autofill-retry]");
	retry.click();
	assert.equal(retry.disabled, true);
	assert.equal(retry.textContent, "Retrying…");
	assert.equal(widget._autofillRetry, "old-job");
	retry.click();
	assert.equal(submissions, 1, "Pending feedback also prevents a second start");
	settle();
	assert.equal(retry.disabled, false);
	assert.equal(retry.textContent, "Retry autofill");
	assert.equal(widget.target.querySelector("input").value, "My draft");
	widget._migrationNotice.destroy();
});

/**
 * @source src/script/forms/revisions/reconciler.mjs::EditReconciler
 * @pair forms:autofill-completion-review
 */
test("test_review_button_shows_feedback_while_refreshing_latest_values", async (t) => {
	createBrowser(t, { html: formHTML });
	let finishGet;
	let gets = 0;
	let opened = 0;
	const latest = new Promise((resolve) => {
		finishGet = resolve;
	});
	const { EditReconciler } = await esmock.strict(
		"../../src/script/forms/revisions/reconciler.mjs",
		{
			"../../src/script/shared/request.mjs": {
				request: {
					get: () => {
						gets += 1;
						return latest;
					},
				},
			},
			"../../src/script/forms/revisions/modals.mjs": {
				FormRevisionModal: class {
					async init() {
						opened += 1;
						return true;
					}
				},
				WholeFormRevisionModal: class {},
			},
		},
	);
	const widget = widgetFixture();
	const marker = widget.target.querySelector("[lp-edited-marker]");
	const button = marker.querySelector("[data-role='edited-reset']");
	button.textContent = "Review values";
	const reconciler = new EditReconciler({});
	Object.assign(reconciler._state(marker), {
		mode: "review",
		response: { form_state: { reviews: [{ operation: "job" }] } },
	});
	const opening = reconciler.handleClick({ target: button });
	assert.equal(button.disabled, true);
	assert.equal(button.textContent, "Opening review…");
	assert.equal(button.getAttribute("aria-busy"), "true");
	reconciler._setAction(marker, "review");
	widget.reviewState.reviews = [{ operation: "job" }];
	const { renderReviewBar } = await import(
		"../../src/script/forms/reviewBar.mjs"
	);
	renderReviewBar(widget);
	assert.equal(
		button.textContent,
		"Opening review…",
		"Bar refreshes keep pending feedback",
	);
	await reconciler.handleClick({ target: button });
	finishGet({ ok: true, unchanged: true });
	await opening;
	assert.equal(gets, 1, "A second click cannot start another review request");
	assert.equal(opened, 1);
	assert.equal(button.disabled, false);
	assert.equal(button.textContent, "Review values");
	assert.equal(button.hasAttribute("aria-busy"), false);
});

/**
 * @source src/script/forms/revisions/reconciler.mjs::EditReconciler
 * @matrix edited-entity-notice : structured-conflict
 */
test("test_stale_update_review_fetches_latest_values_before_opening", async (t) => {
	createBrowser(t, { html: formHTML });
	const fetched = [];
	const opened = [];
	const { EditReconciler } = await esmock.strict(
		"../../src/script/forms/revisions/reconciler.mjs",
		{
			"../../src/script/shared/request.mjs": {
				request: {
					get: async (route) => {
						fetched.push(route);
						return { ok: true, submission: { title: "newest saved" } };
					},
				},
			},
			"../../src/script/forms/revisions/modals.mjs": {
				FormRevisionModal: class {
					constructor(_reconciler, _marker, _widget, state, options) {
						opened.push({
							title: state.response.submission.title,
							blockedAction: options.blockedAction,
						});
					}
					async init() {
						return true;
					}
				},
				WholeFormRevisionModal: class {},
			},
		},
	);
	const widget = widgetFixture();
	delete widget.target.dataset.formState;
	const marker = widget.target.querySelector("[lp-edited-marker]");
	const reconciler = new EditReconciler({});
	const state = reconciler._state(marker);
	state.mode = "review";
	state.response = { submission: { title: "older saved" } };
	reconciler._stageRevision = async (_marker, _widget, response) => {
		state.response = response;
		state.mode = "review";
	};
	assert.equal(
		await reconciler.openConflictReview(widget, { blockedAction: "autofill" }),
		true,
	);
	assert.deepEqual(fetched, ["/tasks/task/replace"]);
	assert.deepEqual(opened, [
		{ title: "newest saved", blockedAction: "autofill" },
	]);
	state.mode = "review";
	state.response = { submission: { title: "older saved" } };
	reconciler._stageRevision = async () => {
		state.response = null;
		marker.dataset.visible = "false";
	};
	assert.equal(await reconciler.openConflictReview(widget), true);
	assert.deepEqual(opened, [
		{ title: "newest saved", blockedAction: "autofill" },
	]);
	assert.equal(marker.dataset.visible, "false");
});

/**
 * @source src/script/forms/revisions/reconciler.mjs::EditReconciler
 * @pair forms:submission-choice
 */
test("test_active_autofill_completion_stages_review_even_when_values_match", async (t) => {
	createBrowser(t, { html: formHTML });
	const { EditReconciler } = await esmock.strict(
		"../../src/script/forms/revisions/reconciler.mjs",
		{
			"../../src/script/forms/revisions/preview.mjs": {
				loadRevisionPreview: async () => ({
					revisionSnapshot: () => "unchanged",
					destroy() {},
				}),
			},
		},
	);
	const widget = widgetFixture();
	widget.unsavedState = false;
	widget.visible = true;
	widget.component.active = widget;
	widget.form = { renderer: {} };
	widget.schema = [{ id: "title", type: "input", input: "text" }];
	widget.submission = { title: "Saved" };
	widget.revisionBaseline = "unchanged";
	widget.revisionSnapshot = () => "unchanged";
	widget.revisionCanReset = () => true;
	widget.buildLocalRevision = (response) => ({ response });
	widget.prepareRevision = () =>
		assert.fail("A viewed form must not be replaced by completion");
	const marker = widget.target.querySelector("[lp-edited-marker]");
	const reconciler = new EditReconciler(
		{},
		{ ownedDeferredCompletion: () => ({ key: "task", operation: "job" }) },
	);
	await reconciler._stageRevision(marker, widget, {
		schema: widget.schema,
		submission: widget.submission,
		form_state: {
			revision: "latest",
			operation: {
				key: "job",
				type: "autofill",
				status: "succeeded",
				terminal: true,
			},
			reviews: [{ operation: "job", submission: { title: "Candidate" } }],
		},
	});
	assert.equal(marker._lp_edited_state.mode, "review");
	assert.equal(marker.dataset.visible, "true");
	assert.equal(
		widget.reviewState.revision,
		"launch",
		"Viewing a candidate must not acknowledge a saved baseline",
	);
	assert.match(marker.textContent, /Autofill is complete/);
});

/**
 * @source src/script/forms/revisions/reconciler.mjs::EditReconciler
 * @pair forms:autofill-completion-review
 */
test("test_remote_form_status_registers_operation_without_regressing_completion", async (t) => {
	createBrowser(t, { html: formHTML });
	const { EditReconciler } = await esmock.strict(
		"../../src/script/forms/revisions/reconciler.mjs",
		{
			"../../src/script/forms/revisions/preview.mjs": {
				loadRevisionPreview: async () => ({
					revisionSnapshot: () => "saved form",
					destroy() {},
				}),
			},
		},
	);
	const { FormWidget } = await import("../../src/script/widgets/base/formWidget.mjs");
	const widget = widgetFixture();
	widget.schema = [];
	widget.submission = {};
	widget.revisionBaseline = "saved form";
	widget.revisionCanReset = () => true;
	widget.lockDeferredOperation = FormWidget.prototype.lockDeferredOperation;
	const tracked = [];
	const operations = {
		track(key, options) {
			tracked.push({ key, options });
		},
	};
	let ensured = 0;
	const reconciler = new EditReconciler({
		async ensureDeferredOperations() {
			ensured += 1;
			return operations;
		},
	});
	const marker = widget.target.querySelector("[lp-edited-marker]");
	const running = {
		key: "remote-job",
		revision: 1,
		type: "autofill",
		status: "running",
		phase_label: "Waiting to start",
		terminal: false,
	};
	await reconciler._stageRevision(marker, widget, {
		schema: [],
		submission: {},
		form_state: { revision: "saved", operation: running, reviews: [] },
	});
	assert.equal(widget.target.dataset.operation, "remote-job");
	assert.equal(tracked[0].key, "remote-job");
	assert.equal(tracked[0].options.node, widget.target);
	assert.equal(tracked[0].options.revision, 1);
	assert.equal(ensured, 1);
	const completed = { ...running, revision: 2, status: "succeeded", terminal: true };
	widget.reviewState.operation = completed;
	await reconciler._stageRevision(marker, widget, {
		schema: [],
		submission: {},
		form_state: { revision: "saved", operation: running, reviews: [] },
	});
	assert.equal(widget.reviewState.operation.status, "succeeded");
	assert.equal(widget.reviewState.operation.revision, 2);
	assert.equal(tracked[1].options.revision, 2);
});

/**
 * @source src/script/forms/revisions/modals.mjs::FormRevisionModal
 * @matrix forms : submission-choice
 */
test("test_review_chooser_calls_blank_values_empty_without_changing_zero", async (t) => {
	createBrowser(t, { html: formHTML });
	const { FormRevisionModal } = await esmock.strict(
		"../../src/script/forms/revisions/modals.mjs",
		{
			"../../src/script/shared/modal.mjs": { Modal: class {} },
		},
	);
	const widget = widgetFixture();
	widget.revisionSnapshot = () => "draft";
	const modal = new FormRevisionModal(
		{ view: {} },
		widget.target.querySelector("[lp-edited-marker]"),
		widget,
		{ response: { schema: [], submission: {} } },
	);
	const placeholder = document.createElement("p");
	placeholder.textContent = "Not provided";
	assert.equal(
		modal._value({ hasSubmission: false, elt: placeholder }).textContent,
		"Empty",
	);
	const zero = document.createElement("p");
	zero.textContent = "0";
	assert.equal(
		modal._value({ hasSubmission: true, elt: zero }).textContent,
		"0",
	);
});

/**
 * @source src/script/forms/revisions/modals.mjs::FormRevisionModal
 * @pair forms:autofill-review
 */
test("test_prestart_conflict_chooser_says_autofill_did_not_start", async (t) => {
	createBrowser(t, { html: formHTML });
	const { FormRevisionModal } = await esmock.strict(
		"../../src/script/forms/revisions/modals.mjs",
		{
			"../../src/script/shared/modal.mjs": {
				Modal: class {
					async attach(node) {
						document.body.append(node);
					}
				},
			},
			"../../src/script/forms/revisions/preview.mjs": {
				loadRevisionPreview: async (_widget, response) => ({
					form: {
						renderer: {
							elements: new Map(
								response.schema.map((schema) => {
									const elt = document.createElement("p");
									elt.textContent = response.submission[schema.id];
									return [schema.id, { schema, elt }];
								}),
							),
						},
					},
					destroy() {},
				}),
			},
		},
	);
	const widget = widgetFixture();
	const schema = [{ id: "title", title: "Summary", type: "input", input: "text" }];
	widget.schema = schema;
	widget.captureFormState = () => ({
		renderer_submission: { title: "A draft" },
	});
	widget.revisionSnapshot = () => "draft";
	widget.buildLocalRevision = (response) => ({
		response: { ...response, submission: { title: "A draft" } },
	});
	const state = {
		response: { schema, submission: { title: "B saved" } },
	};
	const marker = widget.target.querySelector("[lp-edited-marker]");
	const modal = new FormRevisionModal(
		{ view: {} },
		marker,
		widget,
		state,
		{ blockedAction: "autofill" },
	);
	await modal.init();
	assert.equal(
		document.querySelector("#modal h2").textContent,
		"Review changes before autofill",
	);
	assert.match(
		document.querySelector("#modal-content p").textContent,
		/Autofill did not start.*start Autofill again/,
	);
	assert.equal(document.querySelectorAll("[role='radiogroup']").length, 1);
	assert.equal(
		[...document.querySelectorAll("#modal button")].some(
			(button) => button.textContent === "Use selected values",
		),
		true,
	);
});

/**
 * @source src/script/forms/revisions/modals.mjs::FormRevisionModal
 * @pair forms:submission-choice
 */
test("test_review_modal_keeps_incompatible_old_values_and_selects_ai_collection", async (t) => {
	createBrowser(t, { html: formHTML });
	const { FormRevisionModal } = await esmock.strict(
		"../../src/script/forms/revisions/modals.mjs",
		{
			"../../src/script/shared/modal.mjs": {
				Modal: class {
					async attach(node) {
						document.body.append(node);
					}
					async remove() {}
				},
			},
			"../../src/script/forms/revisions/preview.mjs": {
				loadRevisionPreview: async (_widget, response) => ({
					form: {
						renderer: {
							elements: new Map(
								response.schema.map((schema) => {
									const elt = document.createElement("p");
									elt.textContent = JSON.stringify(
										response.submission[schema.id],
									);
									return [schema.id, { schema, elt }];
								}),
							),
						},
					},
					destroy() {},
				}),
			},
		},
	);
	const widget = widgetFixture();
	const schema = [
		{ id: "title", type: "input", input: "text" },
		{ id: "todo", type: "todo" },
		{ id: "untouched", type: "textarea" },
	];
	const local = {
		title: "My draft",
		todo: { items: [{ text: "Read", checked: true }] },
	};
	widget.schema = schema;
	widget.captureFormState = () => ({ renderer_submission: local });
	local.untouched = "";
	widget._baselineSubmission = { title: "Saved", todo: local.todo };
	widget.revisionSnapshot = () => "draft";
	widget.buildLocalRevision = (response) => ({
		response: { ...response, submission: local },
	});
	const proposal = {
		title: "AI title",
		todo: { items: [...local.todo.items, { text: "Review", checked: false }] },
	};
	const state = {
		token: {},
		response: {
			schema,
			submission: { title: "Saved", todo: local.todo },
			form_state: {
				reviews: [{ operation: "job", schema, submission: proposal }],
				migration: {
					schema: [{ id: "title", type: "input", input: "number" }],
					submission: { title: 123 },
				},
			},
		},
	};
	let applied;
	const reconciler = {
		view: {},
		resolveRevision: async (_marker, choice) => {
			applied = choice.selectedSubmission;
		},
	};
	const modal = new FormRevisionModal(
		reconciler,
		widget.target.querySelector("[lp-edited-marker]"),
		widget,
		state,
	);
	await modal.init();
	assert.equal(
		document.querySelectorAll("[role='radiogroup']").length,
		2,
		"Empty controls must not produce spurious differences",
	);
	assert.equal(
		document.querySelector("[data-revision-source=before]").disabled,
		true,
	);
	const suggestions = [
		...document.querySelectorAll("[data-revision-source='ai:job']"),
	];
	suggestions.at(-1).click();
	const use = [...document.querySelectorAll("button")].find(
		(button) =>
			button.querySelector("[data-role='text']")?.textContent ===
			"Use selected values",
	);
	assert.equal(
		use.querySelector("[data-role='icon']")?.dataset.visible,
		"false",
		"Choosing values must not imply the form was submitted",
	);
	assert.equal(
		use.querySelector("[data-role='text']")?.textContent,
		"Use selected values",
	);
	state.probePromise = Promise.resolve().then(() => {
		state.token = {};
		state.response = structuredClone(state.response);
		state.response.form_state.operation = { elapsed_seconds: 25 };
	});
	use.click();
	assert.equal(use.disabled, true);
	assert.equal(
		use.querySelector("[data-role='text']")?.textContent,
		"Applying values…",
	);
	assert.equal(
		use
			.querySelector("[data-role='icon'] [data-icon='spinner']")
			?.getAttribute("aria-hidden"),
		"true",
	);
	await new Promise(setImmediate);
	assert.equal(applied.title, "My draft");
	assert.deepEqual(applied.todo, proposal.todo);
	assert.equal(
		widget.target.querySelector("input").value,
		"My draft",
		"The modal itself must not save or overwrite the live draft",
	);
	applied = null;
	state.token = {};
	state.response.submission.title = "A newer saved answer";
	use.click();
	await new Promise(setImmediate);
	assert.equal(applied, null, "A stale modal must not apply a selection");
	state.response.submission.title = "Saved";
	widget.revisionSnapshot = () => "A newer local draft";
	use.click();
	await new Promise(setImmediate);
	assert.equal(
		applied,
		null,
		"Changes to the local draft also invalidate the review",
	);
});

/**
 * @source src/script/forms/revisions/modals.mjs::FormRevisionModal
 * @pair forms:autofill-review
 */
test("test_review_modal_shows_applied_autofill_changes_without_duplicate_saved_values", async (t) => {
	createBrowser(t, { html: formHTML });
	const schema = [
		{ id: "subject", title: "Subject", type: "input", input: "text" },
		{ id: "code", title: "Evidence code", type: "input", input: "text" },
		{ id: "summary", title: "Summary", type: "textarea" },
		{ id: "quantity", title: "Quantity", type: "input", input: "number" },
	];
	const { FormRevisionModal } = await esmock.strict(
		"../../src/script/forms/revisions/modals.mjs",
		{
			"../../src/script/shared/modal.mjs": {
				Modal: class {
					async attach(node) {
						document.body.append(node);
					}
				},
			},
			"../../src/script/forms/revisions/preview.mjs": {
				loadRevisionPreview: async (_widget, response) => ({
					form: {
						renderer: {
							elements: new Map(
								response.schema.map((field) => {
									const elt = document.createElement("p");
									elt.textContent = String(response.submission[field.id] ?? "");
									return [field.id, { schema: field, elt }];
								}),
							),
						},
					},
					destroy() {},
				}),
			},
		},
	);
	const widget = widgetFixture();
	const saved = {
		subject: "DRAFT BETA",
		code: "ORCHID-482",
		summary: "Direct-file baseline evidence.",
		quantity: 42,
	};
	widget.schema = schema;
	widget.captureFormState = () => ({
		renderer_submission: { ...saved, quantity: "42" },
	});
	widget._baselineSubmission = saved;
	widget.revisionSnapshot = () => "saved";
	widget.buildLocalRevision = (response) => ({ response });
	const state = {
		response: {
			schema,
			submission: saved,
			form_state: {
				refine_url: "/tools/autofill/job/revise",
				reviews: [
					{
						operation: "job",
						fields: ["code", "summary", "quantity"],
						baseline: {
							subject: "DRAFT BETA",
							code: "",
							summary: "Saved baseline note.",
							quantity: 0,
						},
						schema,
						submission: saved,
					},
				],
			},
		},
	};
	const modal = new FormRevisionModal(
		{ view: {} },
		widget.target.querySelector("[lp-edited-marker]"),
		widget,
		state,
	);
	await modal.init();
	assert.equal(
		document.querySelector("[data-role='autofill-launch-context']"),
		null,
	);
	const groups = [...document.querySelectorAll("[role='radiogroup']")];
	assert.deepEqual(
		groups.map((group) => group.getAttribute("aria-label")),
		["Evidence code", "Summary", "Quantity"],
	);
	for (const group of groups) {
		assert.deepEqual(
			[...group.querySelectorAll("[role='radio']")].map(
				(choice) => choice.dataset.revisionSource,
			),
			["local", "ai:job"],
		);
	}
	assert.equal(document.querySelector("[data-revision-source='server']"), null);
	const reviseLabel = document.querySelector("#modal label");
	assert.match(reviseLabel.textContent, /Revise these values/);
	assert.doesNotMatch(reviseLabel.textContent, /with AI/);
	assert.equal(
		reviseLabel.querySelector("textarea").getAttribute("aria-label"),
		"Revise these values with AI",
	);
	assert.equal(reviseLabel.querySelector("[data-icon='generate']"), null);
	const reviseButton = [...document.querySelectorAll("button")].find((button) =>
		button.textContent.includes("Revise suggestions"),
	);
	assert.equal(
		reviseButton.getAttribute("aria-label"),
		"Revise suggestions with AI",
	);
	assert.equal(
		reviseButton
			.querySelector(
				"[data-role='icon'][data-visible='true'] [data-icon='generate']",
			)
			?.getAttribute("aria-hidden"),
		"true",
	);
	assert.equal(reviseButton.classList.contains("action-button"), true);
	assert.equal(
		reviseButton.querySelector("[data-role='text']")?.textContent,
		"Revise suggestions",
	);
	assert.equal(
		document
			.querySelector("button[data-revision-source='ai:job']")
			.getAttribute("aria-checked"),
		"true",
	);
	assert.equal(
		[...document.querySelectorAll("button")]
			.find(
				(button) =>
					button.querySelector("[data-role='text']")?.textContent ===
					"Use selected values",
			)
			.classList.contains("w-full"),
		true,
	);
});

/**
 * @source src/script/forms/revisions/modals.mjs::FormRevisionModal
 * @pair forms:autofill-review
 */
test("test_review_modal_prefers_ai_unless_saved_value_changed_after_launch", async (t) => {
	createBrowser(t, { html: formHTML });
	const schema = [
		{ id: "code", title: "Evidence code", type: "input", input: "text" },
		{ id: "subject", title: "Subject", type: "input", input: "text" },
	];
	const { FormRevisionModal } = await esmock.strict(
		"../../src/script/forms/revisions/modals.mjs",
		{
			"../../src/script/shared/modal.mjs": {
				Modal: class {
					async attach(node) {
						document.body.append(node);
					}
				},
			},
			"../../src/script/forms/revisions/preview.mjs": {
				loadRevisionPreview: async (_widget, response) => ({
					form: {
						renderer: {
							elements: new Map(
								schema.map((field) => {
									const elt = document.createElement("p");
									elt.textContent = response.submission[field.id] ?? "";
									return [field.id, { schema: field, elt }];
								}),
							),
						},
					},
					destroy() {},
				}),
			},
		},
	);
	const widget = widgetFixture();
	widget.schema = schema;
	widget._baselineSubmission = { code: "", subject: "DRAFT BETA" };
	widget.captureFormState = () => ({
		renderer_submission: { code: "", subject: "SAVED ALPHA" },
	});
	widget.revisionSnapshot = () => "unchanged";
	widget.buildLocalRevision = (response) => ({ response });
	const state = {
		response: {
			schema,
			submission: { code: "", subject: "DRAFT BETA" },
			form_state: {
				reviews: [
					{
						operation: "job",
						fields: ["code"],
						schema,
						baseline: { code: "", subject: "SAVED ALPHA" },
						saved_baseline: { code: "", subject: "DRAFT BETA" },
						submission: { code: "AI code", subject: "SAVED ALPHA" },
					},
				],
			},
		},
	};
	let modal = new FormRevisionModal(
		{ view: {} },
		widget.target.querySelector("[lp-edited-marker]"),
		widget,
		state,
	);
	await modal.init();
	assert.deepEqual(
		[...document.querySelectorAll("[role='radiogroup']")].map((group) =>
			group.getAttribute("aria-label"),
		),
		["Evidence code"],
		"An unsaved Subject preserved by AI is context, not another choice",
	);
	assert.deepEqual(
		[...document.querySelectorAll("[role='radiogroup'] [role='radio']")].map(
			(choice) => choice.dataset.revisionSource,
		),
		["local", "ai:job"],
	);
	assert.equal(
		document.querySelector("[data-role='autofill-launch-context']"),
		null,
	);
	assert.equal(
		document
			.querySelector("[data-revision-source='ai:job']")
			.getAttribute("aria-checked"),
		"true",
	);
	assert.deepEqual(
		modal._selectedSubmission(),
		{
			code: "AI code",
			subject: "SAVED ALPHA",
		},
		"A hidden unchanged field must keep this tab's unsaved draft",
	);
	document.querySelector("#modal").remove();
	state.response.submission.code = "Another user's code";
	modal = new FormRevisionModal(
		{ view: {} },
		widget.target.querySelector("[lp-edited-marker]"),
		widget,
		state,
	);
	await modal.init();
	assert.deepEqual(
		[...document.querySelectorAll("[role='radiogroup'] [role='radio']")].map(
			(choice) => choice.dataset.revisionSource,
		),
		["local", "ai:job", "server"],
		"Only a genuinely different post-launch saved value needs the third choice",
	);
	assert.equal(
		document
			.querySelector("[data-revision-source='server']")
			.getAttribute("aria-checked"),
		"true",
	);
	assert.deepEqual(modal._selectedSubmission(), {
		code: "Another user's code",
		subject: "SAVED ALPHA",
	});
	document.querySelector("#modal").remove();
	state.response.submission.code = "AI code";
	modal = new FormRevisionModal(
		{ view: {} },
		widget.target.querySelector("[lp-edited-marker]"),
		widget,
		state,
	);
	await modal.init();
	assert.deepEqual(
		[...document.querySelectorAll("[role='radiogroup'] [role='radio']")].map(
			(choice) => choice.dataset.revisionSource,
		),
		["local", "server"],
		"A concurrently saved value matching AI should appear as saved, not as an AI default",
	);
	assert.equal(
		document
			.querySelector("[data-revision-source='server']")
			.getAttribute("aria-checked"),
		"true",
	);
	assert.deepEqual(modal._selectedSubmission(), {
		code: "AI code",
		subject: "SAVED ALPHA",
	});
});

/**
 * @source src/script/forms/revisions/modals.mjs::FormRevisionModal
 * @pair forms:autofill-review
 */
test("test_review_modal_deduplicates_unchanged_ai_context_after_concurrent_save", async (t) => {
	createBrowser(t, { html: formHTML });
	const schema = [
		{ id: "subject", title: "Subject", type: "input", input: "text" },
		{ id: "quantity", title: "Quantity", type: "input", input: "number" },
	];
	const { FormRevisionModal } = await esmock.strict(
		"../../src/script/forms/revisions/modals.mjs",
		{
			"../../src/script/shared/modal.mjs": {
				Modal: class {
					async attach(node) {
						document.body.append(node);
					}
				},
			},
			"../../src/script/forms/revisions/preview.mjs": {
				loadRevisionPreview: async (_widget, response) => ({
					form: {
						renderer: {
							elements: new Map(
								schema.map((field) => {
									const elt = document.createElement("p");
									elt.textContent = String(response.submission[field.id] ?? "");
									return [field.id, { schema: field, elt }];
								}),
							),
						},
					},
					destroy() {},
				}),
			},
		},
	);
	const widget = widgetFixture();
	const launch = { subject: "SAVED ALPHA", quantity: 0 };
	widget.schema = schema;
	widget._baselineSubmission = launch;
	widget.captureFormState = () => ({ renderer_submission: launch });
	widget.revisionSnapshot = () => "launch";
	widget.buildLocalRevision = (response) => ({ response });
	const state = {
		response: {
			schema,
			submission: { subject: "DRAFT BETA", quantity: 0 },
			form_state: {
				reviews: [
					{
						operation: "job",
						fields: ["subject", "quantity"],
						schema,
						baseline: launch,
						saved_baseline: launch,
						submission: { subject: "SAVED ALPHA", quantity: 11 },
					},
				],
			},
		},
	};
	const modal = new FormRevisionModal(
		{ view: {} },
		widget.target.querySelector("[lp-edited-marker]"),
		widget,
		state,
	);
	await modal.init();
	const groups = [...document.querySelectorAll("[role='radiogroup']")];
	assert.deepEqual(
		groups.map((group) => group.getAttribute("aria-label")),
		["Subject", "Quantity"],
	);
	assert.deepEqual(
		[...groups[0].querySelectorAll("[role='radio']")].map(
			(choice) => choice.dataset.revisionSource,
		),
		["local", "server"],
		"An unchanged AI Subject must not duplicate the tab's Subject",
	);
	assert.deepEqual(
		[...groups[1].querySelectorAll("[role='radio']")].map(
			(choice) => choice.dataset.revisionSource,
		),
		["local", "ai:job"],
	);
	assert.equal(
		groups[0]
			.querySelector("[data-revision-source='server']")
			.getAttribute("aria-checked"),
		"true",
	);
	assert.equal(
		groups[1]
			.querySelector("[data-revision-source='local']")
			.getAttribute("aria-checked"),
		"true",
		"An AI quantity derived from stale Subject context must require explicit selection",
	);
	assert.deepEqual(modal._selectedSubmission(), {
		subject: "DRAFT BETA",
		quantity: 0,
	});
	groups[1].querySelector("[data-revision-source='ai:job']").click();
	assert.deepEqual(
		modal._selectedSubmission(),
		{ subject: "DRAFT BETA", quantity: 11 },
		"The AI proposal stays available for explicit selection",
	);
	document.querySelector("#modal").remove();
	widget.captureFormState = () => ({
		renderer_submission: { subject: "SAVED ALPHA", quantity: 5 },
	});
	const draftModal = new FormRevisionModal(
		{ view: {} },
		widget.target.querySelector("[lp-edited-marker]"),
		widget,
		state,
	);
	await draftModal.init();
	assert.deepEqual(
		draftModal._selectedSubmission(),
		{ subject: "DRAFT BETA", quantity: 5 },
		"A newer unsaved change in this tab still takes precedence over saved and AI values",
	);
});

/**
 * @source src/script/forms/revisions/modals.mjs::FormRevisionModal
 * @pair forms:autofill-review
 */
test("test_review_modal_explains_when_autofill_suggested_no_new_values", async (t) => {
	createBrowser(t, { html: formHTML });
	const schema = [{ id: "summary", title: "Summary", type: "textarea" }];
	const { FormRevisionModal } = await esmock.strict(
		"../../src/script/forms/revisions/modals.mjs",
		{
			"../../src/script/shared/modal.mjs": {
				Modal: class {
					async attach(node) {
						document.body.append(node);
					}
				},
			},
			"../../src/script/forms/revisions/preview.mjs": {
				loadRevisionPreview: async (_widget, response) => ({
					form: {
						renderer: {
							elements: new Map(
								schema.map((field) => {
									const elt = document.createElement("p");
									elt.textContent = response.submission[field.id] ?? "";
									return [field.id, { schema: field, elt }];
								}),
							),
						},
					},
					destroy() {},
				}),
			},
		},
	);
	const widget = widgetFixture();
	widget.schema = schema;
	widget.captureFormState = () => ({
		renderer_submission: { summary: "Already saved" },
	});
	widget.revisionSnapshot = () => "unchanged";
	widget.buildLocalRevision = (response) => ({ response });
	const state = {
		response: {
			schema,
			submission: { summary: "Already saved" },
			form_state: {
				reviews: [
					{
						operation: "job",
						fields: [],
						schema,
						baseline: { summary: "Already saved" },
						saved_baseline: { summary: "Already saved" },
						submission: { summary: "Already saved" },
					},
				],
			},
		},
	};
	const modal = new FormRevisionModal(
		{ view: {} },
		widget.target.querySelector("[lp-edited-marker]"),
		widget,
		state,
	);
	await modal.init();
	assert.equal(
		document.querySelector("#modal h2").textContent,
		"Autofill is complete",
	);
	assert.match(
		document.querySelector("#modal").textContent,
		/No new form values were suggested/,
	);
	assert.equal(document.querySelectorAll("[role='radiogroup']").length, 0);
	const keep = [...document.querySelectorAll("#modal button")].find(
		(button) =>
			button.querySelector("[data-role='text']")?.textContent ===
			"Keep current values",
	);
	assert.equal(
		keep.querySelector("[data-role='icon']")?.dataset.visible,
		"false",
		"Keeping values must not imply the form was submitted",
	);
	assert.equal(
		keep.querySelector("[data-role='text']")?.textContent,
		"Keep current values",
	);
	assert.equal(
		document
			.querySelector("#modal")
			.textContent.includes("Use selected values"),
		false,
	);
});
