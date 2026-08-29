import re

import pytest

from playwright.sync_api import expect

from testing.definitions import SitePages, Tasks, Users
from testing.elements import Buttons, Modal

"""
Tests for the Tasks index page (/tasks).

Unit coverage for backend task-index query behavior lives in
``testing/tests_unit/test_010_task_index.py``.

When implemented, verify against:
- lagniappe/templates/tasks/index.html
- lagniappe/templates/tasks/rows.html
- src/script/views/indexes/task.mjs
"""


pytestmark = pytest.mark.e2e

VISIBLE_TASK_ROW = "#table tbody tr[lp-entity]:visible"
TASK_ROW = "#table tbody tr[lp-entity]"
TASK_NAME_CELL = "td[data-column='name']:visible"
SORTING_PANEL = "[data-widget='TableSorting']"
COLUMN_FILTER_BUTTON = "th[data-column='{column}'] button[data-toggle='filter']"


def _row_for(user, task):
    return user.locate(TASK_ROW).filter(has_text=task.definition.name)


def _open_sort_panel(user, column):
    button = user.locate(COLUMN_FILTER_BUTTON.format(column=column))
    expect(button).to_be_visible()
    button.click()
    panel = user.locate(SORTING_PANEL)
    expect(panel.locator(f'input[type="radio"][name="{column}"]').first).to_be_visible()
    return panel


def _select_sort(user, column, direction):
    panel = _open_sort_panel(user, column)
    radio = panel.locator(f'input[type="radio"][name="{column}"][value="{direction}"]')
    expect(radio).to_be_visible()
    radio.check()


def _assert_visible_task_order(user, tasks):
    expected = [task.definition.name for task in tasks]
    name_pattern = re.compile(
        rf"^(?:{'|'.join(re.escape(name) for name in expected)})$"
    )
    titles = user.locate(
        f"{VISIBLE_TASK_ROW} {TASK_NAME_CELL} a[data-role='title']"
    ).filter(has_text=name_pattern)
    expect(titles).to_have_text(expected)


# @pairs permissions:own-page-only task-index:authenticated-access
def test_task_index_allows_own_page_only_users(get_user):
    user = get_user(Users.user_no_access)

    task_index = user.go(SitePages.TASK_INDEX)

    expect(user.page).to_have_title("Active Tasks")
    expect(user.locate(task_index.TABLE_BODY)).to_have_attribute("loaded", "")
    expect(
        user.locate(f"{task_index.TABLE_BODY} tr[data-role='empty']")
    ).to_be_visible()


# @matrix home task-index : assignee-visibility
# @pair tasks:inaccessible-backing-page
# @template table.html::rows
# @template home/tasks.html::task
def test_assigned_tasks_on_hidden_page_appear_on_home_and_task_index(get_user):
    """Live queries include an assignee's dated and undated restricted tasks.

    Waiting for the task-index table to finish loading executes both pagination
    streams. Together with the home list, this crosses every assigned-task
    composite-index query shape against the managed Datastore.
    """
    owner = get_user(Users.OWNER)
    due_task = Tasks.test_assigned_due_permission_task.get(owner)
    undated_task = Tasks.test_assigned_permission_task.get(owner)

    assignee = get_user(Users.create_user)
    home = assignee.go(SitePages.HOME)
    expect(home.task_list.get_item(due_task)).to_be_visible()
    expect(home.task_list.get_item(undated_task)).not_to_be_attached()

    task_index = assignee.go(SitePages.TASK_INDEX)
    expect(assignee.locate(task_index.TABLE_BODY)).to_have_attribute("loaded", "")
    expect(_row_for(assignee, due_task)).to_be_visible()
    expect(_row_for(assignee, undated_task)).to_be_visible()


# @pair task-index:columns
def test_tasks_table_columns(get_user):
    user = get_user(Users.OWNER)
    Tasks.test_mobile_index_task.get(user)

    user.go(SitePages.TASK_INDEX)

    expected_columns = {
        "completed": "Completed",
        "name": "Name",
        "description": "Description",
        "due_date": "Due Date",
        "assigned_to": "Assigned To",
        "modified": "Modified",
        "selector": "",
    }
    visible_columns = {"name", "due_date", "modified", "selector"}

    for column, title in expected_columns.items():
        header = user.locate(f"th[data-column='{column}']")
        expect(header).to_be_attached()
        if column in visible_columns:
            expect(header).to_be_visible()
        else:
            expect(header).to_be_hidden()
        if title:
            expect(header.locator("[data-role='title']")).to_have_text(title)

# @matrix table-controls : name sort-asc sorting
def test_task_index_name_sort_ascending_reorders_rows(get_user):
    user = get_user(Users.OWNER)
    personal = Tasks.test_task_index_personal_today.get(user)
    page_active = Tasks.test_task_index_page_active.get(user)
    future = Tasks.test_task_index_due_future.get(user)
    user.go(SitePages.TASK_INDEX)

    _select_sort(user, "name", "asc")

    _assert_visible_task_order(user, [future, page_active, personal])


