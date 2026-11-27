import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

const buttons = {
	active({ existingButton }) {
		return {
			activate(text, kind) {
				existingButton.disabled = true;
				existingButton.textContent = text;
				if (kind) existingButton.dataset.kind = kind;
			},
			deactivate(text, kind) {
				existingButton.disabled = false;
				existingButton.textContent = text;
				if (kind) existingButton.dataset.kind = kind;
			},
		};
	},
};

async function loadImportData({ request = {} } = {}) {
	const { ImportData } = await esmock.strict(
		"../../src/script/widgets/ingress.ts",
		{
			"../../src/script/elements/buttons.ts": { buttons },
			"../../src/script/elements/combobox/index.ts": {
				FacetsBox: class {
					init() {}
					clear() {}
					destroy() {}
				},
				SelectBox: class {},
			},
			"../../src/script/elements/primitives.ts": { primitives: {} },
			"../../src/script/shared/index.ts": {
				captureError(error) {
					throw error;
				},
				Modal: class {},
				request,
			},
			"../../src/script/shared/transitions.ts": {
				withTransition: (callback) => callback(),
			},
		},
	);
	return ImportData;
}

function ingressTarget(stage = "IMPORTING") {
	const target = document.createElement("section");
	target.dataset.stage = stage;
	const stageElement = document.createElement("div");
	stageElement.dataset.role = "stage";
	const progress = document.createElement("div");
	progress.dataset.role = "progress";
	target.append(stageElement, progress);
	document.body.append(target);
	return { progress, stageElement, target };
}

test("test_ingress_stage_action_failure_restores_button_and_polling_for_retry", async (t) => {
	createBrowser(t);
	const ImportData = await loadImportData();
	const { stageElement, target } = ingressTarget();
	const widget = new ImportData({ key: "ingress-key", target });
	let pollingRestarts = 0;
	let operationCount = 0;
	let finishRequest;
	let shownError = null;
	widget.importRequestStarted = true;
	widget._clearError = () => {
		shownError = null;
	};
	widget._showError = (message) => {
		shownError = message;
	};
	widget._setImportStopped = () => {
		widget.importRequestStarted = false;
	};
	widget._startImportPolling = () => {
		pollingRestarts += 1;
		widget.importRequestStarted = true;
	};

	const button = document.createElement("button");
	button.dataset.kind = "delete";
	button.textContent = "Stop Import";
	stageElement.append(button);
	button.focus();
	const options = {
		pendingText: "Stopping...",
		pendingKind: "delete",
		fallback: "Import could not be stopped. Please try again.",
		pausePolling: true,
		operation() {
			operationCount += 1;
			return new Promise((resolve) => {
				finishRequest = resolve;
			});
		},
	};

	const first = widget._runStageAction(button, options);
	const duplicate = widget._runStageAction(button, options);
	assert.equal(first, duplicate);
	assert.equal(operationCount, 1);
	assert.equal(button.disabled, true);
	assert.equal(button.getAttribute("aria-busy"), "true");
	finishRequest({ ok: false, error: "Stop unavailable" });
	assert.equal(await first, false);
	assert.equal(button.disabled, false);
	assert.equal(button.textContent, "Stop Import");
	assert.equal(button.hasAttribute("aria-busy"), false);
	assert.equal(shownError, "Stop unavailable");
	assert.equal(pollingRestarts, 1);

	const retry = widget._runStageAction(button, options);
	assert.notEqual(retry, first);
	assert.equal(operationCount, 2);
	finishRequest({ ok: false, error: "Still unavailable" });
	await retry;
});

