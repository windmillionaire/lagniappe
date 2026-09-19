import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { test } from "node:test";
import { setImmediate as nextTurn } from "node:timers/promises";
import esmock from "esmock";

import { BuilderDraft } from "../../src/script/views/builder/draft.mjs";

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

/** @matrix forms : builder-save retryable-action single-flight stale-acknowledgement */
test("test_builder_save_releases_for_retry_and_only_acknowledges_submitted_state", async (t) => {
	const requests = [];
	const classes = new Set();
	const button = {
		classList: {
			add: (name) => classes.add(name),
			remove: (name) => classes.delete(name),
		},
		dataset: { saved: "false", kind: "unsaved" },
		disabled: false,
		isConnected: true,
		attributes: {},
		setAttribute(name, value) {
			this.attributes[name] = value;
		},
		removeAttribute(name) {
			delete this.attributes[name];
		},
		focus() {
			document.activeElement = this;
		},
	};
	const nameDisplay = { dataset: {}, textContent: "Retryable Form" };
	const nameInput = {
		dataset: {},
		value: "Retryable Form",
		addEventListener() {},
		removeEventListener() {},
	};
	const nameHidden = { value: "Retryable Form" };
	const schemaForm = { dataset: { route: "/forms/retry/update" } };
	const notification = {
		attributes: {},
		dataset: { visible: "false" },
		textContent: "",
		setAttribute(name, value) {
			this.attributes[name] = value;
		},
		append(link) {
			this.link = link;
		},
	};
	const previewToggle = { dataset: {} };
	const previewPanel = { dataset: {} };
	const documentBoundary = {
		activeElement: button,
		body: {},
		createElement: () => ({ dataset: {} }),
		getElementById(id) {
			return (
				{
					"form-name-display": nameDisplay,
					"form-name-input": nameInput,
					"form-name-hidden": nameHidden,
					"schema-form": schemaForm,
					notification,
					"preview-toggle": previewToggle,
					"preview-panel": previewPanel,
				}[id] ?? null
			);
		},
		querySelector(selector) {
			return selector === "[data-saved]" ? button : null;
		},
	};
	replaceGlobal(t, "document", documentBoundary);
	replaceGlobal(t, "crypto", webcrypto);
	replaceGlobal(
		t,
		"FormData",
		class {
			constructor(form) {
				this.form = form;
			}
		},
	);
	replaceGlobal(t, "clearTimeout", () => {});
	replaceGlobal(t, "setTimeout", () => {
		throw new Error("Persistent save errors must not schedule hiding");
	});
	const request = {
		put(...args) {
			return new Promise((resolve, reject) => {
				requests.push({ resolve, reject, args });
			});
		},
	};
	const { Header } = await esmock.strict(
		"../../src/script/views/builder/panels/header.mjs",
		{
			"../../src/script/forms/renderer.mjs": { FormRenderer: class {} },
			"../../src/script/shared/index.mjs": {
				areEqual: (a, b) => JSON.stringify(a) === JSON.stringify(b),
				captureError() {},
				request,
			},
			"../../src/script/shared/transitions.mjs": {
				withTransition: (callback) => callback(),
			},
		},
	);
	let schema = [{ id: "first", type: "text" }];
	let restores = 0;
	let settingRefreshes = 0;
	let conditionRefreshes = 0;
	let controlRefreshes = 0;
	const restoredOptions = [];
	const builder = {
		get schema() {
			return schema;
		},
		captureDraft() {
			return {
				schema: structuredClone(schema),
				name: nameHidden.value,
				form_type: "task",
				html_fields: {},
			};
		},
		updateSchema() {
			this.draft.record(this.captureDraft());
			this.draft.dirty ? header.unsaved() : header.saved();
		},
		async draftPayload(state) {
			return structuredClone(state);
		},
		settings: {
			refreshSavedState() {
				settingRefreshes += 1;
			},
		},
		conditions: {
			condition: {
				refreshSavedState() {
					conditionRefreshes += 1;
				},
			},
		},
		refreshDraftControls() {
			controlRefreshes += 1;
			this.draft.dirty ? header.unsaved() : header.saved();
		},
		restoreDraft(options) {
			restores += 1;
			restoredOptions.push(options);
			schema = structuredClone(this.draft.state.schema);
			this.draft.dirty ? header.unsaved() : header.saved();
		},
	};
	builder.draft = new BuilderDraft(builder.captureDraft(), "initial");
	const header = new Header(builder);
	assert.deepEqual(
		{
			describedBy: button.attributes["aria-describedby"],
			role: notification.attributes.role,
			live: notification.attributes["aria-live"],
		},
		{ describedBy: "notification", role: "status", live: "polite" },
		"publishes an accessible save status",
	);

	schema = [{ ...schema[0], title: "Edited notes" }];
	builder.updateSchema();
	assert.deepEqual(
		[builder.draft.dirty, button.disabled, button.attributes["aria-disabled"]],
		[true, false, "false"],
		"enables Save after editing",
	);
	builder.online = false;
	header.unsaved();
	assert.equal(button.attributes["aria-disabled"], "true");
	assert.equal(await header.saveForm(), false, "does not save offline");
	assert.equal(requests.length, 0);
	builder.online = true;
	header.unsaved();
	const first = header.saveForm();
	const duplicate = header.saveForm();
	await nextTurn();
	assert.equal(first, duplicate, "coalesces concurrent saves");
	assert.equal(requests.length, 1);
	assert.deepEqual(
		[
			button.disabled,
			button.attributes["aria-disabled"],
			button.attributes["aria-busy"],
		],
		[false, "true", "true"],
		"stays focusable while pending",
	);
	assert.ok(!classes.has("opacity-50"), "does not dim Save");
	assert.equal(
		requests[0].args[2]?.replaceErrorPage,
		false,
		"preserves retryable page",
	);

	schema = [...schema, { id: "second", type: "number" }];
	builder.updateSchema();
	const firstRequest = requests.shift();
	firstRequest.resolve({
		ok: true,
		draft: firstRequest.args[1],
		baseline: "saved-1",
	});
	assert.equal(await first, true);
	assert.equal(
		button.dataset.saved,
		"false",
		"does not acknowledge newer edits",
	);
	assert.deepEqual(
		[button.disabled, button.attributes["aria-busy"]],
		[false, undefined],
	);
	assert.deepEqual(
		[restores, settingRefreshes, conditionRefreshes, controlRefreshes],
		[0, 1, 1, 1],
		"refreshes restrictions and controls without rebuilding newer edits",
	);
	assert.deepEqual(
		[
			schema.length,
			builder.draft.state.schema.length,
			builder.draft.saved.schema.length,
		],
		[2, 2, 1],
		"keeps newer edits outside saved baseline",
	);

	const rejected = header.saveForm();
	await nextTurn();
	button.dataset.visible = "false";
	requests.shift().reject(new Error("transport failed"));
	assert.equal(await rejected, false);
	assert.equal(button.disabled, false, "releases rejected save");
	assert.equal(
		button.dataset.visible,
		"false",
		"preserves connectivity visibility",
	);
	button.dataset.visible = "true";

	const failed = header.saveForm();
	await nextTurn();
	requests.shift().resolve({ ok: false, error: "Temporary save failure" });
	assert.equal(await failed, false);
	assert.deepEqual(
		[button.disabled, notification.dataset.visible],
		[false, "true"],
	);
	assert.equal(notification.textContent, "Temporary save failure");

	const conflicted = header.saveForm();
	await nextTurn();
	requests.shift().resolve({
		ok: false,
		code: "stale_form_draft",
		error: "Changed elsewhere",
		saved_url: "/forms/current",
	});
	assert.equal(await conflicted, false);
	assert.deepEqual(
		[notification.link?.href, notification.link?.target],
		["/forms/current", "_blank"],
		"links separate saved form after conflict",
	);
	assert.deepEqual(
		[builder.draft.state.schema.length, builder.draft.dirty],
		[2, true],
		"preserves local draft after conflict",
	);

	const retry = header.saveForm();
	await nextTurn();
	assert.notEqual(retry, failed);
	assert.equal(requests.length, 1, "allows retry after release");
	const retriedRequest = requests.shift();
	retriedRequest.resolve({
		ok: true,
		draft: retriedRequest.args[1],
		baseline: "saved-2",
	});
	assert.equal(await retry, true);
	assert.equal(button.dataset.saved, "true", "acknowledges current state");
	assert.deepEqual(
		[notification.dataset.visible, notification.textContent],
		["false", ""],
		"clears prior error",
	);
	assert.deepEqual(
		[button.disabled, button.attributes["aria-disabled"]],
		[false, "true"],
		"keeps saved status focusable",
	);
	assert.deepEqual(
		[restores, settingRefreshes, conditionRefreshes, controlRefreshes],
		[0, 2, 2, 2],
		"refreshes saved controls without rebuilding",
	);
	assert.ok(!classes.has("opacity-50"), "does not leave saved control dimmed");

	const savedRestores = restores;
	const savedRevision = builder.draft.revision;
	assert.equal(await header.saveForm(), true, "treats unchanged form as saved");
	assert.deepEqual(
		[requests.length, restores, builder.draft.revision],
		[0, savedRestores, savedRevision],
		"does not submit or rebuild unchanged draft",
	);
	assert.deepEqual(
		[button.disabled, button.dataset.saved, button.attributes["aria-disabled"]],
		[false, "true", "true"],
	);

	schema = schema.map((field) =>
		field.id === "first"
			? { ...field, title: "   Normalized notes   " }
			: field,
	);
	builder.updateSchema();
	const normalized = header.saveForm();
	await nextTurn();
	const normalizationRequest = requests.shift();
	const accepted = structuredClone(normalizationRequest.args[1]);
	accepted.schema[0].title = "Normalized notes";
	normalizationRequest.resolve({
		ok: true,
		draft: accepted,
		baseline: "saved-3",
	});
	assert.equal(await normalized, true);
	assert.deepEqual([restores, restoredOptions[0]?.preserveFocus], [1, true]);
	assert.deepEqual(
		[schema[0].title, builder.draft.dirty, button.dataset.saved],
		["Normalized notes", false, "true"],
		"reflects normalized saved form",
	);
	assert.deepEqual(
		[settingRefreshes, conditionRefreshes, controlRefreshes],
		[2, 2, 2],
		"uses reconciliation path for normalization",
	);

	schema = schema.map((field) =>
		field.id === "first" ? { ...field, title: "Edited after saving" } : field,
	);
	builder.updateSchema();
	assert.deepEqual(
		[button.disabled, button.attributes["aria-disabled"]],
		[false, "false"],
	);
	const late = header.saveForm();
	await nextTurn();
	header.destroy();
	requests.shift().resolve({ ok: true });
	assert.equal(await late, false, "does not publish after destruction");
});

