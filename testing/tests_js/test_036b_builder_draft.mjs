import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { test } from "node:test";
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

/**
 * @source src/script/views/builder/draft.mjs::BuilderDraft
 * @matrix forms : draft-history
 */
test("test_conversion_instructions_follow_draft_undo_redo_and_publication", () => {
	const initial = {
		name: "Conversion",
		form_type: "task",
		schema: [{ id: "notes", type: "textarea", title: "Notes" }],
		html_fields: {},
	};
	const draft = new BuilderDraft(initial, "before");
	draft.record({
		...initial,
		schema: [{ ...initial.schema[0], type: "todo" }],
		conversion_instructions: { notes: "Keep order" },
	});
	assert.equal(draft.dirty, true);
	draft.undo();
	assert.equal(draft.state.schema[0].type, "textarea");
	assert.equal(draft.state.conversion_instructions, undefined);
	assert.equal(draft.dirty, false);
	draft.redo();
	assert.equal(draft.state.conversion_instructions.notes, "Keep order");
	const submitted = structuredClone(draft.state);
	const published = structuredClone(submitted);
	delete published.conversion_instructions;
	draft.acknowledge(submitted, { draft: published, baseline: "published" });
	assert.equal(draft.state.conversion_instructions, undefined);
	assert.equal(draft.state.schema[0].type, "todo");
	assert.equal(draft.dirty, false);
});

/** @matrix forms : draft-history stable-identity schema-generation */
test("test_builder_draft_history_and_generation", () => {
	const initial = {
		name: "Draft",
		form_type: "task",
		selected_id: "choice",
		schema: [
			{
				id: "choice",
				type: "select",
				multiple: true,
				options: [{ value: "fixed", label: "Old" }],
			},
			{
				id: "table",
				type: "table",
				columns: [
					{ id: "column-original", type: "input", title: "Old column" },
				],
			},
			{ id: "html", type: "html", title: "Instructions" },
		],
		html_fields: { html: "<p>Original</p>" },
	};
	const draft = new BuilderDraft(initial, "baseline-1");
	assert.equal(draft.dirty, false);
	assert.equal(draft.record(structuredClone(initial)), false);
	assert.equal(
		draft.record({
			html_fields: initial.html_fields,
			schema: initial.schema,
			form_type: initial.form_type,
			name: initial.name,
			selected_id: initial.selected_id,
		}),
		false,
	);
	assert.equal(draft.revision, 0);
	draft.applyGeneration({
		operations: [
			{
				op: "update_option",
				field_id: "choice",
				value: "fixed",
				label: "New",
			},
			{
				op: "update_column",
				field_id: "table",
				column_id: "column-original",
				title: "New column",
			},
			{
				op: "add_field",
				field: { id: "added", type: "input", title: "Added" },
			},
		],
		html_fields: { html: "<p>Generated</p>" },
	});
	assert.equal(draft.past.length, 1);
	assert.equal(draft.state.schema[0].options[0].value, "fixed");
	assert.equal(draft.state.schema[0].multiple, true);
	assert.equal(draft.state.schema[1].columns[0].id, "column-original");
	assert.equal(initial.schema[0].options[0].label, "Old");
	const generated = structuredClone(draft.state);
	const typed = structuredClone(generated);
	typed.schema[0].title = "Manual";
	draft.record(typed, "title:choice");
	typed.schema[0].title = "Manual edit";
	draft.record(typed, "title:choice");
	assert.equal(draft.past.length, 2);
	draft.undo();
	assert.deepEqual(draft.state, generated);
	draft.undo();
	assert.deepEqual(draft.state, {
		...initial,
		html_fields: generated.html_fields,
	});
	assert.equal(
		draft.dirty,
		true,
		"schema Undo retains generated document content",
	);
	draft.redo();
	assert.deepEqual(draft.state, generated);
	const beforeInvalid = structuredClone(draft.state);
	assert.throws(() =>
		draft.applyGeneration({
			operations: [
				{
					op: "update_field",
					field_id: "choice",
					changes: { title: "Would apply" },
				},
				{
					op: "update_field",
					field_id: "choice",
					changes: { type: "textarea" },
				},
			],
		}),
	);
	assert.deepEqual(draft.state, beforeInvalid);
	assert.throws(() =>
		draft.applyGeneration({
			operations: [{ op: "add_field", field: { id: "choice", type: "input" } }],
		}),
	);
	assert.equal(draft.applyGeneration({ operations: [] }), false);
	const imageDraft = structuredClone(draft.state);
	imageDraft.html_fields.html = '<p><img src="draft-image:local-1"></p>';
	draft.record(imageDraft);
	const submitted = structuredClone(draft.state);
	const later = structuredClone(submitted);
	later.name = "Edited during Save";
	draft.record(later);
	const persisted = structuredClone(draft.content(submitted));
	persisted.html_fields.html = '<p><img src="/assets/saved.png"></p>';
	persisted.schema[3].input = "text";
	draft.acknowledge(submitted, {
		draft: persisted,
		baseline: "baseline-2",
		image_urls: { "local-1": "/assets/saved.png" },
	});
	assert.equal(draft.state.name, "Edited during Save");
	assert.equal(draft.dirty, true);
	assert.equal(draft.baseline, "baseline-2");
	assert.equal(draft.state.html_fields.html, persisted.html_fields.html);
	draft.undo();
	assert.equal(draft.dirty, false);
	draft.undo();
	assert.equal(draft.dirty, true);
	draft.record({ ...draft.state, name: "New direction" });
	assert.equal(draft.future.length, 0);
	for (let i = 0; i < 120; i += 1) {
		draft.record({ ...draft.state, name: `Name ${i}` });
	}
	assert.equal(draft.past.length, 100);
	const selectionDraft = new BuilderDraft(initial, "source");
	const beforeSelection = structuredClone(selectionDraft.state);
	selectionDraft.state.selected_id = "table";
	selectionDraft.acknowledge(beforeSelection, {
		draft: selectionDraft.content(initial),
		baseline: "accepted",
	});
	assert.equal(selectionDraft.state.selected_id, "table");
});

