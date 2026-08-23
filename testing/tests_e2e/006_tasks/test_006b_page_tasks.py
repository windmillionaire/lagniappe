"""
Tests for creating page tasks with linked project, model task, assignee, and due date.

The create form (``CreateTask`` / ``tasks.html`` action buttons) uses facet search on the
project combobox: searching by project name loads matching projects and, when the cache
expands models, all model tasks for that project. Selecting a model task whose definition
includes a form should auto-fill the form selector (see ``BaseTaskSettings`` in
``src/script/widgets/taskSettings.mjs``). Task rows render ``entity_badge`` chips for
linked project, model, assignee, due date, etc.; use ``Badges`` helpers to assert visibility.

Verified against:
- lagniappe/web/templates/pages/tasks.html (task tab, action_buttons, task_details)
- lagniappe/web/routes/tasks/ (create / update)
- src/script/widgets/taskSettings.mjs (CreateTask, entity selects)
- lagniappe/core/tools/cache/query.py (``kind_search`` project + model expansion)

Definitions:
- testing/definitions/task_definitions.py
- testing/definitions/tasks.py
"""

import base64
import re

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
from testing.elements import (
    Badges,
    FormElements,
    FormSelect,
    Modal,
    Select,
    SpinnerButtons,
    ProjectSelect,
    DateSelect,
    UserSelect,
)
from testing.utility import expect_successful_response


SIGNATURE_FIELD_ID = "task-signature-field"
SIGNATURE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _submit_create_task_form(user, page, task, create_form):
    with expect_successful_response(
        user.page,
        method="POST",
        path=f"/tasks/{page.key}/create",
        entity_key=page.key,
        request_payload_contains=task.definition.name,
    ):
        SpinnerButtons.CREATE.click(create_form)

    expect(create_form).not_to_be_visible()
    task_list = page.active_task_list
    expect(task_list.list).to_be_visible()
    new_task = task_list.new_item(task.definition.name)
    return new_task.get_attribute("data-key")


def _fill_editable_field(form, field_id, selector, value):
    field = form.locator(f"#{field_id}")
    control = field.locator(selector)
    if not control.is_visible():
        field.locator("[data-role='label']").click()
    control.fill(value)


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
        field.locator("[data-role='edit']").click()
        expect(field).to_have_attribute("data-mode", "edit")

    field.locator("[data-role='clear']").click()
    hidden_input = field.locator(f"input[type='hidden'][name='{field_id}']")
    expect(hidden_input).to_have_value("")


# @features tasks
# @dimensions create basic
def test_create_basic_page_task(get_user):
    user = get_user(Users.OWNER)

    task = Tasks.test_create_page_task.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    user.go(page)

    create_form = page.create_task_form
    create_form.locator(FormElements.NAME).fill(task.definition.name)
    create_form.locator(FormElements.DESCRIPTION).fill(task.definition.description)

    task.key = _submit_create_task_form(user, page, task, create_form)
    user.reload(page)
    task.wait_for_load()
    expect(task.element).to_contain_text(task.definition.name)


