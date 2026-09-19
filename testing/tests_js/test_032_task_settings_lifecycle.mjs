import assert from "node:assert/strict";
import { test } from "node:test";
import esmock from "esmock";
import { createBrowser } from "../utility/js/environment.mjs";

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

async function loadTaskSettings({ FormWidget, SectionToggle = {} }) {
	return await esmock.strict("../../src/script/widgets/taskSettings.mjs", {
		"../../src/script/elements/input.mjs": { InputElement: class {} },
		"../../src/script/elements/sectionToggle.mjs": { SectionToggle },
		"../../src/script/elements/textarea.mjs": { TextareaElement: class {} },
		"../../src/script/shared/transitions.mjs": {
			withTransition: (callback) => callback(),
		},
		"../../src/script/widgets/base/formWidget.mjs": { FormWidget },
	});
}

/** @matrix tasks : attach-form model-task-link retained-draft manual-form-choice */
test("test_model_task_selection_replaces_form_and_preserves_later_manual_choice", async () => {
	class FormWidget {
		constructor(attributes) {
			Object.assign(this, attributes);
		}
	}
	const { BaseTaskSettings } = await loadTaskSettings({ FormWidget });
	const widget = new BaseTaskSettings({
		component: { elt: { querySelector: () => null } },
	});
	const selected = new Set();
	const formControl = {
		details: {},
		readonly: false,
		get active() {
			return selected.size > 0;
		},
		clear() {
			selected.clear();
			this.details = {};
		},
		addOption(option) {
			selected.add(option.id);
			this.details = option;
		},
	};
	widget.buttons.selectForm = formControl;
	const choose = (name, option) =>
		widget._formUpdatedListener({
			detail: { name, options: option ? { [option.id]: option } : {} },
		});
	const first = { id: "first-form" };
	const second = { id: "second-form" };
	choose("project", { id: "first-model", kind: "model", form: first });
	assert.deepEqual([...selected], [first.id]);
	choose("project", { id: "second-model", kind: "model", form: second });
	assert.deepEqual([...selected], [second.id]);
	choose("project", { id: "second-model", kind: "model", form: second });
	assert.deepEqual([...selected], [second.id]);

	const manual = { id: "manual-form" };
	formControl.clear();
	formControl.addOption(manual);
	choose("form", manual);
	choose("project", { id: "plain-project", kind: "project" });
	choose("project", { id: "formless-model", kind: "model" });
	choose("project", null);
	choose("category", { id: "category", form: first });
	assert.deepEqual([...selected], [manual.id]);

	formControl.readonly = true;
	choose("project", { id: "first-model", kind: "model", form: first });
	assert.deepEqual([...selected], [manual.id]);
	delete widget.buttons.selectForm;
	choose("project", { id: "first-model", kind: "model", form: first });
});

/** @matrix tasks : active-widget complete uncomplete update-state */
test("test_closed_task_errors_persist_while_waiting_and_retrying", async (t) => {
	createBrowser(t);
	t.mock.timers.enable({ apis: ["setTimeout"], now: 0 });
	const { default: ViewComponent } = await esmock.strict(
		"../../src/script/views/base/component.mjs",
		{
			"../../src/script/elements/nav.mjs": { NavElement: class {} },
			"../../src/script/shared/errors.mjs": {
				captureError(error) {
					throw error;
				},
			},
			"../../src/script/shared/transitions.mjs": {
				withTransition: async (callback) => callback(),
			},
			"../../src/script/widgets/loader.mjs": {
				loadWidget: async () => null,
			},
		},
	);

	for (const cachedForm of [false, true]) {
		const row = document.createElement("li");
		row.id = "task";
		row.dataset.key = "task";
		row.dataset.open = "false";
		const error = document.createElement("div");
		error.dataset.role = "error";
		error.dataset.visible = "false";
		row.append(error);
		document.body.append(row);
		const component = new ViewComponent(row, {});
		component._nav = { show() {}, hide() {} };
		const widgetErrors = [];
		component.active = cachedForm
			? {
					showError: (message) => widgetErrors.push(message),
					enable() {},
				}
			: null;
		for (const message of [
			"Migration in progress",
			"Migration still in progress",
		]) {
			component.disable();
			component.showError(message);
			await Promise.resolve();
			assert.equal(error.dataset.visible, "true");
			assert.equal(error.textContent, message);
			t.mock.timers.tick(60_000);
			await Promise.resolve();
			assert.equal(error.dataset.visible, "true");
			assert.equal(error.textContent, message);
			assert.deepEqual(widgetErrors, []);
		}
		if (cachedForm) {
			row.dataset.open = "TaskForm";
			component.showError("Open form error");
			assert.deepEqual(widgetErrors, ["Open form error"]);
		}
	}
});

