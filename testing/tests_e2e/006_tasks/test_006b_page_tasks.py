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
import json
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


SIGNATURE_FIELD_ID = "task-signature-field"
SIGNATURE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def _submit_create_task_form(user, page, task, create_form):
    with user.page.expect_response("**/create"):
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


def _saved_task_submission(task):
    saved_task = Entities.fetch_one(task.key, request=Fetch.direct())
    return saved_task, json.loads(saved_task.db.get("submission", "{}"))


def _latest_history(task):
    saved_task = Entities.fetch_one(task.key, request=Fetch.direct())
    assert saved_task.history
    return saved_task.history[0]


# @features tasks
# @dimensions create basic
def test_create_basic_page_task(get_user):
    """Test creating a task on a page."""
    user = get_user(Users.OWNER)

    task = Tasks.test_create_page_task.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    user.go(page)

    create_form = page.create_task_form
    create_form.locator(FormElements.NAME).fill(task.definition.name)
    create_form.locator(FormElements.DESCRIPTION).fill(task.definition.description)

    task.key = _submit_create_task_form(user, page, task, create_form)


# @pairs tasks:create-close tasks:empty-state
# @template pages/tasks.html::task_list
# @template pages/tasks.html::task_empty
def test_empty_page_task_list_shows_marker_only_after_create_closes(get_user):
    """An editable empty task list opens CreateTask before its empty marker."""
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
    """Test creating a task on a page with a form."""
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
    """Test completing a task on a page."""
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
    """Create a page task linked to a project; the project badge appears on the row."""
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
    expect(clear_icon).to_be_visible()

    leading_size = float(
        leading_icon.evaluate("node => getComputedStyle(node).fontSize")[:-2]
    )
    clear_size = float(
        clear_icon.evaluate("node => getComputedStyle(node).fontSize")[:-2]
    )
    assert clear_size <= leading_size

    project_button.evaluate("node => { node.style.maxWidth = '8rem'; }")
    assert project_button.bounding_box()["height"] > 40
    project_button.evaluate("node => { node.style.maxWidth = ''; }")

    button_height = project_button.bounding_box()["height"]
    leading_icon.click()
    project_input = settings_form.locator(
        "[data-role='project-select'] + input[role='combobox']"
    )
    expect(project_input).to_be_visible()
    assert abs(project_input.bounding_box()["height"] - button_height) < 1


# @features tasks
# @dimensions create model-task-link attach-form badge
def test_create_page_task_with_model_task(get_user):
    """
    Searching by project name lists each model task; picking one with a form fills the form field.

    Uses a project with two model tasks so the facet panel must show both before selection.
    """
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


# @features tasks
# @dimensions create assignee badge
def test_create_page_task_with_assigned_to(get_user):
    """Assigning a user adds an assignee badge on the task row."""
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


# @features tasks
# @dimensions create due-date badge
def test_create_page_task_with_due_date(get_user):
    """A due date shows the due-date badge on the new task row."""
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

    with user.page.expect_response("**/update"):
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


