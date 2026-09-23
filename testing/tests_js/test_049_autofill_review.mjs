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
test("test_review_bar_keeps_answers_editable_and_combines_reasons", async (t) => {
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
	assert.match(
		widget.target.querySelector("[data-role=edited-message]").textContent,
		/Autofill is complete.*fields have changed/,
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
	widget.target.querySelector("[data-role=autofill-cancel]").click();
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
		(button) => button.textContent === "Use selected values",
	);
	state.probePromise = Promise.resolve().then(() => {
		state.token = {};
		state.response = structuredClone(state.response);
		state.response.form_state.operation = { elapsed_seconds: 25 };
	});
	use.click();
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
