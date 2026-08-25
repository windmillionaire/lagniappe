import json
import re
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.entities import Entities
from testing.definitions import (
    CommonFormFields,
    Forms,
    PageFormFields,
    Schemas,
    SitePages,
    TaskFormFields,
    Users,
)
from testing.elements import Buttons, FormElements, Modal, SpinnerButtons, Table, Tools
from testing.resources.form import Builder
from testing.definitions.form_definitions import FormDefinition
from testing.resources import Form
from testing.utility import expect_reconnect_refresh


# @matrix forms : index tools
# @matrix indexes : fingerprint-gate rendering
# @matrix reconnect-refresh : fallback manifest root-fingerprint
# @template forms/index.html::view
def test_forms_index_page(get_user, browser_failures):
    user = get_user(Users.OWNER)
    user.go(SitePages.FORM_INDEX)

    expect(user.page).to_have_title(re.compile(r"Form Index"))
    expect(user.locate(Table.TABLE)).to_be_attached()
    expect(user.locate("button[lp-show='table:TableEditor']")).not_to_be_attached()

    external_form = Entities.FORM.create(
        {
            "name": f"Refresh Fingerprint Form {uuid4().hex}",
            "form-type": "page",
        }
    )
    external_form.save()
    try:
        with expect_reconnect_refresh(user, browser_failures):
            user.offline = False

        expect(Table(user).get_row(external_form.name)).to_be_visible()
    finally:
        Entities.delete(external_form)

    tools = Tools(user)
    tools.open()
    tools.close()


# @matrix forms : delete-modal instance-query preview-limit
# @template delete/form.html::instance_link
def test_form_delete_modal_lists_page_and_task_users(get_user):
    user = get_user(Users.OWNER)
    suffix = uuid4().hex
    form = Entities.FORM.create(
        {"name": f"Delete Usage Form {suffix}", "form-type": "page"}
    )
    category = Entities.CATEGORY.create(
        {
            "name": f"Delete Usage Category {suffix}",
            "attributes": ["tasks", "document", "notes", "files"],
        }
    )
    form.save()
    category.save()
    pages = []
    tasks = []

    try:
        for index in range(3):
            page = Entities.PAGE.create(
                {
                    "name": f"Delete Usage Page {index} {suffix}",
                    "model": category,
                    "form": form,
                }
            )
            page.save()
            pages.append(page)

        for index in range(3):
            task = Entities.TASK.create(
                {
                    "name": f"Delete Usage Task {index} {suffix}",
                    "page": pages[index],
                    "form": form,
                }
            )
            task.save()
            tasks.append(task)

        user.go(SitePages.FORM_INDEX)
        trigger = Table(user).get_row(form.name).locator(
            f"td[data-column='delete'] {Buttons.LP_DELETE}"
        )
        with user.page.expect_response(f"**/l/delete/{form.urlsafe_key}"):
            modal = Modal(user.page).open(trigger)

        links = modal.element.locator("a[data-role='title']")
        expect(links).to_have_count(5)
        expect(modal.element).to_contain_text("and 1 more")
        expect(
            modal.element.locator("a[data-role='title'][data-kind='page']")
        ).to_have_count(3)
        expect(
            modal.element.locator("a[data-role='title'][data-kind='task']")
        ).to_have_count(2)
        expected_links = [*pages, *tasks[:2]]
        expect(links).to_have_text([entity.name for entity in expected_links])
        for index, entity in enumerate(expected_links):
            link = links.nth(index)
            expect(link).to_have_attribute("data-kind", entity.kind)
            route = "pages" if entity.kind == "page" else "tasks"
            expect(link).to_have_attribute(
                "href", f"/{route}/{entity.urlsafe_key}"
            )

        modal.click("Cancel")
    finally:
        Entities.delete(*tasks)
        Entities.delete(*pages)
        Entities.delete(form, category)


def _create_form(user, form, create_form):
    with user.page.expect_response("**/create"):
        SpinnerButtons.CREATE.click(create_form)
    table = Table(user)
    new_row = table.new_row(form.definition.name)
    return new_row.get_attribute("data-key")