# @pair tasks:update-state
# @pair tasks:refresh
# @pair tasks:complete
# @pair tasks:readonly
# @pair tasks:attached-form
# @pair reconnect-refresh:page-tasks
# @pair reconnect-refresh:component-identity
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

    with user.page.expect_response("**/update"):
        SpinnerButtons.UPDATE.click(task_form)

    task_form = task.element.locator(task.TASK_FORM)
    expect(task_form).to_be_visible()
    for submission in task.definition.submission:
        assert submission.verify_submission_value(task_form)

    with user.page.expect_response("**/refresh") as refresh_info:
        user.page.evaluate(
            """async () => {
                const view = document.querySelector("[lp-view]");
                const watcher = view._lp_view.EditWatcher;
                watcher?.pause();
                view.dataset.fingerprint = "stale-refresh-test";
                try {
                    await view._lp_view._refreshCollectionComponents(
                        Object.values(view._lp_view.components),
                    );
                } finally {
                    watcher?.resume();
                }
            }"""
        )

    refresh_request = json.loads(refresh_info.value.request.post_data or "{}")
    assert refresh_request["view"]["key"] == page.key
    assert refresh_request["view"]["fingerprint"] == "stale-refresh-test"
    assert {target["id"] for target in refresh_request["targets"]} == {"tasks"}
    assert set(refresh_request["targets"][0]) == {"id", "rows"}

    refresh_targets = refresh_info.value.json()["targets"]
    task_refresh = next(
        target for target in refresh_targets if target["id"] == "tasks"
    )
    assert task_refresh["fallback"] is False
    task_form = task.element.locator(task.TASK_FORM)
    expect(task_form).to_be_visible()
    expect(task.element).to_have_attribute("data-open", "TaskForm")

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
# @dimensions refresh update-state stale-widget
# @template pages/tasks.html::task
# @template pages/tasks.html::task_form
def test_task_refresh_closes_when_open_widget_is_missing(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_completed_task_readonly_form.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(task)

    expect(_open_page_task_form(page, task)).to_be_visible()
    result = user.page.evaluate(
        """async (key) => {
            const list = document.querySelector("[data-widget='PageTaskList']")
                ._lp_widget;
            const row = document.querySelector(`[data-key="${key}"]`);
            const replacement = row.cloneNode(true);
            replacement.dataset.modified = `${row.dataset.modified || ""}:replacement`;
            replacement.dataset.default = "";
            replacement.dataset.open = "false";
            replacement.querySelector("[data-widget='TaskForm']")?.remove();
            replacement.querySelector("[lp-control='form']")?.remove();

            list._replaced = [{ from: row, to: replacement }];
            await list.postreconcile();

            const updated = document.querySelector(`[data-key="${key}"]`);
            return {
                hasForm: Boolean(updated.querySelector("[data-widget='TaskForm']")),
                open: updated.dataset.open,
                visibleWidgets: Array.from(updated.querySelectorAll("[data-widget]"))
                    .filter((widget) => widget.dataset.visible === "true")
                    .map((widget) => widget.dataset.widget),
            };
        }""",
        task.key,
    )

    assert result == {"hasForm": False, "open": "false", "visibleWidgets": []}
    expect(task.element.locator(task.TASK_FORM)).to_have_count(0)
    expect(task.element).to_have_attribute("data-open", "false")


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

    saved_task = Entities.fetch_one(task.key, request=Fetch.direct())
    assert saved_task.submission == {}
    assert any(
        history.submission.get("input-textab12") == "Partial completed task text"
        for history in saved_task.history
    )


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


# @features tasks
# @dimensions create refresh dedupe
# @template pages/tasks.html::task_list
# @template pages/tasks.html::task
def test_page_task_refresh_create_reconcile_does_not_duplicate_rows(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_page_task_refresh_create_dedupe.get(user, create=False)
    page = Pages.test_create_page_task.get(user)
    user.go(page)

    create_form = page.create_task_form
    create_form.locator(FormElements.NAME).fill(task.definition.name)
    create_form.locator(FormElements.DESCRIPTION).fill(task.definition.description)

    task.key = _submit_create_task_form(user, page, task, create_form)
    task_rows = page.task_list.locator(f"li[lp-entity][data-key='{task.key}']")
    expect(task_rows).to_have_count(1)

    duplicate_count = user.page.evaluate(
        """async (key) => {
            const list = document.querySelector("[data-widget='PageTaskList']")
                ._lp_widget;
            const rows = () => Array.from(
                list.target.querySelectorAll("li[lp-entity]"),
            ).filter((elt) => elt.dataset.key === key);
            const row = rows()[0];
            if (!row) throw new Error("Created task row not found");

            const refreshRow = row.cloneNode(true);
            const createdRow = row.cloneNode(true);
            row.remove();
            list._added = [refreshRow];
            list._created = [createdRow];

            await list.postreconcile();
            return rows().length;
        }""",
        task.key,
    )

    assert duplicate_count == 1
    expect(task_rows).to_have_count(1)


# @features signature
# @dimensions file-input asset-lifecycle form-value editable readonly reload clear
def test_signature_submission_draw_save_reload_and_clear(get_user):
    user = get_user(Users.OWNER)
    task = Tasks.test_signature_submission.get(user)
    page = Pages.test_create_page_task.get(user)
    user.go(task)

    task_form = _open_page_task_form(page, task)
    expect(_signature_field(task_form)).to_have_attribute("data-mode", "edit")
    saved_task, submission = _saved_task_submission(task)
    assert SIGNATURE_FIELD_ID not in submission
    assert SIGNATURE_FIELD_ID not in saved_task.assets
    assert saved_task.has_signature is False

    _upload_signature(task_form)
    with user.page.expect_response("**/update"):
        SpinnerButtons.UPDATE.click(task_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(task_form)
    expect(task_form).to_be_visible()
    _expect_signature_image(task_form)
    saved_task, submission = _saved_task_submission(task)
    assert submission[SIGNATURE_FIELD_ID] == SIGNATURE_FIELD_ID
    assert SIGNATURE_FIELD_ID in saved_task.assets
    assert saved_task.has_signature is True

    user.reload()
    task.wait_for_load()
    task_form = task.task_form
    _expect_signature_image(task_form)

    _clear_signature(task_form)
    with user.page.expect_response("**/update"):
        SpinnerButtons.UPDATE.click(task_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(task_form)
    field = _signature_field(task_form)
    expect(field).to_have_attribute("data-mode", "edit")
    expect(field.locator("[data-role='read']")).to_have_count(0)
    saved_task, submission = _saved_task_submission(task)
    assert SIGNATURE_FIELD_ID not in submission
    assert SIGNATURE_FIELD_ID not in saved_task.assets
    assert saved_task.has_signature is False

    _upload_signature(task_form)
    with user.page.expect_response("**/update"):
        SpinnerButtons.UPDATE.click(task_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(task_form)
    _expect_signature_image(task_form)
    saved_task, submission = _saved_task_submission(task)
    assert submission[SIGNATURE_FIELD_ID] == SIGNATURE_FIELD_ID
    assert SIGNATURE_FIELD_ID in saved_task.assets
    signature_asset = saved_task.assets[SIGNATURE_FIELD_ID]
    assert saved_task.has_signature is True

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
    saved_task, submission = _saved_task_submission(task)
    assert SIGNATURE_FIELD_ID not in submission
    assert SIGNATURE_FIELD_ID not in saved_task.assets
    assert saved_task.has_signature is False

    history = _latest_history(task)
    assert history.submission[SIGNATURE_FIELD_ID] == SIGNATURE_FIELD_ID
    history_asset = history.assets[SIGNATURE_FIELD_ID]
    assert history_asset["type"] == "image"
    assert history_asset["path"] != signature_asset["path"]
    assert history_asset["path"].endswith(f"_{SIGNATURE_FIELD_ID}.png")
    assert history.properties.submission.form_value[SIGNATURE_FIELD_ID].endswith(
        f"/{SIGNATURE_FIELD_ID}.png"
    )


# @features tasks
# @dimensions create file-upload async-upload remove attachment
# @template pages/tasks.html::action_buttons
def test_create_page_task_with_file(get_user):
    """Attach a file via task file upload and assert the file badge."""
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
