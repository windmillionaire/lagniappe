"""
Tests for project creation and management from the home page.

Tests the project widget including form interactions, manual/AI creation modes,
list toggle behavior, navigation, and project-menu deletion.

Related Files:
    Application:
        - lagniappe/web/routes/projects/main.py: Project routes
        - lagniappe/web/templates/home/projects.html: Project component template
        - lagniappe/web/templates/projects/: Project page templates
        - src/script/widgets/home/lists.mjs: HomeProjectList widget
        - src/script/views/home.mjs: Project initialization

    Core Entity:
        - lagniappe/core/entities/project.py: Project entity

    Test Framework:
        - testing/definitions/projects.py: Projects enum with test definitions
        - testing/resources/project.py: Project resource with create() logic
        - testing/resources/home.py: HomePage selectors for project component

Project Creation Modes:
    - Manual mode: User enters name and description directly
    - AI mode: User provides a prompt, AI generates name and description

Project Attributes:
    Projects can have optional attributes toggled during creation:
    - tasks: Enable model tasks on the project
    - document: Enable document tab
"""

import re

from playwright.sync_api import expect
import pytest

from testing.definitions import Projects, SitePages, Users
from testing.elements import (
    Buttons,
    FormElements,
    HeaderSearch,
    Link,
    Modal,
    Attributes,
    Tabs,
    SpinnerButtons,
)
from testing.utility.network import expect_successful_response

pytestmark = pytest.mark.e2e


# @matrix projects : ai-form create-help manual-form
# @template home/projects.html::create
def test_create_project_form(get_user):
    """
    Verify create project form opens with expected fields and controls.

    Tests:
        - Form is hidden initially, visible after toggle click
        - Name and description fields are present
        - Create button is visible
        - Help button opens modal
        - Close button hides form
        - Modal: Helper for modal interactions
    """
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    form = user.locate(home.CREATE_PROJECT_FORM)
    expect(form).to_be_hidden()

    user.locate(home.CREATE_PROJECT_TOGGLE).click()
    expect(form).to_be_visible()

    manual_name = form.locator(FormElements.NAME)
    manual_description = form.locator(FormElements.DESCRIPTION)
    expect(manual_name).to_be_visible()
    expect(manual_description).to_be_visible()

    attributes = Attributes(form)
    for attribute in ["tasks", "document"]:
        expect(attributes.attribute(attribute)).to_be_visible()
        attributes.expect_selected(attribute)

    form.locator(Buttons.AI_MODE).click()
    ai_description = form.locator(FormElements.AI_DESCRIPTION)
    expect(ai_description).to_be_visible()
    expect(manual_name).not_to_be_visible()
    expect(manual_description).not_to_be_visible()

    form.locator(Buttons.MANUAL_MODE).click()
    expect(manual_name).to_be_visible()
    expect(manual_description).to_be_visible()
    expect(ai_description).not_to_be_visible()

    expect(form.get_by_role("button", name="Create Project")).to_be_visible()

    # Test help modal opens on help button click
    Modal(user.page).open(form.locator(Buttons.LP_HELP)).close()
    expect(form).to_be_visible()

    # Test close button closes form
    form.locator(Buttons.LP_CLOSE).click()
    expect(form).not_to_be_visible()


# @matrix projects : create-manual navigate search
# @template home/projects.html::create
def test_create_project_manual_mode(get_user):
    """
    Verify project creation in manual mode.

    Uses Projects.test_create_project_manual_mode definition which
    creates a project via the UI with manual name/description entry.
    Verifies the project appears in search results after creation.
    """
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    project = Projects.test_create_project_manual_mode.get(user, create=False)
    project_element = home.create_manual_project(project)

    header_search = HeaderSearch(user)
    header_search.verify_entity_in_results(project)

    Link(project_element).click()
    expect(user.page).to_have_title(re.compile(project.definition.name))


# @matrix projects : ai-create ai-form ai-generated explain-button
# @template home/projects.html::create
# @template home/projects.html::project
@pytest.mark.ai
def test_create_project_ai_mode(get_user, results):
    """
    Verify project creation in AI mode.

    Uses AI to generate project name and description from a prompt.
    The provider-backed create request gets the same 90-second budget as the
    other live AI generation stories.
    """
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)
    create_form = home.create_project_form()

    project = Projects.test_create_project_ai_mode.get(user, create=False)

    create_form.locator(Buttons.AI_MODE).click()
    create_form.locator(FormElements.AI_DESCRIPTION).fill(
        project.definition.description_for_ai
    )

    modal = Modal(user.page)
    with expect_successful_response(
        user.page,
        method="POST",
        path="/projects/create",
        timeout=15000,
    ):
        create_form.locator(Buttons.EXPLAIN).click()
    expect(modal.element).to_be_visible(timeout=15000)
    modal.close()
    expect(create_form).to_be_visible()

    with expect_successful_response(
        user.page,
        method="POST",
        path="/projects/create",
        timeout=90000,
    ) as response_info:
        SpinnerButtons.CREATE.click(create_form)

    expect(create_form).not_to_be_visible()
    project.key = home.entity_key_from_response(response_info.value)
    project_list = home.project_list
    new_project = project_list.get_item(project)
    expect(new_project).to_be_visible()

    results.record("project", project.entity.db)


# @pair projects:delete
# @template projects/project.html::view_header
# @template menus.html::title
# @template menus.html::delete
def test_delete_project(get_user):
    """Verify project deletion from its title menu."""
    user = get_user(Users.OWNER)
    project = Projects.test_delete_project.get(user)
    user.go(project)

    user.page.get_by_role("button", name="Project actions").click()
    menu = user.page.get_by_role("menu", name="Project actions")
    menu.get_by_role("menuitem", name="Delete").click()

    Modal(user.page).delete()
    expect(user.page).to_have_url(re.compile(r"/$"))


# @pair projects:attribute-model-tasks
# @template home/projects.html::create
def test_create_project_without_tasks(get_user):
    """
    Verify project created without tasks attribute.

    When tasks attribute is deselected during creation, the project
    page should not show the model tasks card.

    Uses definition with attributes excluding 'tasks'.
    """
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_without_tasks.get(user, create=False)
    home = user.go(SitePages.HOME)

    home.create_manual_project(project)

    project_page = user.go(project)
    model_card = user.locate(project_page.MODEL_TASKS_CARD)
    expect(model_card).to_be_hidden()


# @pair projects:attribute-document
# @template home/projects.html::create
def test_create_project_without_document(get_user):
    """
    Verify project created without document attribute.

    When document attribute is deselected during creation, the project
    page should not show the document tab.

    Uses definition with attributes excluding 'document'.
    """
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_without_document.get(user, create=False)
    home = user.go(SitePages.HOME)

    home.create_manual_project(project)

    user.go(project)
    tabs = Tabs(user)
    document_tab = user.locate(tabs.DOCUMENT_TOGGLE_DESKTOP)
    expect(document_tab).to_be_hidden()