# @matrix forms : components create page-form
# @template forms/tools.html::create_form
# @template forms/builder.html::main
def test_create_page_form(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_create_page_form.get(user, create=False)
    form_index = user.go(SitePages.FORM_INDEX)
    create_form = form_index.create_form_form()
    create_form.locator(FormElements.NAME).fill(form.definition.name)
    create_form.locator(form_index.FORM_TYPE_PAGE).check()

    form.key = _create_form(user, form, create_form)

    builder = form.builder
    expect(user.page.locator(builder.FORM_NAME)).to_be_visible()
    expect(user.page.locator(builder.FORM_NAME)).to_have_text(form.definition.name)

    defaults = builder.default
    expect(defaults.locator("#name")).not_to_be_attached()
    expect(defaults.locator("#description")).not_to_be_attached()

    components = user.locate(builder.COMPONENTS_COLUMN)
    for element_type in CommonFormFields:
        expect(components.locator(element_type.value)).to_be_visible()
    for element_type in PageFormFields:
        expect(components.locator(element_type.value)).to_be_visible()


# @matrix forms : builder-defaults components create task-form
# @template forms/tools.html::create_form
# @template forms/builder.html::main
def test_create_task_form(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_create_task_form.get(user, create=False)
    form_index = user.go(SitePages.FORM_INDEX)
    create_form = form_index.create_form_form()
    create_form.locator(FormElements.NAME).fill(form.definition.name)
    create_form.locator(form_index.FORM_TYPE_TASK).check()

    form.key = _create_form(user, form, create_form)

    builder = form.builder
    expect(user.page.locator(builder.FORM_NAME)).to_be_visible()
    expect(user.page.locator(builder.FORM_NAME)).to_have_text(form.definition.name)

    defaults = builder.default
    expect(defaults.locator("#name")).not_to_be_attached()
    expect(defaults.locator("#description")).not_to_be_attached()

    components = user.locate(builder.COMPONENTS_COLUMN)
    for element_type in CommonFormFields:
        expect(components.locator(element_type.value)).to_be_visible()
    for element_type in TaskFormFields:
        expect(components.locator(element_type.value)).to_be_visible()


# @matrix entity-menu : builder-copy title-menu
# @matrix forms : builder-copy builder-form-name delete form-type navigation schema
# @pair frontend-icons:material-icon-preservation
# @template forms/builder.html::header
def test_copy_form_from_builder_title_menu(get_user):
    user = get_user(Users.OWNER)
    source = Form(
        user=user,
        definition=FormDefinition(
            name="Builder Copy Source",
            form_type="page",
            schema=Schemas.selection_types.get(),
        ),
    ).create()
    builder = source.builder
    source_schema = builder.schema

    actions = user.page.get_by_role("button", name="Form actions")
    actions.click()
    menu = user.page.get_by_role("menu", name="Form actions")
    expect(menu).to_be_visible()
    menu.get_by_role("menuitem", name="Delete Form").click()

    modal = Modal(user.page)
    expect(modal.element).to_be_visible()
    expect(modal.element).to_contain_text(source.definition.name)
    modal.click("Cancel")

    renamed = "Renamed Builder Copy Source"
    name_display = user.locate(Builder.FORM_NAME)
    name_display.click()
    name_input = user.locate("#form-name-input")
    expect(name_input).to_be_visible()
    name_input.fill(renamed)
    name_input.press("Enter")
    expect(name_display).to_have_text(renamed)

    menu_icon = actions.locator(".icon[data-icon='menu']")
    expect(menu_icon.locator(":scope > .icon-glyph")).to_have_text(
        "keyboard_arrow_down"
    )
    assert menu_icon.locator(":scope > .icon-glyph").evaluate(
        "(glyph) => glyph.scrollWidth <= glyph.parentElement.clientWidth + 1"
    )

    actions.click()
    menu = user.page.get_by_role("menu", name="Form actions")
    copy_action = menu.get_by_role("menuitem", name="Copy Form")
    expect(copy_action).to_be_visible()
    expect(copy_action).to_have_attribute("data-kind", "form")
    expect(copy_action.locator('.icon[data-icon="form"]')).to_have_count(1)
    with user.page.expect_response("**/forms/*/copy"):
        copy_action.click()

    expect(user.locate(Builder.FORM_NAME)).to_have_text(f"Copy of {renamed}")
    copied_view = user.locate("[lp-view][data-kind='builder']")
    expect(copied_view).to_have_attribute("initialized", "")
    expect(copied_view).not_to_have_attribute("data-key", source.key)
    expect(copied_view).to_have_attribute("data-form-type", "page")
    assert Builder(user).schema == source_schema


# @matrix forms : builder-add-inputs builder-reload builder-save
def test_add_inputs_to_form(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_add_inputs_to_form.get(user)
    schema = Schemas.add_inputs.get()

    builder = form.builder
    for field in schema:
        builder.add_field(field)

    expect(user.page.locator(builder.UNSAVED)).to_be_visible()
    expect(user.locate(builder.SAVE_BUTTON)).to_have_attribute("data-kind", "unsaved")
    builder.save()

    expect(user.locate(builder.SAVE_BUTTON)).to_have_attribute("data-kind", "saved")

    user.page.reload()
    builder = Builder(user)
    for field in schema:
        element = field.locate(builder.model)
        expect(element).to_be_visible()


# @matrix ai forms : generate-schema live-ai reload saved-state
# @template forms/builder.html::generate
@pytest.mark.ai
def test_generate_form_schema_live_saved_state(get_user, request):
    """
    Make one real provider call through the form builder Generate path.

    The generated schema is saved by ``/forms/create-schema``. The builder should
    therefore show the saved state immediately and keep the generated fields
    after reload. The ``ai`` mark saves the prompt and response under
    reports/test_reports/ for review.
    """
    user = get_user(Users.OWNER)
    form = Form(
        user=user,
        definition=FormDefinition(
            name="Live AI Generated Schema Form",
            form_type="page",
        ),
    ).create()

    builder = form.builder
    prompt = (
        "Create a compact volunteer intake form with full name, email, "
        "phone number, preferred role, availability, and notes."
    )

    report = request.node.ai_results
    report.record("form", {"name": form.definition.name, "key": form.key})
    report.record("prompt", prompt)

    user.locate("button[data-role='generate']").click()
    generate = user.locate("form#generate")
    expect(generate).to_be_visible()
    generate.locator("textarea[name='description']").fill(prompt)

    with user.page.expect_response("**/forms/create-schema", timeout=90000) as response:
        generate.locator("button[type='submit']").click()

    generated_response = response.value
    response_text = generated_response.text()
    report.record("response_status", generated_response.status)
    report.record("response_body", response_text)

    assert generated_response.ok, response_text
    response_body = json.loads(response_text)
    schema = response_body["schema"]
    default_schema = [
        field for field in schema if field["id"] in {"name", "description"}
    ]
    generated_schema = [
        field for field in schema if field["id"] not in {"name", "description"}
    ]
    report.record("schema", schema)

    expect(generate).to_be_hidden()
    expect(user.locate(builder.SAVE_BUTTON)).to_have_attribute("data-saved", "true")
    assert builder.schema == schema
    expect(builder.default.locator(".form-element")).to_have_count(
        len(default_schema)
    )
    expect(builder.model.locator(".form-element")).to_have_count(
        len(generated_schema)
    )

    user.page.reload()
    builder = Builder(user)
    expect(user.locate(builder.SAVE_BUTTON)).to_have_attribute("data-saved", "true")
    assert builder.schema == schema
    expect(builder.default.locator(".form-element")).to_have_count(
        len(default_schema)
    )
    expect(builder.model.locator(".form-element")).to_have_count(
        len(generated_schema)
    )


# @matrix forms : builder-add-fields builder-reload builder-save
def test_add_fields_to_form(get_user):
    user = get_user(Users.OWNER)
    form = Forms.test_add_fields_to_form.get(user)
    schema = Schemas.add_fields.get()

    builder = form.builder
    for field in schema:
        builder.add_field(field)

    expect(user.page.locator(builder.UNSAVED)).to_be_visible()
    builder.save()

    user.page.reload()
    builder = Builder(user)
    for field in schema:
        element = field.locate(builder.model)
        expect(element).to_be_visible()
