"""
Permission tests for task visibility and task-row edit controls.

Verified against:
- lagniappe/web/templates/pages/tasks.html
- lagniappe/web/routes/tasks/main.py
- lagniappe/core/entities/task.py
"""

import hashlib
import json

import pytest
import requests
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe import CONFIG
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get
from testing.definitions import Categories, Pages, Tasks, Uploads, Users
from testing.resources import File, Task
from testing.utility.network import (
    assert_lagniappe_error_response,
    assert_same_etag,
    manual_mutation_headers,
)

pytestmark = pytest.mark.e2e


def _task_side_effect_state(task, *users):
    persisted = Entities.fetch_one(task.key, request=Fetch.direct())
    history_keys = tuple(
        row.key for row in database_get.task_history(persisted)
    )
    notification_keys = tuple(
        (
            user.entity.key,
            tuple(
                row.key
                for row in database_get.activity(
                    user.entity,
                    types="notification",
                )
            ),
        )
        for user in users
    )
    return (
        persisted.fingerprint,
        persisted.modified,
        history_keys,
        notification_keys,
    )


def _submitted_reference_page(category, suffix):
    page = Entities.PAGE.create(
        {
            "name": f"Submitted reference page {suffix}",
            "description": "Submitted reference authorization coverage.",
            "attributes": ["tasks", "files"],
            "categories": [],
            "model": category.entity,
            "form": None,
        }
    )
    page.save()
    return page


def _browser_http_context(user):
    cookies = {
        cookie["name"]: cookie["value"] for cookie in user.page.context.cookies()
    }
    headers = manual_mutation_headers(
        user.page.url,
        user.locate("#token").input_value(),
    )
    return cookies, headers


