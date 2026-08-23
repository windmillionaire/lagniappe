"""
Tests for model task management within projects.

Tests the ModelInfo widget including opening, editing name, form attachment,
form removal, and deletion of model tasks.

Related Files:
    Application:
        - lagniappe/web/routes/projects/tasks.py: Model task routes (create, update, delete)
        - lagniappe/web/templates/projects/model_tasks.html: Model task templates
        - src/script/widgets/project.mjs: CreateModelTask, ModelTaskInfo widgets

    Core Entity:
        - lagniappe/core/entities/model_task.py: ModelTask entity

    Test Framework:
        - testing/definitions/model_tasks.py: ModelTasks enum with test definitions
        - testing/definitions/model_task_definitions.py: ModelTaskDefinition dataclass
        - testing/resources/model_task.py: ModelTask resource with interaction methods

Model Task Structure:
    Each model task in the list has:
    - Header (lp-show): Clickable to open ModelTaskInfo widget
    - Title (data-role='title'): Display name
    - Delete button (lp-delete): Opens delete confirmation modal
    - ModelTaskInfo form (data-widget='ModelTaskInfo'): Edit form with name and form selector
    - Status section: Completed/In Progress buttons (filter links)

ModelTaskInfo Widget:
    When clicking a model task header, the ModelTaskInfo widget shows:
    - Name input: Edit the model task name
    - Form selector: Attach or change the associated task form
    - Update button: Save changes (spinner during submit)
    - Close button: Hide the edit form

See Also:
    - test_005a_projects.py: Project creation and model task creation tests
"""

from playwright.sync_api import expect

from testing.definitions import Forms, ModelTasks, SubmissionFields, Tasks, Users
from testing.elements import Buttons, FormSelect, Modal, SpinnerButtons


# @features model-tasks
# @dimensions info-form
def test_click_model_opens_info(get_user):
    user = get_user(Users.OWNER)
    model_task = ModelTasks.test_create_model_task.get(user)
    user.go(model_task.project)

    info_form = model_task.open_info()
    name_field = SubmissionFields.INPUT.get(
        "name", submission_value=model_task.definition.name
    )
    assert name_field.verify_submission_value(info_form)
    expect(FormSelect(info_form).button).to_be_visible()

    model_task.close_info()
    expect(model_task.info_form).to_be_hidden()


# @features model-tasks
# @dimensions update name
def test_edit_model_task_name(get_user):
    user = get_user(Users.OWNER)
    model_task = ModelTasks.test_edit_model_task_name.get(user)
    user.go(model_task.project)

    info_form = model_task.open_info()
    new_name = "Updated Model Task Name"
    name = SubmissionFields.INPUT.get(
        "name", submission_value=model_task.definition.name
    )
    assert name.verify_submission_value(info_form)
    name.value = new_name

    with user.page.expect_response("**/update-model/**"):
        SpinnerButtons.UPDATE.click(info_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(info_form)

    new_info_form = model_task.open_info()
    name = SubmissionFields.INPUT.get("name", submission_value=new_name)
    assert name.verify_submission_value(new_info_form)

    title = model_task.element.locator(model_task.TITLE)
    expect(title).to_contain_text(new_name)


# @features model-tasks
# @dimensions update form-change
def test_change_model_task_form(get_user):
    user = get_user(Users.OWNER)

    new_form = Forms.test_alternate_task_form.get(user)
    model_task = ModelTasks.test_change_model_task_form.get(user)
    user.go(model_task.project)
    info_form = model_task.open_info()

    form_button = FormSelect(info_form).button
    expect(form_button).to_contain_text(
        model_task.definition.form.value.definition.name
    )

    FormSelect(info_form).select(new_form)

    with user.page.expect_response("**/update-model/**"):
        SpinnerButtons.UPDATE.click(info_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(info_form)

    form_button = FormSelect(info_form).button
    expect(form_button).to_contain_text(new_form.name)


# @features model-tasks
# @dimensions update form-clear
def test_delete_model_task_form(get_user):
    user = get_user(Users.OWNER)
    model_task = ModelTasks.test_delete_model_task_form.get(user)
    user.go(model_task.project)

    info_form = model_task.open_info()

    form_button = FormSelect(info_form).button
    expect(form_button).to_contain_text(
        model_task.definition.form.value.definition.name
    )

    FormSelect(info_form).clear()

    with user.page.expect_response("**/update-model/**"):
        SpinnerButtons.UPDATE.click(info_form)

    expect(FormSelect(info_form).button).to_contain_text("Form")


def _status_filter_context(user):
    completed_task = Tasks.test_status_filter_completed.get(user)
    in_progress_task = Tasks.test_status_filter_in_progress.get(user)
    if not completed_task.entity.completed:
        completed_task.mark_completed()

    model_task = ModelTasks.test_status_filter_model_task.get(user)
    user.go(model_task.project)

    return model_task, completed_task, in_progress_task


def _click_status_filter(model_task, label):
    status_link = (
        model_task.element.locator("[data-role='status']")
        .get_by_role("link", name=label, exact=True)
    )
    expect(status_link).to_be_visible()
    status_link.click()

    results = model_task.user.locate("#table")
    expect(results).to_be_visible()
    return results


# @features model-tasks
# @dimensions status-filter completed
def test_completed_button(get_user):
    user = get_user(Users.OWNER)
    model_task, completed_task, in_progress_task = _status_filter_context(user)

    results = _click_status_filter(model_task, "Completed")

    expect(results.locator(f"tr[data-key='{completed_task.key}']")).to_be_visible()
    expect(
        results.locator(f"tr[data-key='{in_progress_task.key}']")
    ).not_to_be_visible()


# @features model-tasks
# @dimensions status-filter in-progress
def test_in_progress_button(get_user):
    user = get_user(Users.OWNER)
    model_task, completed_task, in_progress_task = _status_filter_context(user)

    results = _click_status_filter(model_task, "In Progress")

    expect(results.locator(f"tr[data-key='{in_progress_task.key}']")).to_be_visible()
    expect(
        results.locator(f"tr[data-key='{completed_task.key}']")
    ).not_to_be_visible()


# @features model-tasks
# @dimensions delete
def test_delete_model_task(get_user):
    user = get_user(Users.OWNER)
    model_task = ModelTasks.test_delete_model_task.get(user)
    user.go(model_task.project)

    delete_button = model_task.element.locator(Buttons.LP_DELETE)
    expect(delete_button).to_be_visible()
    delete_button.click()

    modal = Modal(user.page)
    modal.delete()

    expect(model_task.element).not_to_be_visible()
