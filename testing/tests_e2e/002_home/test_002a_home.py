"""
Tests for the home page base functionality.

Tests basic page load, component visibility, toggle buttons, and loading behavior.
This is the main dashboard that authenticated users see after login.

Related Files:
    Application:
        - lagniappe/web/routes/home/main.py: Home route (/)
        - lagniappe/web/templates/home/home.html: Main home template
        - lagniappe/web/templates/home/*.html: Component templates
        - src/script/views/home.mjs: Client-side initialization
        - src/script/widgets/home/: List, activity, and task widget classes

    Core Entity:
        - lagniappe/core/entities/home.py: Home entity (user dashboard data)

    Test Framework:
        - testing/definitions/site_pages.py: SitePages.HOME
        - testing/resources/home.py: HomePage resource with all selectors

Home Page Components:
    The home page is organized into collapsible components, each with:
    - A toggle button to show/hide the list
    - A create toggle to show the creation form
    - A list container that loads via AJAX (lp-load or lp-prefetch)

    Components: pages, projects, categories, tasks, starred, notes, directory, tools

See Also:
    - test_003b_home_projects.py: Project component tests
    - test_003c_home_categories.py: Category component tests
    - test_003d_home_tasks.py: Task component tests
    - test_003e_home_starred.py: Starred component tests
    - test_003f_home_directory.py: Directory component tests
    - test_003g_home_import.py: Import component tests
"""

import re

import pytest
from playwright.sync_api import expect

from testing.definitions import Categories, Projects, SitePages, Users
from testing.elements import List
from testing.utility import TestFile as _TestFile

pytestmark = pytest.mark.e2e


# @features home icons
# @dimensions material-symbol-markup
# @template home/home.html::main
@pytest.mark.parallel_safe(
    reason="the read-only markup story is scoped to one browser context"
)
def test_home_material_symbols_use_semantic_span_markup(get_user):
    user = get_user(Users.OWNER)
    user.go(SitePages.HOME)

    expected = {
        "category": "stacks",
        "directory": "signpost",
        "generate": "memory",
        "manual": "help",
        "notes": "note_stack",
        "page": "draft",
        "plus": "add_2",
        "project": "flowsheet",
        "star.home": "star",
        "tasks": "check_box",
        "user": "person",
    }
    for semantic_name, glyph in expected.items():
        symbols = user.page.locator(f"span.icon[data-icon='{semantic_name}']")
        expect(symbols.first).to_be_attached()
        expect(symbols.first).to_have_text(glyph)
        expect(symbols.first).to_have_attribute("aria-hidden", "true")
        expect(symbols.first.locator(":scope > span.icon-glyph")).to_have_text(glyph)

    expect(user.page.locator("span.icon[data-icon='page']").first).to_have_css(
        "font-weight", "400"
    )
    expect(user.page.locator("span.icon[data-icon='project']").first).to_have_attribute(
        "data-fill", "0"
    )
    expect(user.page.locator("span.icon[data-icon='plus']").first).to_have_css(
        "font-weight", "600"
    )

    spinner = user.page.locator("span.icon[data-icon='spinner']").first
    expect(spinner.locator(":scope > span.icon-glyph")).to_have_css("display", "none")
    spinner_presentation = spinner.evaluate(
        """
        (element) => {
          const style = getComputedStyle(element, "::before");
          return { content: style.content, boxShadow: style.boxShadow };
        }
        """
    )
    assert spinner_presentation["content"] == '""'
    assert spinner_presentation["boxShadow"] != "none"

    right_column_icons = user.page.locator(
        "span.icon[data-icon='user'], "
        "span.icon[data-icon='star.home'], "
        "span.icon[data-icon='directory'], "
        "span.icon[data-icon='manual']"
    )
    geometry = right_column_icons.evaluate_all(
        """
        (elements) => elements.map((element) => {
          const iconBox = element.getBoundingClientRect();
          const controlBox = element.closest("a, button").getBoundingClientRect();
          return {
            iconWidth: iconBox.width,
            iconHeight: iconBox.height,
            controlHeight: controlBox.height,
          };
        })
        """
    )
    assert len(geometry) == 4
    assert len({round(item["iconWidth"], 2) for item in geometry}) == 1
    assert len({round(item["iconHeight"], 2) for item in geometry}) == 1
    assert len({round(item["controlHeight"], 2) for item in geometry}) == 1

    assert user.page.evaluate(
        """
        async () => {
          const faces = await document.fonts.load(
            '400 24px "Material Symbols Rounded"',
            "draft",
          );
          return faces.length === 1 && faces[0].status === "loaded";
        }
        """
    )


# @features home
# @dimensions directory-list
@pytest.mark.parallel_safe(
    reason="the inline directory toggle creates no shared state"
)
def test_directory_list(get_user):
    """
    Verify a home toggle opens and closes its widget through client-side state.

    Directory is inline in the home template, so this exercises the shared
    lp-show render path without depending on network timing.
    """
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    directory_list = user.locate(home.DIRECTORY_LIST)
    directory_toggle = user.locate(home.DIRECTORY_LIST_TOGGLE)

    expect(directory_list).to_be_hidden()

    directory_toggle.click()
    expect(directory_list).to_be_visible()

    directory_toggle.click()
    expect(directory_list).to_be_hidden()