async function loadFormSettings({ request }) {
	return await esmock.strict(
		"../../src/script/views/builder/panels/formSettings.mjs",
		{
			"../../src/script/forms/controller.mjs": { FormController: class {} },
			"../../src/script/shared/index.mjs": {
				captureError() {},
				ENDPOINTS: { createSchema: "/forms/create-schema" },
				Modal: class {},
				request,
			},
		},
	);
}

/** @matrix forms ui-action : persistent-error retryable-action schema-generation single-flight */
test("test_builder_generation_failure_stays_visible_and_releases_submitter", async (t) => {
	let finishRequest;
	let requestCount = 0;
	class FormDataBoundary {
		get(name) {
			return name === "description" ? "Create a form" : null;
		}
		append() {}
		set() {}
	}
	replaceGlobal(t, "FormData", FormDataBoundary);
	replaceGlobal(t, "crypto", webcrypto);
	const { FormSettings } = await loadFormSettings({
		request: {
			post() {
				requestCount += 1;
				return new Promise((resolve) => {
					finishRequest = resolve;
				});
			},
		},
	});
	const attributes = {};
	const submitter = {
		dataset: {},
		disabled: false,
		isConnected: true,
		setAttribute(name, value) {
			attributes[name] = value;
		},
		removeAttribute(name) {
			delete attributes[name];
		},
	};
	let error = null;
	let resets = 0;
	const settings = {
		_destroyed: false,
		_generationPromise: null,
		builder: {
			updateSchema() {},
			draft: { revision: 0, baseline: "source" },
			captureDraft: () => ({ schema: [], html_fields: {} }),
			header: {
				saveButton: { dataset: { saved: "true" } },
				persistenceState: { name: "Generated Form", schema: [] },
			},
		},
		generateForm: {
			target: { dataset: { visible: "true" } },
			submitButton: submitter,
			showError(message) {
				error = message;
				submitter.disabled = false;
			},
			resetSubmitButton() {
				resets += 1;
				error = null;
			},
		},
		_updateSchema: FormSettings.prototype._updateSchema,
	};
	const event = { submitter, preventDefault() {}, stopPropagation() {} };
	const first = FormSettings.prototype._generateSchema.call(settings, event);
	const duplicate = FormSettings.prototype._generateSchema.call(
		settings,
		event,
	);
	assert.equal(first, duplicate, "coalesces concurrent generation");
	assert.equal(requestCount, 1);
	assert.deepEqual(
		[submitter.disabled, attributes["aria-busy"]],
		[true, "true"],
	);
	finishRequest({ ok: false, error: "Generation unavailable" });
	assert.equal(await first, false);
	assert.deepEqual(
		[error, resets],
		["Generation unavailable", 0],
		"keeps failure visible",
	);
	assert.deepEqual(
		[submitter.disabled, attributes["aria-busy"]],
		[false, undefined],
	);
});

