"""Builder draft generation, editing, publication, and image persistence."""

from copy import deepcopy
import json
import re
from types import SimpleNamespace
from urllib.parse import urljoin
from uuid import uuid4

from bs4 import BeautifulSoup
import pytest
import requests
from playwright.sync_api import expect
from werkzeug.datastructures import FileStorage

from lagniappe.core.definitions import Action, Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools.ai.form_draft import prepare_generated_changes
from lagniappe.core.tools.form_definitions import rendered_html_fields
from lagniappe.core.tools.form_drafts import archive_form_generation, resolve_form_generation
from testing.definitions import Pages, SitePages, Uploads, Users
from testing.definitions.form_definitions import FormDefinition
from testing.definitions.schema_fields import SchemaFields
from testing.definitions.user_definitions import UserDefinition
from testing.elements import EditorAddImage, SpinnerButtons
from testing.resources.form import Builder, Form
from testing.resources.task import Task as TaskResource
from testing.utility.network import expect_successful_response, manual_mutation_headers, multipart_form_fields, scoped_browser_route

pytestmark = pytest.mark.e2e


def _form(user, title="BSU draft"):
    field = SchemaFields.TEXT_INPUT.get(_id="notes", title="Original notes")
    form = Form(user=user, definition=FormDefinition(
        name=f"{title} {uuid4().hex[:8]}", form_type="task", schema=(field,),
    )).create()
    return form, field


def _rename(builder, field, label):
    builder.select_field(field)
    title = builder.settings.locator("input[name='title']")
    title.fill(label)
    title.blur()


def _generation_reply(route, operations):
    data = dict(multipart_form_fields(route.request))
    route.fulfill(status=200, content_type="application/json", body=json.dumps({
        "operations": operations, "html_fields": {},
        "request_id": data["request_id"], "draft_revision": int(data["draft_revision"]),
    }))


def _http(user, method, path, **kwargs):
    return requests.request(
        method, urljoin(user.page.url, path), timeout=20,
        cookies={cookie["name"]: cookie["value"] for cookie in user.page.context.cookies()},
        headers=manual_mutation_headers(user.page.url, user.locate("#token").input_value()),
        allow_redirects=False, **kwargs,
    )


# @source src/script/views/builder/draft.mjs::BuilderDraft
# @source src/script/views/builder/panels/formSettings.mjs::FormSettings._generateSchema
# @matrix forms : draft-history stable-identity schema-generation builder-save builder-reload
# @template forms/builder.html::header
# @template forms/builder.html::generate
def test_generation_is_one_undoable_unsaved_command(get_user):
    user = get_user(Users.OWNER)
    form, field = _form(user)
    builder = form.builder
    before = dict(Entities.fetch_one(form.key, request=Fetch.root()).db)
    _rename(builder, field, "Manual notes")
    operations = [
        {"op": "update_field", "field_id": "notes", "changes": {"title": "Generated notes"}},
        {"op": "add_field", "field": {"id": "generated-extra", "type": "textarea", "title": "Extra notes"}},
    ]
    with scoped_browser_route(user.page.context, "**/forms/create-schema", lambda route: _generation_reply(route, operations)):
        user.locate("button[data-role='form-settings']").click()
        user.locate("button[data-role='generate']").click()
        generate = user.locate("form#generate")
        generate.locator("textarea[name='description']").fill("Update notes and add extra notes")
        generate.locator("button[type='submit']").click()
        expect(generate.get_by_role("button", name="Generated", exact=True)).to_be_visible()
    expect(builder.model).to_contain_text("Generated notes")
    expect(user.locate(builder.UNSAVED)).to_be_visible()
    assert dict(Entities.fetch_one(form.key, request=Fetch.root()).db) == before

    user.locate("[data-role='undo-draft']").click()
    expect(builder.model).to_contain_text("Manual notes")
    assert builder.schema_field("generated-extra") is None
    user.locate("[data-role='redo-draft']").click()
    expect(builder.model).to_contain_text("Generated notes")
    assert builder.schema_field("generated-extra")["title"] == "Extra notes"
    builder.save()
    expect(user.locate(builder.SAVED)).to_be_disabled()
    form.reload()
    assert Builder(user).schema_field("notes")["title"] == "Generated notes"
    assert Builder(user).schema_field("generated-extra")["title"] == "Extra notes"

    saved_schema = Builder(user).schema
    saved_form = dict(Entities.fetch_one(form.key, request=Fetch.root()).db)
    with scoped_browser_route(user.page.context, "**/forms/create-schema", lambda route: _generation_reply(route, [])):
        user.locate("button[data-role='form-settings']").click()
        user.locate("button[data-role='generate']").click()
        generate = user.locate("form#generate")
        generate.locator("textarea[name='description']").fill("Leave every field unchanged")
        generate.locator("button[type='submit']").click()
        submitted = generate.get_by_role("button", name="Generated", exact=True)
        expect(submitted).to_be_visible()
        expect(submitted.locator("[data-icon='check']")).to_be_visible()
    expect(generate.locator("[data-role='error']")).not_to_be_visible()
    expect(user.locate(builder.SAVED)).to_be_visible()
    expect(user.locate(builder.SAVED)).to_be_disabled()
    expect(user.locate("[data-role='undo-draft']")).to_be_disabled()
    expect(user.locate("[data-role='redo-draft']")).to_be_disabled()
    assert Builder(user).schema == saved_schema
    assert dict(Entities.fetch_one(form.key, request=Fetch.root()).db) == saved_form


