"""
Tests for project view page base functionality.

Tests project page load, tab navigation, and basic structure.
Verified against:
- lagniappe/templates/projects/project.html
- src/script/views/project.mjs
- src/script/views/base/entity.mjs
"""

from playwright.sync_api import expect

from testing.definitions import ModelTasks, Projects, Users
from testing.elements import FormElements, FormSelect, SpinnerButtons, List


def _create_model_task(user, project, definition):
    create_form = project.create_model_task_form()
    create_form.locator(FormElements.NAME).fill(definition.name)

    if definition.form:
        model_task_form = definition.form.get(user)
        FormSelect(create_form).select(model_task_form)
    else:
        model_task_form = None

    with user.page.expect_response("**/create-model"):
        SpinnerButtons.CREATE.click(create_form)

    task_list = List(user.locate(project.MODEL_TASKS_LIST))
    new_task = task_list.new_item(definition.name, flash=False)

    if model_task_form:
        new_task.locator('[data-role="header"]').click()
        task_form = new_task.locator(project.MODEL_TASK_INFO_FORM)
        expect(task_form).to_have_attribute("rendered", "")
        assert FormSelect(task_form).contains(model_task_form)

    return new_task.get_attribute("data-key")


# @features model-tasks
# @dimensions create
def test_create_model_task(get_user):
    """Test that model task can be created."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_model_task.get(user)
    user.go(project)

    model_task = ModelTasks.test_create_model_task.get(user, create=False)
    model_task.key = _create_model_task(user, project, model_task.definition)


# @features model-tasks
# @dimensions create attach-form
def test_create_model_task_with_form(get_user):
    """Test that model task can be created with a form."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_model_task_with_form.get(user)
    user.go(project)

    model_task = ModelTasks.test_create_model_task_with_form.get(user, create=False)
    model_task.key = _create_model_task(user, project, model_task.definition)