/**
 * @source src/script/views/builder/draft.mjs::BuilderDraft
 * @matrix forms : draft-history schema-generation
 */
test("test_document_edits_and_html_generation_preserve_schema_redo", () => {
	const initial = {
		name: "Original",
		form_type: "task",
		schema: [
			{ id: "choice", type: "checkbox", title: "Choice" },
			{ id: "html", type: "html", title: "Instructions" },
		],
		html_fields: { html: "<p>Saved</p>" },
	};
	const draft = new BuilderDraft(initial, "baseline");
	draft.record({ ...draft.state, name: "Renamed" }, "name");
	assert.equal(draft.group, "name");
	draft.updateHtml("html", "<p>Typing while renaming</p>");
	assert.equal(
		draft.group,
		"name",
		"document content does not break typing groups",
	);
	assert.equal(draft.past.length, 1);
	draft.undo();
	const revision = draft.revision;
	const state = draft.state;
	const schema = state.schema;
	const past = draft.past;
	const future = draft.future;
	assert.equal(draft.updateHtml("html", "<p>Manual document edit</p>"), true);
	assert.equal(draft.revision, revision + 1);
	assert.equal(draft.state, state);
	assert.equal(
		draft.state.schema,
		schema,
		"document update does not copy schema",
	);
	assert.equal(draft.past, past);
	assert.equal(draft.future, future);
	assert.equal(draft.future.length, 1);
	assert.equal(draft.dirty, true);
	assert.equal(draft.updateHtml("html", "<p>Manual document edit</p>"), false);
	assert.equal(draft.revision, revision + 1);
	assert.equal(
		draft.applyGeneration({
			operations: [],
			html_fields: { html: "<p>AI text only</p>" },
		}),
		true,
	);
	assert.equal(draft.past.length, 0);
	assert.equal(
		draft.future.length,
		1,
		"HTML-only generation retains schema Redo",
	);
	assert.equal(draft.undo(), false, "Form Undo does not undo document content");
	assert.equal(draft.state.html_fields.html, "<p>AI text only</p>");
	assert.equal(draft.redo(), true);
	assert.equal(draft.state.name, "Renamed");
	assert.equal(draft.state.html_fields.html, "<p>AI text only</p>");
	draft.applyGeneration({
		operations: [
			{
				op: "update_field",
				field_id: "choice",
				changes: { title: "Generated choice" },
			},
		],
		html_fields: { html: "<p>Mixed generation text</p>" },
	});
	assert.equal(draft.past.length, 2);
	draft.undo();
	assert.equal(draft.state.schema[0].title, "Choice");
	assert.equal(draft.state.html_fields.html, "<p>Mixed generation text</p>");
	draft.redo();
	assert.equal(draft.state.schema[0].title, "Generated choice");
	assert.equal(draft.state.html_fields.html, "<p>Mixed generation text</p>");
	const lastRevision = draft.revision;
	assert.equal(
		draft.applyGeneration({
			operations: [],
			html_fields: { html: "<p>Mixed generation text</p>" },
		}),
		false,
	);
	assert.equal(draft.revision, lastRevision);
});

/**
 * @source src/script/views/builder/draft.mjs::BuilderDraft
 * @matrix forms : draft-history stable-identity
 */
test("test_schema_undo_redo_restores_document_content_only_when_field_returns", () => {
	const draft = new BuilderDraft(
		{
			name: "Form",
			form_type: "task",
			schema: [{ id: "existing", type: "html", title: "Existing" }],
			html_fields: { existing: "<p>Existing content</p>" },
		},
		"baseline",
	);
	draft.applyGeneration({
		operations: [
			{
				op: "add_field",
				field: { id: "added", type: "html", title: "Added" },
			},
		],
		html_fields: { added: "<p>Generated new document</p>" },
	});
	const image = '<p><img src="draft-image:unsaved-image"></p>';
	draft.updateHtml("added", image);
	draft.undo();
	assert.deepEqual(
		draft.state.schema.map((field) => field.id),
		["existing"],
	);
	assert.equal(Object.hasOwn(draft.state.html_fields, "added"), false);
	draft.updateHtml("existing", "<p>Edited while the new field is absent</p>");
	draft.redo();
	assert.deepEqual(
		draft.state.schema.map((field) => field.id),
		["existing", "added"],
	);
	assert.equal(draft.state.html_fields.added, image);
	assert.equal(
		draft.state.html_fields.existing,
		"<p>Edited while the new field is absent</p>",
	);
	const removed = structuredClone(draft.state);
	removed.schema = removed.schema.filter((field) => field.id !== "added");
	delete removed.html_fields.added;
	draft.record(removed);
	draft.updateHtml("existing", "");
	draft.undo();
	assert.equal(draft.state.html_fields.existing, "");
	assert.equal(draft.state.html_fields.added, image);
	draft.updateHtml("added", `${image}<p>Later edit</p>`);
	draft.redo();
	assert.deepEqual(
		draft.state.schema.map((field) => field.id),
		["existing"],
	);
	draft.undo();
	assert.equal(draft.state.html_fields.added, `${image}<p>Later edit</p>`);
	assert.equal(draft.state.html_fields.existing, "");
});