# @features home
# @dimensions prefetch task-list task-count
@pytest.mark.parallel_safe(
    reason="the read-only prefetch story asserts no collection cardinality"
)
def test_tasks_prefetch(get_user):
    """
    Verify tasks are prefetched on page load.

    The tasks component has lp-prefetch attribute causing it to load
    immediately rather than waiting for user interaction. This ensures
    task count replaces the initial loading marker on page load.

    Verifies:
        - src/script/views/home.mjs: Prefetch initialization
        - lagniappe/web/templates/home/tasks.html: lp-prefetch attribute
        - Task list shell is replaced after prefetch GET /l/get/tasks
        - Task count element is rendered

    Framework note:
        Prefetch swaps the server-rendered list in for the initial shell.
    """
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    task_list = user.locate(home.TASK_LIST)
    expect(task_list).to_be_attached()
    assert List(task_list).is_loaded

    task_count = user.locate(home.TASK_COUNT)
    expect(task_count).to_be_attached()
    expect(task_count).to_have_text(re.compile(r"\d+"))
    expect(user.locate(home.TASK_LIST_TOGGLE)).not_to_be_disabled()


# @features home
# @dimensions lazy-load project-list category-list loading-indicator
def test_model_lists_load_on_toggle(get_user):
    """Verify project and category home lists load through their /l/get branches on demand."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)
    category = Categories.test_create_category_manual_mode.get(user)
    home = user.go(SitePages.HOME)

    expect(user.locate(home.PROJECT_LIST)).to_be_attached()
    expect(user.locate(home.CATEGORY_LIST)).to_be_attached()
    expect(user.locate(home.PROJECT_LIST)).not_to_have_attribute("loaded", "")
    expect(user.locate(home.CATEGORY_LIST)).not_to_have_attribute("loaded", "")
    expect(user.locate("[data-role='project-count']")).to_have_count(0)
    expect(user.locate("[data-role='category-count']")).to_have_count(0)
    expect(user.locate(home.PROJECT_LOADING)).to_be_hidden()
    expect(user.locate(home.CATEGORY_LOADING)).to_be_hidden()

    assert home.project_list.is_loaded
    assert home.category_list.is_loaded
    expect(home.project_list.get_item(project)).to_be_visible()
    expect(home.category_list.get_item(category)).to_be_visible()
    expect(user.locate("[data-role='project-count']")).to_have_count(0)
    expect(user.locate("[data-role='category-count']")).to_have_count(0)
    expect(user.locate(home.PROJECT_LIST_TOGGLE)).not_to_have_attribute(
        "data-loading", "true"
    )
    expect(user.locate(home.CATEGORY_LIST_TOGGLE)).not_to_have_attribute(
        "data-loading", "true"
    )


# @features home
# @dimensions load mobile layout
@pytest.mark.parallel_safe(
    reason="the responsive form smoke story creates no shared state"
)
def test_home_mobile_dashboard_smoke(get_user):
    """Smoke-check the homepage dashboard and a representative form at mobile width."""
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)
    user.mobile = True

    expect(user.page.locator("[lp-search] input")).to_be_visible()
    expect(user.locate(home.CREATE_PROJECT_TOGGLE)).to_be_visible()

    user.locate(home.CREATE_PROJECT_TOGGLE).click()
    form = user.locate(home.CREATE_PROJECT_FORM)
    expect(form).to_be_visible()
    expect(form.get_by_role("button", name="Create Project")).to_be_visible()
    expect(user.locate(home.DIRECTORY_LIST_TOGGLE)).to_be_visible()

    assert user.page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )


# @features notes
# @dimensions body-create photo-picker preview remove combined-input
# @template notes.html::composer
@pytest.mark.parallel_safe(
    reason="the composer draft remains inside its isolated browser context"
)
def test_create_note_composer_keeps_text_and_photo_from_home(get_user):
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    user.locate(home.CREATE_NOTE_TOGGLE).click()
    form = user.locate(home.CREATE_NOTE_FORM)
    expect(form).to_be_visible()
    expect(form.locator("[data-role='title'] .icon")).not_to_be_attached()

    add_photo = form.locator("[data-action='add-photo']")
    expect(add_photo.locator("[data-icon='image']")).to_be_visible()
    expect(add_photo).not_to_have_class(re.compile(r".*\bunderline\b.*"))

    everyone = form.locator("label:has(input[value='everyone'])")
    expect(everyone.locator("[data-icon='group']")).to_be_visible()
    expect(everyone).not_to_have_class(re.compile(r".*\bborder\b.*"))

    body = form.locator("textarea[name='body']")
    expect(body).to_be_visible()
    body.fill("Draft body note")

    with user.page.expect_file_chooser() as chooser_info:
        form.locator("[data-action='add-photo']").click()
    chooser_info.value.set_files(_TestFile("editor_test_image.jpeg").path)
    expect(body).to_be_visible()
    expect(body).to_have_value("Draft body note")
    expect(form.locator("[data-role='photo-selection']")).to_have_attribute(
        "data-visible", "true"
    )
    expect(form.locator("[data-role='photo-preview']")).to_be_visible()

    form.locator("[data-action='remove-photo']").click()
    expect(body).to_be_visible()
    assert form.locator("input[name='note-file']").input_value() == ""
    expect(form.locator("[data-role='photo-selection']")).to_have_attribute(
        "data-visible", "false"
    )
