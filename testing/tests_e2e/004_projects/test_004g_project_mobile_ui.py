"""
Tests for project mobile UI functionality.

These tests cover the current mobile navigation contract for project pages:
- Mobile nav appears below the small-screen breakpoint
- The flipper reveals the section toggles
- The model tasks card becomes a mobile-only section
- Info/document/filters remain tabs within the main tabs card
- Selected section/tab survives resize and reload
"""

from playwright.sync_api import expect

from testing.definitions import ModelTasks, Projects, Users
from testing.elements import FormElements, MobileNav, Tabs
from testing.resources import Project


# @features entity-layout
# @dimensions project-mobile nav visibility
# @template projects/project.html::toggles
def test_mobile_nav_visibility_changes_with_viewport(get_user):
    """Mobile nav replaces desktop tab nav below the mobile breakpoint."""
    user = get_user(Users.OWNER)
    project = user.go(Projects.test_create_project_manual_mode)

    expect(user.locate(project.MOBILE_NAV)).to_be_hidden()
    expect(user.locate(project.DESKTOP_TAB_NAV)).to_be_visible()

    user.mobile = True

    mobile_nav = MobileNav(user)
    expect(mobile_nav.nav).to_be_visible()
    expect(user.locate(project.DESKTOP_TAB_NAV)).to_be_hidden()
    model_symbol = user.page.locator(
        "button[lp-show='model-tasks:ModelTaskList'] span.icon[data-icon='model']"
    )
    expect(model_symbol).to_have_text("automation")
    expect(model_symbol).to_have_attribute("aria-hidden", "true")
    assert mobile_nav.get_section_title() == "Info"


# @features entity-layout
# @dimensions project-mobile flipper
def test_mobile_flipper_reveals_section_toggles(get_user):
    """The mobile flipper reveals hidden section toggles and tracks flipped state."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)
    user.go(project)
    mobile_nav = project.mobile_nav

    document_toggle = user.locate(Tabs.DOCUMENT_TOGGLE_MOBILE)
    expect(document_toggle).to_be_hidden()
    assert mobile_nav.is_tab_slider_open() is False

    mobile_nav.open_tab_slider()

    expect(document_toggle).to_be_visible()
    assert mobile_nav.is_tab_slider_open() is True

    mobile_nav.close_tab_slider()
    expect(document_toggle).to_be_hidden()
    assert mobile_nav.is_tab_slider_open() is False


# @features entity-layout
# @dimensions project-mobile section-switch
def test_mobile_section_switching_updates_visible_cards_and_title(get_user):
    """Mobile nav switches between model tasks card and tabs-backed sections."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)
    user.go(project)
    mobile_nav = project.mobile_nav

    mobile_nav.select_section("model-tasks", "ModelTaskList")
    assert mobile_nav.get_section_title() == "Model Tasks"

    mobile_nav.select_section("document")
    expect(user.locate(Tabs.DOCUMENT_TAB)).to_be_visible()
    assert mobile_nav.get_section_title() == "Document"

    mobile_nav.select_section("filters")
    expect(user.locate(project.FILTERS_TAB)).to_be_visible()
    assert mobile_nav.get_section_title() == "Task Filters"


# @features entity-layout
# @dimensions project-mobile secondary-create
def test_mobile_create_model_form_opens_from_model_tasks_section(get_user):
    """The mobile layout still allows creating model tasks from the models section."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)
    user.go(project)

    project.mobile_nav.select_section("model-tasks", "ModelTaskList")

    create_button = user.locate(Project.MOBILE_CREATE_MODEL_TASK_BUTTON)
    expect(create_button).to_be_visible()
    create_button.click()

    create_form = user.locate(Project.CREATE_MODEL_WIDGET)
    expect(create_form).to_be_visible()
    expect(create_form.locator(FormElements.NAME)).to_be_visible()


# @features entity-layout
# @dimensions project-mobile secondary-info
def test_mobile_model_task_info_still_opens_in_models_section(get_user):
    """Existing model task rows remain editable after switching to the mobile models section."""
    user = get_user(Users.OWNER)
    model_task = ModelTasks.test_create_model_task.get(user)
    user.go(model_task.project)

    user.mobile = True
    mobile_nav = MobileNav(user)
    expect(mobile_nav.nav).to_be_visible()
    mobile_nav.select_section("model-tasks", "ModelTaskList")

    info_form = model_task.open_info()
    expect(info_form).to_be_visible()
    model_task.close_info()
    expect(model_task.info_form).to_be_hidden()


# @features entity-layout
# @dimensions project-mobile resize secondary-card
def test_resize_from_mobile_models_to_desktop_restores_dual_card_layout(get_user):
    """Desktop resize restores the model tasks card beside the tabs card."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)
    user.go(project)

    project.mobile_nav.select_section("model-tasks", "ModelTaskList")
    expect(project.model_tasks_card).to_be_visible()

    user.mobile = False

    expect(user.locate(project.MOBILE_NAV)).to_be_hidden()
    expect(project.model_tasks_card).to_be_visible()
    tabs_card = user.locate(project.TABS_CARD)
    expect(tabs_card).to_be_visible()
    expect(user.locate(Tabs.INFO_TAB)).to_be_visible()


# @features entity-layout
# @dimensions project-mobile resize persistence
def test_resize_from_mobile_filters_to_desktop_preserves_selected_tab(get_user):
    """Resizing back to desktop preserves the currently selected tabs-backed section."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)
    user.go(project)

    project.mobile_nav.select_section("filters")
    expect(user.locate(project.FILTERS_TAB)).to_be_visible()

    user.mobile = False

    expect(user.locate(project.TABS_CARD)).to_be_visible()
    expect(user.locate(project.FILTERS_TAB)).to_be_visible()


# @features entity-layout
# @dimensions project-mobile reload persistence
def test_mobile_selected_section_persists_after_reload(get_user):
    """The last selected mobile section is restored on reload via localStorage."""
    user = get_user(Users.OWNER)
    project = Projects.test_create_project_manual_mode.get(user)
    user.go(project)

    project.mobile_nav.select_section("model-tasks", "ModelTaskList")
    user.page.wait_for_function(
        "(key) => localStorage.getItem(key) === 'model-tasks'",
        arg=f"{project.entity.hash}-active",
    )
    user.page.reload(wait_until="load")

    expect(user.locate(project.MOBILE_NAV)).to_be_visible()
    expect(project.model_tasks_card).to_be_visible()
    assert project.mobile_nav.get_section_title() == "Model Tasks"
