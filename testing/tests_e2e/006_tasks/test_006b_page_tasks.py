"""
Tests for page tasks quick-add and inline metadata chips.

The Page Tasks tab renders an inline quick-add bar above ``PageTaskList``
(``[data-role='task-quick-add']``). Submitting a task name creates the task
immediately, prepends it with its faded chip tray expanded, and keeps focus in
the quick-add input. Task rows render active metadata badges (including a
clickable Form chip that toggles ``TaskForm``) and a compact ``+`` chip tray
that reveals inline per-chip editors saving immediately via partial task
updates.

Verified against:
- lagniappe/web/templates/pages/tasks.html (task_tab, task_list, task, task_details)
- lagniappe/web/routes/tasks/ (create / update partial chip updates)
- src/script/widgets/taskChips.ts (TaskChipController)
- src/script/widgets/pageTaskList.ts (PageTaskList quick-add & chip delegation)
- lagniappe/core/tools/cache/query.py (``kind_search`` project + model expansion)

Definitions:
- testing/definitions/task_definitions.py
- testing/definitions/tasks.py
"""

import base64
import re
from uuid import uuid4

from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import (
    Forms,
    ModelTasks,
    Pages,
    Projects,
    Tasks,
    Uploads,
    Users,
)
from testing.definitions.task_definitions import TaskDefinition
from testing.elements import (
    Badges,
    Modal,
    Select,
    SpinnerButtons,
)
from testing.resources.task import Task
from testing.utility.network import expect_successful_response


SIGNATURE_FIELD_ID = "task-signature-field"
SIGNATURE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _quick_add_page_task(page, task):
    item, key = page.quick_add_task(task.definition.name)
    task.key = key
    task.element = item
    return key


def _open_page_task_form(page, task):
    expect(page.task_list).to_be_visible()
    task.element = task.user.locate(f"[data-key='{task.key}']")
    return task.task_form


def _signature_field(form, field_id=SIGNATURE_FIELD_ID):
    field = form.locator(f"[id^='{field_id}'].form-element")
    expect(field).to_be_visible()
    return field


def _upload_signature(form, field_id=SIGNATURE_FIELD_ID):
    field = _signature_field(form, field_id)
    file_input = field.locator(f"input[type='file'][name='{field_id}']")
    file_input.set_input_files(
        files=[
            {
                "name": "signature.png",
                "mimeType": "image/png",
                "buffer": SIGNATURE_PNG,
            }
        ]
    )
    field.locator("[data-role='signature']").evaluate(
        """node => node.dispatchEvent(new CustomEvent("updated", { bubbles: true }))"""
    )
    expect(field.locator(f"input[type='hidden'][name='{field_id}']")).to_have_value(
        field_id
    )


def _expect_signature_image(form, field_id=SIGNATURE_FIELD_ID):
    field = _signature_field(form, field_id)
    image = field.locator("[data-role='read'] img[alt='Signature']")
    expect(field).to_have_attribute("data-mode", "read")
    expect(image).to_be_visible()
    expect(image).to_have_attribute(
        "src",
        re.compile(r"/assets/.+/task-signature-field\.png"),
    )
    expect(image).to_have_js_property("naturalWidth", 1)
    return image


def _select_page_option(select, page):
    panel = select.open()
    select.input.fill(page.definition.name)
    expect(panel).to_be_visible()
    option = panel.locator(f"[role='option'][data-id='{page.key}']")
    expect(option).to_be_visible()
    option.click()
    select.input.press("Escape")


def _clear_signature(form, field_id=SIGNATURE_FIELD_ID):
    field = _signature_field(form, field_id)
    if field.get_attribute("data-mode") == "read":
        field.locator("[data-role='read']").click()
        expect(field).to_have_attribute("data-mode", "edit")

    field.locator("[data-role='clear']").click()
    hidden_input = field.locator(f"input[type='hidden'][name='{field_id}']")
    expect(hidden_input).to_have_value("")