function emptyClass() {
	return class {};
}

async function loadBuilder({ connectivity, generateElementId, ModelElement }) {
	return await esmock.strict("../../src/script/views/builder/builder.mjs", {
		"../../src/script/elements/combobox/search.mjs": {
			SearchBox: emptyClass(),
		},
		"../../src/script/elements/entityMenu.mjs": { EntityMenu: emptyClass() },
		"../../src/script/shared/directUpload.mjs": { directUpload() {} },
		"../../src/script/shared/index.mjs": {
			captureError() {},
			connectivity,
			DeleteModal: emptyClass(),
			generateElementId,
			HelpModal: emptyClass(),
			OfflineModal: emptyClass(),
			request: {},
		},
		"../../src/script/shared/transitions.mjs": {
			withTransition: (callback) => callback(),
		},
		"../../src/script/views/builder/changeStatus.mjs": {
			FormChangeStatus: emptyClass(),
		},
		"../../src/script/views/builder/conditions/loader.mjs": {
			loadCondition: async () => null,
		},
		"../../src/script/views/builder/draft.mjs": { BuilderDraft: emptyClass() },
		"../../src/script/views/builder/migrations.mjs": {
			fieldKind: () => null,
			needsMigration: () => false,
			repairConditions: () => {},
		},
		"../../src/script/views/builder/panels/components.mjs": {
			ComponentsPanel: emptyClass(),
		},
		"../../src/script/views/builder/panels/condition.mjs": {
			ConditionPanel: emptyClass(),
		},
		"../../src/script/views/builder/panels/elementSettings.mjs": {
			ElementSettings: emptyClass(),
		},
		"../../src/script/views/builder/panels/formSettings.mjs": {
			FormSettings: emptyClass(),
		},
		"../../src/script/views/builder/panels/header.mjs": {
			Header: emptyClass(),
		},
		"../../src/script/views/builder/panels/model.mjs": {
			ModelElement,
			ModelPanel: emptyClass(),
		},
	});
}

