"""
Tests for task completion history from the page task row.

Verified against:
- lagniappe/web/templates/pages/tasks.html
- lagniappe/web/routes/tasks/main.py
- src/script/widgets/tables.mjs
- lagniappe/core/entities/task.py
"""

from dataclasses import replace
import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from testing.definitions import ModelTasks, Pages, Tasks, Users
from testing.resources import Task
from testing.utility import expect_successful_response

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


def _complete_then_uncomplete(task, *, reload=True):
    task.complete()
    assert task.completed
    task.uncomplete()
    assert not task.completed
    history_toggles = task.element.locator("button[lp-control='history']")
    expect(history_toggles).to_have_count(2)
    expect(
        task.element.locator("button[lp-control='history']:visible")
    ).to_have_count(1)
    expect(task.element.locator(Task.TASK_HISTORY)).to_have_count(1)
    if reload:
        task.user.reload()
        task.wait_for_load()


def _open_history(task):
    task._wait_for_page_task_list()
    task._close_task()
    history_toggle = task.element.locator(Task.TASK_HISTORY_TOGGLE)
    expect(history_toggle).to_be_visible()
    with expect_successful_response(
        task.user.page,
        method="GET",
        path=f"/tasks/{task.key}/history",
    ):
        history_toggle.click()

    history = task.element.locator(Task.TASK_HISTORY)
    expect(history).to_be_visible()
    expect(history.locator("table")).to_be_visible()
    return history


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
    with user.page.expect_response(
        lambda response: response.url.split("?", 1)[0]
        .rstrip("/")
        .endswith("/combine")
        and response.request.method == "GET"
    ) as response_info:
        action.click()

    assert response_info.value.headers.get("cache-control") == "no-store"

    combine_form = task.element.locator("[data-widget='TaskCombine']")
    expect(combine_form).to_be_visible()
    expect(combine_form).to_have_attribute("rendered", "")
    return combine_form


# @features tasks
# @dimensions history completion-cycle name description attachments
# @template cell.html::cell
def test_task_history_appears_after_completion_cycle(get_user):
    user = get_user(Users.OWNER)
    task_name = f"History Task {uuid4().hex}"
    task = _create_combine_task(
        user,
        Pages.test_create_page_task.get(user).entity,
        task_name,
    )
    task.definition = replace(
        Tasks.test_history_task.value.definition,
        name=task_name,
    )
    attachment_name = f"History Attachment {uuid4().hex}"
    attachment = Entities.FILE.create(
        data={"name": attachment_name, "filename": "history-attachment.txt"}
    )
    attachment.save()
    task.entity.description = "History task completion description"
    task.entity.properties.files.add(attachment)
    task.entity.save()
    user.go(task)

    _complete_then_uncomplete(task)
    expect(task.element.locator("[data-role='saved-files']")).to_have_count(0)
    history = _open_history(task)

    expect(history.locator("th[data-column='completed_on']")).to_be_visible()
    expect(history.locator("th[data-column='name']")).to_be_visible()
    expect(history.locator("th[data-column='description']")).to_be_visible()
    expect(history.locator("th[data-column='completed_by']")).to_be_hidden()
    expect(history.locator("th[data-column='files']")).to_be_hidden()
    expect(history.locator("tbody tr")).not_to_have_count(0)
    expect(history.locator("tbody")).to_contain_text(task_name)
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
    user = get_user(Users.OWNER)
    task = Tasks.test_history_form_task.get(user)
    _add_task_row_pressure(task)
    user.go(task)

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
# @dimensions history-fill latest-submission repeating-default patch live-update
# @template pages/tasks.html::task_form
def test_task_form_field_fills_from_latest_history(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_history_fill_task.get(user)
    user.go(task)

    _complete_then_uncomplete(task, reload=False)

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
    ):
        fill_button.click()
    expect(text_field).to_contain_text("Historical text value")
    expect(number_field).to_be_visible()

    with user.page.expect_response(
        lambda response: "/default-submission" in response.url
        and response.request.method == "PATCH"
    ):
        number_fill_button.click()

    expect(text_field).to_contain_text("Historical text value")
    expect(text_field.locator("input")).to_have_value("Historical text value")
    expect(number_field.locator("input")).to_have_value("42")

    _complete_then_uncomplete(task, reload=False)
    task_form = task.task_form
    expect(task_form.locator("[name='input-textab12']")).to_have_value(
        "Historical text value"
    )
    expect(task_form.locator("[name='input-numgh78']")).to_have_value("42")

    user.reload()
    task.wait_for_load()
    task_form = task.task_form
    expect(task_form.locator("[name='input-textab12']")).to_have_value(
        "Historical text value"
    )
    expect(task_form.locator("[name='input-numgh78']")).to_have_value("42")