/** @matrix tasks : history-fill latest-submission incompatible-value stale-response */
test("test_task_history_fill_reports_incompatible_values_and_ignores_stale_responses", async () => {
	class FormWidget {
		constructor(attributes) {
			Object.assign(this, attributes);
		}
	}
	const pending = [];
	const request = {
		get: () => new Promise((resolve) => pending.push(resolve)),
	};
	const { TaskForm } = await esmock.strict(
		"../../src/script/widgets/taskForm.mjs",
		{
			"../../src/script/elements/sections.mjs": { sections: {} },
			"../../src/script/forms/controller.mjs": { FormController: class {} },
			"../../src/script/shared/index.mjs": {
				captureError() {
					throw new Error("unexpected request error");
				},
				request,
			},
			"../../src/script/widgets/base/formWidget.mjs": { FormWidget },
		},
	);
	const errors = [];
	const controls = [];
	const form = {
		renderer: {
			addHistoryFillButtons: (values) => controls.push(values),
		},
		showError(error) {
			errors.push(error);
		},
		hideError() {
			errors.length = 0;
		},
	};
	const widget = new TaskForm({
		target: { dataset: { history: "history" } },
		form,
		endpoints: { latestHistorySubmission: "/history" },
	});
	const unavailable = widget.loadHistoryFill();
	pending.shift()({ history_fields: ["note", "invalid"] });
	await unavailable;
	assert.equal(errors.length, 0);
	assert.equal(controls.length, 1);
	assert.equal(typeof controls[0].invalid, "function");
	const rejected = controls[0].invalid();
	pending.shift()({
		ok: false,
		status: 422,
		error: "This saved value cannot be converted.",
	});
	assert.equal(await rejected, null);
	assert.deepEqual(errors, ["This saved value cannot be converted."]);
	const converted = controls[0].note();
	pending.shift()({ ok: true, latest_submission: { note: "7" } });
	assert.equal(await converted, "7");
	assert.equal(errors.length, 0);

	widget._resetHistoryFillCache();
	const old = widget.loadHistoryFill();
	const oldResponse = pending.shift();
	widget._resetHistoryFillCache();
	const current = widget.loadHistoryFill();
	pending.shift()({ history_fields: ["current"] });
	await current;
	assert.equal(controls.length, 2);
	assert.equal(typeof controls[1].current, "function");
	oldResponse({ history_fields: ["stale"] });
	await old;
	assert.equal(controls.length, 2);

	widget._resetHistoryFillCache();
	const destroyed = widget.historyValue("note");
	widget.form = null;
	pending.shift()({ ok: false, status: 422, error: "Late failure" });
	await destroyed;
	assert.equal(errors.length, 0);
	assert.equal(controls.length, 2);
});

/** @matrix tasks : history-fill stale-response */
test("test_history_fill_waits_without_overwriting_new_input", async (t) => {
	const fakeDocument = {
		createElement: () => ({
			dataset: {},
			isConnected: true,
			appendChild(child) {
				return child;
			},
			addEventListener(_type, callback) {
				this.click = callback;
			},
		}),
	};
	replaceGlobal(t, "document", fakeDocument);
	const { BaseElement } = await esmock.strict(
		"../../src/script/elements/base/baseElement.mjs",
		{
			"../../src/script/generated/styles.mjs": {
				STYLES: { form: { icon: "icon" } },
			},
			"../../src/script/shared/icons.mjs": { setIcon() {} },
			"../../src/script/elements/primitives.mjs": { primitives: {} },
		},
	);
	const filled = [];
	const element = Object.assign(Object.create(BaseElement.prototype), {
		renderer: { historyFillEnabled: true },
		schema: { id: "quantity", type: "input" },
		readonly: false,
		static: false,
		submission: null,
		value: "",
		fillFromHistory(value) {
			if (value != null) filled.push(value);
		},
	});
	let release;
	const button = element.historyFillButton(
		() =>
			new Promise((resolve) => {
				release = resolve;
			}),
	);
	const event = { preventDefault() {}, stopPropagation() {} };
	const first = button.click(event);
	assert.equal(button.disabled, true);
	element.value = "Typed while waiting";
	release("Historical value");
	await first;
	assert.deepEqual(filled, []);
	assert.equal(button.disabled, false);
	element.value = "";
	const second = button.click(event);
	release("7");
	await second;
	assert.deepEqual(filled, ["7"]);
	const detached = button.click(event);
	button.isConnected = false;
	release("Old form response");
	await detached;
	assert.deepEqual(filled, ["7"]);
});

