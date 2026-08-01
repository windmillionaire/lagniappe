"""
Tests for task completion history from the page task row.

Verified against:
- lagniappe/web/templates/pages/tasks.html
- lagniappe/web/routes/tasks/main.py
- src/script/widgets/tables.mjs
- lagniappe/core/entities/task.py
"""

import re
from datetime import datetime, timezone
from time import monotonic, sleep
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from testing.definitions import ModelTasks, Pages, Tasks, Users
from testing.resources import Task

pytestmark = pytest.mark.e2e


def _add_task_row_pressure(task, count=40):
    """Keep the history story representative of a well-populated task page."""
    page = task.entity.page
    filler_tasks = [
        Entities.TASK.create(
            {
                "name": f"History list pressure {index:02d}",
                "description": "Task used to exercise cumulative page-list rendering.",
                "page": page,
            }
        )
        for index in range(count)
    ]
    Entities.save(*filler_tasks, page)


def _complete_then_uncomplete(task):
    task.complete()
    assert task.completed
    task.uncomplete()
    assert not task.completed
    _wait_for_history(task)
    history_toggles = task.element.locator("button[lp-control='history']")
    expect(history_toggles).to_have_count(2)
    expect(
        task.element.locator("button[lp-control='history']:visible")
    ).to_have_count(1)
    expect(task.element.locator(Task.TASK_HISTORY)).to_have_count(1)


def _wait_for_history(task, timeout=10):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        entity = Entities.fetch_one(task.key, request=Fetch.direct())
        if entity and entity.has_history and entity.history:
            task.entity = entity
            return entity
        sleep(0.2)

    entity = Entities.fetch_one(task.key, request=Fetch.direct())
    raise AssertionError(f"Task history was not persisted for {task.key}: {entity.db}")


def _open_history(task):
    task._wait_for_page_task_list()
    task._close_task()
    history_toggle = task.element.locator(Task.TASK_HISTORY_TOGGLE)
    expect(history_toggle).to_be_visible()
    history_toggle.click()

    history = task.element.locator(Task.TASK_HISTORY)
    expect(history).to_be_visible()
    expect(history.locator("table")).to_be_visible()
    return history


def _history_columns_key(task):
    return f"columns-{task.entity.hash}-history"


def _clear_history_column_preferences(user, task):
    user.page.evaluate(
        "(key) => localStorage.removeItem(key)", _history_columns_key(task)
    )


def _open_history_visibility(history):
    toggle = history.locator("[data-role='embedded-table-visibility']")
    expect(toggle).to_be_visible()
    toggle.click()

    controller = history.locator("[data-widget='TableVisibility']")
    expect(controller).to_be_visible()
    return controller


