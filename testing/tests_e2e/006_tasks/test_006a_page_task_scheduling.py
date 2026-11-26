from playwright.sync_api import expect

from testing.definitions import SitePages, Tasks, Users
from testing.elements import Badges
from testing.utility.local_time import (
    local_date_plus_days_iso,
)
from testing.utility.network import expect_successful_response


DUE_DATE_BADGE = "[data-role='change-due-date']"
SCHEDULE_BADGE = "[data-role='schedule']"


def _open_schedule_drawer(task):
    drawer = task.open_chip("schedule")
    expect(drawer.locator("input[name='due-date']")).to_be_visible()
    return drawer


def _save_schedule(task, drawer):
    with expect_successful_response(
        task.user.page,
        method="PUT",
        path=f"/tasks/{task.key}/update",
        entity_key=task.key,
    ):
        drawer.locator("[data-role='save-schedule']").click()
    expect(drawer).not_to_be_visible()


def _add_recurring_schedule(task, interval="1", unit="day"):
    drawer = _open_schedule_drawer(task)
    drawer.locator("input[name='recurring']").check()
    expect(drawer.locator("[data-role='recurring']")).to_be_visible()
    drawer.locator("input[name='interval']").fill(interval)
    drawer.locator(f"input[name='unit'][value='{unit}']").check()
    _save_schedule(task, drawer)


def _add_weekly_schedule(task):
    drawer = _open_schedule_drawer(task)
    drawer.locator("input[name='scheduled']").check()
    expect(drawer.locator("[data-role='scheduled']")).to_be_visible()
    drawer.locator("input[name='schedule-type'][value='weekly']").check()
    expect(drawer.locator("[data-role='weekly']")).to_be_visible()
    drawer.locator("input[name='weekly-day-0']").check()
    _save_schedule(task, drawer)


def test_page_task_add_due_date(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_page_task_add_due_date.get(user)
    assignee = Users.create_user.get(user)
    user.go(task)

    task.select_chip_option("assigned_to", assignee)
    Badges.USER.visible(task.element, assignee)

    due_date = local_date_plus_days_iso(4)
    drawer = _open_schedule_drawer(task)
    expect(task.element).to_have_attribute("data-chip-open", "true")
    expect(task.element.locator("[data-role='chip-close']")).to_be_visible()
    # Verify the native DatePicker popover opens from the right-aligned trigger and closes on Escape.
    drawer.locator("[data-role='date-picker-trigger']").first.click()
    popover = user.page.locator("[data-role='date-picker-popover']")
    expect(popover).to_be_visible()
    popover.locator("[data-role='dp-today']").click()
    expect(popover).not_to_be_attached()
    drawer.locator("input[name='due-date']").fill(due_date)
    _save_schedule(task, drawer)

    expect(task.element.locator(DUE_DATE_BADGE)).to_be_visible()
    Badges.USER.visible(task.element, assignee)

    assigned_user = get_user(Users.create_user)
    assigned_home = assigned_user.go(SitePages.HOME)
    _ = assigned_home.task_list
    expect(assigned_user.locate(f"[data-key='{task.key}']")).to_be_visible()


def test_page_task_remove_due_date(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_page_task_remove_due_date.get(user)
    user.go(task)

    drawer = _open_schedule_drawer(task)
    drawer.get_by_role("button", name="Clear").click()
    _save_schedule(task, drawer)

    expect(task.element.locator(DUE_DATE_BADGE)).not_to_be_attached()


def test_page_task_due_today(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_page_task_due_today.get(user)
    user.go(task)

    drawer = _open_schedule_drawer(task)
    drawer.get_by_role("button", name="Today").click()
    _save_schedule(task, drawer)

    expect(task.element.locator(DUE_DATE_BADGE)).to_contain_text("Today")


def test_page_task_repeats_when_completed(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_page_task_repeats_when_completed.get(user)
    user.go(task)

    _add_recurring_schedule(task)

    with user.page.expect_response("**/update"):
        task.element.locator(task.COMPLETE_TASK_CHECKBOX).click()

    expect(task.element.locator(task.COMPLETE_TASK_CHECKBOX)).not_to_be_checked()
    expect(task.element.locator(DUE_DATE_BADGE)).to_be_visible()


def test_page_task_add_schedule(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_page_task_add_schedule.get(user)
    user.go(task)

    _add_weekly_schedule(task)

    expect(task.element.locator(SCHEDULE_BADGE)).to_contain_text("weekly")


def test_page_task_remove_schedule(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_page_task_remove_schedule.get(user)
    user.go(task)

    _add_weekly_schedule(task)

    drawer = _open_schedule_drawer(task)
    drawer.locator("input[name='scheduled']").uncheck()
    _save_schedule(task, drawer)

    expect(task.element.locator(SCHEDULE_BADGE)).not_to_be_attached()


def test_page_task_add_recurring(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_page_task_add_recurring.get(user)
    user.go(task)

    _add_recurring_schedule(task, interval="2", unit="week")

    expect(task.element.locator(SCHEDULE_BADGE)).to_contain_text(
        "2 weeks after completion"
    )