/**
 * @source src/script/views/builder/draft.mjs::BuilderDraft
 * @matrix forms : draft-history stale-acknowledgement
 */
test("test_document_edit_during_save_stays_dirty_across_schema_undo_redo", () => {
	const draft = new BuilderDraft(
		{
			name: "Original",
			form_type: "task",
			schema: [{ id: "html", type: "html" }],
			html_fields: { html: "<p>Saved text</p>" },
		},
		"baseline",
	);
	draft.record({ ...draft.state, name: "Accepted name" });
	draft.updateHtml("html", '<p><img src="draft-image:image-1"></p>');
	const submitted = structuredClone(draft.state);
	draft.updateHtml(
		"html",
		`${submitted.html_fields.html}<p>Typed during Save</p>`,
	);
	const accepted = structuredClone(draft.content(submitted));
	accepted.html_fields.html = '<p><img src="/assets/image-1.png"></p>';
	assert.equal(
		draft.acknowledge(submitted, {
			draft: accepted,
			baseline: "saved-2",
			image_urls: { "image-1": "/assets/image-1.png" },
		}),
		false,
	);
	const latestHtml = `${accepted.html_fields.html}<p>Typed during Save</p>`;
	assert.equal(draft.state.html_fields.html, latestHtml);
	assert.equal(draft.saved.html_fields.html, accepted.html_fields.html);
	assert.equal(draft.past.length, 1);
	assert.equal(draft.dirty, true);
	draft.undo();
	assert.equal(draft.state.name, "Original");
	assert.equal(draft.state.html_fields.html, latestHtml);
	draft.redo();
	assert.equal(draft.state.name, "Accepted name");
	assert.equal(draft.state.html_fields.html, latestHtml);
	assert.equal(draft.dirty, true);
	const final = structuredClone(draft.state);
	assert.equal(
		draft.acknowledge(final, {
			draft: draft.content(final),
			baseline: "saved-3",
		}),
		true,
	);
	assert.equal(draft.dirty, false);
	draft.undo();
	assert.equal(draft.dirty, true);
	assert.equal(draft.state.html_fields.html, latestHtml);
	draft.redo();
	assert.equal(draft.dirty, false);
	assert.equal(draft.state.html_fields.html, latestHtml);
});

/**
 * @source src/script/views/builder/conditions/options.mjs::Options
 * @source src/script/views/builder/conditions/columns.mjs::Columns
 * @matrix forms : stable-identity
 */
test("test_builder_option_and_column_labels_keep_ids", async () => {
	let nextId = 0;
	class Condition {}
	const boundaries = {
		"../../src/script/elements/primitives.mjs": { primitives: {} },
		"../../src/script/shared/utilities.mjs": {
			generateElementId: (prefix) => `${prefix}-${++nextId}`,
		},
		"../../src/script/views/builder/conditions/base.mjs": { Condition },
	};
	const { default: Options } = await esmock.strict(
		"../../src/script/views/builder/conditions/options.mjs",
		boundaries,
	);
	const { default: Columns } = await esmock.strict(
		"../../src/script/views/builder/conditions/columns.mjs",
		{
			...boundaries,
			"../../src/script/elements/combobox/index.mjs": { SelectBox: class {} },
			"../../src/script/views/builder/config.mjs": { CONFIG: {} },
			"../../src/script/views/builder/migrations.mjs": {
				fieldKind: () => null,
			},
		},
	);
	const options = {
		setting: { label: "Relabelled", value: "original" },
		element: { schema: { options: [] } },
	};
	assert.equal(Options.prototype.validate.call(options), true);
	assert.equal(options.setting.value, "original");
	options.element.schema.options = [{ label: "Same", value: "option-1" }];
	options.setting = { label: "Same" };
	Options.prototype.validate.call(options);
	assert.equal(options.setting.value, "option-2");
	const columns = {
		setting: {
			title: "Relabelled",
			id: "column-original",
			type: "input",
		},
		element: { schema: { columns: [] } },
	};
	assert.equal(Columns.prototype.validate.call(columns), true);
	assert.equal(columns.setting.id, "column-original");
	const firstOption = {
		setting: { label: "First option" },
		element: { schema: {} },
	};
	assert.equal(Options.prototype.validate.call(firstOption), true);
	assert.match(firstOption.setting.value, /^option-/);
	assert.deepEqual(firstOption.element.schema, {});
	const firstColumn = {
		setting: { title: "First column", type: "input" },
		element: { schema: {} },
	};
	assert.equal(Columns.prototype.validate.call(firstColumn), true);
	assert.match(firstColumn.setting.id, /^column-/);
	assert.deepEqual(firstColumn.element.schema, {});
});

async function loadFormSettings({ request, FormController = class {} }) {
	return await esmock.strict(
		"../../src/script/views/builder/panels/formSettings.mjs",
		{
			"../../src/script/forms/controller.mjs": { FormController },
			"../../src/script/shared/index.mjs": {
				captureError() {},
				ENDPOINTS: { createSchema: "/generate" },
				request,
			},
		},
	);
}