/** @matrix form-table forms : builder-defaults empty-columns unsaved-preview */
test("test_table_creation_defaults_columns_for_unsaved_preview", async () => {
	const ModelElement = { table: (schema) => ({ id: schema.id }) };
	const { default: FormBuilder } = await loadBuilder({
		connectivity: { hidden: false, online: true },
		generateElementId: (type) => `${type}-1`,
		ModelElement,
	});
	const builder = { elements: new Map(), settings: { create: () => ({}) } };
	const schema = { type: "table" };
	const element = FormBuilder.prototype.createElement.call(builder, schema);
	assert.equal(schema.id, "table-1");
	assert.deepEqual(schema.columns, [], "defaults table columns");
	assert.equal(
		builder.elements.get(schema.id)?.schema,
		schema,
		"retains normalized schema",
	);
	assert.equal(element.id, schema.id, "renders normalized schema");
});

/** @matrix forms offline : builder-lifecycle */
test("test_builder_sync_uses_shared_connectivity_without_orphaned_global_state", async (t) => {
	const search = { dataset: {} };
	const indicator = {
		dataset: {},
		setAttribute(name, value) {
			this[name] = value;
		},
	};
	const saveButton = {
		dataset: {},
		getAttribute(name) {
			return this[name] ?? null;
		},
		setAttribute(name, value) {
			this[name] = value;
		},
	};
	const connectivity = { hidden: false, online: true };
	replaceGlobal(t, "document", {
		hidden: false,
		querySelector: (selector) => (selector === "[lp-search]" ? search : null),
	});
	replaceGlobal(t, "window", {});
	const { default: FormBuilder } = await loadBuilder({
		connectivity,
		generateElementId: (type) => `${type}-1`,
		ModelElement: {},
	});
	const builder = {
		_independentDocuments: new Set(),
		flushIndependentDocuments: FormBuilder.prototype.flushIndependentDocuments,
		header: { saveButton },
		hidden: false,
		offline: FormBuilder.prototype.offline,
		offlineIndicator: indicator,
		online: true,
	};
	connectivity.online = false;
	await FormBuilder.prototype.sync.call(builder, { hidden: true });
	assert.deepEqual([builder.online, builder.hidden], [false, true]);
	assert.deepEqual(
		[
			indicator.dataset.visible,
			search.dataset.visible,
			saveButton.dataset.visible,
			saveButton["aria-disabled"],
		],
		["true", "false", "true", "true"],
		"enters offline state",
	);
	connectivity.online = true;
	await FormBuilder.prototype.sync.call(builder, { hidden: false });
	assert.deepEqual([builder.online, builder.hidden], [true, false]);
	assert.deepEqual(
		[
			indicator.dataset.visible,
			search.dataset.visible,
			saveButton.dataset.visible,
			saveButton["aria-disabled"],
		],
		["false", "true", "true", "false"],
		"recovers online state",
	);
	assert.ok(
		!Object.hasOwn(window, "__LP_OFFLINE__"),
		"does not publish orphaned global state",
	);
});

