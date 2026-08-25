from types import SimpleNamespace
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Forms, Pages, Schemas, Uploads, Users
from testing.definitions.form_definitions import FormDefinition
from testing.definitions.schema_fields import SchemaFields
from testing.definitions.user_definitions import UserDefinition
from testing.elements import EditorAddImage, Select, SpinnerButtons
from testing.resources.form import Builder, Form
from testing.resources.task import Task as TaskResource

pytestmark = pytest.mark.e2e


def _close_condition(builder):
    builder.condition.locator("button[data-role='close']").click()
    expect(builder.condition).not_to_be_visible()


def _condition_select(builder, name, index=0):
    Select(builder.condition.locator("[data-combobox-id]").nth(index)).select_by_name(
        name
    )


def _condition_error(builder):
    return builder.condition.locator("[data-role='error']")


def _option_labels(field):
    return [option["label"] for option in field.get("options", [])]


def _save_select_option(builder, label):
    success = builder.condition.locator(
        "[data-role='title'] [data-kind='success']"
    )
    expect(success).not_to_be_attached()
    builder.condition.locator("button[data-role='save']").click()
    expect(success).to_be_visible()
    expect(
        builder.settings.locator("[data-setting='options']")
    ).to_contain_text(label, timeout=15_000)


def _custom_schema(builder):
    return [
        field
        for field in builder.schema
        if field.get("id") not in {"name", "description"}
    ]


def _html_editor_text_entry(builder):
    editor = builder.condition.locator("[data-role='editor']")
    expect(editor).to_be_visible()
    expect(editor).to_have_attribute("loaded", "")
    text_entry = editor.locator(".ProseMirror")
    expect(text_entry).to_have_attribute("contenteditable", "true")
    return text_entry


def _set_forms_permission(user, action):
    entity = Entities.USER.load(user.email)
    entity.permissions = {**entity.permissions, "forms": action.name}
    entity.save()
    user.entity = entity