/**
 * @source src/script/views/builder/panels/formSettings.mjs::FormSettings._generateSchema
 * @matrix forms : schema-generation draft-history
 */
test("test_builder_generation_rejects_stale_cancelled_and_destroyed_responses", async (t) => {
	const requests = [];
	class FormDataBoundary extends Map {
		constructor() {
			super([["description", "Generate labels"]]);
		}
		append(key, value) {
			this.set(key, value);
		}
	}
	replaceGlobal(t, "FormData", FormDataBoundary);
	replaceGlobal(t, "crypto", webcrypto);
	const { FormSettings } = await loadFormSettings({
		request: {
			post(_route, data, options) {
				assert.equal(options.replaceErrorPage, false);
				return new Promise((resolve) => requests.push({ data, resolve }));
			},
		},
	});
	const { ConditionPanel } = await esmock.strict(
		"../../src/script/views/builder/panels/condition.mjs",
		{
			"../../src/script/shared/transitions.mjs": {
				withTransition: (callback) => callback(),
			},
		},
	);
	let message;
	let restores = 0;
	const submitter = {
		dataset: {},
		disabled: false,
		setAttribute() {},
		removeAttribute() {},
	};
	const textarea = { value: "Keep the prompt" };
	const form = {
		target: {
			dataset: {},
			querySelector: () => textarea,
			removeEventListener() {},
		},
		submitButton: submitter,
		messages: { submit: "Generate" },
		showError(value) {
			message = value;
		},
		success() {},
		resetSubmitButton() {},
		setSubmitButton() {},
		destroy() {},
	};
	const builder = {
		draft: new BuilderDraft(
			{ name: "Original", form_type: "task", schema: [], html_fields: {} },
			"baseline",
		),
		updateSchema() {},
		captureDraft() {
			return structuredClone(this.draft.state);
		},
		restoreDraft() {
			restores += 1;
		},
		header: { message() {} },
	};
	const settings = {
		builder,
		generateForm: form,
		_updateSchema: FormSettings.prototype._updateSchema,
	};
	const generate = () =>
		FormSettings.prototype._generateSchema.call(settings, {
			submitter,
			preventDefault() {},
			stopPropagation() {},
		});
	const finish = () => {
		const { data, resolve } = requests.shift();
		resolve({
			ok: true,
			request_id: data.get("request_id"),
			draft_revision: Number(data.get("draft_revision")),
			operations: [
				{
					op: "add_field",
					field: { id: "generated", type: "input" },
				},
			],
			html_fields: {},
		});
	};
	const first = generate();
	assert.equal(generate(), first, "coalesces generation");
	builder.draft.record({ ...builder.draft.state, name: "Intervening edit" });
	finish();
	assert.equal(await first, false);
	assert.match(message, /Regenerate/);
	assert.equal(restores, 0);
	assert.equal(builder.draft.state.name, "Intervening edit");
	assert.equal(textarea.value, "Keep the prompt");
	const buffered = generate();
	ConditionPanel.prototype._draftInput.call({
		builder,
		condition: { key: "options" },
	});
	finish();
	assert.equal(await buffered, false);
	assert.match(message, /Regenerate/);
	assert.equal(restores, 0);
	const cancelled = generate();
	FormSettings.prototype._click.call(settings, {
		target: { closest: () => ({ dataset: { role: "cancel" } }) },
	});
	finish();
	assert.equal(await cancelled, false);
	assert.equal(restores, 0);
	const accepted = generate();
	finish();
	assert.equal(await accepted, true);
	assert.equal(restores, 1);
	assert.equal(builder.draft.state.schema[0].id, "generated");
	let finishEditor;
	builder.prepareGeneratedDocuments = () =>
		new Promise((resolve) => {
			finishEditor = resolve;
		});
	const loading = FormSettings.prototype._updateSchema.call(settings, {
		ok: true,
		operations: [],
		html_fields: { instructions: "Generated text" },
	});
	builder.draft.record({
		...builder.draft.state,
		name: "Changed during editor load",
	});
	finishEditor();
	assert.equal(await loading, false);
	assert.match(message, /Regenerate/);
	assert.equal(restores, 1);
	const late = generate();
	FormSettings.prototype.destroy.call(settings);
	finish();
	assert.equal(await late, false);
	assert.equal(restores, 1);
});

function emptyClass() {
	return class {};
}

async function loadBuilder({
	connectivity = { hidden: false, online: true },
} = {}) {
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
			generateElementId: (type) => `${type}-1`,
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
		"../../src/script/views/builder/draft.mjs": { BuilderDraft },
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
			ModelElement: {},
			ModelPanel: emptyClass(),
		},
	});
}

/**
 * @source src/script/views/builder/builder.mjs::FormBuilder.deselectElement
 * @source src/script/views/builder/panels/model.mjs::ModelPanel.deselectItem
 * @matrix forms : builder-lifecycle draft-history
 */