def test_create_basic_page_task(get_admin, get_user):
    user = get_admin()

    task = Tasks.test_create_page_task.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    user.go(page)

    _quick_add_page_task(page, task)
    task.set_description(task.definition.description)

    user.reload(page)
    task.wait_for_load()
    expect(task.element).to_contain_text(task.definition.name)
    expect(task.element.locator("[data-role='task-description']")).to_have_text(
        task.definition.description
    )


# @template pages/tasks.html::task_tab
# @template pages/tasks.html::task_list
# @template pages/tasks.html::task_empty
def test_empty_page_task_list_shows_quick_add_and_empty_marker(get_admin, get_user):
    user = get_admin()
    page = Pages.test_empty_page_task_list.get(user)
    user.go(page)

    quick_add = page.quick_add_form
    empty = user.locate(f"{page.TASK_LIST} [data-role='empty']")
    expect(quick_add).to_be_visible()
    expect(empty).to_be_visible()

    item, _ = page.quick_add_task("First quick-added task")
    expect(item).to_be_visible()
    expect(empty).not_to_be_visible()


def test_create_page_task_with_form(get_admin, get_user):
    user = get_admin()

    task = Tasks.test_create_page_task_with_form.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    form = task.definition.form.get(user)
    user.go(page)

    _quick_add_page_task(page, task)
    task.select_chip_option("form", form)

    Badges.FORM.visible(task.element, form)
    expect(task.element.locator(task.TASK_FORM)).to_be_visible()


def test_complete_page_task(get_admin, get_user):
    user = get_admin()

    task = Tasks.test_complete_page_task.get(user)
    user.go(task)

    task.complete()
    assert task.completed
    task.uncomplete()
    assert not task.completed


# @template pages/tasks.html::task_details
def test_create_page_task_with_project(get_admin, get_user):
    user = get_admin()

    task = Tasks.test_create_page_task_with_project.get(user, create=False)
    project = Projects.test_attach_project_to_task.get(user)
    page = Pages.test_create_page_task_with_project.get(user)
    user.go(page)

    _quick_add_page_task(page, task)
    task.select_chip_option("project", project)

    Badges.PROJECT.visible(task.element, project)
    drawer = task.element.locator(task.CHIP_DRAWER)
    expect(drawer).to_be_visible()
    expect(drawer.locator("a[data-role='open-link']")).to_have_attribute(
        "href", re.compile(rf"/projects/{re.escape(project.key)}$")
    )
    expect(drawer.locator("button[data-role='clear']")).to_be_visible()
    expect(drawer.locator("input[role='combobox']")).to_be_visible()
    expect(user.page.locator("[role='listbox'][data-visible='true']")).to_have_count(0)


# @template pages/tasks.html::task_details
def test_create_page_task_with_model_task(get_admin, get_user):
    user = get_admin()

    project = Projects.test_page_tasks_multi_model.get(user)
    model_alpha = ModelTasks.test_multi_model_alpha.get(user)
    model_beta = ModelTasks.test_multi_model_beta_with_form.get(user)

    task = Tasks.test_create_page_task_with_model_task.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    form = Forms.test_create_task_form.get(user)

    user.go(page)
    _quick_add_page_task(page, task)

    drawer = task.open_chip("project")
    combobox = drawer.locator("input[role='combobox']")
    combobox.fill(project.definition.name)
    panel = user.page.locator("[role='listbox'][data-visible='true']")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text(project.definition.name)
    expect(panel).to_contain_text(model_alpha.definition.name)
    expect(panel).to_contain_text(model_beta.definition.name)

    with expect_successful_response(
        user.page,
        method="PUT",
        path=f"/tasks/{task.key}/update",
        entity_key=task.key,
    ):
        panel.locator(f"[role='option'][data-id='{model_beta.key}']").click()

    Badges.PROJECT.visible(task.element, project)
    Badges.MODEL_TASK.visible(task.element, model_beta)
    Badges.FORM.visible(task.element, form)
    expect(task.element.locator(task.TASK_FORM)).to_be_visible()

    project_path = f"/projects/{project.key}"
    model_path = f"{project_path}/status/{model_beta.key}?completed=false"

    page.reload()
    task.wait_for_load()
    Badges.PROJECT.visible(task.element, project)
    Badges.MODEL_TASK.visible(task.element, model_beta)
    Badges.FORM.visible(task.element, form)

    drawer = task.open_chip("project")
    model_link = drawer.locator("a[data-role='open-link']")
    expect(model_link).to_have_attribute("href", re.compile(re.escape(model_path) + "$"))
    with user.page.expect_navigation() as navigation:
        model_link.click()
    assert navigation.value.ok
    expect(user.page).to_have_url(re.compile(re.escape(model_path) + "$"))


