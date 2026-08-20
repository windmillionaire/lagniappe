from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import SitePages, Tasks, Users
from testing.elements import DateSelect, UserSelect
from testing.utility.local_time import (
    local_date_from_utc_datetime,
    local_date_iso,
    local_date_plus_days_iso,
)


DUE_DATE_BADGE = "[data-role='change-due-date']"
SCHEDULE_BADGE = "[data-role='schedule']"


def _fresh_task(task):
    return Entities.fetch_one(task.key, request=Fetch.direct())


def _assert_due_date(task, expected_iso):
    entity = _fresh_task(task)
    assert entity.due_date is not None
    local_value = local_date_from_utc_datetime(entity.due_date)
    local_date = local_value.date() if hasattr(local_value, "date") else local_value
    assert local_date.isoformat() == expected_iso


def _open_schedule_form(task):
    schedule_form = DateSelect(task.settings_form).form()
    expect(schedule_form.locator("input[name='due-date']")).to_be_visible()
    return schedule_form


def _save_settings(task):
    task.save()
    expect(task.element.locator(task.SETTINGS_FORM)).to_be_visible()


def _add_recurring_schedule(task, interval="1", unit="day"):
    schedule_form = _open_schedule_form(task)
    schedule_form.locator("input[name='recurring']").check()
    expect(schedule_form.locator("[data-role='recurring']")).to_be_visible()
    schedule_form.locator("input[name='interval']").fill(interval)
    schedule_form.locator(f"input[name='unit'][value='{unit}']").check()
    _save_settings(task)


def _add_weekly_schedule(task):
    schedule_form = _open_schedule_form(task)
    schedule_form.locator("input[name='scheduled']").check()
    expect(schedule_form.locator("[data-role='scheduled']")).to_be_visible()
    schedule_form.locator("input[name='schedule-type'][value='weekly']").check()
    expect(schedule_form.locator("[data-role='weekly']")).to_be_visible()
    schedule_form.locator("input[name='weekly-day-0']").check()
    _save_settings(task)


# @pairs task-scheduling:due-date task-scheduling:add
# @pairs task-assignment:assignee-preservation task-assignment:home-list
# @source src/script/elements/sectionToggle.mjs::FacetControl
def test_page_task_add_due_date(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_page_task_add_due_date.get(user)
    assignee = Users.create_user.get(user)
    user.go(task)

    UserSelect(task.settings_form).select(assignee)
    _save_settings(task)
    assert _fresh_task(task).properties.assigned_to.key == assignee.entity.page.key
    settings_form = task.settings_form
    expect(UserSelect(settings_form).button).to_contain_text(assignee.definition.name)
    expect(settings_form.locator("select[name='assigned_to']")).to_have_value(
        assignee.entity.page.urlsafe_key
    )

    due_date = local_date_plus_days_iso(4)
    schedule_form = _open_schedule_form(task)
    schedule_form.locator("input[name='due-date']").fill(due_date)
    _save_settings(task)

    expect(task.element.locator(DUE_DATE_BADGE)).to_be_visible()
    _assert_due_date(task, due_date)
    assert _fresh_task(task).properties.assigned_to.key == assignee.entity.page.key

    assigned_user = get_user(Users.create_user)
    assigned_home = assigned_user.go(SitePages.HOME)
    assigned_home.task_list
    expect(assigned_user.locate(f"[data-key='{task.key}']")).to_be_visible()


# @features task-scheduling
# @dimensions due-date remove
def test_page_task_remove_due_date(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_page_task_remove_due_date.get(user)
    user.go(task)

    schedule_form = _open_schedule_form(task)
    schedule_form.get_by_role("button", name="Remove").click()
    _save_settings(task)

    expect(task.element.locator(DUE_DATE_BADGE)).not_to_be_attached()
    assert _fresh_task(task).due_date is None


# @features task-scheduling
# @dimensions due-date today
def test_page_task_due_today(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_page_task_due_today.get(user)
    user.go(task)

    schedule_form = _open_schedule_form(task)
    schedule_form.get_by_role("button", name="Today").click()
    _save_settings(task)

    expect(task.element.locator(DUE_DATE_BADGE)).to_contain_text("Today")
    _assert_due_date(task, local_date_iso())


# @features task-scheduling
# @dimensions recurring complete
def test_page_task_repeats_when_completed(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_page_task_repeats_when_completed.get(user)
    user.go(task)

    _add_recurring_schedule(task)

    with user.page.expect_response("**/update"):
        task.element.locator(task.COMPLETE_TASK_CHECKBOX).click()

    expect(task.element.locator(task.COMPLETE_TASK_CHECKBOX)).not_to_be_checked()
    expect(task.element.locator(DUE_DATE_BADGE)).to_be_visible()

    entity = _fresh_task(task)
    assert entity.completed is False
    assert entity.completed_on is None
    assert entity.active is True
    _assert_due_date(task, local_date_plus_days_iso(1))


# @features task-scheduling
# @dimensions scheduled add
def test_page_task_add_schedule(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_page_task_add_schedule.get(user)
    user.go(task)

    _add_weekly_schedule(task)

    expect(task.element.locator(SCHEDULE_BADGE)).to_contain_text("weekly")
    schedule = _fresh_task(task).properties.schedule.active
    assert schedule.section_id == "scheduled"
    assert schedule.mode == "weekly"
    assert schedule.days == [0]


# @features task-scheduling
# @dimensions scheduled remove
def test_page_task_remove_schedule(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_page_task_remove_schedule.get(user)
    user.go(task)

    _add_weekly_schedule(task)

    schedule_form = _open_schedule_form(task)
    schedule_form.locator("input[name='scheduled']").uncheck()
    _save_settings(task)

    expect(task.element.locator(SCHEDULE_BADGE)).not_to_be_attached()
    assert _fresh_task(task).properties.schedule.active is None


# @features task-scheduling
# @dimensions recurring add
def test_page_task_add_recurring(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_page_task_add_recurring.get(user)
    user.go(task)

    _add_recurring_schedule(task, interval="2", unit="week")

    expect(task.element.locator(SCHEDULE_BADGE)).to_contain_text(
        "2 weeks after completion"
    )
    schedule = _fresh_task(task).properties.schedule.active
    assert schedule.section_id == "recurring"
    assert schedule.interval == 2
    assert schedule.unit == "week"