test("test_builder_deselection_clears_selection_without_editing_form", async (t) => {
	replaceGlobal(t, "document", { getElementById: () => ({}) });
	const { default: FormBuilder } = await loadBuilder();
	const { ModelPanel } = await esmock.strict(
		"../../src/script/views/builder/panels/model.mjs",
		{
			sortablejs: { default: { create: () => ({}) } },
			"../../src/script/elements/primitives.mjs": { primitives: {} },
			"../../src/script/generated/styles.mjs": { STYLES: {} },
			"../../src/script/views/builder/config.mjs": { CONFIG: {} },
		},
	);
	const state = {
		name: "Saved form",
		form_type: "task",
		selected_id: null,
		schema: [{ id: "notes", type: "input", title: "Notes" }],
		html_fields: {},
	};
	let settingsHidden = 0;
	const builder = {
		selectedElement: null,
		draft: new BuilderDraft(state, "source"),
		settings: {
			deselectItem() {
				settingsHidden += 1;
			},
		},
	};
	builder.model = {
		deselectItem() {
			ModelPanel.prototype.deselectItem.call({ builder });
		},
	};
	const deselect = () => FormBuilder.prototype.deselectElement.call(builder);
	deselect();
	assert.equal(settingsHidden, 1);
	const item = { dataset: { selected: "true" } };
	builder.selectedElement = { item, schema: state.schema[0] };
	builder.draft.state.selected_id = "notes";
	deselect();
	assert.equal(item.dataset.selected, "false");
	assert.equal(builder.selectedElement, null);
	assert.equal(builder.draft.state.selected_id, null);
	deselect();
	assert.equal(settingsHidden, 3);
	assert.deepEqual(builder.draft.state, state);
	assert.equal(builder.draft.dirty, false);
	assert.equal(builder.draft.revision, 0);
	assert.equal(builder.draft.past.length, 0);
	assert.equal(builder.draft.future.length, 0);
});

/** @matrix forms : draft-history stale-acknowledgement focus-recovery */
test("test_builder_save_restores_unsubmitted_condition_buffer", async (t) => {
	let focused = false;
	const active = { name: "option-name", selectionStart: 4, selectionEnd: 8 };
	const restoredInput = {
		name: "option-name",
		focus() {
			focused = true;
		},
		setSelectionRange(start, end) {
			assert.deepEqual([start, end], [4, 8]);
		},
	};
	replaceGlobal(t, "document", { activeElement: active });
	const { default: FormBuilder } = await loadBuilder();
	const { Condition } = await esmock.strict(
		"../../src/script/views/builder/conditions/base.mjs",
		{
			"../../src/script/elements/combobox/index.mjs": { SelectBox: class {} },
			"../../src/script/elements/primitives.mjs": { primitives: {} },
			"../../src/script/forms/controller.mjs": {
				FormController: class {
					constructor(owner) {
						this.owner = owner;
					}
					init() {}
				},
			},
			"../../src/script/generated/styles.mjs": { STYLES: {} },
			"../../src/script/shared/icons.mjs": { setIcon() {} },
			"../../src/script/shared/transitions.mjs": {
				withTransition: (callback) => callback(),
			},
		},
	);
	const field = {
		id: "choice",
		type: "select",
		options: [{ value: "fixed", label: "Saved" }],
	};
	const buffer = { value: "fixed", label: "Still typing" };
	const panel = {
		contains: () => true,
		querySelectorAll: () => [restoredInput],
	};
	let reopened;
	const builder = {
		elements: new Map([[field.id, { schema: field }]]),
		conditions: {
			panel,
			condition: {
				key: "options",
				index: 0,
				element: { schema: field },
				setting: buffer,
			},
			hide() {
				this.condition = null;
			},
		},
		settings: { panel: { contains: () => false }, deselectItem() {} },
		header: {
			closePreview() {},
			nameHidden: {},
			nameInput: {},
			nameDisplay: {},
		},
		model: {
			panel: { replaceChildren() {}, append() {} },
			defaultPanel: { replaceChildren() {} },
			show() {},
		},
		elt: { dataset: {} },
		draft: {
			state: {
				name: "Saved",
				schema: [field],
				html_fields: {},
				selected_id: field.id,
			},
		},
		pruneImages() {},
		refreshDraftControls() {},
		updateSchema() {},
		createElement(schema) {
			this.elements.set(schema.id, { schema });
			return {};
		},
		selectElement(id) {
			this.selectedElement = this.elements.get(id);
		},
		showCondition(key, index, setting) {
			reopened = { key, index, setting };
			const condition = {
				setting: { label: "Saved" },
				draftSetting: setting,
				destroy() {},
			};
			Condition.prototype.init.call(condition);
			assert.equal(condition.setting.label, "Still typing");
			assert.notEqual(condition.setting, setting);
			assert.equal(condition.draftSetting, undefined);
			return Promise.resolve();
		},
	};
	await FormBuilder.prototype.restoreDraft.call(builder, {
		preserveFocus: true,
	});
	assert.equal(reopened.key, "options");
	assert.equal(reopened.index, 0);
	assert.equal(reopened.setting.value, "fixed");
	assert.equal(reopened.setting.label, "Still typing");
	assert.equal(field.options[0].label, "Saved");
	assert.equal(focused, true);
});

/**
 * @source src/script/views/builder/draftDocument.mjs::DraftDocument.flush
 * @source src/script/views/builder/builder.mjs::FormBuilder.setHtml
 * @source src/script/elements/html.mjs::HtmlElement.create
 * @matrix forms : draft-history
 */