class TestNode {
	constructor(tagName) {
		this.tagName = tagName.toUpperCase();
		this.children = [];
		this.dataset = {};
		this.className = "";
		this.classList = {
			add: (...classes) => {
				this.className = `${this.className} ${classes.join(" ")}`.trim();
			},
		};
	}
	appendChild(child) {
		this.children.push(child);
		return child;
	}
	append(...children) {
		this.children.push(...children);
	}
}

/** @matrix forms : action-button-centering builder-list-actions */
test("test_builder_schema_lists_use_button_surfaces_and_centered_actions", async (t) => {
	const styles = {
		builder: {
			settings: {
				item: "builder-setting-item",
				open: "builder-setting-open",
				section: "",
				title: "",
				toggle: { container: "action-icon-button size-5", icon: "icon-xs" },
			},
		},
	};
	replaceGlobal(t, "document", {
		createElement: (tagName) => new TestNode(tagName),
		getElementById: () => new TestNode("div"),
	});
	const primitives = {
		toggle({ styles: toggleStyles, data }) {
			const button = new TestNode("button");
			button.className = toggleStyles.container;
			Object.assign(button.dataset, data);
			return button;
		},
		label({ tag = "label", role = "label", styles: labelStyles = {} }) {
			const outer = new TestNode(tag);
			outer.className = labelStyles.label || "";
			const inner = outer.appendChild(new TestNode("div"));
			inner.dataset.role = role;
			inner.className = labelStyles.container || "";
			return outer;
		},
	};
	const { ElementSettings } = await esmock.strict(
		"../../src/script/views/builder/panels/elementSettings.mjs",
		{
			"../../src/script/elements/primitives.mjs": { primitives },
			"../../src/script/generated/styles.mjs": { STYLES: styles },
			"../../src/script/shared/transitions.mjs": {
				withTransition: (callback) => callback(),
			},
			"../../src/script/views/builder/config.mjs": {
				CONFIG: {
					DEFAULT_SETTINGS: {
						conditional: ["visibility"],
						select: ["options"],
						table: ["columns"],
					},
					PRESENTATION_DEFAULTS: {},
				},
			},
		},
	);
	const settings = new ElementSettings({
		elements: new Map([["trigger", { schema: { title: "Approved" } }]]),
		savedField: () => null,
	});
	const conditionSection = settings.create({
		type: "conditional",
		visibility: [{ id: "trigger", checked: true }],
	})[0];
	const optionSection = settings.create({
		type: "select",
		options: [{ label: "First" }, { label: "Second" }],
	})[0];
	const columnSection = settings.create({
		type: "table",
		columns: [
			{ name: "Amount", input: "number" },
			{ name: "Notes", input: "text" },
		],
	})[0];
	const condition = conditionSection.children[1].children[0];
	const option = optionSection.children[1].children[0];
	const column = columnSection.children[1].children[0];
	for (const [name, row] of [
		["condition", condition],
		["option", option],
		["column", column],
	]) {
		const open = row.children[0];
		assert.equal(open.tagName, "BUTTON", `${name} editor uses button`);
		assert.equal(open.type, "button", `${name} editor cannot submit form`);
		assert.equal(
			open.className,
			styles.builder.settings.open,
			`${name} uses shared surface`,
		);
	}
	assert.equal(column.tagName, "LI", "table columns use semantic list items");
	const actions = [
		conditionSection.children[0].children[1],
		condition.children[1],
		...option.children[1].children,
		...column.children[1].children,
	];
	for (const action of actions) {
		assert.equal(
			action.type,
			"button",
			`${action.dataset.role} cannot submit form`,
		);
		const classes = action.className.split(/\s+/);
		assert.ok(
			classes.includes("action-icon-button"),
			`${action.dataset.role} has button geometry`,
		);
		assert.ok(
			classes.includes("size-5"),
			`${action.dataset.role} has centered size`,
		);
	}
});