# @source src/script/views/builder/panels/header.mjs::Header.saveForm
# @matrix forms : builder-preview focus-recovery
# @template forms/builder.html::header
# @style builder.switch.container
def test_preview_toggle_retains_keyboard_focus(get_user):
    user = get_user(Users.OWNER)
    form, notes = _form(user, "Preview keyboard focus")
    builder = form.builder
    _rename(builder, notes, "Keyboard notes")
    preview = user.locate(builder.PREVIEW_TOGGLE)
    panel = user.locate("#preview-panel")
    save = user.locate(builder.SAVE_BUTTON)

    preview.focus()
    user.page.keyboard.press("Space")
    expect(panel).to_be_visible()
    expect(preview).to_be_focused()
    expect(preview).to_have_css("outline-style", "solid")
    expect(preview).to_have_css("outline-width", "2px")
    user.page.keyboard.press("Tab")
    expect(save).to_be_focused()
    user.page.keyboard.press("Shift+Tab")
    expect(preview).to_be_focused()
    user.page.keyboard.press("Enter")
    expect(panel).to_be_hidden()
    expect(preview).to_be_focused()
    expect(preview).to_have_css("outline-style", "solid")
    expect(preview).to_have_css("outline-width", "2px")


# @matrix forms : builder-save focus-recovery
# @template forms/builder.html::header
# @style nav.button
@pytest.mark.parametrize("reconnect_during_save", [False, True])
def test_save_feedback_retains_keyboard_focus(
    get_user, browser_failures, reconnect_during_save,
):
    user = get_user(Users.OWNER)
    form, notes = _form(user, "Save keyboard focus")
    builder = form.builder
    _rename(builder, notes, "Saved keyboard notes")
    save = user.locate(builder.SAVE_BUTTON)
    pending = []

    with scoped_browser_route(user.page.context, f"**/forms/{form.key}/update", lambda route: pending.append(route)):
        save.focus()
        before = save.bounding_box()
        try:
            user.page.keyboard.press("Enter")
            expect(save).to_have_attribute("aria-busy", "true")
            expect(save.locator("[data-icon='spinner']")).to_be_visible()
            expect(save.locator("[data-icon='builder.unsaved']")).to_be_hidden()
            expect(save.locator("[data-icon='builder.saved']")).to_be_hidden()
            if reconnect_during_save:
                with browser_failures.expect_offline(user, max_ping_count=3):
                    try:
                        user.offline = True
                        expect(user.locate("[data-role='offline']")).to_be_visible()
                        expect(save).to_be_focused()
                    finally:
                        user.offline = False
                expect(user.locate("[data-role='offline']")).to_be_hidden()
            expect(save).to_be_focused()
            expect(save).to_have_css("opacity", "1")
            assert save.bounding_box() == before
            user.page.keyboard.press("Enter")
            expect(save).to_have_attribute("aria-busy", "true")
            assert len(pending) == 1
            with expect_successful_response(user.page, method="PUT", path=f"/forms/{form.key}/update"):
                pending.pop().continue_()
        finally:
            for route in pending:
                route.continue_()

    expect(save).not_to_have_attribute("aria-busy", "true")
    expect(save).to_have_attribute("aria-disabled", "true")
    expect(save).to_be_focused()
    expect(save).to_have_css("outline-style", "solid")
    expect(save.locator("[data-icon='spinner']")).to_be_hidden()
    expect(save.locator("[data-icon='builder.unsaved']")).to_be_hidden()
    expect(save.locator("[data-icon='builder.saved']")).to_be_visible()
    assert save.bounding_box() == before
    user.page.keyboard.press("Shift+Tab")
    expect(user.locate(builder.PREVIEW_TOGGLE)).to_be_focused()
    user.page.keyboard.press("Tab")
    expect(save).to_be_focused()
    user.page.keyboard.press("Space")
    expect(save).not_to_have_attribute("aria-busy", "true")
    expect(save).to_have_attribute("data-saved", "true")


# @matrix forms : builder-save builder-reload
# @template forms/builder.html::header
# @template forms/builder.html::main
def test_save_preserves_open_option_editor(get_user):
    user = get_user(Users.OWNER)
    notes = SchemaFields.TEXT_INPUT.get(_id="notes", title="Notes")
    outcome = SchemaFields.SELECT.get(
        _id="outcome", title="Review Outcome",
        options=[{"value": "pending", "label": "Pending review"}],
    )
    form = Form(user=user, definition=FormDefinition(
        name=f"BSU save open panel {uuid4().hex[:8]}", form_type="task",
        schema=(notes, outcome),
    )).create()
    builder = form.builder
    builder.select_field(notes)
    placeholder = builder.settings.locator("input[name='placeholder']")
    placeholder.fill("Enter a BSU verification note")
    placeholder.blur()
    expect(user.locate(builder.SAVE_BUTTON)).to_be_enabled()

    builder.select_field(outcome)
    builder.open_condition("options", role="open")
    option_name = builder.condition.locator("input[name='option-name']")
    expect(option_name).to_have_value("Pending review")
    option_name.fill("Option change still being drafted")
    original_input = option_name.element_handle()
    original_field = outcome.element.element_handle()
    visibility = builder.condition.evaluate_handle("""panel => {
        const changes = [];
        const observer = new MutationObserver(records => changes.push(...records));
        observer.observe(panel, {
            attributes: true, attributeFilter: ["data-visible"], attributeOldValue: true,
        });
        return { panel, changes, observer };
    }""")
    try:
        with expect_successful_response(
            user.page, method="PUT", path=f"/forms/{form.key}/update",
        ):
            user.locate(builder.SAVE_BUTTON).click()
        expect(user.locate(builder.SAVED)).to_be_disabled()
        expect(user.locate(builder.SAVED)).not_to_have_attribute("aria-busy", "true")
        expect(user.locate(builder.SAVED)).to_have_css("opacity", "1")
        expect(builder.condition).to_be_visible()
        expect(option_name).to_have_value("Option change still being drafted")
        assert original_input.evaluate("node => node.isConnected"), "Save replaced the option editor"
        assert original_field.evaluate("node => node.isConnected"), "Save replaced the selected field"
        assert visibility.evaluate("""state => {
            state.changes.push(...state.observer.takeRecords());
            return state.panel.dataset.visible === "true" &&
                state.changes.every(change => change.oldValue === "true");
        }"""), "Save temporarily hid the open option panel"
    finally:
        visibility.evaluate("state => state.observer.disconnect()")
        visibility.dispose()
        original_input.dispose()
        original_field.dispose()

    form.reload()
    builder = Builder(user)
    builder.select_field(notes)
    expect(builder.settings.locator("input[name='placeholder']")).to_have_value("Enter a BSU verification note")
    assert builder.schema_field(outcome.id)["options"] == [{"value": "pending", "label": "Pending review"}]
    expect(user.locate(builder.SAVED)).to_be_disabled()
    expect(user.locate(builder.SAVED)).to_have_css("opacity", "1")


