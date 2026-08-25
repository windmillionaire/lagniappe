"""
Tests for task creation and management from the home page.

Tests the personal task widget including creation (via CreateUserTask UI),
completion, due date management, and postpone functionality.

Related Files:
    Application:
        - lagniappe/web/routes/tasks/main.py: Task routes (including personal POST)
        - lagniappe/web/routes/home/main.py: Home route and task-related responses
        - lagniappe/web/templates/home/tasks.html: CreateUserTask, HomeTaskList
        - src/script/widgets/home/tasks.mjs: HomeTaskList
        - src/script/widgets/taskSettings.mjs: CreateUserTask (BaseTaskSettings)
        - src/script/views/home.mjs: Task initialization

    Core Entity:
        - lagniappe/core/entities/task.py: Task entity

    Test Framework:
        - testing/definitions/tasks.py: Tasks enum with test definitions
        - testing/definitions/due_date.py: DueDates for date presets
        - testing/resources/home.py: HomePage.create_personal_task, task_list
        - testing/resources/task.py: Task resource (programmatic create for non-UI)
        - testing/elements/tasks.py: PostponeDropdown helper
        - testing/utility/local_time.py: Local calendar dates for assertions

Personal Tasks:
    Tasks created from the home page are personal tasks on the user's page.
    These tests create them through HomePage.create_personal_task (same pattern
    as create_project / create_category in 003b / 003c).

Task Due Dates:
    The home task list only includes personal tasks whose due date falls within
    the near-term window (see tasks.personal). Tests that assert due dates on
    the home list for tasks outside that window are skipped until we verify due
    dates on the user page instead.

Date assertions:
    Use ``testing.utility.local_time`` for today / relative ISO dates so checks
    match the test runner's local calendar (including postpone targets).
"""

import re
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from testing.definitions import DueDates, SitePages, Tasks, Users
from testing.definitions.task_definitions import TaskDefinition
from testing.resources import Page, Task
from testing.elements import (
    PostponeDropdown,
    Buttons,
    FormElements,
    SpinnerButtons,
)
from testing.utility.local_time import (
    local_date_from_utc_datetime,
    local_date_iso,
    local_date_plus_days_iso,
    local_postponed_next_week_iso,
    local_today,
)


def _create_personal_task(user, home, definition):
    """
    Create a personal task from the home CreateUserTask form.

    Args:
        definition: TaskDefinition (name, optional description, optional due_date)

    Returns:
        str: urlsafe_key of the new task list item
    """
    create_form = home.create_task_form()

    create_form.locator(FormElements.NAME).fill(definition.name)
    if getattr(definition, "description", None):
        create_form.locator(FormElements.DESCRIPTION).fill(definition.description)

    if definition.due_date:
        create_form.locator('button[data-action="schedule"]').click()
        expect(create_form.locator('input[name="due-date"]')).to_be_visible()
        definition.due_date.set(create_form)

    with user.page.expect_response("**/personal"):
        SpinnerButtons.CREATE.click(create_form)

    expect(create_form).not_to_be_visible()
    task_list = home.task_list
    new_task = task_list.new_item(definition.name, flash=False)

    return new_task.get_attribute("data-key")