test("test_builder_html_flush_stays_local_and_empty_preview_does_not_fetch", async (t) => {
	replaceGlobal(t, "document", {
		createElement: () => ({ innerHTML: "", className: "" }),
	});
	class BaseElement {
		constructor(renderer, schema) {
			this.renderer = renderer;
			this.schema = schema;
		}
	}
	const { HtmlElement } = await esmock.strict(
		"../../src/script/elements/html.mjs",
		{
			"../../src/script/shared/index.mjs": {
				captureError() {},
				ENDPOINTS: {},
				request: {
					get() {
						throw new Error("draft preview fetched persisted content");
					},
				},
			},
			"../../src/script/elements/base/baseElement.mjs": { BaseElement },
		},
	);
	const element = new HtmlElement(
		{ form: { htmlFields: { html: "" } } },
		{ id: "html" },
	);
	assert.equal(element.create().innerHTML, "");
	const { IndependentDocument } = await esmock.strict(
		"../../src/script/elements/editor/independent.mjs",
		{
			"../../src/script/generated/styles.mjs": { STYLES: {} },
			"../../src/script/shared/errors.mjs": { captureError() {} },
			"../../src/script/shared/request.mjs": { request: {} },
			"../../src/script/elements/editor/editor.mjs": {
				independentEditor: () => null,
			},
			"../../src/script/elements/editor/toolbar.mjs": { Toolbar: class {} },
		},
	);
	const { DraftDocument } = await esmock.strict(
		"../../src/script/views/builder/draftDocument.mjs",
		{
			"../../src/script/elements/editor/independent.mjs": {
				IndependentDocument,
			},
		},
	);
	const { default: FormBuilder } = await loadBuilder();
	const initial = {
		name: "Form",
		schema: [{ id: "html", type: "html" }],
		form_type: "task",
		html_fields: { html: "<p>Local</p>" },
	};
	const draft = new BuilderDraft(initial, "saved");
	const schema = draft.state.schema;
	let refreshed = 0;
	const builder = {
		draft,
		htmlFields: { ...initial.html_fields },
		images: new Map([["local-1", { url: "blob:local-1" }]]),
		canonicalHtml: FormBuilder.prototype.canonicalHtml,
		setHtml: FormBuilder.prototype.setHtml,
		refreshDraftControls() {
			refreshed += 1;
		},
		captureDraft() {
			throw new Error("editor flush captured a full draft");
		},
		updateSchema() {
			throw new Error("editor flush rebuilt the schema");
		},
	};
	draft.record = () => {
		throw new Error("editor flush entered Form history");
	};
	const doc = new DraftDocument({
		container: { hasAttribute: () => true },
		editor: { getHTML: () => "<p></p>" },
		fieldId: "html",
		builder,
	});
	await doc.flush();
	assert.equal(draft.state.html_fields.html, "");
	assert.equal(builder.htmlFields.html, "");
	assert.equal(draft.dirty, true);
	assert.equal(draft.past.length, 0);
	assert.equal(draft.state.schema, schema);
	assert.equal(refreshed, 1);
	const revision = draft.revision;
	doc.editor.getHTML = () => "<p><br></p>";
	await doc.flush();
	assert.equal(draft.revision, revision);
	assert.equal(draft.undo(), false);
	assert.equal(draft.state.html_fields.html, "");
	doc.editor.getHTML = () => '<p><img src="blob:local-1"></p>';
	await doc.flush();
	assert.equal(
		draft.state.html_fields.html,
		'<p><img src="draft-image:local-1"></p>',
	);
	assert.equal(builder.htmlFields.html, draft.state.html_fields.html);
	assert.equal(draft.past.length, 0);
	const empty = new BuilderDraft(
		{ ...initial, html_fields: { html: "" } },
		"empty",
	);
	builder.draft = empty;
	builder.htmlFields = { html: "" };
	doc.editor.getHTML = () => "<p><br></p>";
	await doc.flush();
	assert.equal(empty.dirty, false);
	assert.equal(empty.past.length, 0);
});

/**
 * @source src/script/views/builder/panels/formSettings.mjs::FormSettings._generateSchema
 * @source src/script/forms/controller.mjs::FormController.success
 * @pair forms:success
 * @matrix forms : schema-generation draft-history
 */
