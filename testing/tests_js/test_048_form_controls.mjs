import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import ViewComponent from "../../src/script/views/base/component.mjs";
import { createBrowser } from "../utility/js/environment.mjs";

function target(name = "Original", loaded = true) {
	const form = document.createElement("form");
	form.dataset.name = name;
	form.dataset.widget = "Example";
	form.dataset.visible = "true";
	form.setAttribute("lp-load", "");
	if (loaded) form.setAttribute("loaded", "");
	const input = document.createElement("input");
	input.name = "name";
	input.value = name;
	form.append(input);
	document.body.append(form);
	return form;
}

const response = (nextTarget) => ({
	html: { querySelector: () => nextTarget },
});

async function setupFormWidget(t, { name = "Original", loaded = true } = {}) {
	createBrowser(t);
	const initialTarget = target(name, loaded);
	const controllers = [];
	let initialize = async () => {};
	class FormController {
		constructor(widget) {
			this.widget = widget;
			this.destroyed = 0;
			controllers.push(this);
		}

		async init() {
			await initialize(this);
		}

		destroy() {
			this.destroyed = 1;
		}

		syncOfflineState() {}
	}
	const { FormWidget } = await esmock.strict(
		"../../src/script/widgets/base/formWidget.mjs",
		{
			"../../src/script/forms/controller.mjs": { FormController },
		},
	);
	return {
		controllers,
		widget: new FormWidget({ target: initialTarget, name: "Example" }),
		setInitialize(callback) {
			initialize = callback;
		},
	};
}

/** @matrix user-groups forms : initialization conditional-response single-reconciliation */
test("test_form_shell_waits_for_html_and_visibility_does_not_rebuild", async (t) => {
	const { controllers, widget } = await setupFormWidget(t, {
		name: "",
		loaded: false,
	});
	await widget.init();
	assert.equal(widget.initialized, false);
	assert.equal(widget.form, null);
	widget.updated({ ...response(target("Saved")), updated: false });
	await widget.prereconcile();
	widget.postreconcile();
	assert.equal(widget.initialized, true);
	assert.equal(widget.target.hasAttribute("initialized"), true);
	assert.equal(widget.formData.get("name"), "Saved");
	assert.equal(widget.revisionBaseline, widget.revisionSnapshot());
	const form = widget.form;
	await widget.prereconcile();
	widget.postreconcile();
	assert.equal(widget.form, form);
	assert.equal(controllers.length, 1);
});

/** @matrix forms user-groups : rebuild-serialization single-reconciliation */
test("test_form_replacements_serialize_and_adopt_only_latest_controls", async (t) => {
	const { controllers, widget, setInitialize } = await setupFormWidget(t);
	await widget.init();
	const live = widget.form;
	let release;
	setInitialize(async (controller) => {
		controller.widget.selector = { target: controller.widget.target };
		if (controller.widget.target.dataset.name === "First") {
			await new Promise((resolve) => {
				release = resolve;
			});
		}
	});
	widget.updated(response(target("First")));
	const first = widget.prereconcile();
	while (!release) await Promise.resolve();
	assert.equal(widget.target.inert, true);
	assert.equal(
		widget.selector,
		undefined,
		"Detached initialization mutated the live widget",
	);
	widget.updated(response(target("Latest")));
	const second = widget.prereconcile();
	release();
	await Promise.all([first, second]);
	await widget.prereconcile();
	assert.equal(
		controllers.length,
		3,
		"Repeated preparation rebuilt the same response",
	);
	assert.equal(controllers[1].destroyed, 1);
	assert.equal(live.destroyed, 0);
	widget.postreconcile();
	assert.equal(widget.formData.get("name"), "Latest");
	assert.equal(widget.selector.target, widget.target);
	assert.equal(live.destroyed, 1);
	assert.equal(widget.form.destroyed, 0);
	assert.equal(widget.target.inert, false);
	assert.equal(widget.revisionBaseline, widget.revisionSnapshot());
	widget.form.widget.markUnsavedState();
	assert.equal(
		widget.unsavedState,
		true,
		"Adopted controller still writes detached state",
	);
});

/** @matrix forms user-groups : rebuild-serialization single-reconciliation */
test("test_queued_commit_waits_for_newer_replacement", async (t) => {
	const { widget, setInitialize } = await setupFormWidget(t);
	await widget.init();
	widget.target.inert = true;
	const live = widget.form;
	widget.updated(response(target("First")));
	await widget.prereconcile();
	let release;
	setInitialize(
		async () =>
			await new Promise((resolve) => {
				release = resolve;
			}),
	);
	widget.updated(response(target("Latest")));
	widget.postreconcile();
	assert.equal(widget.form, live, "A superseded preparation was committed");
	const pending = widget.prereconcile();
	while (!release) await Promise.resolve();
	widget.modified = false;
	widget.postreconcile();
	assert.equal(widget.modified, true);
	assert.equal(widget._updated, true);
	assert.equal(
		widget.form,
		live,
		"A queued commit interrupted the latest preparation",
	);
	release();
	await pending;
	widget.postreconcile();
	assert.equal(widget.formData.get("name"), "Latest");
	assert.equal(widget._updated, false);
	assert.equal(
		widget.target.inert,
		true,
		"Replacement lost its prior inert state",
	);
});