# @matrix permissions : authorization-before-cache etag resource-gates
# @pair cache:permissions
def test_task_route_is_forbidden_without_model_or_page_permission(
    get_user, browser_failures
):
    owner = get_user(Users.OWNER)
    task = Tasks.test_create_page_task.get(owner)

    blocked = get_user(Users.user_no_access)
    state_before = _task_side_effect_state(task, owner, blocked)
    with browser_failures.expect_http_error(blocked, status=403, path=task.url):
        blocked.navigate(task.url)
        expect(blocked.page).to_have_title("Error 403")

    blocked_fingerprint = hashlib.md5(
        (
            f"{task.entity.fingerprint}-{CONFIG.BUILD_ID}-"
            f"{blocked.entity.authorization_fingerprint}"
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
    assert_lagniappe_error_response(response, status=403)
    assert_same_etag(response.headers.get("etag"), f'"{blocked_fingerprint}"')
    assert task.entity.name not in response.text
    assert _task_side_effect_state(task, owner, blocked) == state_before


# @pairs task-combine:authorization tasks:history
def test_task_history_routes_are_forbidden_without_permission(get_user):
    owner = get_user(Users.OWNER)
    task = Tasks.test_create_page_task.get(owner)

    blocked = get_user(Users.user_no_access)
    state_before = _task_side_effect_state(task, owner, blocked)
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
        assert_lagniappe_error_response(response, status=403)
        assert task.entity.name not in response.text

    assert _task_side_effect_state(task, owner, blocked) == state_before


# @matrix tasks : permission-gates readonly
def test_page_task_viewer_sees_task_without_edit_controls(get_user):
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


# @matrix tasks : completed-only empty-state
# @template pages/tasks.html::task_list
def test_completed_only_task_list_hides_empty_marker(get_user):
    owner = get_user(Users.OWNER)
    task = Tasks.test_completed_only_page_task.get(owner)
    if not task.entity.completed:
        task.mark_completed()

    viewer = get_user(Users.page_acl_one_visible)
    viewer.go(task)

    task_list = viewer.locate("[data-widget='PageTaskList']")
    expect(task_list).to_have_attribute("loaded", "")
    expect(task_list.locator(f"[data-key='{task.key}']")).to_be_visible()
    expect(task_list.locator("[data-role='empty']")).not_to_be_visible()


# @matrix tasks : attached-form empty-fields permission-gates readonly
# @template pages/tasks.html::task
# @template pages/tasks.html::task_form
def test_page_task_viewer_sees_empty_form_structure_without_edit_controls(get_user):
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


# @matrix tasks : assignee permission-gates
def test_assigned_user_can_work_their_assigned_task(get_user):
    owner = get_user(Users.OWNER)
    assignee = get_user(Users.create_user)
    Tasks.test_filter_by_assigned_user.get(owner)
    task = Tasks.test_assigned_permission_task.get(owner)

    assignee.go(task)

    task_row = assignee.locate(f"[data-key='{task.key}']")
    expect(task_row).to_be_visible()
    expect(task_row.locator(Task.COMPLETE_TASK_CHECKBOX)).to_be_visible()
    expect(task_row.locator(Task.SETTINGS_FORM)).to_be_visible()


# @matrix file pages tasks : submitted-reference
def test_forged_hidden_file_key_cannot_be_linked_to_editable_task_or_page(get_user):
    owner = get_user(Users.OWNER)
    category = Categories.test_create_category_manual_mode.get(owner)
    hidden_file_resource = File.upload_from_page(
        owner,
        Pages.test_file_upload_page,
        Uploads.plain_text_file,
    )
    hidden_file = Entities.fetch_one(
        hidden_file_resource.key,
        request=Fetch.direct(),
    )
    page = _submitted_reference_page(category, "forgery")
    task = Entities.TASK.create(
        {
            "name": "Submitted reference forgery task",
            "description": "Must reject hidden File keys.",
            "page": page,
            "form": None,
            "model": None,
            "project": None,
            "assigned_to": None,
            "due_date": None,
        }
    )
    task.save()

    actor = get_user(Users.user_one_category)
    actor.navigate(
        f"{SETTINGS.test_config['BASE_URL']}/pages/{page.urlsafe_key}"
    )
    assert page.allowed(Action.EDIT, user=actor.entity)
    assert task.allowed(Action.EDIT, user=actor.entity)
    assert not hidden_file.allowed(Action.VIEW, user=actor.entity)
    cookies, headers = _browser_http_context(actor)

    persisted_file = Entities.fetch_one(hidden_file.key, request=Fetch.direct())
    persisted_task = Entities.fetch_one(task.key, request=Fetch.direct())
    before = {
        "file_tasks": tuple(persisted_file.db.get("tasks", [])),
        "file_pages": tuple(persisted_file.db.get("pages", [])),
        "file_requires": tuple(persisted_file.db.get("requires", [])),
        "file_modified": persisted_file.modified,
        "task_files": tuple(persisted_task.db.get("files", [])),
        "task_modified": persisted_task.modified,
    }
    forged_assets = json.dumps({"forged": hidden_file.details})

    task_response = requests.put(
        f"{SETTINGS.test_config['BASE_URL']}/tasks/{task.urlsafe_key}/update",
        data={
            "active": "TaskSettings",
            "name": task.name,
            "description": task.description,
            "assets": forged_assets,
        },
        cookies=cookies,
        headers=headers,
        allow_redirects=False,
        timeout=10,
    )
    assert task_response.status_code == 422
    assert task_response.text == "One or more selected items are unavailable."

    page_response = requests.post(
        f"{SETTINGS.test_config['BASE_URL']}/files/{page.urlsafe_key}/upload",
        data={"existing-file": hidden_file.urlsafe_key},
        cookies=cookies,
        headers=headers,
        allow_redirects=False,
        timeout=10,
    )
    assert page_response.status_code == 422
    assert page_response.text == "One or more selected items are unavailable."

    persisted_file = Entities.fetch_one(hidden_file.key, request=Fetch.direct())
    persisted_task = Entities.fetch_one(task.key, request=Fetch.direct())
    assert {
        "file_tasks": tuple(persisted_file.db.get("tasks", [])),
        "file_pages": tuple(persisted_file.db.get("pages", [])),
        "file_requires": tuple(persisted_file.db.get("requires", [])),
        "file_modified": persisted_file.modified,
        "task_files": tuple(persisted_task.db.get("files", [])),
        "task_modified": persisted_task.modified,
    } == before
    assert not persisted_file.allowed(Action.VIEW, user=actor.entity)


# @pair tasks:signed-claim
def test_new_task_attachment_claim_is_required_and_scope_bound(get_user):
    owner = get_user(Users.OWNER)
    category = Categories.test_create_category_manual_mode.get(owner)
    upload_page = _submitted_reference_page(category, "upload")
    other_page = _submitted_reference_page(category, "other-scope")

    actor = get_user(Users.user_one_category)
    actor.navigate(
        f"{SETTINGS.test_config['BASE_URL']}/pages/{upload_page.urlsafe_key}"
    )
    cookies, headers = _browser_http_context(actor)

    upload_response = requests.post(
        f"{SETTINGS.test_config['BASE_URL']}/tasks/{upload_page.urlsafe_key}/upload-file",
        data={"assets": "{}", "mimetype": "text/plain"},
        files={"task-file": ("claim.txt", b"claim-bound attachment", "text/plain")},
        cookies=cookies,
        headers=headers,
        allow_redirects=False,
        timeout=10,
    )
    assert upload_response.status_code == 200
    uploaded = upload_response.json()
    asset = next(iter(uploaded["assets"].values()))
    assert asset["attachment_claim"]
    uploaded_file = Entities.fetch_one(asset["id"], request=Fetch.direct())
    assert not uploaded_file.allowed(Action.VIEW, user=actor.entity)

    wrong_scope = requests.post(
        f"{SETTINGS.test_config['BASE_URL']}/tasks/{other_page.urlsafe_key}/create",
        data={
            "name": "Wrong-scope attachment task",
            "description": "Must not be created.",
            "assets": json.dumps(uploaded["assets"]),
        },
        cookies=cookies,
        headers=headers,
        allow_redirects=False,
        timeout=10,
    )
    assert wrong_scope.status_code == 422
    assert wrong_scope.text == "One or more selected items are unavailable."

    accepted = requests.post(
        f"{SETTINGS.test_config['BASE_URL']}/tasks/{upload_page.urlsafe_key}/create",
        data={
            "name": "Claim-authorized attachment task",
            "description": "Created with a scope-bound upload claim.",
            "assets": json.dumps(uploaded["assets"]),
        },
        cookies=cookies,
        headers=headers,
        allow_redirects=False,
        timeout=10,
    )
    assert accepted.status_code == 200

    linked_file = Entities.fetch_one(asset["id"], request=Fetch.direct())
    assert linked_file.db.get("tasks")
    assert linked_file.allowed(Action.VIEW, user=actor.entity)
