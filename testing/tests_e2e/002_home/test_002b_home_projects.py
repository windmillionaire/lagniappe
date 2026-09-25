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
    SpinnerButtons,
)
from testing.utility.network import expect_successful_response
from testing.utility.live_ai import submit_live_ai

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


# @matrix projects : ai-create ai-form ai-generated
# @template home/projects.html::create
# @template home/projects.html::project
@pytest.mark.ai
@pytest.mark.parametrize("live_ai_quota", [False, True], indirect=True, ids=["live", "quota-fallback"])
def test_create_project_ai_mode(get_user, results, browser_failures, live_ai_quota):
    """
    Verify project creation in AI mode.

    Uses AI to generate project name and description from a prompt.
    The provider-backed create request gets the complete configured retry budget.
    """
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)
    create_form = home.create_project_form()

    project = Projects.test_create_project_ai_mode.get(user, create=False)

    create_form.locator(Buttons.AI_MODE).click()
    create_form.locator(FormElements.AI_DESCRIPTION).fill(
        project.definition.description_for_ai
    )

    expect(create_form.locator("[data-role='explain']")).to_have_count(0)

    def fallback():
        create_form.locator(Buttons.MANUAL_MODE).click()
        create_form.locator(FormElements.NAME).fill(project.definition.name)
        with expect_successful_response(user.page, method="POST", path="/projects/create") as response:
            SpinnerButtons.CREATE.click(create_form)
        results.record("alternate_verification", "Manual creation validates the same save and list workflow; AI content remains unverified.")
        return response.value

    with live_ai_quota(user, "/projects/create"):
        response = submit_live_ai(
            user, path="/projects/create", submit=lambda: SpinnerButtons.CREATE.click(create_form),
            results=results, browser_failures=browser_failures, fallback=fallback,
        )
    expect(create_form).not_to_be_visible()
    project.key = home.entity_key_from_response(response)
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
