"""End-to-end task-form todo list behavior."""

from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch, FetchReason
from lagniappe.core.entities import Entities
from testing.definitions import Pages, Users
from testing.resources import Task
from testing.utility import expect_successful_response

pytestmark = pytest.mark.e2e


# @pairs form-todo:add form-todo:edit form-todo:rename form-todo:delete
# @pairs form-todo:check form-todo:history-fill form-todo:reset
# @pair form-todo:default-persistence
# @template pages/tasks.html::task_form
def test_task_todo_list_editing_and_history_restore(get_user):
    user = get_user(Users.OWNER)
    parent = Pages.test_create_page_task.get(user)
    suffix = uuid4().hex
    form = Entities.FORM.create(
        {"name": f"Todo Form {suffix}", "form-type": "task"}
    )
    form.schema = [
        {"id": "todo-work", "title": "Checklist", "type": "todo"},
    ]
    form.save()
    task_entity = Entities.TASK.create(
        {
            "name": f"Todo Task {suffix}",
            "page": parent.entity,
            "form": form,
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
        task_form = task.task_form
        todo = task_form.locator("[id^='todo-work-'].form-element")
        expect(todo).to_be_visible()
        add_todo = todo.locator("[data-role='todo-edit']")
        expect(add_todo).to_have_attribute(
            "aria-label", "Add to Checklist"
        )
        expect(add_todo).to_have_attribute("data-kind", "add")
        title_action_classes = add_todo.get_attribute("class")
        assert title_action_classes
        assert "outline-offset-0" not in title_action_classes.split()

        add_todo.click()
        draft = todo.locator("[data-role='todo-draft']")
        expect(draft).to_be_focused()
        draft.fill("First step")
        draft.press("Enter")
        expect(todo.locator("li[data-index]")).to_have_count(1)
        expect(todo.locator("[data-role='todo-draft']")).to_be_focused()

        todo.locator("[data-role='todo-draft']").fill("Second step")
        todo.locator("[data-role='todo-commit-draft']").click()
        expect(todo.locator("li[data-index]")).to_have_count(2)
        expect(todo.locator("[data-role='todo-draft']")).to_be_focused()

        todo.locator("[data-role='todo-dismiss-draft']").click()
        expect(todo).to_have_attribute("data-mode", "edit")
        expect(todo.locator("[data-role='todo-draft']")).to_have_count(0)
        done = todo.locator("[data-role='todo-done']")
        expect(done).to_have_attribute("data-kind", "success")
        expect(done).to_have_attribute("class", title_action_classes)
        done.click()
        expect(todo).to_have_attribute("data-mode", "read")

        checkboxes = todo.locator("[data-role='todo-check']")
        expect(checkboxes).to_have_count(2)
        expect(checkboxes.first).to_be_enabled()
        checkboxes.first.check()

        todo.locator("[data-role='todo-edit']").click()
        expect(todo.locator("[data-role='todo-check']").first).to_be_disabled()
        todo.get_by_role("button", name="Rename First step").click()
        rename = todo.locator("[data-role='todo-rename-input']")
        expect(rename).to_be_focused()
        rename.fill("Renamed step")
        rename.press("Enter")
        expect(todo.locator("[data-role='todo-draft']")).to_be_focused()

        second = todo.locator("li[data-index]").filter(has_text="Second step")
        second.locator("[data-role='todo-remove']").click()
        todo.locator("[data-role='todo-draft']").fill("Third step")
        todo.locator("[data-role='todo-done']").click()
        expect(todo.locator("li[data-index]")).to_have_count(2)
        expect(todo).to_contain_text("Renamed step")
        expect(todo).to_contain_text("Third step")

        with expect_successful_response(
            user.page,
            method="PUT",
            path=f"/tasks/{task.key}/update",
            entity_key=task.key,
        ):
            task_form.get_by_role("button", name="Update", exact=True).click()

        saved = Entities.fetch_one(task.key, request=Fetch.direct())
        assert saved.submission["todo-work"] == {
            "items": [
                {"text": "Renamed step", "checked": True},
                {"text": "Third step", "checked": False},
            ]
        }

        parent.complete_task(task)
        parent.uncomplete_task(task)
        user.reload()
        task.wait_for_load()

        default_requests = []
        user.page.on(
            "request",
            lambda request: default_requests.append(request.url)
            if "/default-submission" in request.url
            else None,
        )
        task_form = task.task_form
        todo = task_form.locator("[id^='todo-work-'].form-element")
        expect(todo.locator("li[data-index]")).to_have_count(0)
        history_fill = todo.locator("[data-role='history-fill']")
        expect(history_fill).to_be_visible()
        expect(history_fill).to_have_attribute("class", title_action_classes)
        assert history_fill.get_attribute("data-kind") is None
        history_fill.click()

        expect(todo.locator("li[data-index]")).to_have_count(2)
        restored_checkboxes = todo.locator("[data-role='todo-check']")
        expect(restored_checkboxes.first).not_to_be_checked()
        expect(restored_checkboxes.nth(1)).not_to_be_checked()
        assert default_requests == []

        reopened = Entities.fetch_one(task.key, request=Fetch.direct())
        assert reopened.default_submission == {}
        assert reopened.submission == {}
    finally:
        Entities.delete(task_entity)
        Entities.delete(form)
