"""
Tests for task completion history from the page task row.

Verified against:
- lagniappe/web/templates/pages/tasks.html
- lagniappe/web/routes/tasks/main.py
- src/script/widgets/taskHistory.mjs
- lagniappe/core/entities/task.py
"""

from dataclasses import replace
import re
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from lagniappe.core.tools.tasks.ordering import page_task_roots
from lagniappe.core.tools.forms.drafts import archive_form_generation
from testing.definitions import ModelTasks, Pages, Tasks, Users
from testing.resources import Task
from testing.utility.network import (
    expect_successful_response,
    multipart_form_fields,
    scoped_browser_route,
)

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
    ) as history_response:
        history_toggle.click()
    assert history_response.value.headers["cache-control"] == "no-store"

    history = task.element.locator(Task.TASK_HISTORY)
    expect(history).to_be_visible()
    expect(history.locator("[data-role='history-group'] > .table-container > table").first).to_be_visible()
    return history


def _open_history_visibility(history):
    toggle = history.locator("[data-role='embedded-table-visibility']")
    expect(toggle).to_be_visible()
    toggle.click()

    controller = history.locator("[data-widget='TableVisibility']")
    expect(controller).to_be_visible()
    return controller


# @matrix tasks task-completion : history generation readonly
# @matrix task-completion : original-view archive uncomplete
# @template tasks/history.html::completion_history
# @template pages/tasks.html::task_form
def test_completion_views_follow_generation_and_archive_original_answers(get_user):
    """Uncompletion archives the displayed answers after an optional original view."""
    from testing.resources.form import Form

    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    suffix = uuid4().hex[:8]
    form = Entities.FORM.create({
        "name": f"Completion definitions {suffix}", "form-type": "task",
        "schema": [
            {"id": "note", "type": "input", "title": "Original question"},
            {"id": "intro", "type": "html", "title": "Instructions"},
        ],
    })
    form.set_html_field("intro", "<p>Original instructions</p>")
    form.save()
    original_version = form.version
    original_generation = form.generation
    resources = []
    try:
        for name in (
            "Unopened completion", "Original completion", "Modified completion",
            "Archived completion",
        ):
            entity = Entities.TASK.create({
                "name": f"{name} {suffix}", "page": parent.entity, "form": form,
                "submission": {"note": "Original answer"},
            })
            entity = Entities.fetch_one(entity, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
            entity.save()
            resource = Task(user=user)
            resource.entity = entity
            resources.append(resource)
            user.go(resource)
            expect(resource.task_form.locator("[data-role='view-original-completion']")).to_have_count(0)
            parent.complete_task(resource)
            expect(resource.task_form.locator("[data-role='view-original-completion']")).to_have_count(0)
            expect(resource.task_form.locator("button[type='submit'], input[type='submit']")).to_have_count(0)
        *live_completions, archived = resources
        parent.uncomplete_task(archived)

        form_resource = Form(user=user)
        form_resource.entity = form
        builder = form_resource.builder
        builder.model.locator("[id='note']").click()
        builder.settings.locator("input[name='title']").fill("Updated question")
        builder.model.locator("[id='intro']").click()
        builder.open_condition("html", role="edit")
        editor = builder.condition.locator("[data-role='editor'] .ProseMirror")
        expect(editor).to_have_attribute("contenteditable", "true")
        editor.fill("Updated instructions")
        editor.blur()
        builder.condition.locator("button[data-role='close']").click()
        builder.save()
        saved_form = Entities.fetch_one(form.key, request=Fetch.root())
        assert saved_form.version != original_version
        assert saved_form.generation == original_generation

        user.go(live_completions[0])
        compatible_form = live_completions[0].task_form
        expect(compatible_form).to_contain_text("Updated question")
        expect(compatible_form).to_contain_text("Updated instructions")
        expect(compatible_form.locator("[data-role='original-completion-controls']")).to_have_count(0)
        user.go(archived)
        history = _open_history(archived)
        expect(history.get_by_role("button", name=re.compile("View completion"))).to_have_count(0)
        expect(history.locator("[data-role='completion-detail']")).to_have_count(0)
        original_history_key = history.locator("tbody tr[lp-entity]").get_attribute("data-key")
        controller = _open_history_visibility(history)
        controller.get_by_role("checkbox", name="Updated question", exact=True).check()
        expect(history.locator("th[data-column='note']")).to_be_visible()
        expect(history.locator("th[data-column='note']")).to_have_accessible_name("Updated question")
        expect(history.locator("td[data-column='note']")).to_have_text("Original answer")

        # Controlled generation fixture for the two completion read surfaces.
        # The real conversion engine has separate builder/job coverage; ordinary
        # saves correctly reject these synthetic generation jumps now.
        form = Entities.fetch_one(form.key, request=Fetch.root())
        archive_form_generation(form).save()
        form.schema = [
            {"id": "note", "type": "input", "title": "Next generation question"},
            {"id": "intro", "type": "html", "title": "Instructions"},
        ]
        form.set_html_field("intro", "<p>Next generation instructions</p>")
        form.save()
        form.generation = 1
        Entities.save_root(form, property_mask=("generation",))
        from lagniappe.core.tools.database.utility import save_mutations

        for live in live_completions:
            live.entity = Entities.fetch_one(live.key, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
            live.entity.db["submission"] = json.dumps({"note": "Current converted answer"})
            live.entity.db["generation"] = 1
            save_mutations([(live.entity, ("submission", "generation"))])
            live.entity.save()

        for live, choice in zip(live_completions, ("unopened", "original", "modified")):
            completion_path = f"/tasks/{live.key}/completion-details"
            completion_requests = []

            def track_completion_request(request):
                if request.method == "GET" and request.url.split("?", 1)[0].endswith(completion_path):
                    completion_requests.append(request)

            user.page.on("request", track_completion_request)
            try:
                user.go(live)
                task_form = live.task_form
                current_question = task_form.get_by_text("Next generation question", exact=True)
                current_answer = task_form.get_by_text("Current converted answer", exact=True)
                current_instructions = task_form.get_by_text("Next generation instructions", exact=True)
                expect(current_question).to_be_visible()
                expect(current_answer).to_be_visible()
                expect(current_instructions).to_be_visible()
                expect(task_form.locator("button[type='submit'], input[type='submit'], [data-role='archive-completion']")).to_have_count(0)
                expect(task_form.locator("input:not([type='hidden']):not([type='radio']), textarea, [contenteditable='true']")).to_have_count(0)

                warning = task_form.locator("[data-role='submission-changed-warning']")
                expect(warning).to_be_visible()
                expect(warning).to_contain_text("This form was modified after this task was completed.")
                original_button = task_form.get_by_role("button", name="View Original Submission", exact=True)
                expect(original_button).to_be_visible()
                choices = warning.get_by_role("group", name="When Reopened", include_hidden=True)
                expect(choices).to_be_hidden()
                original = task_form.locator("[data-role='original-completion-detail']")
                expect(original).to_be_hidden()

                if choice != "unopened":
                    with expect_successful_response(user.page, method="GET", path=completion_path) as original_response:
                        original_button.click()
                    assert original_response.value.headers["cache-control"] == "no-store"
                    expect(warning).to_be_visible()
                    expect(original_button).to_be_visible()
                    expect(choices).to_be_visible()
                    save_original = choices.get_by_role("radio", name="Archive original submission", exact=True)
                    save_modified = choices.get_by_role("radio", name="Archive modified submission", exact=True)
                    expect(save_original).to_be_checked()
                    expect(save_modified).not_to_be_checked()
                    expect(original).to_be_visible()
                    expect(original).to_contain_text("Updated question")
                    expect(original).to_contain_text("Original answer")
                    expect(original).to_contain_text("Updated instructions")
                    expect(original).not_to_contain_text("Current converted answer")
                    expect(original.locator("input:not([type='hidden']), textarea, [contenteditable='true']")).to_have_count(0)
                    expect(current_question).to_be_hidden()
                    expect(current_answer).to_be_hidden()
                    expect(current_instructions).to_be_hidden()

                    # The persistent link can show the loaded original again
                    # after previewing the modified values, without a second fetch.
                    save_modified.check()
                    expect(current_answer).to_be_visible()
                    original_button.click()
                    expect(save_original).to_be_checked()
                    expect(original).to_be_visible()
                    expect(current_answer).to_be_hidden()

                    if choice == "modified":
                        # Only the final selected radio should determine the
                        # archived values, even after viewing both forms again.
                        for selected in (save_modified, save_original, save_modified):
                            selected.check()
                            expect(selected).to_be_checked()
                            if selected == save_original:
                                expect(original).to_be_visible()
                                expect(current_question).to_be_hidden()
                                expect(current_answer).to_be_hidden()
                                expect(current_instructions).to_be_hidden()
                            else:
                                expect(original).to_be_hidden()
                                expect(current_question).to_be_visible()
                                expect(current_answer).to_be_visible()
                                expect(current_instructions).to_be_visible()
                    expect(task_form.locator("button[type='submit'], input[type='submit'], [data-role='archive-completion']")).to_have_count(0)

                with expect_successful_response(user.page, method="PUT", path=f"/tasks/{live.key}/update") as uncomplete_response:
                    parent.uncomplete_task(live)
                fields = dict(multipart_form_fields(uncomplete_response.value.request))
                expected_choice = "original" if choice == "original" else "modified"
                assert fields.get("completion_submission", "modified") == expected_choice
                assert len(completion_requests) == (0 if choice == "unopened" else 1)
            finally:
                user.page.remove_listener("request", track_completion_request)

            expect(live.element).to_have_attribute("data-completed", "false")
            expect(live.element.locator("[data-role='original-completion-controls']")).to_have_count(0)
            expect(live.task_form.locator("input[name='note']")).to_have_value("")
            history = _open_history(live)
            expected_generation = "0" if choice == "original" else "1"
            expect(history.locator("[data-role='history-group']")).to_have_attribute("data-generation", expected_generation)
            expect(history.get_by_role("button", name=re.compile("View completion"))).to_have_count(0)
            expect(history.locator("[data-role='completion-detail']")).to_have_count(0)
            controller = _open_history_visibility(history)
            controller.locator("input[type='checkbox'][name='note']").check()
            question = history.locator("th[data-column='note']")
            answer = history.locator("td[data-column='note']")
            expect(question).to_be_visible()
            expect(answer).to_be_visible()
            if choice == "original":
                expect(question).to_have_accessible_name("Updated question")
                expect(answer).to_have_text("Original answer")
            else:
                expect(question).to_have_accessible_name("Next generation question")
                expect(answer).to_have_text("Current converted answer")
            expect(history.locator("tbody input:not([type='hidden']), tbody textarea, tbody [contenteditable='true'], button[type='submit']")).to_have_count(0)

        # Original answers may be archived after a newer generation's answers.
        # They still belong to one original-generation table, not another run.
        archived.entity = Entities.fetch_one(
            archived.key,
            request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
        )
        completed_on = datetime.now(timezone.utc)
        later_histories = []
        for offset, generation, answer in (
            (1, 1, "Middle converted answer"),
            (2, 0, "Latest original answer"),
        ):
            record = Entities.TASK_HISTORY.create(archived.entity, {
                "submission": {"note": answer},
                "generation": generation,
                "completed_on": completed_on,
                "created": completed_on + timedelta(seconds=offset),
            })
            record.save()
            later_histories.append(record)
        user.go(archived)
        history = _open_history(archived)
        groups = history.locator("[data-role='history-group']")
        expect(groups).to_have_count(2)
        expect(groups.nth(0)).to_have_attribute("data-generation", "0")
        expect(groups.nth(1)).to_have_attribute("data-generation", "1")
        expect(history.locator("[data-role='history-group'] > .table-container > table")).to_have_count(2)
        expect(history.locator("[data-role='completion-entry'], [data-role='completion-detail']")).to_have_count(0)
        for generation, title, keys, answers in (
            (0, "Updated question", [later_histories[1].urlsafe_key, original_history_key], ["Latest original answer", "Original answer"]),
            (1, "Next generation question", [later_histories[0].urlsafe_key], ["Middle converted answer"]),
        ):
            group = history.locator(f"[data-role='history-group'][data-generation='{generation}']")
            controller = _open_history_visibility(group)
            controller.locator("input[type='checkbox'][name='note']").check()
            expect(group.locator("th[data-column='note']")).to_have_accessible_name(title)
            rows = group.locator("tbody > tr[lp-entity]")
            expect(rows).to_have_count(len(keys))
            for position, key in enumerate(keys):
                expect(rows.nth(position)).to_have_attribute("data-key", key)
            expect(group.locator("td[data-column='note']")).to_have_text(answers)
    finally:
        for resource in resources:
            Entities.delete(resource.entity)
        Entities.delete(form)


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
        entity.complete(user=user.entity)
        entity.completed_on = completed_on
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


# @matrix tasks : attachments completion-cycle description history name
# @template cell.html::cell
# @template tasks/history.html::completion_history
# @template pages/tasks.html::task_history
# @style table.container
# @style table.thead.th
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

    expect(history).to_have_css("outline-style", "none")
    group = history.locator("[data-role='history-group']")
    expect(group).to_have_css("border-top-width", "1px")
    expect(group).to_have_css("border-top-style", "solid")
    expect(group).to_have_css("border-top-left-radius", "6px")
    expect(group).to_have_css("background-color", "rgb(255, 255, 255)")
    expect(group).to_have_css("outline-style", "none")
    expect(group).to_have_css("padding-top", "0px")
    expect(group).to_have_css("padding-bottom", "0px")
    table_container = group.locator(".table-container")
    expect(table_container).to_have_css("border-top-width", "0px")
    expect(table_container).to_have_css("outline-style", "none")
    expect(table_container).to_have_css("padding-top", "0px")
    expect(table_container).to_have_css("padding-bottom", "0px")
    expect(table_container.locator("table")).to_have_css("margin-top", "0px")
    expect(table_container.locator("table")).to_have_css("margin-bottom", "0px")
    completed_header = history.locator("th[data-column='completed_on']")
    expect(completed_header).to_have_css("padding-top", "10px")
    expect(completed_header).to_have_css("padding-bottom", "10px")
    expect(history.get_by_role("button", name=re.compile("View completion"))).to_have_count(0)
    expect(history.locator("[data-role='completion-detail']")).to_have_count(0)

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


# @matrix tasks : active-widget complete history-refresh uncomplete
# @template pages/tasks.html::task
def test_uncomplete_from_loaded_task_history_closes_task(get_user):
    user = get_user(Users.OWNER)
    task_name = f"History Uncomplete Task {uuid4().hex}"
    task = _create_combine_task(
        user,
        Pages.test_create_page_task.get(user).entity,
        task_name,
    )
    task.definition = replace(
        Tasks.test_history_task.value.definition,
        name=task_name,
    )
    user.go(task)

    _complete_then_uncomplete(task)
    history = _open_history(task)
    expect(history.locator("tbody tr[lp-entity]")).to_have_count(1)
    task._close_task()
    task.complete()
    expect(task.element).to_have_attribute("data-open", "false")
    history = _open_history(task)
    expect(history.locator("tbody tr[lp-entity]")).to_have_count(1)
    controller = _open_history_visibility(history)
    expect(controller.get_by_role("checkbox", name="Completed On", exact=True)).to_be_visible()
    history.locator("[data-role='embedded-table-visibility']").click()
    expect(controller).to_be_hidden()

    task.uncomplete()

    expect(task.element).to_have_attribute("data-completed", "false")
    expect(task.element).to_have_attribute("data-open", "false")
    settings = task.element.locator(Task.SETTINGS_FORM)
    expect(settings).not_to_have_attribute("rendered", "")
    expect(settings).to_be_hidden()
    expect(task.element.locator(Task.TASK_HISTORY)).to_be_hidden()

    refreshed_history = _open_history(task)
    expect(refreshed_history.locator("tbody tr[lp-entity]")).to_have_count(2)


# @matrix tasks : active-widget history-refresh uncomplete
# @template pages/tasks.html::task_form
# @template pages/tasks.html::task_history
def test_reopening_discards_inactive_history_until_next_click(get_user):
    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    form = Entities.FORM.create({
        "name": f"History refresh {uuid4().hex[:8]}", "form-type": "task",
        "schema": [{"id": "answer", "type": "input", "title": "Answer"}],
    })
    form.save()
    task = _create_combine_task(
        user, parent.entity, f"History refresh {uuid4().hex[:8]}",
        form=form, submission={"answer": "First completion"},
    )
    user.go(task)
    parent.complete_task(task)
    parent.uncomplete_task(task)
    history = _open_history(task)
    expect(history.locator("tbody tr[lp-entity]")).to_have_count(1)

    task.task_form.locator("input[name='answer']").fill("Second completion")
    parent.complete_task(task)
    expect(task.element).to_have_attribute("data-open", "false")
    history = _open_history(task)
    expect(history.locator("tbody tr[lp-entity]")).to_have_count(1)
    expect(task.task_form).to_contain_text("Second completion")
    expect(history).to_be_hidden()
    expect(history.locator("tbody tr[lp-entity]")).to_have_count(1)

    history_requests = []
    history_path = f"/tasks/{task.key}/history"

    def track_history(request):
        if request.method == "GET" and request.url.split("?", 1)[0].endswith(history_path):
            history_requests.append(request)

    user.page.on("request", track_history)
    try:
        parent.uncomplete_task(task)
        expect(task.element).to_have_attribute("data-open", "false")
        expect(task.element.locator(Task.TASK_FORM)).to_be_hidden()
        expect(task.task_form.locator("input[name='answer']")).to_have_value("")
        expect(history).to_be_hidden()
        assert history_requests == [], "Reopening must not fetch History"

        refreshed = _open_history(task)
        assert len(history_requests) == 1
        expect(refreshed.locator("tbody tr[lp-entity]")).to_have_count(2)
        controller = _open_history_visibility(refreshed)
        controller.get_by_role("checkbox", name="Answer", exact=True).check()
        expect(refreshed.locator("td[data-column='answer']")).to_have_text(
            ["Second completion", "First completion"]
        )
    finally:
        user.page.remove_listener("request", track_history)


# @matrix tasks : active-widget complete uncomplete update-state
# @template pages/tasks.html::task
# @template pages/tasks.html::task_form
def test_completion_waits_for_acceptance_and_moves_closed_task(get_user, browser_failures):
    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    form = Entities.FORM.create({
        "name": f"Completion transition {uuid4().hex[:8]}", "form-type": "task",
        "schema": [{"id": "answer", "type": "input", "title": "Answer"}],
    })
    form.save()
    task = _create_combine_task(
        user, parent.entity, f"Completion transition {uuid4().hex[:8]}", form=form,
    )
    user.go(task)
    task.task_form.locator("input[name='answer']").fill("Keep this answer")
    row = user.locate(f"li[lp-component][data-key='{task.key}']")
    path = f"/tasks/{task.key}/update"
    held = []

    def hold_update(route):
        held.append(route)

    with scoped_browser_route(user.page.context, f"**{path}", hold_update):
        for completed in (False, True):
            # Hold the response in each direction: the current form stays open,
            # and a server rejection must preserve it and its entered values.
            for rejected in (True, False):
                with user.page.context.expect_event(
                    "request",
                    predicate=lambda request: request.method == "PUT" and request.url.endswith(path),
                ):
                    row.locator("[data-role='complete-toggle']").click()
                expect(row).to_have_attribute("data-completed", str(completed).lower())
                expect(row).to_have_attribute("data-open", "TaskForm")
                expect(row.locator(Task.TASK_FORM)).to_be_visible()
                assert len(held) == 1
                pending = held.pop()
                if rejected:
                    with browser_failures.expect_http_error(user, status=422, path=path):
                        pending.fulfill(
                            status=422, content_type="text/plain",
                            body="Completion change rejected; review your answer.",
                        )
                        expect(row.locator("[data-role='error']:visible")).to_contain_text(
                            "Completion change rejected"
                        )
                    expect(row).to_have_attribute("data-open", "TaskForm")
                    expect(row).to_have_attribute("data-completed", str(completed).lower())
                    if completed:
                        expect(row.locator(Task.TASK_FORM)).to_contain_text("Keep this answer")
                    else:
                        expect(row.locator("input[name='answer']")).to_have_value("Keep this answer")
                else:
                    with expect_successful_response(
                        user.page, method="PUT", path=path, entity_key=task.key,
                    ):
                        pending.continue_()
                    expect(row).to_have_attribute("data-completed", str(not completed).lower())
                    expect(row).to_have_attribute("data-open", "false")
                    expect(row.locator(Task.TASK_FORM)).to_be_hidden()

            destination = parent.active_task_list if completed else parent.completed_task_list
            task.element = destination.get_item(task)
            expect(task.element).to_be_visible()
            if not completed:
                expect(task.task_form).to_contain_text("Keep this answer")


# @matrix table-controls : column-visibility persistence
# @matrix tasks : history reload
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


# @matrix tasks : history-fill latest-submission live-update
# @matrix task-completion : field-reset uncomplete
# @source lagniappe/core/entities/task.py::Task.uncomplete
# @template pages/tasks.html::task_form
def test_task_form_field_fills_from_latest_history(get_user):
    """History restores this submission only; the next cycle starts empty."""
    user = get_user(Users.OWNER)
    task = Tasks.test_history_fill_task.get(user)
    saved_settings = {
        name: task.entity.db.get(name)
        for name in ("form", "page", "name", "description")
    }
    assert not task.entity.has_history
    history_requests = []

    def record_history_request(request):
        if f"/tasks/{task.key}/history/latest-submission" in request.url:
            history_requests.append(request.url)

    user.page.context.on("request", record_history_request)
    try:
        user.go(task)
        expect(task.task_form).to_have_attribute("initialized", "")
        expect(task.task_form.locator("[data-role='history-fill']")).to_have_count(0)
        assert history_requests == [], "A Task without history must not fetch it"
    finally:
        user.page.context.remove_listener("request", record_history_request)

    _complete_then_uncomplete(task, reload=False)

    task_form = task.task_form
    text_field = task_form.locator("[id^='input-textab12'].form-element")
    expect(text_field).to_be_visible()
    fill_button = text_field.locator("[data-role='history-fill']")
    expect(fill_button).to_be_visible()
    expect(text_field.locator("input")).to_have_value("")

    number_field = task_form.locator("[id^='input-numgh78'].form-element")
    number_fill_button = number_field.locator("[data-role='history-fill']")
    expect(number_fill_button).to_be_visible()
    expect(number_field.locator("input")).to_have_value("")

    empty_field = task_form.locator("[id^='input-datecd34'].form-element")
    expect(empty_field.locator("[data-role='history-fill']")).to_have_count(0)

    fill_button.click()
    expect(text_field).to_contain_text("Historical text value")
    expect(number_field).to_be_visible()
    number_fill_button.click()

    expect(text_field).to_contain_text("Historical text value")
    expect(text_field.locator("input")).to_have_value("Historical text value")
    expect(number_field.locator("input")).to_have_value("42")

    with expect_successful_response(
        user.page,
        method="PUT",
        path=f"/tasks/{task.key}/update",
        entity_key=task.key,
    ):
        task_form.locator("button[type='submit']:not([data-role])").click()

    user.reload()
    task.wait_for_load()
    task_form = task.task_form
    expect(task_form.locator("[name='input-textab12']")).to_have_value(
        "Historical text value"
    )
    expect(task_form.locator("[name='input-numgh78']")).to_have_value("42")

    _complete_then_uncomplete(task, reload=False)
    task_form = task.task_form
    expect(task_form.locator("[name='input-textab12']")).to_have_value("")
    expect(task_form.locator("[name='input-numgh78']")).to_have_value("")

    user.reload()
    task.wait_for_load()
    task_form = task.task_form
    expect(task_form.locator("[name='input-textab12']")).to_have_value("")
    expect(task_form.locator("[name='input-numgh78']")).to_have_value("")
    expect(task_form.locator("[id^='input-textab12'].form-element [data-role='history-fill']")).to_be_visible()
    expect(task_form.locator("[id^='input-numgh78'].form-element [data-role='history-fill']")).to_be_visible()

    saved_task = Entities.fetch_one(task.key, request=Fetch.root())
    assert {name: saved_task.db.get(name) for name in saved_settings} == saved_settings
    assert "default_submission" not in saved_task.db
    history = _open_history(task)
    expect(history.locator("tbody tr[lp-entity]")).to_have_count(2)


# @matrix tasks : history-fill latest-submission incompatible-value
# @template pages/tasks.html::task_form
def test_history_fill_converts_selected_fields_and_reports_invalid_values(get_user, browser_failures):
    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    source = [{"id": key, "type": "input", "input": "text", "title": title}
              for key, title in (("quantity", "Quantity"), ("invalid", "Invalid quantity"), ("notes", "Notes"))]
    form = Entities.FORM.create({
        "name": f"History conversion {uuid4().hex[:8]}", "form-type": "task", "schema": source,
    })
    form.save()
    task = Entities.TASK.create({
        "name": f"History conversion {uuid4().hex[:8]}", "page": parent.entity,
        "form": form, "submission": {"quantity": "7", "invalid": "not a number", "notes": "Keep this"},
    })
    task = Entities.fetch_one(task, request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS))
    task.save()
    task.complete(user=user.entity)
    task.save()
    # Archived-generation fixture; this story tests requesting individual old
    # answers after reopening. Builder/job conversion has its own browser story.
    archive_form_generation(form).save()
    form.schema = [{**field, "input": "number" if field["id"] != "notes" else "text"} for field in source]
    form.generation = 1
    from lagniappe.core.tools.database.utility import save_mutations

    save_mutations([(form, ("schema", "generation"))])
    task.db["generation"] = 1
    task.db["submission"] = json.dumps({"quantity": 7, "notes": "Keep this"})
    save_mutations([(task, ("generation", "submission"))])
    task.save()
    resource = Task(user=user)
    resource.entity = task
    user.go(resource)
    resource.task_form.get_by_role("button", name="View Original Submission", exact=True).click()
    expect(resource.task_form.get_by_role("radio", name="Archive original submission", exact=True)).to_be_checked()
    parent.uncomplete_task(resource)
    task_form = resource.task_form
    expect(task_form.get_by_text("Saved answers use a different form definition", exact=False)).to_have_count(0)
    expect(task_form.locator("[data-role='history-fill-error']")).to_have_count(0)
    fields = {key: task_form.locator(f"[id^='{key}-'].form-element") for key in ("quantity", "invalid", "notes")}
    for field in fields.values():
        expect(field.get_by_role("button", name="Fill from latest history", exact=True)).to_be_visible()

    route = f"/tasks/{task.urlsafe_key}/history/latest-submission"
    with expect_successful_response(user.page, method="GET", path=route):
        fields["quantity"].get_by_role("button", name="Fill from latest history", exact=True).click()
    expect(fields["quantity"].locator("input")).to_have_value("7")
    invalid_button = fields["invalid"].get_by_role("button", name="Fill from latest history", exact=True)
    with browser_failures.expect_http_error(user, status=422, path=route):
        with user.page.expect_response(lambda response: response.url.endswith(f"{route}?field=invalid")) as rejected:
            invalid_button.click()
        assert rejected.value.status == 422
        expect(task_form.locator("[data-role='error']")).to_have_text(
            'The saved value for "Invalid quantity" cannot be converted to the current field type.'
        )
    expect(fields["invalid"].locator("input")).to_have_value("")
    expect(invalid_button).to_be_enabled()
    fields["notes"].get_by_role("button", name="Fill from latest history", exact=True).click()
    expect(fields["notes"].locator("input")).to_have_value("Keep this")
    expect(task_form.locator("[data-role='error']")).to_be_hidden()
    expect(fields["quantity"].locator("input")).to_have_value("7")
    assert Entities.fetch_one(task.key, request=Fetch.root()).properties.submission.value == {}
    history = _open_history(resource)
    controller = _open_history_visibility(history)
    controller.get_by_role("checkbox", name="Invalid quantity", exact=True).check()
    expect(history.locator("td[data-column='invalid']")).to_have_text("not a number")


# @matrix tasks : element-matrix history-fill latest-submission live-update
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
        expect(table.locator("tbody tr[data-index]")).to_have_count(0)
        table.locator("[data-role='history-fill']").click()
        expect(table.locator("tbody tr[data-index]")).to_have_count(1)
        expect(table).to_contain_text("Historical row")

        todo = task_form.locator("[id^='history-todo-'].form-element")
        expect(todo.locator("li[data-index]")).to_have_count(0)
        todo.locator("[data-role='history-fill']").click()
        expect(todo.locator("li[data-index]")).to_have_count(1)
        expect(todo).to_contain_text("Historical to-do")
        expect(todo.locator("[data-role='todo-check']")).not_to_be_checked()
    finally:
        Entities.delete(task_entity)
        Entities.delete(form)


# @pair embedded-table:table-cell-expand
# @template cell.html::table_cell
# @template controls.html::expand
# @template tasks/history.html::completion_history
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
        "[data-role='history-group'] > .table-container > table > tbody > tr[data-embedded='true']"
    )
    expect(embedded).to_be_visible()
    expect(embedded).to_contain_text("Note")
    expect(embedded).to_contain_text("History row")


