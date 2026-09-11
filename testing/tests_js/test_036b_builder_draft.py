"""Draft-only builder state, generation, and stable nested identity."""


# @matrix forms : draft-history stable-identity schema-generation
def test_builder_draft_history_and_generation(run_node):
    run_node(
        r'''
const assert = await import("node:assert/strict").then((module) => module.default);
const { BuilderDraft } = await import(process.cwd() + "/src/script/views/builder/draft.mjs");
const initial = {
  name: "Draft", form_type: "task", selected_id: "choice",
  schema: [
    { id: "choice", type: "select", multiple: true, options: [{ value: "fixed", label: "Old" }] },
    { id: "table", type: "table", columns: [{ id: "column-original", type: "input", title: "Old column" }] },
    { id: "html", type: "html", title: "Instructions" },
  ],
  html_fields: { html: "<p>Original</p>" },
};
const draft = new BuilderDraft(initial, "baseline-1");
assert.equal(draft.dirty, false);
assert.equal(draft.record(structuredClone(initial)), false);
assert.equal(draft.record({ html_fields: initial.html_fields, schema: initial.schema, form_type: initial.form_type, name: initial.name, selected_id: initial.selected_id }), false);
assert.equal(draft.revision, 0);
draft.applyGeneration({ operations: [
  { op: "update_option", field_id: "choice", value: "fixed", label: "New" },
  { op: "update_column", field_id: "table", column_id: "column-original", title: "New column" },
  { op: "add_field", field: { id: "added", type: "input", title: "Added" } },
], html_fields: { html: "<p>Generated</p>" } });
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
assert.deepEqual(draft.state, initial);
assert.equal(draft.dirty, false);
draft.redo();
assert.deepEqual(draft.state, generated);
const beforeInvalid = structuredClone(draft.state);
assert.throws(() => draft.applyGeneration({ operations: [
  { op: "update_field", field_id: "choice", changes: { title: "Would apply" } },
  { op: "update_field", field_id: "choice", changes: { type: "textarea" } },
] }));
assert.deepEqual(draft.state, beforeInvalid);
assert.throws(() => draft.applyGeneration({ operations: [{ op: "add_field", field: { id: "choice", type: "input" } }] }));
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
draft.acknowledge(submitted, { draft: persisted, baseline: "baseline-2", image_urls: { "local-1": "/assets/saved.png" } });
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
for (let i = 0; i < 120; i++) draft.record({ ...draft.state, name: `Name ${i}` });
assert.equal(draft.past.length, 100);
const selectionDraft = new BuilderDraft(initial, "source");
const beforeSelection = structuredClone(selectionDraft.state);
selectionDraft.state.selected_id = "table";
selectionDraft.acknowledge(beforeSelection, { draft: selectionDraft.content(initial), baseline: "accepted" });
assert.equal(selectionDraft.state.selected_id, "table");
'''
    )