# @source src/script/views/builder/panels/model.mjs::ModelPanel.focusItem
# @source src/script/views/builder/panels/model.mjs::ModelPanel.blurItem
# @matrix forms : builder-lifecycle
# @template forms/builder.html::main
# @template forms/builder.html::header
def test_condition_panels_fit_outline_to_selected_field(get_user):
    user = get_user(Users.OWNER)
    choice = SchemaFields.SELECT.get(
        _id="choice", title="Decision", options=[{"value": "ready", "label": "Ready"}],
    )
    rows = SchemaFields.TABLE.get(
        _id="rows", title="Items",
        columns=[SchemaFields.TEXT_INPUT.get(_id="description", title="Description")],
    )
    notes = SchemaFields.TEXT_INPUT.get(_id="notes", title="Notes")
    status = SchemaFields.STATUS.get(_id="status", title="Status")
    instructions = SchemaFields.HTML.get(_id="instructions", title="Instructions")
    fields = (choice, rows, notes, status, instructions)
    form = Form(user=user, definition=FormDefinition(
        name=f"Panel outline {uuid4().hex[:8]}", form_type="task", schema=fields,
    )).create()
    builder = form.builder
    expect(user.locate(builder.SAVED)).to_be_disabled()
    saved_schema = builder.schema
    normal_height = builder.model.bounding_box()["height"]
    normal_min_height = builder.model.evaluate("node => getComputedStyle(node).minHeight")
    assert float(normal_min_height.removesuffix("px")) > 0

    for setting, field, role in (
        ("options", choice, "add"),
        ("columns", rows, "add"),
        ("visibility", notes, "add"),
        ("status", status, "add"),
        ("html", instructions, "edit"),
    ):
        builder.select_field(field)
        builder.open_condition(setting, role=role)
        expect(builder.model.locator(".form-element:visible")).to_have_count(1)
        expect(field.element).to_be_visible()
        bounds = field.element.evaluate("""node => {
            const panel = node.parentElement;
            const outer = panel.getBoundingClientRect();
            const inner = node.getBoundingClientRect();
            const style = getComputedStyle(panel);
            return {
                gaps: [inner.top - outer.top, outer.bottom - inner.bottom,
                       inner.left - outer.left, outer.right - inner.right],
                padding: [style.paddingTop, style.paddingBottom,
                          style.paddingLeft, style.paddingRight].map(parseFloat),
            };
        }""")
        assert bounds["gaps"] == pytest.approx(bounds["padding"], abs=1), setting
        expect(user.locate(builder.SAVED)).to_be_disabled()
        expect(builder.condition).to_be_visible()

        builder.condition.locator("button[data-role='close']").click()
        expect(builder.condition).not_to_be_visible()
        expect(builder.model.locator(".form-element:visible")).to_have_count(len(fields))
        expect(builder.model).to_have_css("min-height", normal_min_height)
        assert builder.model.bounding_box()["height"] == pytest.approx(normal_height, abs=1), setting
        assert builder.schema == saved_schema, f"Closing {setting} changed the form schema"
        expect(user.locate(builder.SAVED)).to_be_disabled()