/** @matrix forms : access-restrictions explicit-submit retryable-action single-flight */
test("test_restriction_save_submits_snapshot_and_releases_failed_submitter", async (t) => {
	const requests = [];
	let settle;
	class FormDataBoundary {
		constructor(form) {
			this.groups = [...form.groups];
		}
		*[Symbol.iterator]() {
			for (const group of this.groups) yield ["group-key", group];
		}
	}
	replaceGlobal(t, "FormData", FormDataBoundary);
	const { FormSettings } = await loadFormSettings({
		request: {
			put(route, data) {
				requests.push({ route, data });
				return new Promise((resolve) => {
					settle = resolve;
				});
			},
		},
	});
	const messages = [];
	const button = { disabled: false };
	const settings = {
		_destroyed: false,
		_restrictionPromise: null,
		restrictions: {
			dataset: { route: "/forms/example/restrictions" },
			groups: ["group-one"],
		},
		restrictionForm: {
			submitButton: button,
			submitting: () => messages.push("spinner"),
			success: () => messages.push("saved"),
			resetSubmitButton: () => messages.push("reset"),
			markUnsavedState: () => messages.push("unsaved"),
			showError: (error) => messages.push(error),
		},
	};
	const event = { preventDefault() {}, stopPropagation() {} };
	const save = () =>
		FormSettings.prototype._saveRestrictions.call(settings, event);
	const first = save();
	assert.equal(save(), first, "coalesces restriction saves");
	assert.equal(requests.length, 1);
	assert.equal(button.disabled, true);
	assert.equal(messages[0], "spinner");
	settings.restrictions.groups.push("group-two");
	assert.equal(requests[0].data.groups.length, 1, "submits captured snapshot");
	settle({ ok: false, error: "Queue unavailable" });
	await first;
	assert.equal(button.disabled, false);
	assert.equal(messages.at(-1), "Queue unavailable");
	const retry = save();
	assert.equal(requests.length, 2);
	assert.equal(
		requests[1].data.groups.length,
		2,
		"retry captures current groups",
	);
	settle({ ok: true });
	await retry;
	assert.equal(button.disabled, false);
	assert.equal(messages.at(-1), "saved");
	const pending = save();
	settings.restrictions.groups.push("group-three");
	settle({ ok: true });
	await pending;
	assert.equal(
		messages.at(-1),
		"unsaved",
		"does not mark changed snapshot saved",
	);
	assert.equal(button.disabled, false);
});