def _make_recurring_daily(task):
    entity = Entities.fetch_one(
        task.key,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    recurring = entity.properties.recurring
    recurring.section.update({"interval": 1, "unit": "day"})
    recurring.complete = True
    entity.save()


# @matrix tasks : create-form due-date
@pytest.mark.e2e
def test_create_task_form(get_user):
    """
    Verify create personal task form opens with expected fields.

    Tests:
        - Form hidden initially, visible after toggle
        - Name and description fields present
        - Schedule button (due date) visible
        - Close button hides form

    Note: Personal tasks use the Schedule button (opens due date UI).
    """
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    form = user.locate(home.CREATE_TASK_FORM)
    expect(form).to_be_hidden()

    user.locate(home.CREATE_TASK_TOGGLE).click()
    expect(form).to_be_visible()

    expect(form.locator(FormElements.NAME)).to_be_visible()
    expect(form.locator(FormElements.DESCRIPTION)).to_be_visible()
    expect(form.locator("button[data-action='schedule']")).to_be_visible()

    form.locator(Buttons.LP_CLOSE).click()
    expect(form).not_to_be_visible()


# @matrix tasks : create-personal due-date
@pytest.mark.e2e
def test_create_personal_task_due_today(get_user):
    """
    Verify personal task creation with today's due date via UI.

    Same pattern as test_create_project_manual_mode / test_create_category_manual_mode:
    get(user, create=False), then task.key = home.create_personal_task(definition)
    (assigning key loads entity via SiteResource). Verifies user task count increments
    and the list shows today's data-due-date.

    Framework usage:
        - home.create_personal_task: Fills CreateUserTask and submits
        - home.task_list: Opens list and returns List helper
    """
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    task = Tasks.test_create_personal_task_due_today.get(user, create=False)
    task.key = _create_personal_task(user, home, task.definition)

    task_item = home.task_list.get_item(task)
    expect(task_item).to_have_attribute("data-due-date", local_date_iso())


# @matrix tasks : create-personal due-date
@pytest.mark.e2e
def test_create_personal_task_due_in_four_days(get_user):
    """
    Verify personal task creation with a due date four days out via UI.

    Tasks due within the near-term window are returned in the home_task response;
    otherwise verify due date on the user page.
    """
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)
    task = Tasks.test_create_personal_task_due_in_four_days.get(user, create=False)
    task.key = _create_personal_task(user, home, task.definition)

    expected = local_date_plus_days_iso(4)

    task_item = home.task_list.get_item(task)
    expect(task_item).to_have_attribute("data-due-date", expected)


# @pair tasks:complete
@pytest.mark.e2e
def test_complete_task_from_home_page(get_user):
    """
    Verify task completion via checkbox.

    Tests the complete flow:
        1. Get task from enum (this task either re-uses an existing task or creates a new one programmatically), open task list
        2. Click complete checkbox
        3. Task disappears from list (completed tasks hidden)
        4. Un-complete task via user page (for test cleanup)
        5. Reset due date and verify task reappears

    Framework usage:
        - COMPLETE_TASK_CHECKBOX: Checkbox input for completion
        - user.get_user_page(): Navigate to user's personal page
        - user_page.uncomplete_task(): Undo completion
        - task.set_due_date(): Update task due date
        - task.save(): Persist changes to database
    """
    user = get_user(Users.OWNER)
    task = Tasks.test_complete_task_from_home_page.get(user)
    home = user.go(SitePages.HOME)

    task_item = home.task_list.get_item(task)
    task_item.locator(home.COMPLETE_TASK_CHECKBOX).click()
    expect(task_item).to_be_hidden()

    with user.page.expect_navigation():
        home.user_page_button.click()
        user_page = Page(user=user)

    user_page.uncomplete_task(task)

    task.element = user_page.active_task_list.get_item(task)

    task.set_due_date(DueDates.personal_task_due_today)
    task.save()

    home = user.go(SitePages.HOME)
    task_item = home.task_list.get_item(task)
    expect(task_item).to_have_attribute("data-due-date", local_date_iso())


# @matrix tasks : complete recurring
@pytest.mark.e2e
def test_complete_recurring_task_from_home_page_reappears(get_user):
    """Completing a near-term recurring home task replaces it with the next occurrence."""
    user = get_user(Users.OWNER)
    task = Task(
        user=user,
        definition=TaskDefinition(
            name=f"Recurring Home Task {uuid4().hex}",
            origin=SitePages.HOME,
            due_date=DueDates.personal_task_due_today,
        ),
    ).create()
    _make_recurring_daily(task)
    home = user.go(SitePages.HOME)

    task_item = home.task_list.get_item(task)

    with user.page.expect_response("**/complete"):
        task_item.locator(home.COMPLETE_TASK_CHECKBOX).click()

    refreshed_task = home.task_list.get_item(task)
    expect(refreshed_task).to_be_visible()
    expect(refreshed_task.locator(home.COMPLETE_TASK_CHECKBOX)).not_to_be_checked()
    expect(refreshed_task).to_have_attribute(
        "data-due-date", local_date_plus_days_iso(1)
    )