# @template pages/tasks.html::task_details
def test_model_task_replaces_form_on_task_chip(get_admin, get_user):
    user = get_admin()
    page = Pages.test_create_page_task.get(user)
    original_form = Forms.test_create_task_form.get(user)
    token = uuid4().hex[:12]
    project = Entities.PROJECT.create({"name": f"Draft model project {token}"})
    project.save()
    form = Entities.FORM.create(
        {
            "name": f"Current model form {token}",
            "form-type": "task",
            "schema": [
                {
                    "id": "current-result",
                    "type": "input",
                    "input": "text",
                    "title": "Current result",
                }
            ],
        }
    )
    form.save()
    model = Entities.MODEL_TASK.create(
        project, {"name": f"Draft model {token}", "form": form}
    )
    model.save()
    task = Task(
        user=user,
        definition=TaskDefinition(
            name=f"Model replacement task {token}", origin=Pages.test_create_page_task
        ),
    )
    user.go(page)
    _quick_add_page_task(page, task)
    task.select_chip_option("form", original_form)
    Badges.FORM.visible(task.element, original_form)

    drawer = task.open_chip("project")
    combobox = drawer.locator("input[role='combobox']")
    combobox.fill(model.name)
    panel = user.page.locator("[role='listbox'][data-visible='true']")
    expect(panel).to_be_visible()
    with expect_successful_response(
        user.page,
        method="PUT",
        path=f"/tasks/{task.key}/update",
        entity_key=task.key,
    ):
        panel.locator(f"[role='option'][data-id='{model.urlsafe_key}']").click()

    saved = Entities.fetch_one(task.key, request=Fetch.direct())
    assert saved.properties.form.key == form.key
    assert saved.properties.model.key == model.key
    expect(task.task_form.locator("input[name='current-result']")).to_be_visible()


# @template notifications.html::item
def test_create_page_task_with_assigned_to(get_admin, get_user):
    user = get_admin()

    task = Tasks.test_create_page_task_with_assigned_to.get(user, create=False)
    assignee = Users.create_user.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(page)

    _quick_add_page_task(page, task)
    task.select_chip_option("assigned_to", assignee)

    assert Badges.USER.visible(task.element, assignee)

    assigned_user = get_user(Users.create_user)
    assigned_user.go(task)
    notifications = assigned_user.locate("[data-role='notifications']")
    notifications.click()
    panel = assigned_user.page.locator("[role='dialog'][data-visible='true']")
    assignment = (
        panel.locator("[role='group']")
        .filter(has_text=f"{user.entity.name} assigned you a task.")
        .filter(has_text=task.definition.name)
    )
    expect(assignment).to_be_visible()
    expect(assignment.locator("[data-role='target']")).to_have_attribute(
        "href", f"/tasks/{task.key}"
    )


def test_create_page_task_with_due_date(get_admin, get_user):
    user = get_admin()

    task = Tasks.test_create_page_task_with_due_date.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    user.go(page)

    _quick_add_page_task(page, task)
    task.set_due_date(task.definition.due_date)

    expect(task.element.locator("[data-role='change-due-date']")).to_be_visible()