/** @matrix tasks : active-widget complete history-refresh uncomplete */
test("test_task_completion_replaces_closed_row_in_one_transition", async () => {
	const transitions = [];
	let committing = false;
	let beforeCommit;
	const withTransition = async (commit, options) => {
		transitions.push(options.label);
		await beforeCommit();
		committing = true;
		try {
			commit();
		} finally {
			committing = false;
		}
	};
	const { default: ViewComponent } = await esmock.strict(
		"../../src/script/views/base/component.mjs",
		{
			"../../src/script/elements/nav.mjs": { NavElement: class {} },
			"../../src/script/shared/errors.mjs": {
				captureError(error) {
					throw error;
				},
			},
			"../../src/script/shared/transitions.mjs": { withTransition },
			"../../src/script/widgets/loader.mjs": {
				loadWidget: async () => null,
			},
		},
	);
	const { Task } = await esmock.strict("../../src/script/views/base/task.mjs", {
		"../../src/script/shared/transitions.mjs": { withTransition },
		"../../src/script/views/base/component.mjs": { default: ViewComponent },
	});
	const { PageTaskList } = await esmock.strict(
		"../../src/script/widgets/pageTaskList.mjs",
		{
			"../../src/script/elements/base/baseList.mjs": { BaseList: class {} },
			"../../src/script/shared/transitions.mjs": { withTransition },
		},
	);

	async function updateTask({
		completed,
		nextCompleted,
		cancel = false,
		active = "TaskHistory",
	}) {
		transitions.length = 0;
		const renders = [];
		const destroyed = [];
		const flashes = [];
		const lists = [[], []];
		const row = (rowCompleted, connected) => ({
			id: "task-row",
			dataset: {
				key: "task-key",
				completed: String(rowCompleted),
				open: connected ? active : "false",
			},
			isConnected: connected,
			closest() {
				return this;
			},
			append(...items) {
				assert.equal(items.length, 0);
			},
		});
		const currentRow = row(completed, true);
		const nextRow = row(nextCompleted, false);
		lists[Number(completed)].push(currentRow);
		const view = {
			components: {},
			addFlash(element) {
				flashes.push(element);
			},
		};
		const list = Object.create(PageTaskList.prototype);
		list.view = view;
		list.target = { querySelectorAll: () => lists.flat() };
		Object.defineProperties(
			list,
			Object.fromEntries(
				["activeTasks", "completedTasks"].map((name, index) => [
					name,
					{
						value: {
							contains: (element) => lists[index].includes(element),
							prepend(element) {
								assert.equal(committing, true);
								assert.equal(element.dataset.open, "false");
								for (const rows of lists) {
									const itemIndex = rows.indexOf(element);
									if (itemIndex !== -1) rows.splice(itemIndex, 1);
								}
								lists[index].unshift(element);
							},
						},
					},
				]),
			),
		);
		const current = new Task(currentRow, view);
		current.widgets.TaskHistory = {
			name: "TaskHistory",
			destroy() {
				destroyed.push("history");
			},
		};
		current.widgets.TaskForm = {
			name: "TaskForm",
			destroy() {
				destroyed.push("form");
			},
		};
		current.active = current.widgets[active] || null;
		current._replaceNav = () => {};
		current._removeMissingWidgets = () => {};
		current.prepareRender = async () => {
			assert.equal(currentRow.dataset.open, active);
		};
		current.render = () => {
			assert.equal(committing, true);
			renders.push(active);
		};
		view.components[current.name] = current;
		let replacement;
		view.getComponent = (element) => {
			assert.equal(committing, true);
			assert.equal(element, nextRow);
			replacement = new Task(element, view);
			view.components[replacement.name] = replacement;
			replacement.activate = () => {
				throw new Error("Completion must not activate or fetch a widget");
			};
			replacement.render = (visible) => {
				assert.equal(committing, true);
				assert.equal(visible, false);
				assert.equal(replacement.active, null);
				assert.equal(nextRow.isConnected, true);
				assert.equal(currentRow.isConnected, false);
				assert.equal(view.components[current.name], replacement);
				assert.equal(Object.keys(replacement.widgets).length, 0);
				list._moveTaskIfNecessary(element);
				renders.push("closed");
			};
			return replacement;
		};
		currentRow.replaceWith = (element) => {
			assert.equal(committing, true);
			assert.equal(element, nextRow);
			assert.equal(currentRow.dataset.completed, String(completed));
			assert.equal(currentRow.dataset.open, active);
			const rows = lists[Number(completed)];
			rows[rows.indexOf(currentRow)] = nextRow;
			currentRow.isConnected = false;
			nextRow.isConnected = true;
		};
		beforeCommit = async () => {
			assert.equal(currentRow.isConnected, true);
			assert.equal(currentRow.dataset.completed, String(completed));
			assert.equal(currentRow.dataset.open, active);
			assert.equal(view.components[current.name], current);
			assert.equal(replacement, undefined);
			if (cancel) current.destroy();
		};
		await current.updated({
			html: { querySelector: () => nextRow, querySelectorAll: () => [] },
		});
		if (completed === nextCompleted) {
			assert.equal(replacement, undefined);
			assert.deepEqual(renders, [active]);
			assert.deepEqual(destroyed, []);
		} else if (cancel) {
			assert.equal(replacement, undefined);
			assert.equal(nextRow.isConnected, false);
			assert.deepEqual(renders, []);
		} else {
			assert.deepEqual(renders, ["closed"]);
			assert.deepEqual(destroyed, ["history", "form"]);
			assert.equal(lists[Number(nextCompleted)][0], nextRow);
			assert.equal(lists[Number(completed)].length, 0);
			assert.deepEqual(flashes, []);
		}
		assert.equal(transitions.length, 1);
	}

	for (const active of ["TaskHistory", "TaskForm", "false"]) {
		await updateTask({ completed: false, nextCompleted: true, active });
		await updateTask({ completed: true, nextCompleted: false, active });
	}
	await updateTask({
		completed: false,
		nextCompleted: false,
		active: "TaskForm",
	});
	await updateTask({ completed: true, nextCompleted: true });
	await updateTask({ completed: true, nextCompleted: false, cancel: true });
});

