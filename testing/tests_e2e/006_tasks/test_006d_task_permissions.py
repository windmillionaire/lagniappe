"""
Permission tests for task visibility and task-row edit controls.

Verified against:
- lagniappe/web/templates/pages/tasks.html
- lagniappe/web/routes/tasks/main.py
- lagniappe/core/entities/task.py
"""

import hashlib

import pytest
import requests
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe import CONFIG
from testing.definitions import Tasks, Users
from testing.resources import Task

pytestmark = pytest.mark.e2e


# @pairs permissions:etag permissions:authorization-before-cache
# @pairs permissions:resource-gates cache:permissions
def test_task_route_is_forbidden_without_model_or_page_permission(get_user):
    """A signed-in user with no model/page access cannot follow a task URL."""
    owner = get_user(Users.OWNER)
    task = Tasks.test_create_page_task.get(owner)

    blocked = get_user(Users.user_no_access)
    blocked.navigate(task.url)

    expect(blocked.page).to_have_title("Error 403")

    blocked_fingerprint = hashlib.md5(
        (
            f"{task.entity.fingerprint}-{CONFIG.BUILD_ID}-"
            f"{blocked.entity.permissions_fingerprint}"
        ).encode("utf-8")
    ).hexdigest()
    task_url = (
        task.url
        if task.url.startswith("http")
        else f"{SETTINGS.test_config['BASE_URL']}{task.url}"
    )
    cookies = {
        cookie["name"]: cookie["value"]
        for cookie in blocked.page.context.cookies()
    }
    response = requests.get(
        task_url,
        headers={"If-None-Match": f'"{blocked_fingerprint}"'},
        cookies=cookies,
        allow_redirects=False,
        timeout=10,
    )
    assert response.status_code == 403


# @pairs tasks:history task-combine:authorization
def test_task_history_routes_are_forbidden_without_permission(get_user):
    """History/combine fragments enforce the task permission boundary."""
    owner = get_user(Users.OWNER)
    task = Tasks.test_create_page_task.get(owner)

    blocked = get_user(Users.user_no_access)
    cookies = {
        cookie["name"]: cookie["value"]
        for cookie in blocked.page.context.cookies()
    }
    base_url = SETTINGS.test_config["BASE_URL"]

    for suffix in ("history", "history/latest-submission", "combine"):
        response = requests.get(
            f"{base_url}/tasks/{task.key}/{suffix}",
            cookies=cookies,
            allow_redirects=False,
            timeout=10,
        )
        assert response.status_code == 403


# @pairs tasks:readonly tasks:permission-gates
def test_page_task_viewer_sees_task_without_edit_controls(get_user):
    """A page-level viewer reads a task row but cannot complete, edit, or delete it."""
    owner = get_user(Users.OWNER)
    task = Tasks.test_view_only_page_task.get(owner)

    viewer = get_user(Users.page_acl_one_visible)
    viewer.go(task)

    task_row = viewer.locate(f"[data-key='{task.key}']")
    expect(task_row).to_be_visible()
    complete_checkbox = task_row.locator(Task.COMPLETE_TASK_CHECKBOX)
    expect(complete_checkbox).to_be_visible()
    expect(complete_checkbox).to_be_disabled()
    expect(task_row.locator(Task.SETTINGS_FORM)).not_to_be_attached()
    expect(task_row.locator("button[lp-control='delete']")).not_to_be_attached()
    expect(
        task_row.get_by_role("menuitem", name="Combine with Task")
    ).not_to_be_attached()


# @pairs tasks:completed-only tasks:empty-state
# @template pages/tasks.html::task_list
def test_completed_only_task_list_hides_empty_marker(get_user):
    """A completed task prevents the page-task empty marker from appearing."""
    owner = get_user(Users.OWNER)
    task = Tasks.test_view_only_page_task.get(owner)
    task.mark_completed()

    viewer = get_user(Users.page_acl_one_visible)
    viewer.go(task)

    task_list = viewer.locate("[data-widget='PageTaskList']")
    expect(task_list).to_have_attribute("loaded", "")
    expect(task_list.locator(f"[data-key='{task.key}']")).to_be_visible()
    expect(task_list.locator("[data-role='empty']")).not_to_be_visible()


# @features tasks
# @dimensions readonly attached-form empty-fields permission-gates
# @template pages/tasks.html::task
# @template pages/tasks.html::task_form
def test_page_task_viewer_sees_empty_form_structure_without_edit_controls(get_user):
    """A page-level viewer sees active task form structure without edit controls."""
    owner = get_user(Users.OWNER)
    task = Tasks.test_view_only_page_task_with_empty_form.get(owner)

    viewer = get_user(Users.page_acl_one_visible)
    viewer.go(task)

    task_row = viewer.locate(f"[data-key='{task.key}']")
    expect(task_row).to_be_visible()
    expect(task_row).to_have_attribute("data-completed", "false")
    expect(task_row).to_have_attribute("data-readonly", "true")

    task_form = task.task_form
    expect(task_form).to_be_visible()
    expect(task_form.locator("[data-role='show-autofill']")).to_have_count(0)
    expect(task_form.locator("button[type='submit']")).to_have_count(0)
    complete_checkbox = task_row.locator(Task.COMPLETE_TASK_CHECKBOX)
    expect(complete_checkbox).to_be_visible()
    expect(complete_checkbox).to_be_disabled()
    expect(task_row.locator(Task.SETTINGS_FORM)).not_to_be_attached()
    expect(task_row.locator("button[lp-control='delete']")).not_to_be_attached()

    readonly_field = task_form.locator("[id^='input-textab12'].form-element")
    expect(readonly_field).to_be_visible()
    expect(readonly_field).to_have_attribute("data-mode", "read")
    expect(readonly_field).to_contain_text("Text Field")
    expect(readonly_field).to_contain_text("Not provided")
    expect(readonly_field.locator("input")).to_have_count(0)


# @features tasks
# @dimensions assignee permission-gates
def test_assigned_user_can_work_their_assigned_task(get_user):
    """A task assigned to a user is actionable for that assignee."""
    owner = get_user(Users.OWNER)
    assignee = get_user(Users.create_user)
    Tasks.test_filter_by_assigned_user.get(owner)
    task = Tasks.test_assigned_permission_task.get(owner)

    assignee.go(task)

    task_row = assignee.locate(f"[data-key='{task.key}']")
    expect(task_row).to_be_visible()
    expect(task_row.locator(Task.COMPLETE_TASK_CHECKBOX)).to_be_visible()
    expect(task_row.locator(Task.SETTINGS_FORM)).to_be_visible()
