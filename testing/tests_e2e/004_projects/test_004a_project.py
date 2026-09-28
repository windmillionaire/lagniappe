"""
Tests for project view page base functionality.

Tests project page load, tab navigation, and basic structure.
Verified against:
- lagniappe/templates/projects/project.html
- src/script/views/project.mjs
- src/script/views/base/entity.mjs
"""

from dataclasses import replace
from uuid import uuid4

from playwright.sync_api import expect

from testing.definitions import ModelTasks, Projects
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


# @pair model-tasks:create
def test_create_model_task(get_admin, get_user):
    user = get_admin()
    project = Projects.test_create_model_task.get(user)
    user.go(project)

    definition = replace(
        ModelTasks.test_create_model_task.value.definition,
        name=f"Created Model Task {uuid4().hex}",
    )
    _create_model_task(user, project, definition)


# @matrix model-tasks : attach-form create
def test_create_model_task_with_form(get_admin, get_user):
    user = get_admin()
    project = Projects.test_create_model_task_with_form.get(user)
    user.go(project)

    definition = replace(
        ModelTasks.test_create_model_task_with_form.value.definition,
        name=f"Created Model Task with Form {uuid4().hex}",
    )
    _create_model_task(user, project, definition)