# @source src/script/views/builder/draft.mjs::BuilderDraft
# @matrix forms : draft-history schema-generation
# @template forms/builder.html::header
# @template forms/builder.html::generate
def test_manual_edit_after_undo_discards_generated_redo(get_user):
    user = get_user(Users.OWNER)
    note = SchemaFields.TEXT_INPUT.get(_id="notes", title="Existing note")
    checkbox = SchemaFields.CHECKBOX.get(_id="check", title="BSU check")
    form = Form(user=user, definition=FormDefinition(
        name=f"BSU redo branch {uuid4().hex[:8]}", form_type="task", schema=(note, checkbox),
    )).create()
    builder = form.builder
    undo = user.page.get_by_role("button", name="Undo draft change", exact=True)
    redo = user.page.get_by_role("button", name="Redo draft change", exact=True)
    expect(undo).to_be_disabled()
    expect(redo).to_be_disabled()
    expect(undo).to_have_css("opacity", "0.5")
    expect(redo).to_have_css("opacity", "0.5")

    _rename(builder, note, "Manual note")
    operations = [{"op": "update_field", "field_id": "check", "changes": {"title": "Ready for review"}}]
    with scoped_browser_route(user.page.context, "**/forms/create-schema", lambda route: _generation_reply(route, operations)):
        user.locate("button[data-role='form-settings']").click()
        user.locate("button[data-role='generate']").click()
        generate = user.locate("form#generate")
        generate.locator("textarea[name='description']").fill("Rename BSU check to Ready for review")
        generate.locator("button[type='submit']").click()
        expect(generate.get_by_role("button", name="Generated", exact=True)).to_be_visible()
    expect(builder.model).to_contain_text("Manual note")
    expect(builder.model).to_contain_text("Ready for review")

    undo.click()
    expect(builder.model).to_contain_text("Manual note")
    expect(builder.model).to_contain_text("BSU check")
    undo.click()
    expect(builder.model).to_contain_text("Existing note")
    expect(undo).to_be_disabled()
    expect(undo).to_have_css("opacity", "0.5")
    expect(redo).to_be_enabled()
    expect(redo).to_have_css("opacity", "1")

    redo.click()
    expect(builder.model).to_contain_text("Manual note")
    expect(builder.model).to_contain_text("BSU check")
    redo.click()
    expect(builder.model).to_contain_text("Ready for review")
    undo.click()
    expect(builder.model).to_contain_text("BSU check")

    builder.select_field(note)
    title = builder.settings.locator("input[name='title']")
    title.fill("")
    title.press_sequentially("Different note")
    expect(redo).to_be_disabled()
    expect(redo).to_have_css("opacity", "0.5")
    title.blur()
    expect(redo).to_be_disabled()
    expect(undo).to_be_enabled()
    expect(undo).to_have_css("opacity", "1")

    undo.click()
    expect(builder.model).to_contain_text("Manual note")
    expect(builder.model).to_contain_text("BSU check")
    redo.click()
    expect(builder.model).to_contain_text("Different note")
    expect(builder.model).to_contain_text("BSU check")
    expect(builder.model).not_to_contain_text("Ready for review")
    expect(redo).to_be_disabled()
    expect(redo).to_have_css("opacity", "0.5")


# @source src/script/views/builder/draft.mjs::BuilderDraft
# @source src/script/views/builder/draftDocument.mjs::DraftDocument.flush
# @source src/script/elements/editor/independent.mjs::IndependentDocument._initEditor
# @source src/script/elements/editor/editor.mjs::independentEditor
# @matrix forms : draft-history
# @matrix editor : initial-load
# @template forms/builder.html::header
def test_form_undo_preserves_document_edits(get_user):
    user = get_user(Users.OWNER)
    note = SchemaFields.TEXT_INPUT.get(_id="notes", title="Original notes")
    document = SchemaFields.HTML.get(_id="instructions", title="Instructions")
    form = Form(user=user, definition=FormDefinition(
        name=f"BSU separate undo {uuid4().hex[:8]}",
        form_type="task", schema=(note, document),
    )).create()
    form.entity.set_html_field(document.id, "<p>Original instructions.</p>")
    form.entity.save()
    builder = form.builder
    undo = user.page.get_by_role("button", name="Undo draft change", exact=True)
    redo = user.page.get_by_role("button", name="Redo draft change", exact=True)

    def open_document():
        builder.select_field(document)
        builder.open_condition("html", role="edit")
        editor = builder.condition.locator("[data-role='editor']")
        expect(editor).to_have_attribute("loaded", "")
        text_entry = editor.locator(".ProseMirror")
        expect(text_entry).to_have_attribute("contenteditable", "true")
        return text_entry

    text_entry = open_document()
    text_entry.press("Control+End")
    text_entry.press_sequentially(" First edit.")
    expect(text_entry).to_have_text("Original instructions. First edit.")
    expect(user.locate(builder.UNSAVED)).to_be_visible()
    expect(undo).to_be_disabled()
    expect(redo).to_be_disabled()
    builder.condition.locator("button[data-role='close']").click()
    expect(builder.condition).not_to_be_visible()

    _rename(builder, note, "Renamed notes")
    expect(undo).to_be_enabled()
    text_entry = open_document()
    text_entry.press("Control+End")
    text_entry.press_sequentially(" Second edit.")
    expect(text_entry).to_have_text("Original instructions. First edit. Second edit.")
    builder.condition.locator("button[data-role='close']").click()
    expect(builder.condition).not_to_be_visible()

    undo.click()
    expect(builder.model).to_contain_text("Original notes")
    expect(undo).to_be_disabled()
    expect(redo).to_be_enabled()
    text_entry = open_document()
    expect(text_entry).to_have_text("Original instructions. First edit. Second edit.")
    text_entry.press("Control+End")
    text_entry.press_sequentially(" After undo.")
    expected_document = "Original instructions. First edit. Second edit. After undo."
    expect(text_entry).to_have_text(expected_document)
    expect(undo).to_be_disabled()
    expect(redo).to_be_enabled()
    builder.condition.locator("button[data-role='close']").click()
    expect(builder.condition).not_to_be_visible()

    redo.click()
    expect(builder.model).to_contain_text("Renamed notes")
    expect(undo).to_be_enabled()
    expect(redo).to_be_disabled()
    text_entry = open_document()
    expect(text_entry).to_have_text(expected_document)
    text_entry.press("Control+End")
    text_entry.press_sequentially(" Editor undo only.")
    expect(text_entry).to_have_text(expected_document + " Editor undo only.")
    text_entry.press("Control+z")
    expect(text_entry).to_have_text(expected_document)
    expect(undo).to_be_enabled()
    expect(redo).to_be_disabled()
    builder.condition.locator("button[data-role='close']").click()
    expect(builder.condition).not_to_be_visible()
    expect(builder.model).to_contain_text("Renamed notes")