test("test_ingress_next_waits_for_pending_stage_update", async (t) => {
	createBrowser(t);
	let finishPatch;
	let patchFinished = false;
	const calls = [];
	const request = {
		patch() {
			calls.push("patch:start");
			return new Promise((resolve) => {
				finishPatch = () => {
					patchFinished = true;
					calls.push("patch:finish");
					resolve({ ok: true });
				};
			});
		},
		async put() {
			calls.push(`next:${patchFinished}`);
			return { stage: "ASSIGN_COLUMNS" };
		},
	};
	const ImportData = await loadImportData({ request });
	const { target } = ingressTarget("CHOOSE_FORM");
	const form = document.createElement("form");
	document.body.append(form);
	const widget = new ImportData({
		endpoints: {
			update: () => "/update",
			next: () => "/next",
		},
		key: "ingress-key",
		target,
	});
	widget.stageSettings = { target: form };
	widget._setStage = () => true;

	const change = widget._change({ target: form });
	const next = widget._next();
	await Promise.resolve();
	assert.equal(calls.includes("next:false"), false);

	finishPatch();
	await Promise.all([change, next]);
	assert.deepEqual(calls, ["patch:start", "patch:finish", "next:true"]);
});

test("test_ingress_polling_tracks_widget_visibility", async (t) => {
	createBrowser(t);
	const ImportData = await loadImportData();
	const subscriptions = new Map();
	const coordinator = {
		subscribe(descriptor, hooks) {
			subscriptions.set(descriptor.id, { descriptor, hooks });
			return () => subscriptions.delete(descriptor.id);
		},
	};
	const { target } = ingressTarget();
	target.dataset.fingerprint = "ingress-v1";
	const ancestor = document.createElement("section");
	ancestor.setAttribute("lp-component", "");
	ancestor.dataset.visible = "false";
	const componentElement = document.createElement("div");
	ancestor.append(componentElement);
	document.body.append(ancestor);
	const component = {
		active: null,
		visible: false,
		elt: componentElement,
	};
	const widget = new ImportData({
		component,
		key: "ingress-key",
		target,
		view: { PollingCoordinator: coordinator },
		visible: false,
	});

	widget._startImportPolling();
	assert.equal(subscriptions.size, 0);

	component.active = widget;
	component.visible = true;
	widget.visible = true;
	await widget.syncPollingSubscription();
	assert.equal(subscriptions.size, 0);

	ancestor.dataset.visible = "true";
	await widget.syncPollingSubscription();
	assert.equal(subscriptions.has("ingress:ingress-key"), true);

	widget.visible = false;
	await widget.syncPollingSubscription();
	assert.equal(subscriptions.size, 0);

	widget.visible = true;
	await widget.syncPollingSubscription();
	assert.equal(subscriptions.has("ingress:ingress-key"), true);

	widget._setImportStopped();
	assert.equal(subscriptions.size, 0);
	assert.equal(widget.importRequestStarted, false);
});

test("test_ingress_choose_parent_toggles_and_resets_create_model", async (t) => {
	createBrowser(t);
	const ImportData = await loadImportData();
	const { progress, target } = ingressTarget("CHOOSE_PARENT");
	const form = document.createElement("form");
	const existing = document.createElement("div");
	existing.dataset.option = "existing-parent";
	const createModel = document.createElement("div");
	createModel.dataset.section = "create-model";
	createModel.dataset.parentKind = "none";
	createModel.dataset.visible = "false";
	form.append(existing, createModel);
	progress.append(form);

	const widget = new ImportData({ key: "ingress-key", target });
	widget.stageSettings = { target: form, destroyables: [] };
	widget._setChooseParent();

	form.dispatchEvent(
		new CustomEvent("updated", {
			bubbles: true,
			detail: { options: { p1: { id: "p1", kind: "project" } } },
		}),
	);
	assert.equal(createModel.dataset.parentKind, "project");
	assert.equal(createModel.dataset.visible, "true");

	form.dispatchEvent(
		new CustomEvent("updated", {
			bubbles: true,
			detail: { options: { m1: { id: "m1", kind: "model" } } },
		}),
	);
	assert.equal(createModel.dataset.parentKind, "model");
	assert.equal(createModel.dataset.visible, "false");

	form.dispatchEvent(
		new CustomEvent("updated", {
			bubbles: true,
			detail: { options: { p1: { id: "p1", kind: "project" } } },
		}),
	);
	assert.equal(createModel.dataset.visible, "true");

	form.dispatchEvent(
		new CustomEvent("updated", {
			bubbles: true,
			detail: { options: {} },
		}),
	);
	assert.equal(createModel.dataset.parentKind, "none");
	assert.equal(createModel.dataset.visible, "false");
});