/** @matrix tasks : action-control-lifecycle teardown */
test("test_task_settings_awaits_action_controls_and_cleans_up", async () => {
	const events = [];
	let resolveUpload;
	const uploadReady = new Promise((resolve) => {
		resolveUpload = resolve;
	});
	class FormWidget {
		constructor(attributes) {
			Object.assign(this, attributes);
			this.destroyables = [];
		}

		async _initForm() {
			events.push("form:init");
		}

		destroy() {
			events.push("form:destroy");
			for (const destroyable of this.destroyables) destroyable.destroy?.();
			this.destroyables = [];
		}
	}
	const controls = {};
	const createControl = (kind) => {
		const control = {
			kind,
			async init() {
				events.push(`${kind}:init`);
				if (kind === "upload") await uploadReady;
				events.push(`${kind}:ready`);
			},
			destroy() {
				events.push(`${kind}:destroy`);
			},
		};
		controls[kind] = control;
		return control;
	};
	const SectionToggle = {
		facet: () => createControl("facet"),
		date: () => createControl("date"),
		upload: () => createControl("upload"),
	};
	let updatedListener = null;
	const actionButtons = {
		querySelectorAll(selector) {
			assert.equal(selector, "button[data-action]");
			return [
				{ dataset: { action: "uploadFile" } },
				{ dataset: { action: "selectProject" } },
			];
		},
		addEventListener(name, listener) {
			events.push(`listener:add:${name}`);
			updatedListener = listener;
		},
		removeEventListener(name, listener) {
			if (name === "updated" && listener === updatedListener) {
				events.push(`listener:remove:${name}`);
				updatedListener = null;
			}
		},
	};
	const target = {
		querySelector(selector) {
			return selector === "[data-role='action-buttons']" ? actionButtons : null;
		},
	};
	const { BaseTaskSettings } = await loadTaskSettings({
		FormWidget,
		SectionToggle,
	});
	const widget = new BaseTaskSettings({ target });
	assert.equal(widget.actions, actionButtons);
	assert.equal(events.length, 0);

	let settled = false;
	const initializing = widget._initForm().then(() => {
		settled = true;
	});
	await new Promise((resolve) => setImmediate(resolve));
	assert.equal(settled, false);
	assert.deepEqual(events, ["form:init", "upload:init"]);
	assert.equal(updatedListener, null);
	assert.equal(Object.keys(widget.buttons).length, 0);
	assert.equal(widget.destroyables.length, 0);

	resolveUpload();
	await initializing;
	assert.deepEqual(events, [
		"form:init",
		"upload:init",
		"upload:ready",
		"facet:init",
		"facet:ready",
		"listener:add:updated",
	]);
	assert.equal(widget.buttons.uploadFile, controls.upload);
	assert.equal(widget.buttons.selectProject, controls.facet);
	assert.equal(widget.destroyables.length, 2);
	assert.ok(updatedListener);

	widget.destroy();
	assert.deepEqual(events.slice(-4), [
		"listener:remove:updated",
		"form:destroy",
		"upload:destroy",
		"facet:destroy",
	]);
	assert.equal(Object.keys(widget.buttons).length, 0);
	assert.equal(widget.destroyables.length, 0);
	assert.equal(updatedListener, null);
});

