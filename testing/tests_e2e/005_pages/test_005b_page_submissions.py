"""
Tests for page form submissions across all practical field types.

Covers fill → save → verify for:
- Basic inputs: text, date, time, number, email, phone
- Selection types: textarea, checkbox, radio, single select, multi-select
- External link: url + title

Maps to:
- Entity: lagniappe/core/entities/page.py
- Routes: lagniappe/web/routes/pages/
- Templates: lagniappe/web/templates/pages/
- View: src/script/views/page.mjs
"""

import json

import pytest
from playwright.sync_api import expect

from testing.definitions import Pages, Submissions, Users
from testing.elements import SpinnerButtons

pytestmark = pytest.mark.e2e


def _table_field(page):
    table = page.info_form.locator("[id^='items-'].form-element")
    expect(table).to_be_visible()
    return table


def _table_rows(table):
    return table.locator("tbody tr")


def _open_row_actions(table, index):
    row = _table_rows(table).nth(index)
    expect(row).to_be_visible()
    row.hover()
    row.focus()

    actions = row.locator("[data-role='row-actions']")
    expect(actions).to_be_visible()
    expect(actions).to_have_attribute("data-index", str(index))
    return actions


def _add_table_row(user, table, note):
    table.locator("button[data-role='create']").click()
    form = table.locator("form")
    expect(form).to_be_visible()
    form.locator("input[name='row_note']").fill(note)

    with user.page.expect_response("**/validate-row/items**"):
        form.locator("button[data-role='validate']").click()

    expect(form).not_to_be_attached()


def _table_value(table):
    value = table.locator("input[name='items']").input_value()
    return json.loads(value or "[]")


# @pairs template-formatting:date template-formatting:time
# @pairs template-formatting:phone template-formatting:number pages:basic-inputs
def test_basic_input_submission(get_user):
    """Fill and verify text, date, time, number, email, and phone fields."""
    user = get_user(Users.OWNER)
    page = Pages.test_basic_input_submission.get(user)
    user.go(page)

    submission = Submissions.basic_inputs.get()
    page.set_submission(submission)
    page.submit_and_verify_submission(submission)


# @features pages
# @dimensions submission selection-fields read-mode
def test_selection_submission(get_user):
    """Fill and verify textarea, checkbox, radio, select, and multi-select fields."""
    user = get_user(Users.OWNER)
    page = Pages.test_selection_submission.get(user)
    user.go(page)

    submission = Submissions.selection_types.get()
    page.set_submission(submission)
    page.submit_and_verify_submission(submission)

    for field_id, labels in {
        "radio-priorityef": ("Medium",),
        "select-statusgh": ("Published",),
        "select-tagsij12": ("Featured", "Sale"),
    }.items():
        read_value = page.info_form.locator(
            f"[id^='{field_id}-'] [data-role='read']"
        )
        expect(read_value).to_be_visible()
        expect(read_value.locator("i")).to_have_count(0)
        for label in labels:
            expect(read_value).to_contain_text(label)


# @pairs pages:submission form-link:read-layout
# @style form.linkLabel
def test_link_submission(get_user):
    """Fill and verify external link (url + title) field."""
    user = get_user(Users.OWNER)
    page = Pages.test_link_submission.get(user)
    user.go(page)

    submission = Submissions.link_external.get()
    page.set_submission(submission)
    page.submit_and_verify_submission(submission)

    read_value = page.info_form.locator(
        "[id^='link-ab12-'] [data-role='read']"
    )
    layout = read_value.evaluate(
        """readValue => {
          const label = readValue.querySelector(".form-link-label");
          const icon = readValue.querySelector(".icon[data-icon='out']");
          return {
            iconHeight: icon.getBoundingClientRect().height,
            lineHeight: Number.parseFloat(getComputedStyle(label).lineHeight),
          };
        }"""
    )
    assert layout["lineHeight"] == pytest.approx(layout["iconHeight"])


# @features form-table
# @dimensions row-actions reorder edit delete reload
def test_table_submission_row_actions(get_user):
    """Desktop row actions can edit, delete, reorder, and persist rows."""
    user = get_user(Users.OWNER)
    page = Pages.test_table_submission.get(user)
    user.go(page)

    table = _table_field(page)
    rows = _table_rows(table)
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Row one")

    _add_table_row(user, table, "Row two")
    expect(rows).to_have_count(2)
    expect(rows.nth(1)).to_contain_text("Row two")

    first_actions = _open_row_actions(table, 0)
    expect(first_actions.locator("button[data-role='moveUp']")).to_be_disabled()
    expect(first_actions.locator("button[data-role='moveDown']")).to_be_enabled()

    second_actions = _open_row_actions(table, 1)
    expect(second_actions.locator("button[data-role='moveUp']")).to_be_enabled()
    expect(second_actions.locator("button[data-role='moveDown']")).to_be_disabled()
    second_actions.locator("button[data-role='moveUp']").click()

    expect(second_actions).not_to_be_visible()
    expect(rows.nth(0)).to_contain_text("Row two")
    expect(rows.nth(1)).to_contain_text("Row one")
    assert _table_value(table) == [
        {"row_note": "Row two"},
        {"row_note": "Row one"},
    ]

    edit_actions = _open_row_actions(table, 0)
    edit_actions.locator("button[data-role='edit']").click()
    edit_form = table.locator("form")
    expect(edit_form).to_be_visible()
    expect(edit_form).to_be_in_viewport()
    edit_form.locator("input[name='row_note']").fill("Row two edited")

    with user.page.expect_response("**/validate-row/items**"):
        edit_form.locator("button[data-role='validate']").click()

    expect(edit_form).not_to_be_attached()
    expect(rows.nth(0)).to_contain_text("Row two edited")
    assert _table_value(table) == [
        {"row_note": "Row two edited"},
        {"row_note": "Row one"},
    ]

    delete_actions = _open_row_actions(table, 1)
    delete_actions.locator("button[data-role='delete']").click()
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Row two edited")
    assert _table_value(table) == [{"row_note": "Row two edited"}]

    with user.page.expect_response("**/update"):
        SpinnerButtons.UPDATE.click(page.info_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(page.info_form)
    user.reload(page)
    table = _table_field(page)
    rows = _table_rows(table)
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Row two edited")


# @features form-table
# @dimensions row-actions mobile touch-gesture
def test_table_submission_mobile_row_action_gestures(get_user):
    """Real mobile touchscreen taps toggle row actions."""
    user = get_user(Users.OWNER, has_touch=True)
    page = Pages.test_table_submission.get(user)
    user.go(page)
    user.mobile = True

    table = _table_field(page)
    rows = _table_rows(table)
    actions = table.locator("[data-role='row-actions']")
    expect(rows).to_have_count(1)
    rows.first.scroll_into_view_if_needed()
    expect(rows.first).to_be_in_viewport()
    expect(actions).not_to_be_visible()

    rows.first.tap(position={"x": 12, "y": 12})
    expect(actions).to_be_visible()

    rows.first.tap(position={"x": 12, "y": 12})
    expect(actions).not_to_be_visible()
