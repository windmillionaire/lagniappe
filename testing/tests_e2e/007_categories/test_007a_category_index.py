"""
Tests for the Category index page (/categories/{key}).

Tests page listing, page creation (manual/AI), category settings, and filtering.
Verified against:
- lagniappe/templates/categories/index.html
- lagniappe/templates/categories/tools.html
- src/script/views/category.mjs
- src/script/widgets/category.mjs
"""

import json
from uuid import uuid4

from playwright.sync_api import expect

from lagniappe.core.entities import Entities
from testing.definitions import Categories, Forms, Pages, Users
from testing.elements import (
    Attributes,
    Buttons,
    FormElements,
    FormSelect,
    Modal,
    SpinnerButtons,
    Table,
)
from testing.utility import expect_reconnect_refresh


def _create_page(user, page, create_form):
    with user.page.expect_response("**/create") as response_info:
        SpinnerButtons.CREATE.click(create_form)

    table = Table(user)
    new_row = table.new_row(page.definition.name)
    return new_row.get_attribute("data-key"), response_info.value


def _response_entity_fingerprint(response, key):
    revisions = json.loads(
        response.headers["x-lagniappe-entity-revisions"]
    )
    matches = [revision for revision in revisions if revision["key"] == key]
    assert len(matches) == 1
    return matches[0]["fingerprint"]


def _fill_editable_field(form, field_id, selector, value):
    field = form.locator(f"#{field_id}")
    control = field.locator(selector)
    if not control.is_visible():
        field.locator("[data-role='label']").click()
    expect(control).to_be_visible()
    control.fill(value)


def _view_hash(user):
    return user.locate("[lp-view][data-kind='category']").get_attribute("data-hash")


def _clear_column_prefs(user, category_hash):
    user.page.evaluate(
        """([columnsKey, sortsKey]) => {
            localStorage.removeItem(columnsKey);
            sessionStorage.removeItem(sortsKey);
        }""",
        [f"columns-{category_hash}", f"sorts-{category_hash}"],
    )


def _open_visibility_panel(user, category):
    toggle = user.locate(category.TABLE_VISIBILITY_TOGGLE)
    expect(toggle).to_be_visible()
    toggle.click()
    panel = user.locate(category.TABLE_VISIBILITY_PANEL)
    expect(panel).to_be_visible()
    return panel


# @features pages
# @dimensions create category-index
def test_create_page_from_category_index(get_user):
    user = get_user(Users.OWNER)
    category = Categories.test_empty_category.get(user)
    page = Pages.test_create_page.get(user, create=False)
    user.go(category)

    create_form = category.new_page_form()

    create_form.locator(FormElements.NAME).fill(page.definition.name)
    create_form.locator(FormElements.DESCRIPTION).fill(page.definition.description)

    page.key, response = _create_page(user, page, create_form)
    fingerprint = _response_entity_fingerprint(response, category.key)
    expect(user.locate("[lp-view][lp-entity]")).to_have_attribute(
        "data-fingerprint", fingerprint
    )


# @pair category-index:refresh
# @pair reconnect-refresh:category-index
# @pair reconnect-refresh:component-identity
# @template table.html::row
def test_category_index_reconnect_refreshes_external_page(get_user, browser_failures):
    user = get_user(Users.OWNER)
    category = Categories.test_empty_category.get(user)
    user.go(category)

    root = user.locate("[lp-view]")
    fingerprint = root.get_attribute("data-fingerprint")
    assert fingerprint
    external_page = Entities.PAGE.create(
        {
            "name": f"Reconnect Refresh Page {uuid4().hex}",
            "model": category.entity,
        }
    )
    external_page.save()
    try:
        with expect_reconnect_refresh(user, browser_failures) as refresh_info:
            user.offline = False

        request_payload = json.loads(refresh_info.value.request.post_data or "{}")
        assert request_payload["view"]["key"] == category.key
        assert request_payload["view"]["fingerprint"] == fingerprint
        assert {target["id"] for target in request_payload["targets"]} == {"table"}
        assert set(request_payload["targets"][0]) == {"id", "rows"}

        payload = refresh_info.value.json()
        assert payload["fingerprint"] != fingerprint
        table_refresh = next(target for target in payload["targets"] if target["id"] == "table")
        assert table_refresh["fallback"] is False
        assert external_page.urlsafe_key in {
            row["key"] for row in table_refresh["upsert"]
        }
        expect(root).to_have_attribute("data-fingerprint", payload["fingerprint"])
        expect(Table(user).get_row(external_page.name)).to_be_visible()
    finally:
        Entities.delete(external_page)