# @matrix task-combine : checkbox-form compatible lazy-form lazy-reload linked-page no-model same-model same-page view-page
# @pair web-headers:no-store
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

# @matrix task-combine : attachments checkbox-submit completed-on current-snapshot delete delta existing-history isolated-form migrate-history no-reload ordering remove upsert winner
# @template pages/tasks.html::combine_form
# @template pages/tasks.html::task
# @template tasks/history.html::completion_history
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

    source.entity.properties.files.add(archived_attachment)
    source.entity.complete(user=user.entity)
    source.entity.completed_on = datetime(2026, 6, 1, tzinfo=timezone.utc)
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
    ) as response_info:
        combine_form.get_by_role("button", name="Combine Tasks").click()

    delta = response_info.value.json()["task_delta"]
    assert [update["key"] for update in delta["upsert"]] == [winner.key]
    assert set(delta["remove"]) == {source.key, secondary.key}
    assert delta["order"] == [task.urlsafe_key for task in page_task_roots(page)]

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
    groups = history.locator("[data-role='history-group']")
    for name in (
        "Combine source archived",
        "Combine source current",
        "Combine secondary current",
    ):
        expect(history).to_contain_text(name)

    source_group = groups.filter(has_text="Combine source archived")
    expect(source_group).to_have_count(1)
    expect(source_group).to_contain_text("Combine source current")
    controller = _open_history_visibility(source_group)
    controller.locator("input[type='checkbox'][name='files']").set_checked(True)
    for attachment in (
        "Combine archived attachment",
        "Combine current attachment",
    ):
        expect(history.get_by_role("link", name=attachment)).to_be_visible()