# @matrix table-controls : due-date filtering sorting
def test_task_index_due_date_sort_filters_to_dated_rows(get_user):
    user = get_user(Users.OWNER)
    today = Tasks.test_task_index_personal_today.get(user)
    undated = Tasks.test_task_index_page_active.get(user)
    future = Tasks.test_task_index_due_future.get(user)
    user.go(SitePages.TASK_INDEX)

    _select_sort(user, "due_date", "asc")

    expect(_row_for(user, undated)).to_have_attribute("data-visible", "false")
    _assert_visible_task_order(user, [today, future])


# @matrix tasks : focus page-task row-link
def test_task_index_title_link_opens_backing_page_task(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_task_index_project_linked.get(user)
    user.go(SitePages.TASK_INDEX)

    row = _row_for(user, task)
    expect(row).to_be_visible()
    row.locator("td[data-column='name'] a[data-role='title']").click()

    task_on_page = user.locate(f"li[data-key='{task.key}']")
    expect(task_on_page).to_be_visible()
    expect(task_on_page.locator("[data-widget='TaskSettings']")).to_be_visible()


# @matrix tasks : canonical-url navigation reload
def test_task_route_rewrites_to_page_url_after_focus(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_task_index_page_active.get(user)
    page = task.definition.origin.get(user)
    canonical = re.compile(rf".*/pages/{re.escape(page.key)}$")

    user.go(task)

    task_on_page = user.locate(f"li[data-key='{task.key}']")
    expect(task_on_page).to_be_visible()
    expect(task_on_page.locator("[data-widget='TaskSettings']")).to_be_visible()
    expect(user.page).to_have_url(canonical)

    user.page.reload(wait_until="load")
    user.page.wait_for_selector("[lp-view][initialized]")

    expect(user.page).to_have_url(canonical)
    expect(user.locate("#tasks")).to_be_visible()
    expect(task_on_page).to_be_visible()


# @pair task-index:delete
# @template table.html::row
def test_task_index_delete_task_from_row(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_task_index_delete_from_index.get(user)
    user.go(SitePages.TASK_INDEX)

    row = user.locate(f"{TASK_ROW}[data-key='{task.key}']")
    expect(row).to_be_visible()
    desktop_delete = row.locator(f"td[data-column='delete'] {Buttons.LP_DELETE}")
    mobile_delete = row.locator(f"td[data-column='name'] {Buttons.LP_DELETE}")

    expect(desktop_delete).to_be_visible()
    expect(mobile_delete).to_be_hidden()

    user.mobile = True

    expect(desktop_delete).to_be_hidden()
    expect(mobile_delete).to_be_visible()
    mobile_delete.click()

    Modal(user.page).delete()

    expect(row).not_to_be_visible()


# @matrix task-index : editable-cell link-affordance quick-edit
def test_task_index_quick_edit_updates_editable_cell(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_task_index_page_active.get(user)
    user.go(SitePages.TASK_INDEX)

    row = user.locate(f"{TASK_ROW}[data-key='{task.key}']")
    expect(row).to_be_visible()

    edit_toggle = user.locate("button[lp-show='table:TableEditor']")
    expect(edit_toggle).to_be_visible()
    edit_toggle.click()

    body = user.locate("#table tbody")
    expect(body).to_have_attribute("data-editing", "true")

    cell = row.locator("td[data-column='name']")
    expect(cell).to_have_attribute("data-editable", "true")
    title = cell.locator("a[data-role='title']")
    title.hover()
    expect(title).to_have_css("text-decoration-line", "none")
    title.click()

    name_input = cell.locator("input[name='name']")
    expect(name_input).to_be_visible()

    updated_name = "Task Index Quick Edit Updated"
    name_input.fill(updated_name)
    with user.page.expect_response("**/tasks/*/patch"):
        name_input.press("Enter")

    expect(cell).to_contain_text(updated_name)


# @matrix table-controls task-index : checkbox-cell column-visibility quick-edit
def test_task_index_quick_edit_keeps_revealed_completed_column_editable(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_task_index_page_active.get(user)
    user.go(SitePages.TASK_INDEX)

    row = user.locate(f"{TASK_ROW}[data-key='{task.key}']")
    completed = row.locator("td[data-column='completed']")
    expect(row).to_be_visible()
    expect(completed).to_be_hidden()

    edit_toggle = user.locate("button[lp-show='table:TableEditor']")
    edit_toggle.click()

    body = user.locate("#table tbody")
    expect(body).to_have_attribute("data-editing", "true")

    visibility_toggle = user.locate(
        "button[lp-show='table:TableVisibility'][aria-label='Choose visible columns']"
    )
    visibility_toggle.click()
    visibility = user.locate("tr[data-widget='TableVisibility']")
    expect(visibility).to_have_attribute("data-visible", "true")

    completed_toggle = visibility.locator(
        "input[type='checkbox'][name='completed']"
    )
    expect(completed_toggle).not_to_be_checked()
    completed_toggle.set_checked(True)

    expect(completed).to_be_visible()
    expect(body).to_have_attribute("data-editing", "true")
    expect(
        completed.locator("input[type='checkbox'][name='completed']")
    ).to_be_visible()

    visibility_toggle.click()
    expect(visibility).to_have_attribute("data-visible", "false")
    expect(body).to_have_attribute("data-editing", "true")
    expect(edit_toggle).to_have_attribute("data-editing", "true")