# @matrix tasks : due-date postpone
@pytest.mark.e2e
def test_postpone_task_due_date_to_tomorrow(get_user):
    """
    Verify postponing task due date via dropdown.

    Tests the postpone dropdown which allows quick date changes:
        1. Open task list and find task
        2. Use PostponeDropdown.TOMORROW to postpone
        3. Verify task's due date updated to tomorrow

    Framework usage:
        - PostponeDropdown enum: Helpers for postpone options
        - PostponeDropdown.TOMORROW.select(): Selects "Tomorrow" option
    """
    user = get_user(Users.OWNER)
    task = Tasks.test_postpone_task_due_date_to_tomorrow.get(user)
    home = user.go(SitePages.HOME)

    task_item = home.task_list.get_item(task)
    tomorrow = local_date_plus_days_iso(1)

    PostponeDropdown.TOMORROW.select(task_item)
    postponed_task = home.task_list.get_item(task)
    expect(postponed_task).to_have_attribute("data-due-date", tomorrow)


# @matrix tasks : due-date postpone
@pytest.mark.e2e
def test_postpone_task_due_date_to_this_week(get_user):
    """Choose any remaining calendar date through Sunday from 'This Week…'."""
    user = get_user(Users.OWNER)
    task = Tasks.test_postpone_task_due_date_to_this_week.get(user)
    home = user.go(SitePages.HOME)

    task_item = home.task_list.get_item(task)
    today = local_today()

    if today.weekday() == 6:
        _, panel = PostponeDropdown.open(task_item)
        expect(
            panel.get_by_role("option", name="This Week…", exact=True)
        ).to_have_count(0)
        return

    expected = local_date_plus_days_iso(6 - today.weekday())
    _, panel = PostponeDropdown.open_this_week(task_item)
    expect(panel.get_by_role("option", name="Back", exact=True)).to_be_visible()

    weekday_names = (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    )
    for weekday in weekday_names[today.weekday() + 1 :]:
        expect(
            panel.get_by_role("option", name=re.compile(rf"^{weekday} · "))
        ).to_be_visible()

    panel.get_by_role("option", name="Back", exact=True).click()
    expect(panel.get_by_role("option", name="This Week…", exact=True)).to_be_visible()

    PostponeDropdown.THIS_SUNDAY.select(task_item)
    postponed = home.task_list.get_item(task)
    expect(postponed).to_have_attribute("data-due-date", expected)


# @matrix tasks : due-date postpone
@pytest.mark.e2e
def test_postpone_task_due_date_to_next_week(get_user):
    """Choose a dated weekday from the progressive next-week postpone menu."""
    user = get_user(Users.OWNER)
    task = Tasks.test_postpone_task_due_date_to_next_week.get(user)
    home = user.go(SitePages.HOME)

    task_item = home.task_list.get_item(task)
    expected = local_postponed_next_week_iso(4)

    dropdown, panel = PostponeDropdown.open_next_week(task_item)
    expect(panel.get_by_role("option", name="Back", exact=True)).to_be_visible()
    for weekday in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
        expect(
            panel.get_by_role("option", name=re.compile(rf"^{weekday} · "))
        ).to_be_visible()

    panel.get_by_role("option", name="Back", exact=True).click()
    expect(panel.get_by_role("option", name="Tomorrow", exact=True)).to_be_visible()
    expect(panel.get_by_role("option", name="Next Week…", exact=True)).to_be_visible()
    expect(dropdown.panel).to_be_visible()

    PostponeDropdown.NEXT_FRIDAY.select(task_item)
    postponed = Entities.fetch_one(task.key, request=Fetch.direct())
    assert postponed.due_date is not None
    assert local_date_from_utc_datetime(postponed.due_date).date().isoformat() == expected


# @matrix tasks : due-date postpone
@pytest.mark.e2e
def test_postpone_task_due_date_to_no_due_date(get_user):
    """
    Clear due date via postpone menu; task leaves the home list (no near-term due).

    Restores due today on the user page (same pattern as test_complete cleanup).
    """
    user = get_user(Users.OWNER)
    task = Tasks.test_postpone_task_due_date_to_no_due_date.get(user)
    home = user.go(SitePages.HOME)

    task_item = home.task_list.get_item(task)
    PostponeDropdown.NO_DUE_DATE.select(task_item)
    expect(task_item).to_be_hidden()

    with user.page.expect_navigation():
        home.user_page_button.click()

    user_page = Page(user=user)
    task.element = user_page.active_task_list.get_item(task)

    task.set_due_date(DueDates.personal_task_due_today)
    task.save()

    home = user.go(SitePages.HOME)
    task_item = home.task_list.get_item(task)
    expect(task_item).to_have_attribute("data-due-date", local_date_iso())