# @matrix editor html-field : image-layout
# @template forms/builder.html::header
@pytest.mark.parametrize(("position", "float_value", "right_margin"), [
    ("Align right", "none", "0px"),
    ("Float left", "left", "1em"),
])
def test_image_layout_survives_builder_save_and_reload(get_user, position, float_value, right_margin):
    user = get_user(Users.OWNER)
    document = SchemaFields.HTML.get(_id="instructions", title="Instructions")
    form = Form(user=user, definition=FormDefinition(
        name=f"BSU image layout {uuid4().hex[:8]}", form_type="task", schema=(document,),
    )).create()
    form.entity.set_html_field(document.id, "<p><strong>Keep this instruction.</strong></p>")
    form.entity.save()
    builder = form.builder
    builder.select_field(document)
    builder.open_condition("html", role="edit")
    editor = builder.condition.locator("[data-role='editor']")
    expect(editor).to_have_attribute("loaded", "")
    text_entry = editor.locator(".ProseMirror")
    text_entry.press("Control+End")
    text_entry.press("Enter")
    toolbar = builder.condition.locator("[data-role='toolbar']")
    image_form = EditorAddImage(SimpleNamespace(toolbar=toolbar)).form
    Uploads.editor_test_image.set(image_form)
    SpinnerButtons.UPLOAD.click(image_form)
    image = text_entry.locator("img")
    expect(image).to_be_visible()
    # The image is inserted before the upload panel finishes closing. Selecting
    # it sooner lets that pending close hide the newly opened image controls.
    expect(image_form).not_to_be_visible()
    image.click()
    toolbar.locator("button[title='Decrease size']").click()
    toolbar.locator("button[title='Decrease size']").click()
    toolbar.locator(f"button[title='{position}']").click()
    expect(image).to_have_attribute("style", re.compile("width: 80%"))
    expect(image).to_have_css("float", float_value)
    assert image.evaluate("image => image.style.marginRight") == right_margin
    builder.condition.locator("button[data-role='close']").click()
    expect(builder.condition).not_to_be_visible()
    builder.save()

    preview = builder.toggle_preview()
    image = preview.locator(".html-content img")
    expect(image).to_have_attribute("style", re.compile(r"width:\s*80%"))
    expect(image).to_have_css("float", float_value)
    assert image.evaluate("image => image.style.marginRight") == right_margin
    form.reload()
    builder = Builder(user)
    preview = builder.toggle_preview()
    image = preview.locator(".html-content img")
    expect(image).to_be_visible()
    expect(image).to_have_attribute("style", re.compile(r"width:\s*80%"))
    expect(image).to_have_css("float", float_value)
    assert image.evaluate("image => image.style.marginRight") == right_margin
    expect(preview.locator(".html-content strong")).to_have_text("Keep this instruction.")
    user.locate(builder.PREVIEW_TOGGLE).click()
    builder.select_field(document)
    builder.open_condition("html", role="edit")
    expect(builder.condition.locator("[data-role='editor']")).to_have_attribute("loaded", "")
    image = builder.condition.locator(".ProseMirror img")
    expect(image).to_have_attribute("style", re.compile("width: 80%"))
    expect(image).to_have_css("float", float_value)
    assert image.evaluate("image => image.style.marginRight") == right_margin