# @features pages
# @dimensions autofill create deferred deferred-submit
# @template categories/tools.html::create_page
def test_create_page_autofill_is_deferred(get_user):
    """Category-tool autofill persists the page and queues its form fill."""
    user = get_user(Users.OWNER)
    category = Categories.test_create_page.get(user)
    user.go(category)

    create_form = category.new_page_form()
    expect(create_form).to_have_attribute("lp-deferred", "")
    create_form.locator(FormElements.NAME).fill("Deferred Create Autofill")
    create_form.locator("[data-role='show-autofill']").click()
    create_form.locator("textarea[name='autofill-description']").fill(
        "Use the available page context to fill the attached form."
    )

    with user.page.expect_response("**/create") as response_info:
        create_form.locator("button[data-role='autofill-submit']").click()

    payload = response_info.value.json()
    assert payload["deferred"] is True
    assert "locked" not in payload
    assert "Autofilling page" in payload["notification"]


# @pair categories:info-form
# @pair categories:update
# @pair web-headers:local-save
# @pair web-headers:acknowledgement
# @pair web-headers:entity-revision
# @template categories/index.html::view_header
def test_update_category_info_from_tools(get_user):
    user = get_user(Users.OWNER)
    category = Categories.test_category_info_update.get(user)
    updated_form = Forms.test_create_page_form.get(user)
    user.go(category)
    expect(user.page.get_by_role("button", name="Category actions")).to_be_visible()

    info_form = category.category_info_form()

    updated_name = "Updated Category Info"
    updated_description = "A category updated through the tools panel."
    _fill_editable_field(info_form, "name", FormElements.NAME, updated_name)
    _fill_editable_field(
        info_form,
        "description",
        FormElements.DESCRIPTION,
        updated_description,
    )
    expect(info_form.locator("[data-icon='builder.unsaved']")).to_be_visible()
    FormSelect(info_form).select(updated_form)
    Attributes(info_form).set_selected("files", False)

    with user.page.expect_response("**/update") as response_info:
        SpinnerButtons.UPDATE.click(info_form)

    response = response_info.value
    fingerprint = _response_entity_fingerprint(response, category.key)
    expect(user.locate("[lp-view][lp-entity]")).to_have_attribute(
        "data-fingerprint", fingerprint
    )
    expect(user.locate("[data-nav='view'] [data-role='title']")).to_have_text(
        updated_name
    )
    expect(info_form.locator("#name")).to_contain_text(updated_name)
    expect(info_form.locator("#description")).to_contain_text(updated_description)
    FormSelect(info_form).contains(updated_form)
    Attributes(info_form).expect_selected("files", False)


