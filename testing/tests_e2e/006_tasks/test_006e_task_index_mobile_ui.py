"""
Tests for the task index mobile table controls.

Verified against:
- lagniappe/web/templates/tasks/index.html
- lagniappe/web/templates/table.html
- src/script/widgets/tables/mobileControls.ts
- src/script/widgets/tables/visibility.ts
- src/script/widgets/tables/sorting.ts
"""

import pytest
from playwright.sync_api import expect

from testing.definitions import SitePages, Tasks
from testing.elements import MobileTableControls
from testing.resources.site import TaskIndex

pytestmark = pytest.mark.e2e


def test_task_index_mobile_controls_open_with_task_columns(get_admin, get_user):
    user = get_admin()
    Tasks.test_mobile_index_task.get(user)
    user.go(SitePages.TASK_INDEX)

    controls = MobileTableControls(user)
    expect(controls.panel).to_be_hidden()

    user.mobile = True
    controls = MobileTableControls(user)
    controls.open()

    expect(controls.row("name")).to_be_visible()
    expect(controls.row("due_date")).to_be_visible()
    expect(controls.row("modified")).to_be_visible()


def test_task_index_mobile_visibility_toggle_hides_column(get_admin, get_user):
    user = get_admin()
    Tasks.test_mobile_index_task.get(user)
    user.go(SitePages.TASK_INDEX)
    user.mobile = True

    controls = MobileTableControls(user)
    controls.open()
    modified_toggle = controls.toggle_column("modified")

    expect(modified_toggle).to_have_attribute("data-active", "false")
    expect(user.locate(TaskIndex.TABLE_BODY)).to_have_attribute("loaded", "")
    expect(user.locate("th[data-column='modified']")).to_be_hidden()
    expect(user.locate("#table td[data-column='modified']:visible")).to_have_count(0)


def test_task_index_mobile_filter_button_opens_sorting_panel(get_admin, get_user):
    user = get_admin()
    Tasks.test_mobile_index_task.get(user)
    user.go(SitePages.TASK_INDEX)
    user.mobile = True

    controls = MobileTableControls(user)
    controls.open()
    controls.filter_button("name").click()

    sorting = user.locate("#mobile-controls [data-sorts='name']")
    expect(sorting).to_be_visible()
    expect(
        sorting.locator('input[type="radio"][name="name"][value="asc"]')
    ).to_be_visible()