# @source lagniappe/core/tools/files/html.py::render_markdown
# @source src/script/views/builder/panels/formSettings.mjs::FormSettings._generateSchema
# @matrix forms : schema-generation builder-save builder-reload
# @matrix form-html security : html-sanitization owned-image
# @template forms/builder.html::header
# @template forms/builder.html::generate
def test_generated_instructions_preserve_current_image_layout(get_user):
    user = get_user(Users.OWNER)
    note = SchemaFields.TEXT_INPUT.get(_id="notes", title="Notes")
    document = SchemaFields.HTML.get(_id="instructions", title="Instructions")
    form = Form(user=user, definition=FormDefinition(
        name=f"BSU generated image {uuid4().hex[:8]}", form_type="task", schema=(note, document),
    )).create()
    upload = Uploads.editor_test_image.value.file
    with upload.path.open("rb") as stream:
        source = form.entity.add_html_field_image(document.id, FileStorage(
            stream=stream, filename=upload.name, content_type=upload.mime_type,
        ))
    form.entity.set_html_field(document.id, (
        '<p><strong>Original instruction</strong></p>'
        f'<img src="{source}" style="width: 80%; display: block; float: none; margin-left: auto; margin-right: auto">'
    ))
    form.entity.save()
    before = dict(Entities.fetch_one(form.key, request=Fetch.root()).db)
    builder = form.builder
    builder.select_field(document)
    builder.open_condition("html", role="edit")
    editor = builder.condition.locator("[data-role='editor']")
    expect(editor).to_have_attribute("loaded", "")
    image = editor.locator(".ProseMirror img")
    image.click()
    toolbar = builder.condition.locator("[data-role='toolbar']")
    for _ in range(3):
        toolbar.locator("button[title='Decrease size']").click()
    toolbar.locator("button[title='Align right']").click()
    expect(image).to_have_attribute("style", re.compile(r"width:\s*50%"))
    builder.condition.locator("button[data-role='close']").click()
    expect(builder.condition).not_to_be_visible()

    def generated_reply(route):
        data = dict(multipart_form_fields(route.request))
        draft = {"schema": json.loads(data["schema"]), "html_fields": json.loads(data["html_fields"])}
        # Reproduce the provider's attribute suffix through the real converter.
        proposal = prepare_generated_changes({
            "operations": [{"op": "update_field", "field_id": "notes", "changes": {
                "placeholder": "Enter a generated verification note",
            }}],
            "content_markdown": {"instructions": (
                f'**Generated instruction**\n\n![Image]({source})'
                '{width="50%" style="display:block;float:none;margin-left:auto;margin-right:0"}'
            )},
        }, draft, form_type="task", image_sources={"instructions": [(source, source)]})
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            **proposal, "request_id": data["request_id"], "draft_revision": int(data["draft_revision"]),
        }))

    with scoped_browser_route(user.page.context, "**/forms/create-schema", generated_reply):
        user.locate("button[data-role='form-settings']").click()
        user.locate("button[data-role='generate']").click()
        generate = user.locate("form#generate")
        generate.locator("textarea[name='description']").fill("Update the instruction and placeholder, keeping the image layout")
        generate.locator("button[type='submit']").click()
        expect(generate.get_by_role("button", name="Generated", exact=True)).to_be_visible()
    expect(user.locate(builder.UNSAVED)).to_be_visible()
    assert dict(Entities.fetch_one(form.key, request=Fetch.root()).db) == before

    for saved in (False, True):
        if saved:
            builder.save()
            form.reload()
            builder = Builder(user)
        preview = builder.toggle_preview()
        content = preview.locator(".html-content")
        expect(content).to_have_text("Generated instruction")
        expect(content.locator("strong")).to_have_text("Generated instruction")
        expect(preview.get_by_placeholder("Enter a generated verification note")).to_be_visible()
        image = content.locator("img")
        expect(image).to_have_attribute("style", re.compile(r"width:\s*50%"))
        expect(image).to_have_css("float", "none")
        assert image.evaluate("image => image.style.marginLeft") == "auto"
        assert image.evaluate("image => image.style.marginRight") == "0px"
        user.locate(builder.PREVIEW_TOGGLE).click()
        builder.select_field(document)
        builder.open_condition("html", role="edit")
        editor = builder.condition.locator("[data-role='editor']")
        expect(editor).to_have_attribute("loaded", "")
        content = editor.locator(".ProseMirror")
        expect(content).to_have_text("Generated instruction")
        expect(content.locator("strong")).to_have_text("Generated instruction")
        image = content.locator("img")
        expect(image).to_have_attribute("style", re.compile(r"width:\s*50%"))
        assert image.evaluate("image => image.style.marginLeft") == "auto"
        assert image.evaluate("image => image.style.marginRight") == "0px"
        builder.condition.locator("button[data-role='close']").click()
        expect(builder.condition).not_to_be_visible()


# @source src/script/views/builder/panels/formSettings.mjs::FormSettings._generateSchema
# @matrix forms : draft-history schema-generation stale-response
# @template forms/builder.html::generate
def test_generation_rejects_result_after_intervening_edit(get_user):
    user = get_user(Users.OWNER)
    form, field = _form(user, "BSU stale generation")
    builder = form.builder
    def reply_after_intervening_edit(route):
        # Edit only once the service-worker-owned request has actually arrived.
        # Completing the handler also avoids leaving an unresolved route on failure.
        try:
            _rename(builder, field, "Intervening edit")
        except BaseException:
            route.abort()
            raise
        _generation_reply(route, [
            {"op": "update_field", "field_id": "notes", "changes": {"title": "Stale label"}},
        ])

    with scoped_browser_route(user.page.context, "**/forms/create-schema", reply_after_intervening_edit):
        user.locate("button[data-role='generate']").click()
        generate = user.locate("form#generate")
        generate.locator("textarea[name='description']").fill("Rename notes")
        generate.locator("button[type='submit']").click()
        expect(builder.model).to_contain_text("Intervening edit")
        user.locate("button[data-role='form-settings']").click()
        expect(generate.locator("[data-role='error']")).to_contain_text("draft changed")
        expect(generate.get_by_role("button", name="Regenerate", exact=True)).to_be_enabled()
        assert builder.schema_field("notes")["title"] == "Intervening edit"