# @features pages
# @dimensions create category-index related-forms
def test_create_page_related_form_badge_selects_form(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_category_filter_related_form_registration_page.get(user)
    category = page.definition.category.get(user)
    related_form = page.definition.form.get(user)
    user.go(category)

    create_form = category.new_page_form()
    related_forms = create_form.locator("[data-role='related-forms']")
    expect(related_forms).to_be_visible()

    badge = related_forms.locator(
        "[data-role='related-form']",
        has_text=related_form.definition.name,
    )
    expect(badge).to_have_attribute("data-selected", "false")

    badge.click()

    expect(badge).to_have_attribute("data-selected", "true")
    FormSelect(create_form).contains(related_form)
    FormSelect(create_form).clear()
    expect(badge).to_have_attribute("data-selected", "false")

    badge.click()
    FormSelect(create_form).contains(related_form)

    created_name = "Related Form Badge Page"
    create_form.locator(FormElements.NAME).fill(created_name)
    create_form.locator(FormElements.DESCRIPTION).fill(
        "Created with a related form badge."
    )

    with user.page.expect_response("**/create"):
        SpinnerButtons.CREATE.click(create_form)

    Table(user).new_row(created_name)


# @features category-index
# @dimensions quick-edit editable-cell
def test_category_index_quick_edit_updates_text_cell(get_user):
    """Quick edit can update and persist an editable category-index text cell."""
    user = get_user(Users.OWNER)
    page = Pages.test_basic_input_submission.get(user)
    category = page.definition.category.get(user)
    user.go(category)

    row = user.locate(f"{category.TABLE} tbody tr[data-key='{page.key}']")
    expect(row).to_be_visible()

    edit_toggle = user.locate("button[lp-show='table:TableEditor']")
    expect(edit_toggle).to_be_visible()
    edit_toggle.click()

    body = user.locate(category.TABLE_BODY)
    expect(body).to_have_attribute("data-editing", "true")

    cell = row.locator("td[data-column='name']")
    expect(cell).to_have_attribute("data-editable", "true")
    cell.click()

    name_input = cell.locator("input[name='name']")
    expect(name_input).to_be_visible()

    updated_name = "Category Index Quick Edit Updated"
    name_input.fill(updated_name)
    with user.page.expect_response("**/pages/*/patch"):
        name_input.press("Enter")

    expect(cell).to_contain_text(updated_name)
    user.reload(category)

    row = user.locate(f"{category.TABLE} tbody tr[data-key='{page.key}']")
    expect(row.locator("td[data-column='name']")).to_contain_text(updated_name)


# @features category-index
# @dimensions quick-edit checkbox-cell
def test_category_index_quick_edit_renders_checkbox_cells(get_user):
    """Quick edit renders visible checkbox columns immediately and saves toggles."""
    user = get_user(Users.OWNER)
    page = Pages.test_category_filter_match_page.get(user)
    category = page.definition.category.get(user)
    user.go(category)
    _clear_column_prefs(user, _view_hash(user))
    user.reload(category)

    field = "category-filter-flagged"
    panel = _open_visibility_panel(user, category)
    visible_toggle = panel.locator(f"input[type='checkbox'][name='{field}']")
    expect(visible_toggle).to_be_visible()
    visible_toggle.set_checked(True)

    row = user.locate(f"{category.TABLE} tbody tr[data-key='{page.key}']")
    expect(row).to_be_visible()
    cell = row.locator(f"td[data-column='{field}']")
    expect(cell).to_be_visible()

    edit_toggle = user.locate("button[lp-show='table:TableEditor']")
    expect(edit_toggle).to_be_visible()
    edit_toggle.click()

    body = user.locate(category.TABLE_BODY)
    expect(body).to_have_attribute("data-editing", "true")

    checkbox = cell.locator(f"input[type='checkbox'][name='{field}']")
    expect(checkbox).to_be_visible()
    expect(checkbox).to_be_checked()

    with user.page.expect_response("**/pages/*/patch"):
        checkbox.set_checked(False)

    expect(checkbox).not_to_be_checked()
    expect(cell).to_have_attribute("data-edit-value", "false")

    edit_toggle.click()
    expect(
        cell.locator(f"input[type='checkbox'][name='{field}']")
    ).not_to_be_attached()


# @features form-table table-controls
# @dimensions table-cell-expand form-table-column
# @template cell.html::table_cell
# @template controls.html::expand
def test_category_index_expands_table_submission_cell(get_user):
    """A category row with a table-valued submission expands in-place."""
    user = get_user(Users.OWNER)
    page = Pages.test_category_table_expansion.get(user)
    category = page.definition.category.get(user)
    user.go(category)
    _clear_column_prefs(user, _view_hash(user))
    user.reload(category)

    panel = _open_visibility_panel(user, category)
    items = panel.locator("input[type='checkbox'][name='items']")
    expect(items).to_be_visible()
    items.set_checked(True)

    row = user.locate(f"{category.TABLE} tbody tr[data-key='{page.key}']")
    expect(row).to_be_visible()
    cell = row.locator("td[data-column='items']")
    expect(cell).to_be_visible()
    expect(cell).to_contain_text("1 row")

    expand = cell.locator("button[data-role='expand']")
    expect(expand).to_be_visible()
    with user.page.expect_response("**/forms/*/expand-table-cell/items"):
        expand.click()

    expect(expand).to_have_attribute("data-open", "true")
    embedded = user.locate(f"{category.TABLE} > tbody > tr[data-embedded='true']")
    expect(embedded).to_be_visible()
    expect(embedded).to_contain_text("Note")
    expect(embedded).to_contain_text("Row one")


# @features pages
# @dimensions generate ai-form explain-button
def test_generate_pages_explain_prompt_from_category_tools(get_user):
    user = get_user(Users.OWNER)
    category = Categories.test_create_page.get(user)
    user.go(category)

    generate_form = category.generate_pages_form()
    generate_form.locator(FormElements.AI_DESCRIPTION).fill(
        "Create a few example pages for testing."
    )
    generate_form.locator("input[name='num_pages']").fill("2")

    explain_button = generate_form.locator(Buttons.EXPLAIN)
    expect(explain_button).to_be_visible()
    explain_button.click()

    Modal(user.page).close()
    expect(generate_form).to_be_visible()


# @features pages
# @dimensions generate ai-form deferred-submit success-state
def test_generate_pages_submit_marks_form_successful(get_user):
    """Queued page generation marks the submit button successful."""
    user = get_user(Users.OWNER)
    category = Categories.test_create_page.get(user)
    user.go(category)

    generate_form = category.generate_pages_form()
    generate_form.locator(FormElements.AI_DESCRIPTION).fill(
        "Create a few pages about follow-up tasks."
    )
    generate_form.locator("input[name='num_pages']").fill("2")

    submit_button = generate_form.locator(
        "button[type='submit']:has-text('Generate Pages')"
    )
    with user.page.expect_response("**/generate-pages"):
        submit_button.click()

    success_button = generate_form.locator(
        "button[type='submit']:has-text('Pages Queued')"
    )
    expect(success_button).to_be_visible()
    expect(success_button.locator("[data-icon='check']")).to_be_visible()