# @matrix forms : stable-identity
# @source src/script/views/builder/conditions/options.mjs::Options
# @source src/script/views/builder/conditions/columns.mjs::Columns
def test_builder_option_and_column_labels_keep_ids(run_node):
    run_node(
        r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
let nextId = 0;
const context = { Condition: class {}, generateElementId: (prefix) => `${prefix}-${++nextId}` };
vm.createContext(context);
for (const [file, name] of [["options", "Options"], ["columns", "Columns"]]) {
  const source = fs.readFileSync(`src/script/views/builder/conditions/${file}.mjs`, "utf8")
    .replace(/^import[\s\S]*?from ["'][^"']+["'];\n/gm, "")
    .replace(`export default class ${name}`, `globalThis.${name} = class ${name}`);
  vm.runInContext(source, context);
}
const options = { setting: { label: "Relabelled", value: "original" }, element: { schema: { options: [] } } };
assert.equal(context.Options.prototype.validate.call(options), true);
assert.equal(options.setting.value, "original");
options.element.schema.options = [{ label: "Same", value: "option-1" }];
options.setting = { label: "Same" };
context.Options.prototype.validate.call(options);
assert.equal(options.setting.value, "option-2");
const columns = { setting: { title: "Relabelled", id: "column-original", type: "input" }, element: { schema: { columns: [] } } };
assert.equal(context.Columns.prototype.validate.call(columns), true);
assert.equal(columns.setting.id, "column-original");
'''
    )


# @matrix forms : schema-generation draft-history
# @source src/script/views/builder/panels/formSettings.mjs::FormSettings._generateSchema
def test_builder_generation_rejects_stale_cancelled_and_destroyed_responses(run_node):
    run_node(
        r'''
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { BuilderDraft } from "./src/script/views/builder/draft.mjs";
const requests = [];
const context = { console, crypto, ENDPOINTS: { createSchema: "/generate" }, captureError: () => {},
  FormData: class extends Map { constructor() { super([["description", "Generate labels"]]); } append(key, value) { this.set(key, value); } },
  request: { post(route, data, options) { assert.equal(options.replaceErrorPage, false); return new Promise((resolve) => requests.push({ data, resolve })); } },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync("src/script/views/builder/panels/formSettings.mjs", "utf8")
  .replace(/^import.*\n/gm, "").replace("export class FormSettings", "globalThis.FormSettings = class FormSettings"), context);
vm.runInContext(fs.readFileSync("src/script/views/builder/panels/condition.mjs", "utf8")
  .replace(/^import.*\n/gm, "").replace("export class ConditionPanel", "globalThis.ConditionPanel = class ConditionPanel"), context);
let message, restores = 0;
const submitter = { dataset: {}, disabled: false, setAttribute() {}, removeAttribute() {} };
const textarea = { value: "Keep the prompt" };
const form = { target: { dataset: {}, querySelector: () => textarea, removeEventListener() {} }, submitButton: submitter, messages: { submit: "Generate" },
  showError(value) { message = value; }, resetSubmitButton() {}, setSubmitButton() {}, destroy() {} };
const builder = { draft: new BuilderDraft({ name: "Original", form_type: "task", schema: [], html_fields: {} }, "baseline"),
  updateSchema() {}, captureDraft() { return structuredClone(this.draft.state); }, restoreDraft() { restores++; }, header: { message() {} } };
const settings = { builder, generateForm: form, _updateSchema: context.FormSettings.prototype._updateSchema };
const generate = () => context.FormSettings.prototype._generateSchema.call(settings, { submitter, preventDefault() {}, stopPropagation() {} });
const finish = () => { const { data, resolve } = requests.shift(); resolve({ ok: true, request_id: data.get("request_id"), draft_revision: Number(data.get("draft_revision")), operations: [{ op: "add_field", field: { id: "generated", type: "input" } }], html_fields: {} }); };
const first = generate();
assert.equal(generate(), first);
builder.draft.record({ ...builder.draft.state, name: "Intervening edit" });
finish();
assert.equal(await first, false);
assert.match(message, /Regenerate/);
assert.equal(restores, 0);
assert.equal(builder.draft.state.name, "Intervening edit");
assert.equal(textarea.value, "Keep the prompt");
const buffered = generate();
context.ConditionPanel.prototype._draftInput.call({ builder, condition: { key: "options" } });
finish();
assert.equal(await buffered, false);
assert.match(message, /Regenerate/);
assert.equal(restores, 0);
const cancelled = generate();
context.FormSettings.prototype._click.call(settings, { target: { closest: () => ({ dataset: { role: "cancel" } }) } });
finish();
assert.equal(await cancelled, false);
assert.equal(restores, 0);
const accepted = generate();
finish();
assert.equal(await accepted, true);
assert.equal(restores, 1);
assert.equal(builder.draft.state.schema[0].id, "generated");
const late = generate();
context.FormSettings.prototype.destroy.call(settings);
finish();
assert.equal(await late, false);
assert.equal(restores, 1);
''',
        module=True,
    )


# @matrix forms : draft-history stale-acknowledgement focus-recovery
def test_builder_save_restores_unsubmitted_condition_buffer(run_node):
    run_node(
        r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
let focused = false;
const active = { name: "option-name", selectionStart: 4, selectionEnd: 8 };
const restoredInput = { name: "option-name", focus() { focused = true; }, setSelectionRange(start, end) { assert.equal(start, 4); assert.equal(end, 8); } };
const context = { structuredClone, document: { activeElement: active }, withTransition: (callback) => callback(),
  BaseForm: class { constructor(owner) { this.owner = owner; } init() {} } };
vm.createContext(context);
vm.runInContext(fs.readFileSync("src/script/views/builder/builder.mjs", "utf8")
  .replace(/^import[\s\S]*?from ["'][^"']+["'];\n/gm, "").replace("export default FormBuilder;", "globalThis.FormBuilder = FormBuilder;"), context);
vm.runInContext(fs.readFileSync("src/script/views/builder/conditions/base.mjs", "utf8")
  .replace(/^import.*\n/gm, "").replaceAll("export class", "class") + "\nglobalThis.Condition = Condition;", context);
const field = { id: "choice", type: "select", options: [{ value: "fixed", label: "Saved" }] };
const buffer = { value: "fixed", label: "Still typing" };
const panel = { contains: () => true, querySelectorAll: () => [restoredInput] };
let reopened;
const builder = {
  elements: new Map([[field.id, { schema: field }]]),
  conditions: { panel, condition: { key: "options", index: 0, element: { schema: field }, setting: buffer }, hide() { this.condition = null; } },
  settings: { panel: { contains: () => false }, deselectItem() {} },
  header: { closePreview() {}, nameHidden: {}, nameInput: {}, nameDisplay: {} },
  model: { panel: { replaceChildren() {}, append() {} }, defaultPanel: { replaceChildren() {} }, show() {} },
  elt: { dataset: {} }, draft: { state: { name: "Saved", schema: [field], html_fields: {}, selected_id: field.id } },
  pruneImages() {}, refreshDraftControls() {}, updateSchema() {},
  createElement(schema) { this.elements.set(schema.id, { schema }); return {}; },
  selectElement(id) { this.selectedElement = this.elements.get(id); },
  showCondition(key, index, setting) {
    reopened = { key, index, setting };
    const condition = { setting: { label: "Saved" }, draftSetting: setting, destroy() {} };
    context.Condition.prototype.init.call(condition);
    assert.equal(condition.setting.label, "Still typing");
    assert.notEqual(condition.setting, setting);
    assert.equal(condition.draftSetting, undefined);
    return Promise.resolve();
  },
};
(async () => {
  await context.FormBuilder.prototype.restoreDraft.call(builder, { preserveFocus: true });
  assert.equal(reopened.key, "options");
  assert.equal(reopened.index, 0);
  assert.equal(reopened.setting.value, "fixed");
  assert.equal(reopened.setting.label, "Still typing");
  assert.equal(field.options[0].label, "Saved");
  assert.equal(focused, true);
})().catch((error) => { console.error(error); process.exitCode = 1; });
'''
    )