test("test_stale_generation_retry_label_survives_base_form_error_transition", async (t) => {
	const transitions = [];
	const text = { textContent: "Generate" };
	const error = { textContent: "", dataset: {} };
	const textarea = { value: "Keep my request", matches: () => true };
	const icon = {
		dataset: {},
		children: [],
		replaceChildren(...children) {
			this.children = children;
		},
	};
	const submitter = {
		dataset: {},
		disabled: false,
		querySelector(selector) {
			if (selector.includes("data-role='text'")) return text;
			if (selector.includes("data-role='icon'")) return icon;
			return null;
		},
		prepend() {},
		setAttribute() {},
		removeAttribute() {},
		classList: { remove() {}, toggle() {} },
	};
	const target = {
		dataset: { visible: "true" },
		contains: () => true,
		hasAttribute: () => false,
		querySelector: (selector) => (selector === "textarea" ? textarea : null),
	};
	let request;
	replaceGlobal(t, "crypto", webcrypto);
	replaceGlobal(t, "document", {
		createElement: () => ({ dataset: {}, replaceChildren() {} }),
	});
	class FormDataBoundary extends Map {
		constructor() {
			super([["description", textarea.value]]);
		}
		append(key, value) {
			this.set(key, value);
		}
	}
	replaceGlobal(t, "FormData", FormDataBoundary);
	const transitionBoundary = (callback) => transitions.push(callback);
	const { FormController } = await esmock.strict(
		"../../src/script/forms/controller.mjs",
		{
			"../../src/script/elements/primitives.mjs": { primitives: {} },
			"../../src/script/shared/icons.mjs": {
				createIcon: (name) => ({ dataset: { icon: name } }),
			},
			"../../src/script/shared/transitions.mjs": {
				withTransition: transitionBoundary,
			},
			"../../src/script/shared/utilities.mjs": {
				showBriefly(wrapper, content) {
					wrapper.replaceChildren(content);
				},
			},
			"../../src/script/forms/controls/loader.mjs": {
				initFormControls: async () => {},
			},
			"../../src/script/forms/renderer.mjs": { FormRenderer: class {} },
		},
	);
	const { FormSettings } = await loadFormSettings({
		FormController,
		request: {
			post(_route, data) {
				return new Promise((resolve) => {
					request = { data, resolve };
				});
			},
		},
	});
	const widget = {
		target,
		submitButton: submitter,
		error,
		messages: {
			submit: "Generate",
			submitting: "Thinking...",
			submitted: "Generated",
		},
	};
	const form = new FormController(widget);
	let restores = 0;
	const builder = {
		updateSchema() {},
		draft: new BuilderDraft(
			{
				name: "Original",
				form_type: "task",
				schema: [],
				html_fields: {},
				selected_id: null,
			},
			"source",
		),
		captureDraft() {
			return structuredClone(this.draft.state);
		},
		restoreDraft() {
			restores += 1;
		},
	};
	const settings = {
		builder,
		generateForm: form,
		_updateSchema: FormSettings.prototype._updateSchema,
	};
	const generate = () =>
		FormSettings.prototype._generateSchema.call(settings, {
			submitter,
			preventDefault() {},
			stopPropagation() {},
		});
	const finishTransitions = () => {
		while (transitions.length) transitions.shift()();
	};
	const displayedIcon = () => icon.children[0]?.dataset.icon;

	const unchanged = structuredClone(builder.draft.state);
	form.showError("An earlier generation failed");
	finishTransitions();
	form.markUnsavedState({ target: textarea });
	const noChanges = generate();
	request.resolve({
		ok: true,
		request_id: request.data.get("request_id"),
		draft_revision: Number(request.data.get("draft_revision")),
		operations: [],
		html_fields: {},
	});
	assert.equal(await noChanges, true);
	finishTransitions();
	assert.deepEqual(builder.draft.state, unchanged);
	assert.equal(builder.draft.dirty, false);
	assert.equal(builder.draft.revision, 0);
	assert.equal(builder.draft.past.length, 0);
	assert.equal(builder.draft.future.length, 0);
	assert.equal(restores, 0);
	assert.equal(widget.unsavedState, false);
	assert.equal(text.textContent, "Generated");
	assert.equal(displayedIcon(), "check");
	assert.equal(error.dataset.visible, "false");
	assert.equal(submitter.disabled, false);
	form.syncOfflineState();
	assert.equal(text.textContent, "Generated");
	assert.equal(displayedIcon(), "check");

	form.markUnsavedState({ target: textarea });
	assert.equal(displayedIcon(), "builder.unsaved");
	const pending = generate();
	builder.draft.record({ ...builder.draft.state, name: "Intervening edit" });
	request.resolve({
		ok: true,
		request_id: request.data.get("request_id"),
		draft_revision: 0,
		operations: [],
		html_fields: {},
	});
	assert.equal(await pending, false);
	assert.equal(transitions.length, 1);
	finishTransitions();
	assert.match(error.textContent, /draft changed/);
	assert.equal(text.textContent, "Regenerate");
	assert.equal(submitter.disabled, false);
	assert.equal(widget.unsavedState, true);
	assert.equal(restores, 0);
	form.syncOfflineState();
	assert.equal(text.textContent, "Regenerate");

	const accepted = generate();
	request.resolve({
		ok: true,
		request_id: request.data.get("request_id"),
		draft_revision: Number(request.data.get("draft_revision")),
		operations: [
			{
				op: "add_field",
				field: {
					id: "generated",
					type: "checkbox",
					title: "Reviewed",
				},
			},
		],
		html_fields: {},
	});
	assert.equal(await accepted, true);
	finishTransitions();
	assert.equal(builder.draft.state.schema[0].title, "Reviewed");
	assert.equal(builder.draft.dirty, true);
	assert.equal(restores, 1);
	assert.equal(widget.unsavedState, false);
	assert.equal(text.textContent, "Generated");
	assert.equal(displayedIcon(), "check");
	assert.equal(target.dataset.visible, "true");
	assert.equal(textarea.value, "Keep my request");
	assert.equal(error.dataset.visible, "false");
	assert.equal(submitter.disabled, false);
	form.syncOfflineState();
	assert.equal(text.textContent, "Generated");
	assert.equal(displayedIcon(), "check");

	const generated = structuredClone(builder.draft.state);
	textarea.value = "Add another field";
	form.markUnsavedState({ target: textarea });
	assert.equal(text.textContent, "Generate");
	assert.equal(displayedIcon(), "builder.unsaved");
	const failed = generate();
	request.resolve({ ok: false, error: "Generation unavailable" });
	assert.equal(await failed, false);
	finishTransitions();
	assert.equal(error.textContent, "Generation unavailable");
	assert.equal(error.dataset.visible, "true");
	assert.equal(widget.unsavedState, true);
	assert.equal(text.textContent, "Generate");
	assert.equal(displayedIcon(), "builder.unsaved");
	assert.equal(submitter.disabled, false);
	assert.equal(textarea.value, "Add another field");
	assert.deepEqual(builder.draft.state, generated);

	FormSettings.prototype._click.call(settings, {
		target: { closest: () => ({ dataset: { role: "cancel" } }) },
	});
	assert.equal(text.textContent, "Generate");
	assert.equal(target.dataset.visible, "false");
});