/** @matrix forms : teardown reset unsaved-preservation */
test("test_form_discard_and_failure_leave_live_controls_intact", async (t) => {
	const { controllers, widget, setInitialize } = await setupFormWidget(t);
	await widget.init();
	const live = widget.form;
	let release;
	setInitialize(
		async () =>
			await new Promise((resolve) => {
				release = resolve;
			}),
	);
	const pending = widget.prepareReset({ nextTarget: target("Discarded") });
	while (!release) await Promise.resolve();
	widget.discardPreparedReset();
	release();
	await pending;
	assert.equal(widget.commitReset(), false);
	assert.equal(controllers[1].destroyed, 1);
	assert.equal(live.destroyed, 0);
	assert.equal(widget.formData.get("name"), "Original");
	setInitialize(async (controller) => {
		controller.widget.target.querySelector("[name='name']").value =
			"Partially initialized";
		throw new Error("control initialization failed");
	});
	widget.updated(response(target("Failed")));
	await assert.rejects(widget.prereconcile(), /control initialization failed/);
	assert.equal(controllers[2].destroyed, 1);
	assert.equal(live.destroyed, 0);
	assert.equal(widget.target.inert, false);
	assert.equal(widget.commitReset(), false);
	setInitialize(async () => {});
	await widget.prereconcile();
	widget.postreconcile();
	assert.equal(
		widget.formData.get("name"),
		"Failed",
		"Retry reused partially initialized markup",
	);
});

/** @matrix forms : reset unsaved-preservation */
test("test_explicit_revision_reset_can_replace_dirty_form", async (t) => {
	const { widget } = await setupFormWidget(t);
	await widget.init();
	widget.target.querySelector("[name='name']").value = "Local draft";
	widget.markUnsavedState();
	const commit = await widget.prepareRevision(
		response(target("Saved elsewhere")),
	);
	assert.equal(widget.formData.get("name"), "Local draft");
	commit();
	assert.equal(widget.formData.get("name"), "Saved elsewhere");
	assert.equal(widget.unsavedState, false);
	assert.equal(widget.revisionBaseline, widget.revisionSnapshot());
});

/** @matrix user-groups : conditional-response initialization */
test("test_validated_html_initializes_cold_widget_without_rebuilding_loaded_widget", async () => {
	const calls = [];
	const widget = {
		name: "GroupPermissions/one",
		route: "/group",
		initialized: false,
		updated(result) {
			calls.push(result);
		},
	};
	const component = Object.create(ViewComponent.prototype);
	component.active = widget;
	component.view = { load: async () => ({ updated: false }) };
	await component.load(widget);
	assert.equal(calls.length, 1);
	widget.initialized = true;
	await component.load(widget);
	assert.equal(calls.length, 1);
});

/** @matrix forms : initialization teardown readonly */
test("test_declared_controls_are_lazy_owned_and_cleaned_on_failed_initialization", async (t) => {
	createBrowser(t);
	const controls = [];
	let failure = false;
	let release = null;
	class Control {
		constructor(root, options) {
			Object.assign(this, { root, options, destroyed: 0 });
			controls.push(this);
		}

		async init() {
			if (failure) throw new Error("failed control");
			await new Promise((resolve) => {
				release = resolve;
			});
		}

		destroy() {
			this.destroyed = 1;
		}
	}
	const { initFormControls } = await esmock.p(
		"../../src/script/forms/controls/loader.mjs",
		{
			"../../src/script/forms/controls/accessRestrictions.mjs": {
				default: Control,
			},
		},
	);
	const { FormController } = await esmock.strict(
		"../../src/script/forms/controller.mjs",
		{
			"../../src/script/forms/controls/loader.mjs": { initFormControls },
		},
	);
	function root(marked = false) {
		const form = document.createElement("form");
		if (marked) form.dataset.formControl = "access-restrictions";
		return form;
	}
	function makeForm(formTarget, readonly = false) {
		const form = new FormController({ target: formTarget, readonly });
		form._initSubmitButton =
			form._initOfflineState =
			form._initUnsavedState =
				() => {};
		return form;
	}

	await makeForm(root()).init();
	assert.equal(controls.length, 0);
	const form = makeForm(root(true), true);
	const pending = form.init();
	while (!release) await Promise.resolve();
	assert.equal(controls[0].options.readonly, true);
	assert.equal(form.destroyables[0], controls[0]);
	form.destroy();
	release();
	await pending;
	assert.equal(controls[0].destroyed, 1);
	failure = true;
	await assert.rejects(makeForm(root(true)).init(), /failed control/);
	assert.equal(controls[1].destroyed, 1);
});

/** @matrix forms : review-notice-placement */
test("test_form_review_notice_stays_above_expanded_autofill_context", async (t) => {
	createBrowser(t);
	const { FormController } = await import("../../src/script/forms/controller.mjs");
	const target = document.createElement("form");
	const submitGroup = document.createElement("div");
	submitGroup.dataset.role = "submit-group";
	const submitButton = submitGroup.appendChild(document.createElement("button"));
	submitButton.type = "submit";
	const panel = document.createElement("div");
	panel.dataset.role = "autofill";
	panel.dataset.visible = "true";
	const marker = document.createElement("div");
	marker.setAttribute("lp-edited-marker", "");
	target.append(submitGroup, panel, marker);
	document.body.append(target);
	const controller = new FormController({
		target,
		readonly: false,
		schema: [],
		submitGroup,
		submitButton,
	});
	controller._initSubmitButton =
		controller._initOfflineState =
		controller._initUnsavedState = () => {};
	await controller.init();
	assert.equal(marker.nextElementSibling, panel);
	assert.equal(panel.dataset.visible, "true");
});