# @pairs tasks:create-close tasks:empty-state
# @template pages/tasks.html::task_list
# @template pages/tasks.html::task_empty
def test_empty_page_task_list_shows_marker_only_after_create_closes(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_empty_page_task_list.get(user)
    user.go(page)

    create_form = page.create_task_form
    empty = user.locate(f"{page.TASK_LIST} [data-role='empty']")
    expect(create_form).to_be_visible()
    expect(empty).to_be_attached()
    expect(empty).not_to_be_visible()

    close = user.locate(
        "#tabs [data-role='controls'] button[lp-close='tasks:PageTaskList']"
    )
    expect(close).to_be_visible()
    close.click()

    expect(create_form).not_to_be_visible()
    expect(empty).to_be_visible()


# @features tasks
# @dimensions create attach-form
def test_create_page_task_with_form(get_user):
    user = get_user(Users.OWNER)

    task = Tasks.test_create_page_task_with_form.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    form = task.definition.form.get(user)
    user.go(page)

    create_form = page.create_task_form
    create_form.locator(FormElements.NAME).fill(task.definition.name)
    FormSelect(create_form).select(form)

    task.key = _submit_create_task_form(user, page, task, create_form)


# @features tasks
# @dimensions complete
def test_complete_page_task(get_user):
    user = get_user(Users.OWNER)

    task = Tasks.test_complete_page_task.get(user)
    user.go(task)

    task.complete()
    assert task.completed
    task.uncomplete()
    assert not task.completed


# @features tasks
# @dimensions create project-link badge
# @pair tasks:project-link
# @pair tasks:select-toggle-layout
# @style select.button
# @template pages/tasks.html::action_buttons
def test_create_page_task_with_project(get_user):
    user = get_user(Users.OWNER)

    task = Tasks.test_create_page_task_with_project.get(user, create=False)
    project = Projects.test_attach_project_to_task.get(user)
    page = Pages.test_create_page_task_with_project.get(user)
    user.go(page)

    create_form = page.create_task_form
    create_form.locator(FormElements.NAME).fill(task.definition.name)
    ProjectSelect(create_form).select(project)

    task.key = _submit_create_task_form(user, page, task, create_form)

    Badges.PROJECT.visible(task.element, project)

    settings_form = task.settings_form
    project_button = ProjectSelect(settings_form).button
    leading_icon = project_button.locator(":scope > span > [data-icon]").first
    clear_icon = project_button.locator(
        ":scope > [data-role='clear'] > [data-icon]"
    )
    expect(leading_icon).to_be_visible()
    expect(clear_icon).to_be_visible()

    user.mobile = True
    mobile_button = project_button.element_handle()
    assert mobile_button is not None
    user.page.wait_for_function(
        "button => button.getBoundingClientRect().height > 40",
        arg=mobile_button,
    )

    user.mobile = False
    expect(project_button).to_have_css("height", "40px")
    leading_icon.click()
    project_input = settings_form.locator(
        "[data-role='project-select'] + input[role='combobox']"
    )
    expect(project_input).to_be_visible()
    expect(project_input).to_have_css("height", "40px")


# @features tasks
# @dimensions create model-task-link attach-form badge
def test_create_page_task_with_model_task(get_user):
    user = get_user(Users.OWNER)

    project = Projects.test_page_tasks_multi_model.get(user)
    model_alpha = ModelTasks.test_multi_model_alpha.get(user)
    model_beta = ModelTasks.test_multi_model_beta_with_form.get(user)

    task = Tasks.test_create_page_task_with_model_task.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    form = Forms.test_create_task_form.get(user)

    user.go(page)

    create_form = page.create_task_form
    create_form.locator(FormElements.NAME).fill(task.definition.name)

    project_button = ProjectSelect(create_form)
    project_panel = project_button.panel(fill=project.definition.name)
    expect(project_panel).to_contain_text(project.definition.name)
    expect(project_panel).to_contain_text(model_alpha.definition.name)
    expect(project_panel).to_contain_text(model_beta.definition.name)
    project_button.select_by_key(model_beta)
    assert FormSelect(create_form).contains(form)

    task.key = _submit_create_task_form(user, page, task, create_form)

    Badges.PROJECT.visible(task.element, project)
    Badges.MODEL_TASK.visible(task.element, model_beta)


# @pairs tasks:create tasks:assignee
# @pair tasks:badge
# @pair notifications:assignee-target
# @template notifications.html::item
def test_create_page_task_with_assigned_to(get_user):
    user = get_user(Users.OWNER)

    task = Tasks.test_create_page_task_with_assigned_to.get(user, create=False)
    assignee = Users.create_user.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(page)

    create_form = page.create_task_form
    create_form.locator(FormElements.NAME).fill(task.definition.name)
    UserSelect(create_form).select(assignee)

    task.key = _submit_create_task_form(user, page, task, create_form)

    assert Badges.USER.visible(task.element, assignee)

    assigned_user = get_user(Users.create_user)
    assigned_user.go(task)
    notifications = assigned_user.locate("[data-role='notifications']")
    notifications.click()
    panel = assigned_user.page.locator("[role='listbox'][data-visible='true']")
    assignment = (
        panel.locator("[role='option']")
        .filter(has_text=f"{user.entity.name} assigned you a task.")
        .filter(has_text=task.definition.name)
    )
    expect(assignment).to_be_visible()
    expect(assignment.locator("[data-role='target']")).to_have_attribute(
        "href", f"/tasks/{task.key}"
    )


# @features tasks
# @dimensions create due-date badge
def test_create_page_task_with_due_date(get_user):
    user = get_user(Users.OWNER)

    task = Tasks.test_create_page_task_with_due_date.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    user.go(page)

    create_form = page.create_task_form
    create_form.locator(FormElements.NAME).fill(task.definition.name)

    due_form = DateSelect(create_form).form()
    task.definition.due_date.set(due_form)

    task.key = _submit_create_task_form(user, page, task, create_form)

    expect(task.element.locator("[data-role='change-due-date']")).to_be_visible()


# @features tasks
# @dimensions update settings-form unsaved-marker
# @template controls.html::task_save
# @template pages/tasks.html::task_title
def test_update_page_task_settings_from_row(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_update_page_task_settings.get(user)
    user.go(task)

    updated_name = "Task Settings After"
    updated_description = "Updated task settings description."

    settings_form = task.settings_form
    save_toggle = task.element.locator("[data-role='save-toggle']")
    expect(
        task.element.locator("[data-role='save-toggle'] ~ [data-role='controls']")
    ).to_have_count(1)
    expect(
        task.element.locator("[data-role='save-toggle'] ~ [data-role='nav-toggles']")
    ).to_have_count(1)
    expect(save_toggle).to_be_hidden()
    expect(save_toggle).to_have_attribute("data-saved", "false")
    _fill_editable_field(settings_form, "name", FormElements.NAME, updated_name)
    _fill_editable_field(
        settings_form, "description", FormElements.DESCRIPTION, updated_description
    )
    expect(save_toggle).to_be_visible()
    expect(save_toggle).to_have_attribute("data-saved", "false")
    expect(save_toggle).to_have_attribute("aria-label", "Unsaved changes")
    task.save()
    expect(save_toggle).to_have_attribute("data-saved", "true")
    expect(save_toggle).to_have_attribute("aria-label", "Saved")

    expect(task.element.locator("[data-role='title']")).to_contain_text(updated_name)
    expect(task.element).to_contain_text(updated_description)

    user.reload()
    task.wait_for_load()
    expect(task.element.locator("[data-role='title']")).to_contain_text(updated_name)
    expect(task.element).to_contain_text(updated_description)


# @features tasks
# @dimensions attach-form widget-identity merged-submission
# @template pages/tasks.html::task
# @template pages/tasks.html::settings_form
# @template pages/tasks.html::task_form
def test_adding_form_from_task_settings_preserves_widget_identity(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_update_page_task_settings.get(user)
    form = Forms.test_task_history_form.get(user)
    user.go(task)

    settings_form = task.settings_form
    FormSelect(settings_form).select(form)
    task.save()

    expect(task.element.locator(task.SETTINGS_FORM)).to_have_count(1)
    expect(task.element.locator(task.TASK_FORM)).to_have_count(1)
    settings_form = task.element.locator(task.SETTINGS_FORM)
    expect(settings_form.locator("[name='name']")).to_have_count(1)
    expect(settings_form.locator("[name='description']")).to_have_count(1)
    expect(settings_form.locator("[name='input-textab12']")).to_have_count(0)
    state = task.element.evaluate(
        """row => {
            const component = row._lp_component;
            return {
                active: component.active?.name,
                activeTarget: component.active?.target?.dataset.widget,
                settingsTarget: component.widgets.TaskSettings?.target?.dataset.widget,
                formTarget: component.widgets.TaskForm?.target?.dataset.widget ?? null,
                domWidgets: Array.from(row.querySelectorAll(':scope > [data-widget]'))
                    .map(widget => widget.dataset.widget),
            };
        }"""
    )
    assert state == {
        "active": "TaskSettings",
        "activeTarget": "TaskSettings",
        "settingsTarget": "TaskSettings",
        "formTarget": None,
        "domWidgets": [
            "TaskSettings",
            "TaskMove",
            "TaskCombine",
            "TaskForm",
        ],
    }

    task_form = task.task_form
    task_value = "Saved with a settings update"
    task_form.locator("[name='input-textab12']").fill(task_value)
    user.page.keyboard.press("Tab")

    settings_toggle = task.element.locator(
        f"{task.SETTINGS_FORM_TOGGLE}:visible"
    )
    expect(settings_toggle).to_be_visible()
    settings_toggle.click()
    settings_form = task.element.locator(task.SETTINGS_FORM)
    expect(settings_form).to_be_visible()
    expect(task_form).to_be_hidden()
    updated_name = "Task Settings and Form After"
    _fill_editable_field(settings_form, "name", FormElements.NAME, updated_name)
    with expect_successful_response(
        user.page,
        method="PUT",
        path=f"/tasks/{task.key}/update",
        entity_key=task.key,
    ):
        SpinnerButtons.UPDATE.click(settings_form)
    assert SpinnerButtons.UPDATE_SUCCESS.successful(settings_form)

    settings_form = task.element.locator(task.SETTINGS_FORM)
    task_form = task.element.locator(task.TASK_FORM)
    expect(settings_form).to_be_visible()
    expect(task_form).to_have_count(1)
    for role in ("project-select", "form-select", "file-select"):
        expect(settings_form.locator(f"[data-role='{role}']")).to_be_visible()
    expect(settings_form.locator("[name='input-textab12']")).to_have_count(0)
    expect(task_form.locator("[name='input-textab12']")).to_have_count(1)

    user.reload()
    task.wait_for_load()
    expect(task.element.locator("[data-role='title']")).to_contain_text(updated_name)
    reloaded_task_form = task.task_form
    expect(reloaded_task_form.locator("[name='input-textab12']")).to_have_value(
        task_value
    )


# @features tasks
# @dimensions move completed title-menu
# @template pages/tasks.html::task_title
# @template pages/tasks.html::move_form
# @template pages/tasks.html::move_page_select
def test_completed_task_can_move_to_another_page(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_page_task_move_pages.get(user)
    source_page = Pages.test_task_pages_move_source.get(user)
    target_page = Pages.test_task_pages_move_target.get(user)
    user.go(task)

    task.complete()
    expect(task.element).to_have_attribute("data-completed", "true")
    expect(task.element).to_have_attribute("data-content-readonly", "true")
    expect(task.element.locator(task.SETTINGS_FORM)).to_have_count(0)

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
    source_page.task_list
    expect(user.locate(f"[data-key='{task.key}']")).not_to_be_attached()


# @features tasks
# @dimensions delete
# @template pages/tasks.html::task
def test_delete_page_task_from_page_row(get_user):
    user = get_user(Users.OWNER)
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


# @features tasks
# @dimensions attached-form submission autofill
# @template pages/tasks.html::task_form
def test_submit_attached_task_form(get_user):
    user = get_user(Users.OWNER)
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


# @pair tasks:update-state
# @pair tasks:refresh
# @pair tasks:complete
# @pair tasks:readonly
# @pair tasks:attached-form
# @pair reconnect-refresh:page-tasks
# @template pages/tasks.html::task
# @template pages/tasks.html::task_form
# @template pages/tasks.html::settings_form
def test_task_update_preserves_open_widget_and_completed_readonly_state(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_task_update_preserves_open_widget.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(task)

    expect(task.settings_form).to_be_visible()
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
    expect(task_form).to_be_visible()
    for submission in task.definition.submission:
        assert submission.verify_submission_value(task_form)

    task.complete()

    task_form = task.element.locator(task.TASK_FORM)
    expect(task.element).to_have_attribute("data-completed", "true")
    expect(task.element).not_to_have_attribute("data-readonly", "true")
    expect(task.element).to_have_attribute("data-content-readonly", "true")
    expect(task_form).to_have_attribute("data-readonly", "true")
    expect(task_form).to_be_visible()
    expect(task.element.locator(task.SETTINGS_FORM)).to_have_count(0)
    expect(task.element.locator("[data-role='save-toggle']")).to_have_count(0)
    expect(task_form.locator("[data-role='show-autofill']")).to_have_count(0)
    expect(task_form.locator("button[type='submit']")).to_have_count(0)

    readonly_field = task_form.locator("[id^='input-textab12'].form-element")
    expect(readonly_field).to_have_attribute("data-mode", "read")
    expect(readonly_field).to_contain_text("Task update state text")
    readonly_field.locator("[data-role='label']").click()
    expect(readonly_field).to_have_attribute("data-mode", "read")
    expect(readonly_field.locator("input")).to_have_count(0)


# @features tasks
# @dimensions complete readonly attached-form empty-fields
# @template pages/tasks.html::task
# @template pages/tasks.html::task_form
# @template pages/tasks.html::settings_form
def test_completed_task_with_empty_form_is_readonly(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_completed_task_readonly_form.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(task)

    expect(_open_page_task_form(page, task)).to_be_visible()

    task.complete()

    expect(task.element).to_have_attribute("data-completed", "true")
    expect(task.element).not_to_have_attribute("data-readonly", "true")
    expect(task.element).to_have_attribute("data-content-readonly", "true")
    expect(task.element.locator(task.TASK_FORM)).to_have_count(0)
    expect(task.element.locator(task.SETTINGS_FORM)).to_have_count(0)
    expect(task.element.locator("[data-role='show-autofill']")).to_have_count(0)
    expect(task.element.locator("[data-widget='TaskMove']")).to_have_count(1)

    task.uncomplete()
    expect(task.element).to_have_attribute("data-completed", "false")
    expect(task.element).to_have_attribute("data-content-readonly", "false")
    expect(_open_page_task_form(page, task)).to_be_visible()


# @features tasks
# @dimensions complete readonly attached-form partial-submission empty-fields
# @template pages/tasks.html::task
# @template pages/tasks.html::task_form
def test_completed_task_with_partial_submission_omits_empty_fields(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_completed_partial_task_readonly_form.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(task)

    expect(_open_page_task_form(page, task)).to_be_visible()

    task.complete()

    task_form = task.element.locator(task.TASK_FORM)
    expect(task.element).to_have_attribute("data-completed", "true")
    expect(task.element).not_to_have_attribute("data-readonly", "true")
    expect(task.element).to_have_attribute("data-content-readonly", "true")
    expect(task_form).to_have_attribute("data-readonly", "true")
    expect(task_form).to_be_visible()
    expect(task_form).to_contain_text("Partial completed task text")
    expect(task_form.locator("[id^='input-textab12'].form-element")).to_have_count(1)
    expect(task_form.locator("[id^='input-datecd34'].form-element")).to_have_count(0)
    expect(task_form).not_to_contain_text("Not provided")
    expect(task_form.locator("input")).to_have_count(0)

    task.uncomplete()
    active_form = task.task_form
    expect(active_form).not_to_have_attribute("data-readonly", "true")
    expect(active_form.locator("[name='input-textab12']")).to_have_value("")


# @features tasks
# @dimensions create while-open list-state
# @template pages/tasks.html::task_tab
# @template pages/tasks.html::task_list
# @template pages/tasks.html::task
def test_create_page_task_while_another_task_is_open_keeps_rows_clear(get_user):
    user = get_user(Users.OWNER)
    existing_task = Tasks.test_create_while_open_existing.get(user)
    new_task = Tasks.test_create_while_open_new.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    user.go(existing_task)

    expect(existing_task.settings_form).to_be_visible()

    create_form = page.create_task_form
    expect(existing_task.element).to_have_attribute("data-open", "false")
    expect(
        existing_task.element.locator(existing_task.SETTINGS_FORM)
    ).not_to_be_visible()

    create_form.locator(FormElements.NAME).fill(new_task.definition.name)
    create_form.locator(FormElements.DESCRIPTION).fill(
        new_task.definition.description
    )

    new_task.key = _submit_create_task_form(user, page, new_task, create_form)

    expect(page.task_list).to_be_visible()
    expect(page.active_task_list.get_item(existing_task)).to_be_visible()
    expect(page.active_task_list.get_item(new_task)).to_be_visible()
    expect(user.locate(page.CREATE_TASK_FORM)).not_to_be_visible()
    expect(existing_task.element).to_have_attribute("data-open", "false")
    expect(
        existing_task.element.locator(existing_task.SETTINGS_FORM)
    ).not_to_be_visible()


# @features signature
# @dimensions file-input asset-lifecycle form-value editable readonly reload clear
def test_signature_submission_draw_save_reload_and_clear(get_user):
    user = get_user(Users.OWNER)
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


# @features tasks
# @dimensions create file-upload async-upload remove attachment
# @template pages/tasks.html::action_buttons
def test_create_page_task_with_file(get_user):
    user = get_user(Users.OWNER)

    task = Tasks.test_create_page_task_with_file.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    user.go(page)

    create_form = page.create_task_form
    create_form.locator(FormElements.NAME).fill(task.definition.name)

    file_select = create_form.locator("[data-role='file-select']")
    expect(file_select).to_have_attribute("data-title", "Attach File/Photo")
    file_select.click()
    expect(create_form.locator("[data-role='dropzone']")).to_be_visible()
    with user.page.expect_response(
        lambda response: response.request.method == "POST"
        and f"/tasks/{page.key}/upload-file" in response.url
    ):
        Uploads.csv_file_input.set(create_form)

    filename = Uploads.csv_file_input.definition.filename
    create_saved_files = create_form.locator("[data-role='saved-files']")
    expect(create_saved_files).to_be_visible()
    expect(create_saved_files).to_contain_text(filename)
    expect(create_saved_files.locator("a").first).to_have_attribute(
        "href", re.compile(r"/files/")
    )

    task.key = _submit_create_task_form(user, page, task, create_form)

    expect(task.element).to_contain_text(filename)

    page_entity = Entities.fetch_one(page.key, request=Fetch.direct())
    assert filename not in [file.name for file in page_entity.files]

    settings_form = task.settings_form
    settings_form.locator("[data-role='file-select']").click()
    saved_files = settings_form.locator("[data-role='saved-files']")
    expect(saved_files).to_be_visible()
    expect(saved_files).to_contain_text(filename)
    expect(saved_files.locator("a").first).to_have_attribute(
        "href", re.compile(r"/files/")
    )

    delete_button = saved_files.locator("[data-role='delete-task-file']").first
    with user.page.expect_response(
        lambda response: response.request.method == "DELETE"
        and f"/tasks/{task.key}/files/" in response.url
    ):
        delete_button.click()

    expect(task.element).not_to_contain_text(filename)
    expect(saved_files).not_to_be_visible()
