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
    """
    Verify clicking model task header opens the ModelInfo widget.

    Tests the toggle behavior where clicking the model task header
    reveals the edit form with name input and form selector.

    Flow:
        1. Get existing model task
        2. Click the header (lp-show='...:ModelInfo')
        3. Verify ModelInfo form becomes visible
        4. Verify name input and form selector are present
        5. Close the form and verify it hides

    Framework usage:
        - model_task.open_info(): Opens the ModelInfo widget
        - model_task.close_info(): Closes the widget
        - model_task.info_form: Property to access the form element

    Verifies:
        - lagniappe/web/templates/projects/model_tasks.html: Header toggle
        - src/script/widgets/project.mjs: ModelInfo show/hide behavior
    """
    user = get_user(Users.OWNER)
    model_task = ModelTasks.test_create_model_task.get(user)
    user.go(model_task.project)

    # Open the ModelInfo widget
    info_form = model_task.open_info()

    # Verify form elements are visible
    name_field = SubmissionFields.INPUT.get(
        "name", submission_value=model_task.definition.name
    )
    assert name_field.verify_submission_value(info_form)
    expect(FormSelect(info_form).button).to_be_visible()

    # Close and verify hidden
    model_task.close_info()
    expect(model_task.info_form).to_be_hidden()


# @features model-tasks
# @dimensions update name
def test_edit_model_task_name(get_user):
    """
    Verify editing a model task's name via the ModelInfo widget.

    Tests the complete name edit flow including form submission
    and verification that the title updates.

    Flow:
        1. Create model task with initial name
        2. Open ModelInfo widget
        3. Clear and fill name input with new name
        4. Submit form and wait for update response
        5. Verify title element shows new name

    Framework usage:
        - SpinnerButtons.UPDATE: Submit button with loading spinner
        - model_task.title: Title text element for verification

    Verifies:
        - lagniappe/web/routes/projects/tasks.py: update_model route
        - src/script/widgets/project.mjs: ModelInfo.update() method
    """
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
    """
    Verify changing a model task's associated form to a different one.

    Tests the complete form change flow: model task starts with one form
    attached, then is changed to a different form via the form selector.

    Flow:
        1. Create model task with initial form (test_create_task_form)
        2. Open ModelInfo widget
        3. Verify initial form is shown in selector
        4. Use form selector to change to different form (test_alternate_task_form)
        5. Submit and wait for update response
        6. Verify form selector shows the new form name

    Framework usage:
        - FormSelect.select(): Selects form from dropdown
        - Forms.test_alternate_task_form: Different form to change to

    Verifies:
        - lagniappe/web/templates/projects/model_tasks.html: Form selector
        - src/script/elements/sectionToggle.mjs: SectionToggle facet selection
        - src/script/widgets/modelTasks.mjs: ModelTaskInfo.postreconcile() method
    """
    user = get_user(Users.OWNER)

    # Get the new form to change to
    new_form = Forms.test_alternate_task_form.get(user)

    # Open ModelInfo
    model_task = ModelTasks.test_change_model_task_form.get(user)
    user.go(model_task.project)
    info_form = model_task.open_info()

    # Verify initial form is attached
    form_button = FormSelect(info_form).button
    expect(form_button).to_contain_text(
        model_task.definition.form.value.definition.name
    )

    # Change to the new form
    FormSelect(info_form).select(new_form)

    # Submit and wait for response
    with user.page.expect_response("**/update-model/**"):
        SpinnerButtons.UPDATE.click(info_form)

    assert SpinnerButtons.UPDATE_SUCCESS.successful(info_form)

    form_button = FormSelect(info_form).button
    expect(form_button).to_contain_text(new_form.name)


# @features model-tasks
# @dimensions update form-clear
def test_delete_model_task_form(get_user):
    """
    Verify removing a model task's associated form.

    Tests the clear functionality of the form selector to remove
    an attached form from a model task.

    Flow:
        1. Create model task with an attached form
        2. Open ModelInfo widget
        3. Click the clear button on the form selector
        4. Submit and wait for update response
        5. Verify form selector shows default placeholder

    Framework usage:
        - FormSelect.clear(): Clicks the 'x' button to clear
        - Form selector reverts to placeholder text after clearing

    Verifies:
        - src/script/elements/sectionToggle.mjs: clear selection behavior
        - lagniappe/web/routes/projects/tasks.py: update with form=None
    """
    user = get_user(Users.OWNER)
    model_task = ModelTasks.test_delete_model_task_form.get(user)
    user.go(model_task.project)

    # Open ModelInfo
    info_form = model_task.open_info()

    # Verify form is currently attached
    form_button = FormSelect(info_form).button
    expect(form_button).to_contain_text(
        model_task.definition.form.value.definition.name
    )

    # Clear the form selection
    FormSelect(info_form).clear()

    # Submit and wait for response
    with user.page.expect_response("**/update-model/**"):
        SpinnerButtons.UPDATE.click(info_form)

    # Verify form selector shows default placeholder
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
    """
    Verify completed button navigates to the completed task filter.

    The filtered view should include completed tasks for the selected
    model task and exclude in-progress tasks from the same model task.
    """
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
    """
    Verify in progress button navigates to the in-progress task filter.

    The filtered view should include active tasks for the selected model
    task and exclude completed tasks from the same model task.
    """
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
    """
    Verify deleting a model task via the delete button.

    Tests the complete delete flow with confirmation modal.

    Flow:
        1. Create model task
        2. Click delete button (lp-delete)
        3. Confirm in modal
        4. Verify model task removed from list

    Framework usage:
        - Buttons.LP_DELETE: Delete button selector
        - Modal.delete(): Confirms delete with spinner wait

    Verifies:
        - lagniappe/web/templates/projects/model_tasks.html: Delete button
        - lagniappe/web/routes/projects/tasks.py: delete_model route
    """
    user = get_user(Users.OWNER)
    model_task = ModelTasks.test_delete_model_task.get(user)
    user.go(model_task.project)

    # Click delete button
    delete_button = model_task.element.locator(Buttons.LP_DELETE)
    expect(delete_button).to_be_visible()
    delete_button.click()

    # Confirm delete in modal
    modal = Modal(user.page)
    modal.delete()

    # Verify model task removed
    expect(model_task.element).not_to_be_visible()