# @pair forms:builder-preview
# @template forms/builder.html::header
def test_preview_panel(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_preview_panel.get(user)
    form.schema = Schemas.add_fields.get()

    builder = form.builder
    preview_panel = builder.toggle_preview()
    preview_toggle = user.locate(builder.PREVIEW_TOGGLE)
    expect(preview_toggle).to_have_attribute("data-active", "true")
    expect(preview_toggle).to_have_attribute("aria-checked", "true")

    for field_title in ["Name", "Reason For Living", "Subscribe to Newsletter"]:
        expect(preview_panel).to_contain_text(field_title)

    preview_toggle.click()
    expect(preview_panel).to_be_hidden()
    expect(preview_toggle).to_have_attribute("data-active", "false")
    expect(preview_toggle).to_have_attribute("aria-checked", "false")


# @pair forms:builder-delete-components
def test_delete_components(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_delete_components.get(user)
    builder = form.builder

    deleted = builder.model.locator(".form-element").filter(
        has_text="Reason For Living"
    )
    expect(deleted).to_be_visible()
    deleted.click()

    builder.settings.locator("button[data-role='delete']").click()

    expect(
        builder.model.locator(".form-element").filter(has_text="Reason For Living")
    ).not_to_be_attached()
    assert builder.schema_field(title="Reason For Living") is None

    builder.save()
    user.page.reload()
    builder = Builder(user)
    expect(
        builder.model.locator(".form-element").filter(has_text="Reason For Living")
    ).not_to_be_attached()


# @matrix forms : builder-field-title builder-select-options
# @pair frontend-icons:material-icon-preservation
def test_change_select_options(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_change_select_options.get(user)
    builder = form.builder
    field = SchemaFields.SELECT.get(title="Snack Choice")
    builder.add_field(field)

    label = field.element.locator("[data-role='label']").first
    expect(label.locator(":scope > span:not([data-icon])")).to_have_text(field.title)
    expect(label.locator(":scope > [data-icon='select'] .icon-glyph")).to_be_visible()

    builder.open_condition("options")
    for option in ["Apple", "Banana"]:
        option_name = builder.condition.locator("input[name='option-name']")
        option_name.fill(option)
        _save_select_option(builder, option)
        expect(builder.condition.locator("input[name='option-name']")).to_be_focused()
    _close_condition(builder)

    assert _option_labels(builder.schema_field(field.id)) == ["Apple", "Banana"]

    builder.settings.locator(
        "[data-setting='options'] li:has-text('Apple') [data-role='open']"
    ).click()
    option_name = builder.condition.locator("input[name='option-name']")
    expect(option_name).to_have_value("Apple")
    option_name.fill("Apricot")
    _save_select_option(builder, "Apricot")
    _close_condition(builder)

    builder.open_condition("options")
    builder.condition.locator("input[name='option-name']").fill("Cherry")
    _save_select_option(builder, "Cherry")
    _close_condition(builder)

    assert _option_labels(builder.schema_field(field.id)) == [
        "Apricot",
        "Banana",
        "Cherry",
    ]
    expect(builder.settings.locator("[data-setting='options']")).to_contain_text(
        "Apricot"
    )
    expect(builder.settings.locator("[data-setting='options']")).to_contain_text(
        "Cherry"
    )

    builder.save()
    user.page.reload()
    builder = Builder(user)
    builder.select_field(field)
    assert _option_labels(builder.schema_field(field.id)) == [
        "Apricot",
        "Banana",
        "Cherry",
    ]


# @pair forms:builder-field-visibility
def test_field_visibility(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_field_visibility.get(user)
    builder = form.builder
    checkbox = SchemaFields.CHECKBOX.get(title="Show Private Notes")
    notes = SchemaFields.TEXTAREA.get(title="Private Notes")

    builder.add_field(checkbox)
    builder.add_field(notes)
    builder.open_condition("visibility")
    _condition_select(builder, checkbox.title)
    expect(builder.condition).to_contain_text("is checked")
    builder.save_condition()
    _close_condition(builder)

    visibility = builder.schema_field(notes.id)["visibility"][0]
    assert visibility["id"] == checkbox.id
    assert visibility["name"] == checkbox.title
    assert visibility["type"] == "checkbox"
    assert visibility["checked"] is True

    preview = builder.toggle_preview()
    target = preview.locator(f"[id^='{notes.id}-']")
    expect(target).to_have_attribute("data-visible", "false")
    preview.locator(f"[id^='{checkbox.id}-'] input[type='checkbox']").check()
    expect(target).to_have_attribute("data-visible", "true")

    builder.save()
    user.page.reload()
    builder = Builder(user)
    builder.select_field(notes)
    expect(builder.settings.locator("[data-setting='visibility']")).to_contain_text(
        checkbox.title
    )


# @matrix forms : builder-field-visibility select-or-values
def test_field_visibility_select_multiple_values(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_field_visibility_select_multiple_values.get(user)
    builder = form.builder
    color = SchemaFields.SELECT.get(title="Color")
    notes = SchemaFields.TEXTAREA.get(title="Color Notes")

    builder.add_field(color)
    for option in ["Red", "Blue", "Green"]:
        builder.open_condition("options")
        builder.condition.locator("input[name='option-name']").fill(option)
        _save_select_option(builder, option)
        _close_condition(builder)

    assert _option_labels(builder.schema_field(color.id)) == ["Red", "Blue", "Green"]

    builder.add_field(notes)
    for option in ["Red", "Blue"]:
        builder.open_condition("visibility")
        _condition_select(builder, color.title)
        _condition_select(builder, option, index=1)
        builder.save_condition()
        _close_condition(builder)

    visibility = builder.schema_field(notes.id)["visibility"]
    assert [condition["label"] for condition in visibility] == ["Red", "Blue"]

    preview = builder.toggle_preview()
    target = preview.locator(f"[id^='{notes.id}-']")
    expect(target).to_have_attribute("data-visible", "false")

    preview_select = Select(preview.locator(f"[id^='{color.id}-']"))
    preview_select.select_by_name("Red")
    expect(target).to_have_attribute("data-visible", "true")
    preview_select.select_by_name("Green")
    expect(target).to_have_attribute("data-visible", "false")
    preview_select.select_by_name("Blue")
    expect(target).to_have_attribute("data-visible", "true")


# @pair forms:builder-table-column
def test_table_column_condition_editor(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_table_column_condition_editor.get(user)
    builder = form.builder
    table = SchemaFields.TABLE.get(title="Line Items")
    builder.add_field(table)

    builder.open_condition("columns")
    _condition_select(builder, "Text")
    column_name = builder.condition.locator("input[name='column-name']")
    column_name.fill("Quantity")
    builder.save_condition()
    expect(builder.condition.locator("[data-combobox-id] input")).to_be_focused()
    _close_condition(builder)

    builder.settings.locator(
        "[data-setting='columns'] [data-role='open']:has-text('Quantity')"
    ).click()
    column_name = builder.condition.locator("input[name='column-name']")
    column_name.fill("")
    builder.condition.locator("button[data-role='save']").click()
    expect(_condition_error(builder)).to_contain_text("Please enter a column name")
    column_name.fill("Amount")
    column_type = Select(builder.condition.locator("[data-combobox-id]"))
    column_type.select_by_key("number")
    expect(column_type.input).to_have_attribute("placeholder", "Number")
    builder.save_condition()
    _close_condition(builder)

    column_setting = builder.settings.locator(
        "[data-setting='columns'] [data-role='open']"
    ).filter(has_text="Amount")
    expect(column_setting).to_be_visible()
    expect(column_setting.locator("[data-icon='number']")).to_be_visible()

    builder.save()
    user.page.reload()
    builder = Builder(user)
    builder.select_field(table)
    saved_column = builder.settings.locator(
        "[data-setting='columns'] [data-role='open']"
    ).filter(has_text="Amount")
    expect(saved_column).to_be_visible()
    expect(saved_column.locator("[data-icon='number']")).to_be_visible()


# @pair forms:builder-status-message
def test_status_message_condition_editor(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_status_message_condition_editor.get(user)
    builder = form.builder
    approved = SchemaFields.CHECKBOX.get(title="Approved")
    status = SchemaFields.STATUS.get(title="Approval Feedback")

    builder.add_field(approved)
    builder.add_field(status)

    preview = builder.toggle_preview()
    empty_status_message = preview.locator("[data-kind='status']")
    expect(empty_status_message).to_have_attribute("data-visible", "false")
    expect(empty_status_message.locator("input[type='hidden']")).to_have_count(1)
    user.page.locator(builder.PREVIEW_TOGGLE).click()
    expect(preview).to_have_attribute("data-visible", "false")
    builder.select_field(status)

    builder.open_condition("status")
    _condition_select(builder, approved.title)
    message = builder.condition.locator("input[name='status-message']")
    message.fill("Ready to submit")
    builder.save_condition()
    _close_condition(builder)

    builder.settings.locator(
        "[data-setting='status'] [data-role='open']:has-text('Approved')"
    ).click()
    message = builder.condition.locator("input[name='status-message']")
    message.fill("")
    builder.condition.locator("button[data-role='save']").click()
    expect(_condition_error(builder)).to_contain_text(
        "Please enter a status message"
    )
    message.fill("Approved and ready")
    builder.save_condition()
    _close_condition(builder)

    status_schema = builder.schema_field(status.id)["status"][0]
    assert status_schema["id"] == approved.id
    assert status_schema["name"] == approved.title
    assert status_schema["type"] == "checkbox"
    assert status_schema["checked"] is True
    assert status_schema["text"] == "Approved and ready"

    preview = builder.toggle_preview()
    status_message = preview.locator("[data-kind='status']")
    expect(status_message).to_have_attribute("data-visible", "false")
    preview.locator(f"[id^='{approved.id}-'] input[type='checkbox']").check()
    expect(status_message).to_have_attribute("data-visible", "true")
    expect(status_message).to_contain_text("Approved and ready")

    builder.save()
    user.page.reload()
    builder = Builder(user)
    builder.select_field(status)
    expect(builder.settings.locator("[data-setting='status']")).to_contain_text(
        "Approved"
    )


# @matrix forms signature : builder-preview builder-signature-field unique-component
def test_signature_field_builder_unique_component(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_signature_field_builder_unique_component.get(user)
    builder = form.builder
    signature = SchemaFields.SIGNATURE.get(title="Customer Signature")
    builder.add_field(signature)

    assert builder.schema_field(signature.id)["type"] == "signature"

    signature_component = builder.components.locator(signature.component)
    signature_component.hover()
    add_button = signature_component.locator(builder.ADD_BUTTON)
    expect(add_button).to_be_visible()
    add_button.click()
    expect(builder.model.locator("[id^='signature']")).to_have_count(1)
    expect(user.locate("#notification")).to_contain_text(
        "Only one signature element is allowed per form"
    )

    preview = builder.toggle_preview()
    expect(preview.locator(f"[id^='{signature.id}-']")).to_contain_text(
        "Customer Signature"
    )

    builder.save()
    user.page.reload()
    builder = Builder(user)
    expect(builder.model.locator(f"[id='{signature.id}']")).to_be_visible()


# @matrix html-field : asset-lifecycle builder-html-field form-asset image-upload render-fetch submitter-key unsaved-schema
def test_html_field(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_html_field.get(user)
    builder = form.builder
    html = SchemaFields.HTML.get(title="Instructions")
    builder.add_field(html)

    text_entry = _html_editor_text_entry(builder)
    text = "Use this form carefully."
    text_entry.press_sequentially(text)

    editor = SimpleNamespace(
        toolbar=builder.condition.locator("[data-role='toolbar']")
    )
    image_form = EditorAddImage(editor).form
    with user.page.expect_response(
        f"**/assets/{form.key}/document/image?field={html.id}"
    ):
        Uploads.editor_test_image.set(image_form)
        SpinnerButtons.UPLOAD.click(image_form)
    expect(text_entry.locator("img")).to_be_visible()

    text_entry.click()
    with user.page.expect_response(f"**/assets/{form.key}/form-html/{html.id}"):
        text_entry.blur()
    _close_condition(builder)

    assert builder.schema_field(html.id)["type"] == "html"
    preview = builder.toggle_preview()
    expect(preview.locator(".html-content")).to_contain_text(text)
    expect(preview.locator(".html-content img")).to_be_visible()

    builder.save()

    saved_form = Entities.fetch_one(form.key, request=Fetch.root())
    assets = saved_form.assets
    image_assets = [
        key for key in assets if key.startswith(f"image_{html.id}_")
    ]
    assert assets[html.id]["type"] == "html"
    assert len(image_assets) == 1
    assert assets[image_assets[0]]["type"] == "image"
    assert image_assets[0] in saved_form.get_html_field(html.id)

    user.page.reload()
    builder = Builder(user)
    builder.select_field(html)
    builder.open_condition("html", role="edit")
    text_entry = _html_editor_text_entry(builder)
    expect(text_entry).to_contain_text(text)

    page = Pages.test_create_page_task.get(user)
    task_entity = Entities.TASK.create(
        {
            "name": "HTML Instructions Render Task",
            "description": "",
            "page": page.entity,
            "form": saved_form,
        }
    )
    task_entity.save()

    user.go(page)
    page.task_list
    task = TaskResource(user=user)
    task.entity = task_entity
    with user.page.expect_response(
        f"**/assets/{task_entity.urlsafe_key}/html/{html.id}"
    ):
        task_form = task.task_form

    html_content = task_form.locator(".html-content")
    expect(html_content).to_contain_text(text)
    expect(html_content.locator("img")).to_be_visible()


# @matrix editor : authoritative-content error-reporting initial-load intentional-clear retry server-acknowledgement
# @matrix html-field : authoritative-content builder-html-field error-reporting form-asset initial-load intentional-clear retry server-acknowledgement
# @style message
# @style editor.container
def test_html_editor_recovers_from_failed_load_and_save(
    get_user, browser_failures
):
    owner = get_user(Users.OWNER)
    html = SchemaFields.HTML.get(title="Resilient instructions")
    form = Form(
        user=owner,
        definition=FormDefinition(
            name="Builder HTML Persistence Recovery",
            form_type="task",
            schema=(html,),
        ),
    ).create()
    user = get_user(
        UserDefinition(
            name="Builder HTML Recovery Editor",
            email=f"builder-html-recovery-{uuid4().hex}@example.test",
        ),
        creator=owner,
    )
    _set_forms_permission(user, Action.EDIT)
    form.user = user
    builder = form.builder
    load_path = f"/assets/{form.key}/html/{html.id}"
    _set_forms_permission(user, Action.NONE)
    with browser_failures.expect_http_error(user, status=403, path=load_path):
        with user.page.context.expect_event(
            "response",
            predicate=lambda response: response.url.endswith(load_path)
            and response.request.method == "GET"
            and response.status == 403,
        ):
            builder.select_field(html)
            builder.open_condition("html", role="edit")

        status = builder.condition.locator("[data-role='editor-status']")
        editor = builder.condition.locator("[data-role='editor']")
        expect(status).to_be_visible()
        expect(status).to_contain_text("Error 403")
        expect(editor).to_have_attribute("inert", "")
        expect(editor).not_to_have_attribute("aria-busy", "true")
        expect(editor.locator(".ProseMirror")).to_have_count(0)

    _set_forms_permission(user, Action.EDIT)
    with user.page.context.expect_event(
        "response",
        predicate=lambda response: response.url.endswith(load_path)
        and response.request.method == "GET"
        and response.status == 200,
    ):
        status.locator("[data-role='retry']").click()

    text_entry = _html_editor_text_entry(builder)
    expect(status).to_be_hidden()

    save_path = f"/assets/{form.key}/form-html/{html.id}"
    text = "Retry this durable text."
    text_entry.press_sequentially(text)
    _set_forms_permission(user, Action.VIEW)
    with browser_failures.expect_http_error(user, status=403, path=save_path):
        with user.page.context.expect_event(
            "response",
            predicate=lambda response: response.url.endswith(save_path)
            and response.request.method == "PUT"
            and response.status == 403,
        ):
            text_entry.blur()

        expect(status).to_be_visible()
        expect(status).to_contain_text("Error 403")

    _set_forms_permission(user, Action.EDIT)
    with user.page.context.expect_event(
        "response",
        predicate=lambda response: response.url.endswith(save_path)
        and response.request.method == "PUT"
        and response.status == 200,
    ):
        status.locator("[data-role='retry']").click()
    expect(status).to_be_hidden()

    saved_form = Entities.fetch_one(form.key, request=Fetch.root())
    assert text in saved_form.get_html_field(html.id)

    text_entry.click()
    text_entry.press("Control+A")
    text_entry.press("Backspace")
    with user.page.context.expect_event(
        "response",
        predicate=lambda response: response.url.endswith(save_path)
        and response.request.method == "PUT"
        and response.status == 200
    ):
        text_entry.blur()

    cleared_form = Entities.fetch_one(form.key, request=Fetch.root())
    assert cleared_form.get_html_field(html.id) is None


# @pair forms:builder-drag-component
def test_drag_component(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_drag_component.get(user)
    builder = form.builder

    textarea_component = builder.components.locator("[data-type='textarea']")
    checkbox_component = builder.components.locator("[data-type='checkbox']")
    textarea_component.drag_to(builder.model)
    checkbox_component.drag_to(builder.model)

    expect(builder.model.locator(".form-element")).to_have_count(2)
    assert [field["type"] for field in _custom_schema(builder)] == [
        "textarea",
        "checkbox",
    ]

    checkbox = builder.model.locator(".form-element").nth(1)
    checkbox.drag_to(builder.model.locator(".form-element").first)
    assert [field["type"] for field in _custom_schema(builder)] == [
        "checkbox",
        "textarea",
    ]
