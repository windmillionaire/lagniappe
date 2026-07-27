"""
Project permission tests for view, edit affordances, and model task creation.

Verified against:
- lagniappe/web/templates/projects/project.html
- lagniappe/web/templates/projects/info.html
- lagniappe/web/templates/projects/model_tasks.html
- lagniappe/web/routes/projects/main.py
"""

import pytest
from playwright.sync_api import expect

from testing.definitions import ModelTasks, Projects, Users
from testing.elements import (
    Dropdown,
    Filters,
    FormElements,
    ProjectFilterConditions,
    SpinnerButtons,
    Tabs,
)

pytestmark = pytest.mark.e2e


# @features projects
# @dimensions permission-gates
def test_project_is_forbidden_without_model_permission(get_user):
    """A signed-in user with no model access cannot open an existing project."""
    owner = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(owner)

    blocked = get_user(Users.user_no_access)
    blocked.navigate(project.url)

    expect(blocked.page).to_have_title("Error 403")


# @features projects
# @dimensions load readonly permission-gates
def test_project_viewer_reads_project_without_editing_controls(get_user):
    """A model viewer reads the project but cannot change project settings or models."""
    owner = get_user(Users.OWNER)
    model_task = ModelTasks.test_create_model_task.get(owner)
    project = model_task.project

    viewer = get_user(Users.general_models_view_only)
    viewer.go(project)
    model_task.user = viewer

    expect(viewer.locate(project.PROJECT_TITLE)).to_contain_text(
        project.definition.name
    )
    expect(viewer.locate(project.CREATE_MODEL_BUTTON)).not_to_be_attached()

    info_form = project.info_form
    name_field = info_form.locator(project.INFO_NAME)
    description_field = info_form.locator(project.INFO_DESCRIPTION)
    expect(name_field).to_contain_text("Project Name")
    expect(name_field).to_contain_text(project.definition.name)
    expect(description_field).to_contain_text("Project Description")
    expect(description_field).to_contain_text(project.definition.description)
    expect(info_form.locator(FormElements.NAME)).not_to_be_attached()
    expect(info_form.locator(FormElements.DESCRIPTION)).not_to_be_attached()
    # Possible product bug: the current project info template renders feature
    # toggles and an update submitter without checking project.allowed(EDIT).
    # The intended user story is read-only project settings for VIEW-only users.
    expect(info_form.locator("[data-role='attributes']")).not_to_be_attached()
    expect(info_form.locator(SpinnerButtons.UPDATE.value)).not_to_be_attached()

    model_info = model_task.open_info()
    expect(model_info.locator("#name")).to_contain_text("Name")
    expect(model_info.locator("#name")).to_contain_text(model_task.definition.name)
    expect(model_info.locator(FormElements.NAME)).not_to_be_attached()
    expect(model_task.element.locator(model_task.TITLE)).to_contain_text(
        model_task.definition.name
    )
    expect(model_task.element.locator(model_task.TITLE)).not_to_contain_text(
        "undefined"
    )

    filters = Filters(viewer, project)
    expect(filters.form).to_have_attribute("data-readonly", "false")
    expect(filters.run_button).to_be_visible()
    expect(filters.reset_button).to_be_visible()
    panel = Dropdown(filters.conditions).open()
    condition = panel.get_by_role(
        "option",
        name=ProjectFilterConditions.NAME.value,
        exact=True,
    )
    expect(condition).to_be_visible()


# @features projects
# @dimensions readonly document-tab
# @template projects/project.html::main
def test_project_viewer_sees_document_tab_only_when_content_exists(get_user):
    """Readonly viewers do not see empty document affordances, but can read saved docs."""
    owner = get_user(Users.OWNER)
    project = Projects.test_readonly_document_visibility.get(owner)

    viewer = get_user(Users.general_models_view_only)
    viewer.go(project)

    expect(viewer.locate(Tabs.DOCUMENT_TOGGLE_DESKTOP)).not_to_be_attached()
    expect(viewer.locate(Tabs.DOCUMENT_TAB)).not_to_be_attached()

    project.entity.properties.document.save(
        html="<p>Readonly project document content marker</p>",
        ydoc=None,
    )
    project.entity.save()

    viewer.go(project)

    expect(viewer.locate(Tabs.DOCUMENT_TOGGLE_DESKTOP)).to_be_visible()
    document = Tabs(viewer).document
    expect(document).to_be_visible()
    expect(document).to_contain_text("Readonly project document content marker")


# @features model-tasks
# @dimensions create permission-gates
def test_project_editor_can_open_model_task_creation(get_user):
    """A project editor sees the model-task creation path and can start a model."""
    owner = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(owner)

    editor = get_user(Users.admin)
    editor.go(project)

    create_form = project.create_model_task_form()
    expect(create_form).to_be_visible()
    expect(create_form.locator(FormElements.NAME)).to_be_visible()
    expect(create_form.locator("[data-role='form-select']")).to_be_visible()