def _create_combine_task(
    user,
    page,
    name,
    *,
    model=None,
    form=None,
    submission=None,
    completed_on=None,
):
    entity = Entities.TASK.create(
        {
            "name": name,
            "description": f"History retained from {name}",
            "page": page,
            "model": model,
            "form": form,
            "submission": submission,
        }
    )
    entity = Entities.fetch_one(
        entity,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    if completed_on:
        entity.completed = True
        entity.completed_on = completed_on
        entity.completed_by = user.entity
    entity.save()

    resource = Task(user=user)
    resource.entity = entity
    return resource


def _open_combine_form(user, task):
    task.wait_for_load()
    task.element.get_by_role("button", name="Task actions").click()
    menu = user.page.get_by_role("menu", name="Task actions")
    expect(menu).to_be_visible()
    action = menu.get_by_role("menuitem", name="Combine with Task")
    expect(action).to_have_attribute("data-kind", "task")
    view_key = user.locate("[lp-view]").get_attribute("data-key")
    with user.page.expect_response(
        lambda response: response.url.split("?", 1)[0]
        .rstrip("/")
        .endswith("/combine")
        and response.request.method == "GET"
    ) as response_info:
        action.click()

    response = response_info.value
    assert parse_qs(urlparse(response.url).query).get("page") == [view_key]
    assert response.headers.get("cache-control") == "no-store"

    combine_form = task.element.locator("[data-widget='TaskCombine']")
    expect(combine_form).to_be_visible()
    expect(combine_form).to_have_attribute("rendered", "")
    return combine_form


# @features tasks
# @dimensions history completion-cycle name description attachments
# @template cell.html::cell
def test_task_history_appears_after_completion_cycle(get_user):
    """Completing and reopening a task leaves a visible history record."""
    user = get_user(Users.OWNER)
    task = Tasks.test_history_task.get(user)
    attachment_name = "History Attachment"
    attachment = Entities.FILE.create(
        data={"name": attachment_name, "filename": "history-attachment.txt"}
    )
    attachment.save()
    task.entity.description = "History task completion description"
    task.entity.properties.files.add(attachment)
    task.entity.save()
    user.go(task)
    _clear_history_column_preferences(user, task)

    task.complete()
    completed = Entities.fetch_one(
        task.key,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    completed.uncomplete()
    completed.save()
    task.entity = completed
    user.reload()
    task.wait_for_load()
    _wait_for_history(task)
    expect(task.element.locator("[data-role='saved-files']")).to_have_count(0)
    history = _open_history(task)

    expect(history.locator("th[data-column='completed_on']")).to_be_visible()
    expect(history.locator("th[data-column='name']")).to_be_visible()
    expect(history.locator("th[data-column='description']")).to_be_visible()
    expect(history.locator("th[data-column='completed_by']")).to_be_hidden()
    expect(history.locator("th[data-column='files']")).to_be_hidden()
    expect(history.locator("tbody tr")).not_to_have_count(0)
    expect(history.locator("tbody")).to_contain_text("History Task")
    expect(history.locator("tbody")).to_contain_text(
        "History task completion description"
    )
    expect(history.locator("tbody")).to_contain_text(attachment_name)
    attachment_link = history.locator("td[data-column='files'] a").filter(
        has_text=attachment_name
    )
    expect(attachment_link).to_be_hidden()
    expect(attachment_link).to_have_attribute("href", re.compile(r"/files/.+"))


# @pairs tasks:history tasks:reload
# @pairs table-controls:column-visibility table-controls:persistence
# @template pages/tasks.html::task_tab
def test_task_history_visibility_persists_after_reload(get_user):
    """A task history column choice survives a full page reload."""
    user = get_user(Users.OWNER)
    task = Tasks.test_history_form_task.get(user)
    _add_task_row_pressure(task)
    user.go(task)
    _clear_history_column_preferences(user, task)

    _complete_then_uncomplete(task)

    history = _open_history(task)
    form_column = history.locator("th[data-column='input-textab12']")
    expect(form_column).to_be_hidden()

    controller = _open_history_visibility(history)
    form_column_toggle = controller.locator(
        "input[type='checkbox'][name='input-textab12']"
    )
    expect(form_column_toggle).not_to_be_checked()
    form_column_toggle.set_checked(True)
    expect(form_column).to_be_visible()
    assert "input-textab12" in user.page.evaluate(
        "(key) => JSON.parse(localStorage.getItem(key))", _history_columns_key(task)
    )

    user.reload()
    task.wait_for_load()

    history = _open_history(task)
    expect(history.locator("th[data-column='completed_on']")).to_be_visible()
    expect(history.locator("th[data-column='input-textab12']")).to_be_visible()
    expect(history.locator("tbody tr")).not_to_have_count(0)

    controller = _open_history_visibility(history)
    expect(
        controller.locator("input[type='checkbox'][name='input-textab12']")
    ).to_be_checked()


# @features tasks
# @dimensions history-fill latest-submission repeating-default patch
# @template pages/tasks.html::task_form
def test_task_form_field_fills_from_latest_history(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_history_fill_task.get(user)
    user.go(task)

    history_fill_requests = []
    user.page.on(
        "request",
        lambda request: history_fill_requests.append(request.url)
        if "/history/latest-submission" in request.url
        else None,
    )

    _complete_then_uncomplete(task)

    task_form = task.task_form

    text_field = task_form.locator("[id^='input-textab12'].form-element")
    expect(text_field).to_be_visible()
    fill_button = text_field.locator("[data-role='history-fill']")
    expect(fill_button).to_be_visible()

    number_field = task_form.locator("[id^='input-numgh78'].form-element")
    number_fill_button = number_field.locator("[data-role='history-fill']")
    expect(number_fill_button).to_be_visible()

    empty_field = task_form.locator("[id^='input-datecd34'].form-element")
    expect(empty_field.locator("[data-role='history-fill']")).to_have_count(0)

    with user.page.expect_response(
        lambda response: "/default-submission" in response.url
        and response.request.method == "PATCH"
    ) as text_default_response:
        fill_button.click()
    assert text_default_response.value.status == 200
    expect(text_field).to_contain_text("Historical text value")
    expect(number_field).to_be_visible()

    with user.page.expect_response(
        lambda response: "/default-submission" in response.url
        and response.request.method == "PATCH"
    ) as number_default_response:
        number_fill_button.click()
    assert number_default_response.value.status == 200

    expect(text_field).to_contain_text("Historical text value")
    expect(text_field.locator("input")).to_have_value("Historical text value")
    expect(number_field.locator("input")).to_have_value("42")
    assert len(history_fill_requests) == 1

    saved = Entities.fetch_one(task.key, request=Fetch.direct())
    assert saved.default_submission == {
        "input-textab12": "Historical text value",
        "input-numgh78": 42.0,
    }


# @features embedded-table
# @dimensions table-cell-expand
# @template cell.html::table_cell
# @template controls.html::expand
def test_task_history_expands_table_submission_cell(get_user):
    """A completed task history row can expand a table-valued submission."""
    user = get_user(Users.OWNER)
    task = Tasks.test_history_table_task.get(user)
    user.go(task)
    _clear_history_column_preferences(user, task)

    _complete_then_uncomplete(task)
    history = _open_history(task)

    cell = history.locator("td[data-column='items']")
    expect(cell).to_be_hidden()
    controller = _open_history_visibility(history)
    controller.locator("input[type='checkbox'][name='items']").set_checked(True)
    expect(cell).to_be_visible()
    expect(cell).to_contain_text("1 row")

    expand = cell.locator("button[data-role='expand']")
    expect(expand).to_be_visible()
    with user.page.expect_response("**/forms/*/expand-table-cell/items"):
        expand.click()

    expect(expand).to_have_attribute("data-open", "true")
    embedded = history.locator(
        "[data-role='table'] > #embedded-table > tbody > tr[data-embedded='true']"
    )
    expect(embedded).to_be_visible()
    expect(embedded).to_contain_text("Note")
    expect(embedded).to_contain_text("History row")


# @pairs task-combine:compatible task-combine:same-page
# @pairs task-combine:same-model task-combine:no-model
# @pairs task-combine:checkbox-form task-combine:lazy-form
# @pairs task-combine:lazy-reload
# @pairs task-combine:view-page task-combine:linked-page
# @pairs web-headers:no-store
# @template pages/tasks.html::combine_form
def test_combine_task_form_filters_compatible_tasks(get_user):
    """The picker exposes same-model tasks owned by the currently viewed page."""
    user = get_user(Users.OWNER)
    fixture = Tasks.test_history_task.get(user)
    page = fixture.entity.page
    model_one = ModelTasks.test_create_model_task.get(user).entity
    model_two = ModelTasks.test_create_model_task_with_form.get(user).entity

    no_model_source = _create_combine_task(user, page, "Combine no-model source")
    no_model_peer = _create_combine_task(user, page, "Combine no-model peer")
    modeled_peer = _create_combine_task(
        user, page, "Combine modeled distractor", model=model_one
    )
    user.go(no_model_source)

    combine_form = _open_combine_form(user, no_model_source)
    expect(
        combine_form.get_by_role("checkbox", name=no_model_peer.entity.name)
    ).to_be_visible()
    expect(
        combine_form.get_by_role("checkbox", name=modeled_peer.entity.name)
    ).to_have_count(0)

    late_no_model_peer = _create_combine_task(
        user, page, "Combine late no-model peer"
    )
    no_model_source._close_task()
    combine_form = _open_combine_form(user, no_model_source)
    expect(
        combine_form.get_by_role("checkbox", name=late_no_model_peer.entity.name)
    ).to_be_visible()

    modeled_source = _create_combine_task(
        user, page, "Combine modeled source", model=model_one
    )
    same_model_peer = _create_combine_task(
        user, page, "Combine same-model peer", model=model_one
    )
    other_model_peer = _create_combine_task(
        user, page, "Combine other-model peer", model=model_two
    )
    user.go(modeled_source)

    combine_form = _open_combine_form(user, modeled_source)
    expect(
        combine_form.get_by_role("checkbox", name=same_model_peer.entity.name)
    ).to_be_visible()
    expect(
        combine_form.get_by_role("checkbox", name=no_model_peer.entity.name)
    ).to_have_count(0)

    expect(
        combine_form.get_by_role("checkbox", name=other_model_peer.entity.name)
    ).to_have_count(0)

    linked_page = Pages.test_task_pages_move_target.get(user)
    linked_source = _create_combine_task(
        user, page, "Combine source shown on linked page"
    )
    linked_source.entity.linked_pages = [linked_page.entity]
    linked_source.entity.save()
    linked_page_peer = _create_combine_task(
        user, linked_page.entity, "Combine linked-page peer"
    )

    user.go(linked_page)
    linked_page.task_list
    combine_form = _open_combine_form(user, linked_source)
    expect(
        combine_form.get_by_role("checkbox", name=linked_page_peer.entity.name)
    ).to_be_visible()
    expect(
        combine_form.get_by_role("checkbox", name=no_model_peer.entity.name)
    ).to_have_count(0)

    combine_form.get_by_role(
        "checkbox", name=linked_page_peer.entity.name
    ).check()
    with user.page.expect_response(
        lambda response: response.url.split("?", 1)[0]
        .rstrip("/")
        .endswith("/combine")
        and response.request.method == "PUT"
    ) as response_info:
        combine_form.get_by_role("button", name="Combine Tasks").click()

    response = response_info.value
    assert parse_qs(urlparse(response.url).query).get("page") == [linked_page.key]
    assert "task_delta" in response.json()


# @pairs task-combine:winner task-combine:completed-on
# @pairs task-combine:current-snapshot task-combine:source-snapshot
# @pairs task-combine:existing-history
# @pairs task-combine:attachments task-combine:migrate-history task-combine:delete
# @pairs task-combine:delta task-combine:upsert task-combine:remove task-combine:ordering
# @pairs task-combine:checkbox-submit task-combine:isolated-form task-combine:no-reload
# @template pages/tasks.html::combine_form
# @template pages/tasks.html::task
def test_combine_tasks_migrates_history_and_reconciles_task_delta(get_user):
    """Combining retains each losing timeline and reconciles the page list in place."""
    user = get_user(Users.OWNER)
    fixture = Tasks.test_history_form_task.get(user)
    page = fixture.entity.page
    form = fixture.entity.form
    source = _create_combine_task(
        user,
        page,
        "Combine source archived",
        form=form,
        submission={"input-textab12": "Archived source submission"},
    )
    secondary = _create_combine_task(user, page, "Combine secondary current")
    winner = _create_combine_task(
        user,
        page,
        "Combine completed winner",
        completed_on=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    archived_attachment = Entities.FILE.create(
        data={
            "name": "Combine archived attachment",
            "filename": "combine-archived.txt",
        }
    )
    current_attachment = Entities.FILE.create(
        data={
            "name": "Combine current attachment",
            "filename": "combine-current.txt",
        }
    )
    Entities.save(archived_attachment, current_attachment)

    source.entity.completed = True
    source.entity.completed_on = datetime(2026, 6, 1, tzinfo=timezone.utc)
    source.entity.completed_by = user.entity
    source.entity.properties.files.add(archived_attachment)
    source.entity.uncomplete()
    source.entity.name = "Combine source current"
    source.entity.submission = {"input-textab12": "Current source submission"}
    source.entity.properties.files.add(current_attachment)
    source.entity.save()
    source.entity = Entities.fetch_one(
        source.key,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    original_history = source.entity.history[0]
    original_history_key = original_history.urlsafe_key

    user.go(source)
    combine_form = _open_combine_form(user, source)
    before_url = user.page.url
    combine_form.get_by_role("checkbox", name=secondary.entity.name).check()
    combine_form.get_by_role("checkbox", name=winner.entity.name).check()

    with user.page.expect_response(
        lambda response: response.url.split("?", 1)[0]
        .rstrip("/")
        .endswith("/combine")
        and response.request.method == "PUT"
    ) as response_info:
        combine_form.get_by_role("button", name="Combine Tasks").click()

    response = response_info.value
    assert response.status == 200
    delta = response.json()["task_delta"]
    assert delta["upsert"][0]["key"] == winner.key
    assert set(delta["remove"]) == {source.key, secondary.key}
    assert winner.key in delta["order"]
    assert source.key not in delta["order"]
    assert secondary.key not in delta["order"]
    assert user.page.url == before_url

    winner_row = user.locate(f"[data-key='{winner.key}']")
    expect(winner_row).to_be_attached()
    expect(winner_row).to_have_attribute("data-completed", "true")
    expect(user.locate(f"[data-key='{source.key}']")).not_to_be_attached()
    expect(user.locate(f"[data-key='{secondary.key}']")).not_to_be_attached()

    saved_winner = Entities.fetch_one(
        winner.key,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    migrated_history = saved_winner.history
    assert len(migrated_history) == 3
    assert {history.name for history in migrated_history} == {
        "Combine source archived",
        "Combine source current",
        "Combine secondary current",
    }
    assert {
        file.name
        for history in migrated_history
        for file in history.files
    } == {
        "Combine archived attachment",
        "Combine current attachment",
    }
    assert Entities.fetch_one(source.key, request=Fetch.root()) is None
    assert Entities.fetch_one(secondary.key, request=Fetch.root()) is None
    assert Entities.fetch_one(original_history_key, request=Fetch.root()) is None