# @template pages/tasks.html::task_title
# @template pages/tasks.html::task_nav
# @template pages/tasks.html::task_details
def test_update_page_task_settings_from_row(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_update_page_task_settings.get(user)
    user.go(task)

    updated_name = "Task Settings After"
    updated_description = "Updated task settings description.\n\n  Keep this line indented."

    task.rename(updated_name)
    task.set_description(updated_description)

    expect(task.element.locator("[data-role='title']")).to_contain_text(updated_name)
    description = task.element.locator("[data-role='task-description']")
    expect(description).to_have_text(updated_description)
    expect(description).to_have_css("white-space", "pre-wrap")
    assert description.text_content() == updated_description

    user.reload()
    task.wait_for_load()
    expect(task.element.locator("[data-role='title']")).to_contain_text(updated_name)
    description = task.element.locator("[data-role='task-description']")
    expect(description).to_have_text(updated_description)
    expect(description).to_have_css("white-space", "pre-wrap")
    assert description.text_content() == updated_description


# @template controls.html::task_save
# @template pages/tasks.html::task
# @template pages/tasks.html::task_form
# @template pages/tasks.html::task_details
def test_adding_form_from_chip_and_editing_chips_preserves_open_task_form(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_update_page_task_settings.get(user)
    form = Forms.test_task_history_form.get(user)
    user.go(task)

    task.select_chip_option("form", form)

    expect(task.element.locator(task.TASK_FORM)).to_be_visible()
    Badges.FORM.visible(task.element, form)

    task_form = task.task_form
    save_toggle = task.element.locator("[data-role='save-toggle']")
    expect(save_toggle).to_have_attribute("data-saved", "true")

    task_value = "Saved alongside chip edit"
    task_form.locator("[name='input-textab12']").fill(task_value)
    user.page.keyboard.press("Tab")
    expect(save_toggle).to_be_visible()
    expect(save_toggle).to_have_attribute("data-saved", "false")

    # Renaming the task while TaskForm is open preserves unsaved form answers.
    updated_name = "Task Renamed While Form Open"
    task.rename(updated_name)
    expect(task_form).to_be_visible()
    expect(task_form.locator("[name='input-textab12']")).to_have_value(task_value)
    expect(task.element.locator("[data-role='save-toggle']")).to_be_visible()

    with expect_successful_response(
        user.page,
        method="PUT",
        path=f"/tasks/{task.key}/update",
        entity_key=task.key,
    ):
        SpinnerButtons.UPDATE.click(task_form)
    assert SpinnerButtons.UPDATE_SUCCESS.successful(task_form)

    user.reload()
    task.wait_for_load()
    expect(task.element.locator("[data-role='title']")).to_contain_text(updated_name)
    reloaded_task_form = task.task_form
    expect(reloaded_task_form.locator("[name='input-textab12']")).to_have_value(
        task_value
    )


# @template pages/tasks.html::task_title
# @template pages/tasks.html::move_form
# @template pages/tasks.html::move_page_select
def test_completed_task_can_move_to_another_page(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_page_task_move_pages.get(user)
    source_page = Pages.test_task_pages_move_source.get(user)
    target_page = Pages.test_task_pages_move_target.get(user)
    user.go(task)

    task.complete()
    expect(task.element).to_have_attribute("data-completed", "true")
    expect(task.element).to_have_attribute("data-content-readonly", "true")
    expect(task.element.locator(task.CHIP_TRAY_TOGGLE)).to_have_count(0)

    task.element.get_by_role("button", name="Task actions").click()
    menu = user.page.get_by_role("menu", name="Task actions")
    expect(menu).to_be_visible()
    move_action = menu.get_by_role("menuitem", name="Move to Page")
    expect(move_action).to_have_attribute("data-kind", "page")
    expect(move_action.locator("span[data-icon='page']")).to_be_visible()
    move_action.click()

    move_form = task.element.locator("[data-widget='TaskMove']")
    expect(move_form).to_be_visible()
    expect(move_form).to_have_attribute("rendered", "")
    pages = Select(move_form.locator("[data-role='page-select']"))
    _select_page_option(pages, target_page)

    with user.page.expect_navigation(wait_until="domcontentloaded"):
        move_form.get_by_role("button", name="Move Task").click()

    user.go(target_page)
    moved_task = target_page.completed_task_list.get_item(task)
    expect(moved_task).to_be_visible()
    expect(moved_task).to_have_attribute("data-content-readonly", "true")

    user.go(source_page)
    _ = source_page.task_list
    expect(user.locate(f"[data-key='{task.key}']")).not_to_be_attached()


# @template pages/tasks.html::task
def test_delete_page_task_from_page_row(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_delete_page_task_from_page.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(page)

    task.element = page.active_task_list.get_item(task)
    task.element.get_by_role("button", name="Task actions").click()
    menu = user.page.get_by_role("menu", name="Task actions")
    expect(menu).to_be_visible()
    menu.get_by_role("menuitem", name="Delete").click()

    Modal(user.page).delete()

    expect(task.element).not_to_be_visible()


# @template pages/tasks.html::task_form
def test_submit_attached_task_form(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_submit_attached_task_form.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(task)

    task_form = _open_page_task_form(page, task)
    expect(task_form).to_have_attribute("data-kind", "form")
    for submission in task.definition.submission:
        submission.set_submission_value(task_form)

    user.page.keyboard.press("Tab")
    expect(task_form.locator("[data-icon='builder.unsaved']")).to_be_visible()

    with expect_successful_response(
        user.page,
        method="PUT",
        path=f"/tasks/{task.key}/update",
        entity_key=task.key,
    ):
        task_form.locator("button[type='submit']:not([data-role])").click()

    expect(task_form).to_be_visible()
    expect(task_form.locator("button[type='submit']:has-text('Updated')")).to_be_visible()
    expect(task_form.locator("[data-icon='builder.unsaved']")).to_have_count(0)
    for submission in task.definition.submission:
        assert submission.verify_submission_value(task_form)

    task_form.locator("[data-role='show-autofill']").click()
    expect(task_form.locator("[data-role='autofill']")).to_be_visible()
    task_form.locator("[data-role='cancel-autofill']").click()
    expect(task_form.locator("[data-role='autofill']")).to_be_hidden()

    user.reload()
    task.wait_for_load()
    task_form = task.task_form
    for submission in task.definition.submission:
        assert submission.verify_submission_value(task_form)


# @template pages/tasks.html::task
# @template pages/tasks.html::task_form
def test_task_update_preserves_open_widget_and_completed_readonly_state(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_task_update_preserves_open_widget.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(task)

    expect(task.element.locator(task.CHIP_TRAY_TOGGLE)).to_be_attached()
    task_form = _open_page_task_form(page, task)
    expect(task_form).to_be_visible()

    with expect_successful_response(
        user.page,
        method="PUT",
        path=f"/tasks/{task.key}/update",
        entity_key=task.key,
    ):
        SpinnerButtons.UPDATE.click(task_form)

    task_form = task.element.locator(task.TASK_FORM)
    # The response arrives before the widget adopts its new form revision.
    expect(task_form.get_by_role("button", name="Updated", exact=True)).to_be_visible()
    expect(task_form).to_be_visible()
    for submission in task.definition.submission:
        assert submission.verify_submission_value(task_form)

    task.complete()

    expect(task.element).to_have_attribute("data-open", "false")
    expect(task.element.locator(task.TASK_FORM)).to_be_hidden()
    task_form = task.task_form
    expect(task.element).to_have_attribute("data-completed", "true")
    expect(task.element).not_to_have_attribute("data-readonly", "true")
    expect(task.element).to_have_attribute("data-content-readonly", "true")
    expect(task_form).to_have_attribute("data-readonly", "true")
    expect(task_form).to_be_visible()
    expect(task.element.locator(task.CHIP_TRAY_TOGGLE)).to_have_count(0)
    expect(task.element.locator("[data-role='save-toggle']")).to_have_count(0)
    expect(task_form.locator("[data-role='show-autofill']")).to_have_count(0)
    expect(task_form.locator("button[type='submit']")).to_have_count(0)

    readonly_field = task_form.locator("[id^='input-textab12'].form-element")
    expect(readonly_field).to_have_attribute("data-mode", "read")
    expect(readonly_field).to_contain_text("Task update state text")
    readonly_field.locator("[data-role='label']").click()
    expect(readonly_field).to_have_attribute("data-mode", "read")
    expect(readonly_field.locator("input")).to_have_count(0)


# @template pages/tasks.html::task
# @template pages/tasks.html::task_form
def test_completed_task_with_empty_form_is_readonly(get_admin, get_user, tmp_path):
    user = get_admin()
    task = Tasks.test_completed_task_readonly_form.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(task)

    expect(_open_page_task_form(page, task)).to_be_visible()

    task.complete()

    expect(task.element).to_have_attribute("data-completed", "true")
    expect(task.element).not_to_have_attribute("data-readonly", "true")
    expect(task.element).to_have_attribute("data-content-readonly", "true")
    expect(task.element).to_have_attribute("data-open", "false")
    expect(task.element.locator(task.TASK_FORM)).to_be_hidden()
    completed_form = task.task_form
    expect(completed_form).to_have_attribute("data-readonly", "true")
    expect(completed_form.locator("[lp-edited-marker]")).to_have_count(0)
    expect(completed_form.get_by_text("Task was completed with an empty submission", exact=True)).to_be_visible()
    expect(completed_form.locator("input:not([type='hidden'])")).to_have_count(0)
    expect(completed_form).not_to_contain_text("Not provided")
    expect(task.element.locator(task.CHIP_TRAY_TOGGLE)).to_have_count(0)
    expect(task.element.locator("[data-role='show-autofill']")).to_have_count(0)
    expect(task.element.locator("[data-widget='TaskMove']")).to_have_count(1)

    task.element.screenshot(path=tmp_path / "empty-completed-submission.png")

    task.uncomplete()
    expect(task.element).to_have_attribute("data-completed", "false")
    expect(task.element).to_have_attribute("data-content-readonly", "false")
    expect(_open_page_task_form(page, task)).to_be_visible()

    expect(task.task_form.locator("[lp-edited-marker]")).to_have_count(1)
    expect(task.task_form.locator("[data-role='empty-completed-submission']")).to_have_count(0)


# @template pages/tasks.html::task
# @template pages/tasks.html::task_form
def test_completed_task_with_partial_submission_omits_empty_fields(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_completed_partial_task_readonly_form.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(task)

    expect(_open_page_task_form(page, task)).to_be_visible()

    task.complete()

    expect(task.element).to_have_attribute("data-open", "false")
    task_form = task.task_form
    expect(task.element).to_have_attribute("data-completed", "true")
    expect(task.element).not_to_have_attribute("data-readonly", "true")
    expect(task.element).to_have_attribute("data-content-readonly", "true")
    expect(task_form).to_have_attribute("data-readonly", "true")
    expect(task_form).to_be_visible()
    expect(task_form).to_contain_text("Partial completed task text")
    expect(task_form.locator("[lp-edited-marker]")).to_have_count(0)
    expect(task_form.locator("[data-role='empty-completed-submission']")).to_have_count(0)
    expect(task_form.locator("[id^='input-textab12'].form-element")).to_have_count(1)
    expect(task_form.locator("[id^='input-datecd34'].form-element")).to_have_count(0)
    expect(task_form).not_to_contain_text("Not provided")
    expect(task_form.locator("input:not([type='hidden'])")).to_have_count(0)

    task.uncomplete()
    active_form = task.task_form
    expect(active_form).not_to_have_attribute("data-readonly", "true")
    expect(active_form.locator("[name='input-textab12']")).to_have_value("")


# @template pages/tasks.html::task_tab
# @template pages/tasks.html::task_list
# @template pages/tasks.html::task
def test_create_page_task_while_another_task_is_open_keeps_rows_clear(get_admin, get_user):
    user = get_admin()
    existing_task = Tasks.test_create_while_open_existing.get(user)
    new_task = Tasks.test_create_while_open_new.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    user.go(existing_task)

    expect(existing_task.element.locator(existing_task.CHIP_TRAY)).to_have_attribute(
        "data-tray-open", "true"
    )

    _quick_add_page_task(page, new_task)

    expect(page.task_list).to_be_visible()
    expect(page.active_task_list.get_item(existing_task)).to_be_visible()
    expect(page.active_task_list.get_item(new_task)).to_be_visible()


def test_signature_submission_draw_save_reload_and_clear(get_admin, get_user):
    user = get_admin()
    task = Tasks.test_signature_submission.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(task)

    task_form = _open_page_task_form(page, task)
    expect(_signature_field(task_form)).to_have_attribute("data-mode", "edit")

    _upload_signature(task_form)
    with expect_successful_response(
        user.page,
        method="PUT",
        path=f"/tasks/{task.key}/update",
        entity_key=task.key,
    ):
        SpinnerButtons.UPDATE.click(task_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(task_form)
    expect(task_form).to_be_visible()
    _expect_signature_image(task_form)

    user.reload()
    task.wait_for_load()
    task_form = task.task_form
    _expect_signature_image(task_form)

    _clear_signature(task_form)
    with expect_successful_response(
        user.page,
        method="PUT",
        path=f"/tasks/{task.key}/update",
        entity_key=task.key,
    ):
        SpinnerButtons.UPDATE.click(task_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(task_form)
    field = _signature_field(task_form)
    expect(field).to_have_attribute("data-mode", "edit")
    expect(field.locator("[data-role='read']")).to_have_count(0)

    _upload_signature(task_form)
    with expect_successful_response(
        user.page,
        method="PUT",
        path=f"/tasks/{task.key}/update",
        entity_key=task.key,
    ):
        SpinnerButtons.UPDATE.click(task_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(task_form)
    _expect_signature_image(task_form)

    task.complete()
    readonly_form = task.task_form
    expect(readonly_form).to_have_attribute("data-readonly", "true")
    _expect_signature_image(readonly_form)
    expect(_signature_field(readonly_form).locator("input")).to_have_count(0)

    task.uncomplete()
    reset_form = task.task_form
    reset_field = _signature_field(reset_form)
    expect(reset_field).to_have_attribute("data-mode", "edit")
    expect(reset_field.locator("[data-role='read']")).to_have_count(0)


# @template pages/tasks.html::task_details
def test_create_page_task_with_file(get_admin, get_user):
    user = get_admin()

    task = Tasks.test_create_page_task_with_file.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    user.go(page)

    _quick_add_page_task(page, task)
    drawer = task.open_chip("files")
    expect(drawer.locator("[data-role='dropzone']")).to_be_visible()

    with user.page.expect_response(
        lambda response: response.request.method == "POST"
        and f"/tasks/{task.key}/upload-file" in response.url
    ), expect_successful_response(
        user.page,
        method="PUT",
        path=f"/tasks/{task.key}/update",
        entity_key=task.key,
    ):
        Uploads.csv_file_input.set(drawer)

    filename = Uploads.csv_file_input.definition.filename
    saved_files = drawer.locator("[data-role='saved-files']")
    expect(saved_files).to_be_visible()
    expect(saved_files).to_contain_text(filename)
    expect(saved_files.locator("li").first).to_have_css("align-items", "center")
    expect(saved_files.locator("a").first).to_have_attribute(
        "href", re.compile(r"/files/")
    )
    expect(task.element.locator("[data-role='task-chips']")).to_contain_text(filename)

    page_entity = Entities.fetch_one(page.key, request=Fetch.direct())
    assert filename not in [file.name for file in page_entity.files]

    delete_button = saved_files.locator("[data-role='delete-task-file']").first
    with user.page.expect_response(
        lambda response: response.request.method == "DELETE"
        and f"/tasks/{task.key}/files/" in response.url
    ):
        delete_button.click()

    expect(task.element.locator("[data-role='task-chips']")).not_to_contain_text(
        filename
    )
    expect(saved_files).not_to_be_visible()