# @pairs tasks:history-fill tasks:latest-submission tasks:live-update tasks:element-matrix
# @template pages/tasks.html::task_form
def test_task_history_fill_controls_cover_submission_elements(get_user):
    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    suffix = uuid4().hex
    options = [
        {"label": "First option", "value": "first"},
        {"label": "Second option", "value": "second"},
    ]
    form = Entities.FORM.create(
        {"name": f"History Fill Matrix Form {suffix}", "form-type": "task"}
    )
    form.schema = [
        {
            "id": "history-text",
            "type": "input",
            "input": "text",
            "title": "Text",
        },
        {
            "id": "history-date",
            "type": "input",
            "input": "date",
            "title": "Date",
        },
        {
            "id": "history-time",
            "type": "input",
            "input": "time",
            "title": "Time",
        },
        {
            "id": "history-number",
            "type": "input",
            "input": "number",
            "title": "Number",
        },
        {
            "id": "history-email",
            "type": "input",
            "input": "email",
            "title": "Email",
        },
        {
            "id": "history-phone",
            "type": "input",
            "input": "tel",
            "title": "Phone",
        },
        {"id": "history-notes", "type": "textarea", "title": "Notes"},
        {"id": "history-checkbox", "type": "checkbox", "title": "Checkbox"},
        {
            "id": "history-radio",
            "type": "radio",
            "title": "Radio",
            "options": options,
        },
        {
            "id": "history-select",
            "type": "select",
            "title": "Select",
            "options": options,
        },
        {
            "id": "history-multiselect",
            "type": "select",
            "title": "Multiple Select",
            "multiple": True,
            "options": options,
        },
        {
            "id": "history-link",
            "type": "link",
            "title": "External Link",
            "location": "out",
        },
        {"id": "history-location", "type": "location", "title": "Location"},
        {
            "id": "history-table",
            "type": "table",
            "title": "Table",
            "columns": [
                {
                    "id": "history-row-note",
                    "type": "input",
                    "input": "text",
                    "title": "Row Note",
                }
            ],
        },
        {"id": "history-todo", "type": "todo", "title": "To-do List"},
        {
            "id": "history-signature",
            "type": "signature",
            "title": "Signature",
        },
    ]
    form.save()

    fillable_values = {
        "history-text": "Historical text",
        "history-date": "2026-08-15",
        "history-time": "13:45",
        "history-number": 42,
        "history-email": "history@example.com",
        "history-phone": "5551234567",
        "history-notes": "Historical notes",
        "history-checkbox": True,
        "history-radio": "second",
        "history-select": "first",
        "history-multiselect": ["first", "second"],
        "history-link": {
            "url": "https://example.com/history",
            "title": "History Link",
        },
        "history-location": {
            "id": "history-place",
            "name": "History Place",
            "address": "123 History Street, Test City",
        },
        "history-table": {"rows": [{"history-row-note": "Historical row"}]},
        "history-todo": {
            "items": [{"text": "Historical to-do", "checked": True}]
        },
    }
    task_entity = Entities.TASK.create(
        {
            "name": f"History Fill Matrix Task {suffix}",
            "page": parent.entity,
            "form": form,
            "submission": fillable_values,
        }
    )
    task_entity = Entities.fetch_one(
        task_entity,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    task_entity.save()
    task = Task(user=user)
    task.entity = task_entity

    try:
        user.go(task)
        parent.complete_task(task)
        parent.uncomplete_task(task)

        task_form = task.task_form
        for field_id in fillable_values:
            field = task_form.locator(f"[id^='{field_id}-'].form-element")
            expect(field).to_be_visible()
            history_fill = field.locator("[data-role='history-fill']")
            expect(history_fill).to_be_visible()
            expect(history_fill).to_have_attribute(
                "aria-label", "Fill from latest history"
            )
            expect(
                history_fill.locator("[data-icon='historyFill'] .icon-glyph")
            ).to_be_visible()

        signature = task_form.locator(
            "[id^='history-signature-'].form-element"
        )
        expect(signature).to_be_visible()
        expect(signature.locator("[data-role='history-fill']")).to_have_count(0)

        table = task_form.locator("[id^='history-table-'].form-element")
        with expect_successful_response(
            user.page,
            method="PATCH",
            path=f"/tasks/{task.key}/default-submission",
            entity_key=task.key,
        ):
            table.locator("[data-role='history-fill']").click()
        expect(table.locator("tbody tr[data-index]")).to_have_count(1)

        todo = task_form.locator("[id^='history-todo-'].form-element")
        todo.locator("[data-role='history-fill']").click()
        expect(todo.locator("[data-role='todo-check']")).not_to_be_checked()
    finally:
        Entities.delete(task_entity)
        Entities.delete(form)


# @features embedded-table
# @dimensions table-cell-expand
# @template cell.html::table_cell
# @template controls.html::expand
def test_task_history_expands_table_submission_cell(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_history_table_task.get(user)
    user.go(task)

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

# @pairs task-combine:winner task-combine:completed-on
# @pairs task-combine:attachments task-combine:migrate-history task-combine:delete
# @pairs task-combine:delta task-combine:checkbox-submit task-combine:isolated-form
# @pairs task-combine:no-reload
# @template pages/tasks.html::combine_form
# @template pages/tasks.html::task
def test_combine_tasks_migrates_history_and_reconciles_task_delta(get_user):
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
    ):
        combine_form.get_by_role("button", name="Combine Tasks").click()

    assert user.page.url == before_url

    winner_row = user.locate(f"[data-key='{winner.key}']")
    expect(winner_row).to_be_attached()
    expect(winner_row).to_have_attribute("data-completed", "true")
    expect(user.locate(f"[data-key='{source.key}']")).not_to_be_attached()
    expect(user.locate(f"[data-key='{secondary.key}']")).not_to_be_attached()

    fixture.definition.origin.get(user).completed_task_list
    expect(winner_row).to_be_visible()
    winner.element = winner_row
    history = _open_history(winner)
    history_rows = history.locator("tbody")
    for name in (
        "Combine source archived",
        "Combine source current",
        "Combine secondary current",
    ):
        expect(history_rows).to_contain_text(name)

    controller = _open_history_visibility(history)
    controller.locator("input[type='checkbox'][name='files']").set_checked(True)
    for attachment in (
        "Combine archived attachment",
        "Combine current attachment",
    ):
        expect(history.get_by_role("link", name=attachment)).to_be_visible()
