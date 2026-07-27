"""
Tests for the task index mobile table controls.

Verified against:
- lagniappe/web/templates/tasks/index.html
- lagniappe/web/templates/table.html
- src/script/widgets/mobileTableControls.mjs
- src/script/widgets/tableVisibility.mjs
- src/script/widgets/tableSorting.mjs
"""

import pytest
from playwright.sync_api import expect

from testing.definitions import SitePages, Tasks, Users
from testing.elements import MobileTableControls
from testing.resources.site import TaskIndex

pytestmark = pytest.mark.e2e


def _clear_task_column_prefs(user):
    user.page.evaluate(
        """() => {
            localStorage.removeItem('columns-tasks');
            sessionStorage.removeItem('sorts-tasks');
        }"""
    )


# @features table-controls
# @dimensions mobile-controls columns
def test_task_index_mobile_controls_open_with_task_columns(get_user):
    """A phone user opens the task table controls and sees task columns."""
    user = get_user(Users.OWNER)
    Tasks.test_mobile_index_task.get(user)
    task_index = user.go(SitePages.TASK_INDEX)
    _clear_task_column_prefs(user)
    user.reload(task_index)

    controls = MobileTableControls(user)
    expect(controls.panel).to_be_hidden()

    user.mobile = True
    controls = MobileTableControls(user)
    controls.open()

    expect(controls.row("name")).to_be_visible()
    expect(controls.row("due_date")).to_be_visible()
    expect(controls.row("modified")).to_be_visible()


# @features table-controls
# @dimensions mobile-controls column-visibility
def test_task_index_mobile_visibility_toggle_hides_column(get_user):
    """Mobile column controls hide a visible task column in the table."""
    user = get_user(Users.OWNER)
    Tasks.test_mobile_index_task.get(user)
    task_index = user.go(SitePages.TASK_INDEX)
    _clear_task_column_prefs(user)
    user.reload(task_index)
    user.mobile = True

    controls = MobileTableControls(user)
    controls.open()
    modified_toggle = controls.toggle_column("modified")

    expect(modified_toggle).to_have_attribute("data-active", "false")
    expect(user.locate(TaskIndex.TABLE_BODY)).to_have_attribute("loaded", "")
    expect(user.locate("th[data-column='modified']")).to_be_hidden()
    expect(user.locate("#table td[data-column='modified']:visible")).to_have_count(0)


# @features table-controls
# @dimensions mobile-controls sorting
def test_task_index_mobile_filter_button_opens_sorting_panel(get_user):
    """The mobile filter control opens the same sort choices as the desktop header."""
    user = get_user(Users.OWNER)
    Tasks.test_mobile_index_task.get(user)
    task_index = user.go(SitePages.TASK_INDEX)
    _clear_task_column_prefs(user)
    user.reload(task_index)
    user.mobile = True

    controls = MobileTableControls(user)
    controls.open()
    controls.filter_button("name").click()

    sorting = user.locate("#mobile-controls [data-sorts='name']")
    expect(sorting).to_be_visible()
    expect(
        sorting.locator('input[type="radio"][name="name"][value="asc"]')
    ).to_be_visible()