/** @matrix forms : schema-ownership sibling-widgets */
test("test_form_response_metadata_stays_with_renderer_widget", async () => {
	class FormController {}
	const { FormWidget } = await esmock.strict(
		"../../src/script/widgets/base/formWidget.mjs",
		{
			"../../src/script/forms/controller.mjs": { FormController },
			"../../src/script/forms/migrationNotice.mjs": {
				installMigrationNotice: () => null,
			},
			"../../src/script/forms/representation.mjs": {
				compatibleField: () => true,
			},
			"../../src/script/shared/transitions.mjs": {
				withTransition: (callback) => callback(),
			},
		},
	);
	const target = ({ renderer = false } = {}) => ({
		dataset: {},
		cloneNode() {
			return target({ renderer });
		},
		hasAttribute(name) {
			return renderer && ["data-schema", "data-submission"].includes(name);
		},
	});
	const responseState = {
		schema: [{ id: "task-form-field" }],
		submission: { "task-form-field": "saved value" },
		generation: 3,
		migration_notice: [],
	};
	const settingsReplacement = target();
	const settings = new FormWidget({ name: "TaskSettings", target: target() });
	settings.updated({
		...responseState,
		html: {
			querySelector(selector) {
				assert.equal(selector, "[data-widget='TaskSettings']");
				return settingsReplacement;
			},
		},
	});
	assert.equal(settings.schema, null);
	assert.equal(settings.submission, null);
	assert.equal(settings.initialTarget, settingsReplacement);
	assert.equal(settings._updated, true);

	const renderer = new FormWidget({
		name: "TaskForm",
		target: target({ renderer: true }),
	});
	renderer.updated({
		...responseState,
		html: { querySelector: () => target({ renderer: true }) },
	});
	assert.equal(renderer.schema, responseState.schema);
	assert.equal(renderer.submission, responseState.submission);
	assert.equal(renderer.initialTarget.dataset.formGeneration, "3");
	assert.equal(renderer.initialTarget.dataset.migrationNotice, "[]");
	assert.equal(settingsReplacement.dataset.formGeneration, undefined);
	assert.equal(settingsReplacement.dataset.migrationNotice, undefined);

	const revision = new FormWidget({
		name: "TaskForm",
		target: target({ renderer: true }),
	});
	revision.updated(responseState);
	assert.equal(revision.schema, responseState.schema);
	assert.equal(revision.submission, responseState.submission);
});