# @matrix forms : builder-save stale-acknowledgement persistent-error concurrent-edit
# @template forms/builder.html::header
def test_stale_save_preserves_local_draft_after_another_editor_saves(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    form, field = _form(owner, "BSU concurrent save")
    first = form.builder
    editor = get_user(UserDefinition(
        name="BSU second editor", email=f"bsu-editor-{uuid4().hex}@example.test",
    ), creator=owner)
    editor.go(SitePages.HOME)
    editor_entity = Entities.USER.load(editor.email)
    editor_entity.permissions = {**editor_entity.permissions, "forms": Action.EDIT.name}
    editor_entity.save()
    second_form = Form(user=editor)
    second_form.entity = form.entity
    second = second_form.builder
    _rename(first, field, "First editor saved")
    first.save()
    _rename(second, field, "Second editor draft")
    path = editor.locate("#schema-form").get_attribute("data-route")
    with browser_failures.expect_http_error(editor, status=409, path=path):
        with editor.page.expect_response(lambda response: response.request.method == "PUT" and response.url.endswith(path)) as response:
            editor.locate(second.SAVE_BUTTON).click()
        assert response.value.status == 409
        expect(editor.locate("#notification")).to_contain_text("draft is preserved")
        expect(editor.locate(second.UNSAVED)).to_be_visible()
        assert second.schema_field("notes")["title"] == "Second editor draft"
    persisted = Entities.fetch_one(form.key, request=Fetch.root())
    assert persisted.schema[0]["title"] == "First editor saved"


# @matrix forms : builder-save migration-required save-receipt
def test_builder_publication_rejects_incompatible_payload_and_reuses_receipt(get_user):
    user = get_user(Users.OWNER)
    form, _ = _form(user, "BSU publication contract")
    form.builder
    bootstrap = json.loads(user.locate("#builder-draft").text_content())
    request = {**bootstrap, "save_id": uuid4().hex, "image_manifest": []}
    incompatible = deepcopy(request)
    incompatible["schema"][0]["type"] = "textarea"
    response = _http(user, "PUT", f"/forms/{form.key}/update", json=incompatible)
    assert response.status_code == 422
    assert "migration" in response.text
    assert Entities.fetch_one(form.key, request=Fetch.root()).schema[0]["type"] == "input"

    request["schema"][0]["title"] = "Accepted label"
    accepted = _http(user, "PUT", f"/forms/{form.key}/update", json=request)
    repeated = _http(user, "PUT", f"/forms/{form.key}/update", json=request)
    assert accepted.status_code == repeated.status_code == 200
    assert accepted.json()["baseline"] == repeated.json()["baseline"]
    form.reload()
    assert Builder(user).schema_field("notes")["title"] == "Accepted label"


# @matrix task-completion html-field permissions : schema-version owned-image record-scope
def test_historical_images_are_bound_to_the_authorized_completion(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_create_page_task.get(user)
    field = SchemaFields.HTML.get(_id="instructions", title="Instructions")
    form = Form(user=user, definition=FormDefinition(
        name=f"BSU historical image {uuid4().hex[:8]}", form_type="task", schema=(field,),
    )).create()
    image = Uploads.editor_test_image.value.file
    with image.path.open("rb") as stream:
        source_url = form.entity.add_html_field_image(field.id, FileStorage(
            stream=stream, filename=image.name, content_type=image.mime_type,
        ))
    form.entity.set_html_field(field.id, f'<p>Original instructions</p><img src="{source_url}">')
    form.entity.save()
    task = Entities.TASK.create({"name": "BSU completed image", "page": page.entity, "form": form.entity})
    task.save()
    task.complete(user=user.entity)
    task.save()
    archive_form_generation(form.entity).save()
    form.entity.set_html_field(field.id, f'<p>New active instructions</p><img src="{source_url}">')
    form.entity.save()
    # Supply a later-generation fixture; conversion itself is outside step 1.
    form.entity.generation = 1
    Entities.save_root(form.entity, property_mask=("generation",))
    html = rendered_html_fields(task, original=True)[field.id]
    image_url = BeautifulSoup(html, "html.parser").find("img")["src"]
    user.go(page)
    response = _http(user, "GET", image_url)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Type"].startswith("image/")
    metadata = _http(user, "HEAD", image_url)
    assert metadata.status_code == 200
    assert int(metadata.headers["Content-Length"]) == len(response.content)
    assert metadata.content == b""
    snapshot = resolve_form_generation(task.properties.form.key, 0)
    image_name = next(name for name in snapshot.assets if name.startswith(f"image_{field.id}_"))
    assert _http(user, "GET", snapshot.get_asset(image_name).url).status_code == 403
    wrong_version = image_url.replace("/form-generation/0/", "/form-generation/99/")
    assert _http(user, "GET", wrong_version).status_code == 404
    outsider = get_user(UserDefinition(
        name="BSU unrelated viewer", email=f"bsu-viewer-{uuid4().hex}@example.test",
    ), creator=user)
    outsider.go(SitePages.HOME)
    assert _http(outsider, "GET", image_url).status_code == 403

    assert "New active instructions" in rendered_html_fields(task)[field.id]
    assert "Original instructions" in rendered_html_fields(task, original=True)[field.id]
    # Arrange the current migrated generation; the original completion stays at 0.
    task._form_change_write = True
    task.db["generation"] = 1
    Entities.save_root(task, property_mask=("generation",))
    Entities.delete(form.entity)
    restored = Entities.fetch_one(task.key, request=Fetch.root())
    assert "Original instructions" in rendered_html_fields(restored, original=True)[field.id]
    assert _http(user, "GET", image_url).status_code == 200
    assert _http(outsider, "GET", image_url).status_code == 403
    archived = _http(user, "GET", f"/tasks/{task.urlsafe_key}/archived-submission")
    assert archived.status_code == 200
    assert _http(outsider, "GET", f"/tasks/{task.urlsafe_key}/archived-submission").status_code == 403
    assert archived.json()["generation"] == 1
    archived_html = archived.json()["html_fields"][field.id]
    assert "New active instructions" in archived_html
    current_image_url = BeautifulSoup(archived_html, "html.parser").find("img")["src"]
    assert "/form-generation/1/" in current_image_url
    assert _http(user, "GET", current_image_url).status_code == 200
    assert _http(outsider, "GET", current_image_url).status_code == 403


# @source src/script/views/builder/conditions/options.mjs::Options
# @source src/script/views/builder/conditions/columns.mjs::Columns
# @matrix forms : stable-identity builder-select-options builder-table-column builder-save builder-reload
# @matrix tasks forms : cache-invalidation live-metadata
# @template forms/builder.html::header
# @template pages/tasks.html::task_form
def test_saved_relabels_preserve_active_task_answers_and_conditions(get_user):
    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    channels = SchemaFields.SELECT.get(
        _id="channels", title="Contact channels", multiple=True,
        options=[{"value": "email-original", "label": "Email"},
                 {"value": "sms-original", "label": "SMS"}],
    )
    decision = SchemaFields.RADIO.get(
        _id="decision", title="Dispatch decision",
        options=[{"value": "approved-original", "label": "Approved"},
                 {"value": "hold-original", "label": "Hold"}],
    )
    column = SchemaFields.TEXT_INPUT.get(_id="item-original", title="Item")
    items = SchemaFields.TABLE.get(_id="items", title="Dispatch items", columns=[column])
    details = SchemaFields.TEXTAREA.get(
        _id="details", title="Email instructions", visibility=[{
            "id": channels.id, "name": channels.title, "type": "select",
            "value": "email-original", "label": "Email",
        }],
    )
    feedback = SchemaFields.STATUS.get(_id="feedback", title="Dispatch status", status=[{
        "id": decision.id, "name": decision.title, "type": "radio",
        "value": "approved-original", "label": "Approved", "text": "Ready for dispatch",
    }])
    form = Form(user=user, definition=FormDefinition(
        name=f"BSU identity preservation {uuid4().hex[:8]}", form_type="task",
        schema=(channels, decision, items, details, feedback),
    )).create()
    answers = {
        channels.id: ["email-original", "sms-original"],
        decision.id: "approved-original",
        items.id: {"rows": [{column.id: "Router"}, {column.id: "Spare cable"}]},
        details.id: "Use the saved delivery address",
    }
    task_entity = Entities.TASK.create({
        "name": "BSU active dispatch", "page": parent.entity, "form": form.entity,
        "submission": answers,
    })
    task_entity = Entities.fetch_one(task_entity, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
    task_entity.save()
    task = TaskResource(user=user)
    task.entity = task_entity

    def assert_active_answers(channel_label, decision_label, column_label):
        user.go(task)
        task_form = task.task_form
        selection = task_form.locator(f"select[name='{channels.id}']")
        expect(selection).to_have_values(answers[channels.id])
        expect(selection.locator("option:checked")).to_have_text([channel_label, "SMS"])
        selected_channels = task_form.locator(f"[id^='{channels.id}-'].form-element [data-role='read']")
        expect(selected_channels).to_contain_text(channel_label)
        expect(selected_channels).to_contain_text("SMS")
        radio = task_form.locator(f"[id^='{decision.id}-'].form-element")
        expect(radio.locator("[data-role='read']")).to_have_text(decision_label)
        radio.get_by_role("button", name=f"Edit {decision.title}", exact=True).click()
        expect(task_form.get_by_role("radio", name=decision_label, exact=True)).to_be_checked()
        expect(task_form.locator(f"input[name='{decision.id}'][value='approved-original']")).to_be_checked()
        table = task_form.locator(f"[id^='{items.id}-'].form-element")
        expect(table.locator("thead")).to_contain_text(column_label)
        expect(table.locator("tbody tr[data-index]")).to_have_count(2)
        expect(table.locator("tbody")).to_contain_text("Router")
        expect(table.locator("tbody")).to_contain_text("Spare cable")
        assert json.loads(table.locator(f"input[name='{items.id}']").input_value()) == answers[items.id]["rows"]
        visible_details = task_form.locator(f"[id^='{details.id}-'].form-element")
        expect(visible_details).to_have_attribute("data-visible", "true")
        expect(visible_details).to_be_visible()
        expect(task_form.locator(f"textarea[name='{details.id}']")).to_have_value(answers[details.id])
        status = task_form.locator("[data-kind='status']")
        expect(status).to_have_attribute("data-visible", "true")
        expect(status).to_contain_text("Ready for dispatch")

    assert_active_answers("Email", "Approved", "Item")
    builder = form.builder
    original_visibility = deepcopy(builder.schema_field(details.id)["visibility"])
    original_status = deepcopy(builder.schema_field(feedback.id)["status"])
    for field, old_label, new_label in (
        (channels, "Email", "Email delivery"),
        (decision, "Approved", "Cleared for dispatch"),
    ):
        builder.select_field(field)
        builder.settings.locator("[data-setting='options'] li").filter(has_text=old_label).locator("[data-role='open']").click()
        expect(builder.condition).to_be_visible()
        builder.condition.locator("input[name='option-name']").fill(new_label)
        builder.save_condition()
        builder.condition.locator("button[data-role='close']").click()
        expect(builder.condition).to_be_hidden()
    builder.select_field(items)
    builder.open_condition("columns", role="open")
    builder.condition.locator("input[name='column-name']").fill("Equipment")
    builder.save_condition()
    builder.condition.locator("button[data-role='close']").click()
    expect(builder.condition).to_be_hidden()
    builder.save()
    form.reload()
    reloaded = Builder(user)
    assert [option["value"] for option in reloaded.schema_field(channels.id)["options"]] == answers[channels.id]
    assert reloaded.schema_field(channels.id)["options"][0]["label"] == "Email delivery"
    assert reloaded.schema_field(decision.id)["options"][0]["value"] == answers[decision.id]
    assert reloaded.schema_field(decision.id)["options"][0]["label"] == "Cleared for dispatch"
    assert reloaded.schema_field(items.id)["columns"][0]["id"] == column.id
    assert reloaded.schema_field(items.id)["columns"][0]["title"] == "Equipment"
    assert reloaded.schema_field(details.id)["visibility"] == original_visibility
    assert reloaded.schema_field(feedback.id)["status"] == original_status
    persisted_task = Entities.fetch_one(task.key, request=Fetch.direct())
    assert not persisted_task.completed
    for field_id, value in answers.items():
        assert persisted_task.submission[field_id] == value
    assert_active_answers("Email delivery", "Cleared for dispatch", "Equipment")