/** @matrix forms : builder-save stable-identity */
test("test_saved_controls_refresh_without_replacing_draft_inputs", async (t) => {
	replaceGlobal(t, "document", {
		createElement: (tagName) => ({
			tagName,
			dataset: {},
			children: [],
			append(...children) {
				this.children.push(...children);
			},
		}),
	});
	const { ElementSettings } = await esmock.strict(
		"../../src/script/views/builder/panels/elementSettings.mjs",
		{
			"../../src/script/elements/primitives.mjs": { primitives: {} },
			"../../src/script/generated/styles.mjs": { STYLES: {} },
			"../../src/script/shared/transitions.mjs": {
				withTransition: (callback) => callback(),
			},
			"../../src/script/views/builder/config.mjs": { CONFIG: {} },
		},
	);
	const { default: Columns } = await esmock.strict(
		"../../src/script/views/builder/conditions/columns.mjs",
		{
			"../../src/script/elements/combobox/index.mjs": { SelectBox: class {} },
			"../../src/script/elements/primitives.mjs": { primitives: {} },
			"../../src/script/shared/utilities.mjs": {
				generateElementId: () => "column-1",
			},
			"../../src/script/views/builder/config.mjs": { CONFIG: {} },
			"../../src/script/views/builder/migrations.mjs": {
				fieldKind: () => null,
			},
			"../../src/script/views/builder/conditions/base.mjs": {
				Condition: class {},
			},
		},
	);
	let saved;
	const schema = {
		id: "choice",
		type: "select",
		options: [
			{ value: "first", label: "First" },
			{ value: "later", label: "Later" },
		],
	};
	const title = { disabled: false, value: "Still editing this label" };
	let typeNotice;
	const inputSection = {
		dataset: { setting: "input" },
		querySelector: () => typeNotice,
		replaceChildren: (notice) => {
			typeNotice = notice;
		},
	};
	const multiple = { disabled: false };
	const location = { disabled: false };
	const remove = {
		dataset: { setting: "deleteButton" },
		disabled: false,
		matches: () => true,
	};
	const removeFirst = { disabled: false };
	const removeLater = { disabled: false };
	const sections = [
		...["title", "multiple", "location"].map((setting) => ({
			dataset: { setting },
			matches: () => false,
			querySelectorAll: () => [{ title, multiple, location }[setting]],
		})),
		inputSection,
		remove,
		{
			dataset: { setting: "options" },
			querySelectorAll: () =>
				[removeFirst, removeLater].map((control, index) => ({
					dataset: { index: String(index) },
					querySelector: () => control,
				})),
		},
	];
	const builder = { selectedElement: { schema }, savedField: () => saved };
	const settings = Object.assign(Object.create(ElementSettings.prototype), {
		builder,
		panel: { children: sections },
	});
	settings.refreshSavedState();
	assert.equal(typeNotice, undefined);
	assert.equal(remove.disabled, false);
	saved = { ...schema, options: [schema.options[0]] };
	settings.refreshSavedState();
	assert.equal(typeNotice.dataset.role, "saved-input-type");
	assert.equal(typeNotice.children[0], "Click ");
	assert.equal(typeNotice.children[1].tagName, "strong");
	assert.equal(typeNotice.children[1].textContent, "Replace or Delete");
	assert.equal(
		typeNotice.children[2],
		" in order to change this input's type.",
	);
	assert.ok(multiple.disabled && location.disabled && !remove.disabled);
	assert.equal(removeFirst.disabled, false);
	assert.equal(removeLater.disabled, false);
	assert.deepEqual(title, {
		disabled: false,
		value: "Still editing this label",
	});
	assert.equal(settings.panel.children, sections);
	saved = schema;
	const previousNotice = typeNotice;
	settings.refreshSavedState();
	assert.equal(typeNotice, previousNotice);
	assert.equal(removeLater.disabled, false);
	const columnBuffer = {
		id: "quantity",
		title: "A name not yet applied",
		type: "input",
		input: "number",
	};
	const columnType = {
		select: { disabled: false },
		element: { disabled: false },
		panelOpen: true,
		hidePanel() {
			this.panelOpen = false;
		},
	};
	const columns = Object.assign(Object.create(Columns.prototype), {
		builder,
		element: { schema: { id: "items", type: "table" } },
		setting: columnBuffer,
		columnType,
	});
	saved = { columns: [{ id: "other" }] };
	columns.refreshSavedState();
	assert.equal(columnType.element.disabled, false);
	saved = {
		columns: [
			{ id: "quantity", title: "Quantity", type: "input", input: "number" },
		],
	};
	columns.refreshSavedState();
	assert.equal(columnType.panelOpen, true);
	assert.ok(!columnType.select.disabled && !columnType.element.disabled);
	assert.equal(columns.setting, columnBuffer);
	assert.equal(columns.setting.title, "A name not yet applied");
});