# @matrix forms : draft-history
# @source src/script/views/builder/draftDocument.mjs::DraftDocument.flush
# @source src/script/elements/html.mjs::HtmlElement.create
def test_builder_html_flush_stays_local_and_empty_preview_does_not_fetch(run_node):
    run_node(
        r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
let saved;
const context = { IndependentDocument: class {}, BaseElement: class { constructor(renderer, schema) { this.renderer = renderer; this.schema = schema; } },
  document: { createElement() { return { innerHTML: "", className: "" }; } }, request: { get() { throw new Error("Draft preview fetched persisted content"); } } };
vm.createContext(context);
for (const [path, name] of [["src/script/elements/editor/independent.mjs", "IndependentDocument"], ["src/script/views/builder/draftDocument.mjs", "DraftDocument"], ["src/script/elements/html.mjs", "HtmlElement"]]) {
  vm.runInContext(fs.readFileSync(path, "utf8").replace(/^import.*\n/gm, "").replace(`export class ${name}`, `globalThis.${name} = class ${name}`), context);
}
const doc = new context.DraftDocument({ container: { hasAttribute() { return true; } }, editor: { getHTML() { return "<p>Local</p>"; } },
  fieldId: "html", builder: { setHtml(id, html) { saved = { id, html }; } } });
context.DraftDocument.prototype.flush.call(doc, { keepalive: true });
assert.deepEqual(saved, { id: "html", html: "<p>Local</p>" });
const element = new context.HtmlElement({ form: { htmlFields: { html: "" } } }, { id: "html" });
assert.equal(element.create().innerHTML, "");
(async () => {
  const { BuilderDraft } = await import(process.cwd() + "/src/script/views/builder/draft.mjs");
  const initial = { name: "Form", schema: [{ id: "html", type: "html" }], form_type: "task", html_fields: { html: "<p>Local</p>" } };
  const draft = new BuilderDraft(initial, "saved");
  doc.builder.setHtml = (id, html) => draft.record({ ...draft.state, html_fields: { [id]: html } }, `html:${id}`);
  doc.editor.getHTML = () => "<p></p>";
  await doc.flush();
  assert.equal(draft.state.html_fields.html, "");
  assert.equal(draft.dirty, true);
  assert.equal(draft.past.length, 1);
  const revision = draft.revision;
  doc.editor.getHTML = () => "<p><br></p>";
  await doc.flush();
  assert.equal(draft.revision, revision, "Equivalent empty editor markup created another draft change");
  draft.undo();
  assert.equal(draft.state.html_fields.html, "<p>Local</p>");
  const empty = new BuilderDraft({ ...initial, html_fields: { html: "" } }, "empty");
  doc.builder.setHtml = (id, html) => empty.record({ ...empty.state, html_fields: { [id]: html } });
  await doc.flush();
  assert.equal(empty.dirty, false);
  assert.equal(empty.past.length, 0);
})().catch((error) => { console.error(error); process.exitCode = 1; });
'''
    )


# @matrix forms : schema-generation draft-history
# @source src/script/views/builder/panels/formSettings.mjs::FormSettings._generateSchema
def test_stale_generation_retry_label_survives_base_form_error_transition(run_node):
    run_node(
        r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const transitions = [];
const text = { textContent: "Generate" };
const error = { textContent: "", dataset: {} };
const textarea = { value: "Keep my request" };
const submitter = { dataset: {}, disabled: false,
  querySelector(selector) { return selector.includes("data-role='text'") ? text : null; },
  prepend() {}, setAttribute() {}, removeAttribute() {}, classList: { remove() {}, toggle() {} } };
const target = { dataset: { visible: "true" }, contains: () => true,
  hasAttribute: () => false,
  querySelector(selector) { return selector === "textarea" ? textarea : null; } };
let request;
const context = { console, crypto: require("node:crypto").webcrypto, ENDPOINTS: { createSchema: "/generate" },
  document: { createElement() { return { dataset: {}, replaceChildren() {} }; } }, createIcon() { return {}; },
  captureError(error) { throw error; }, withTransition(callback) { transitions.push(callback); },
  FormData: class extends Map { constructor() { super([["description", textarea.value]]); } },
  request: { post(route, data) { return new Promise((resolve) => { request = { data, resolve }; }); } },
};
vm.createContext(context);
for (const [path, name] of [["src/script/elements/base/baseForm.mjs", "BaseForm"], ["src/script/views/builder/panels/formSettings.mjs", "FormSettings"]]) {
  vm.runInContext(fs.readFileSync(path, "utf8").replace(/^import.*\n/gm, "")
    .replace(`export class ${name}`, `globalThis.${name} = class ${name}`), context);
}
const form = new context.BaseForm({ target, submitButton: submitter, error, messages: { submit: "Generate" }, unsavedState: true });
const builder = { updateSchema() {}, draft: { revision: 0, baseline: "source" },
  captureDraft() { return { schema: [], html_fields: {} }; } };
const settings = { builder, generateForm: form };
(async () => {
  const pending = context.FormSettings.prototype._generateSchema.call(settings, { submitter, preventDefault() {}, stopPropagation() {} });
  builder.draft.revision++;
  request.resolve({ ok: true, request_id: request.data.get("request_id"), draft_revision: 0, operations: [], html_fields: {} });
  assert.equal(await pending, false);
  assert.equal(transitions.length, 1);
  transitions.shift()();
  assert.match(error.textContent, /draft changed/);
  assert.equal(text.textContent, "Regenerate");
  assert.equal(submitter.disabled, false);
  form.syncOfflineState();
  assert.equal(text.textContent, "Regenerate", "Form-state refresh replaced the retry label");
  context.FormSettings.prototype._click.call(settings, { target: { closest: () => ({ dataset: { role: "cancel" } }) } });
  assert.equal(text.textContent, "Generate");
  assert.equal(target.dataset.visible, "false");
})().catch((error) => { console.error(error); process.exitCode = 1; });
'''
    )
