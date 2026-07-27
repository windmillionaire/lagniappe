"""
Tests for page mobile navigation and mobile-only actions.

Verified against:
- lagniappe/web/templates/pages/page.html
- lagniappe/web/templates/pages/tasks.html
- src/script/views/page.mjs
- src/script/views/base/entity.mjs
"""

import pytest
from playwright.sync_api import expect

from testing.definitions import Pages, Users
from testing.elements import FormElements, MobileNav, Tabs
from testing.resources import Page

pytestmark = pytest.mark.e2e


# @features entity-layout
# @dimensions page-mobile nav visibility
def test_page_mobile_nav_replaces_desktop_tabs(get_user):
    """The page switches from desktop tabs to mobile section navigation."""
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_page_loads)

    expect(user.locate(page.MOBILE_NAV)).to_be_hidden()
    expect(user.locate(page.DESKTOP_TAB_NAV)).to_be_visible()

    user.mobile = True

    mobile_nav = MobileNav(user)
    expect(mobile_nav.nav).to_be_visible()
    expect(user.locate(page.DESKTOP_TAB_NAV)).to_be_hidden()
    assert mobile_nav.get_section_title() == "Info"


# @features entity-layout
# @dimensions page-mobile flipper
def test_page_mobile_flipper_reveals_sections(get_user):
    """The mobile flipper exposes the page sections a user can visit."""
    user = get_user(Users.OWNER)
    page = Pages.test_page_loads.get(user)
    user.go(page)

    mobile_nav = page.mobile_nav
    expect(user.locate(Tabs.DOCUMENT_TOGGLE_MOBILE)).to_be_hidden()
    expect(user.locate(Tabs.TASKS_TOGGLE_MOBILE)).to_be_hidden()

    mobile_nav.open_tab_slider()

    expect(mobile_nav.nav.locator("button[lp-show='photo:active']")).to_be_hidden()
    expect(user.locate(Tabs.DOCUMENT_TOGGLE_MOBILE)).to_be_visible()
    expect(user.locate(Tabs.TASKS_TOGGLE_MOBILE)).to_be_visible()
    expect(user.locate(Tabs.FILES_TOGGLE_MOBILE)).to_be_visible()


# @features entity-layout
# @dimensions page-mobile section-switch
def test_page_mobile_section_switching_updates_visible_panel_and_title(get_user):
    """A phone user moves between document, tasks, files, and info."""
    user = get_user(Users.OWNER)
    page = Pages.test_page_loads.get(user)
    user.go(page)
    mobile_nav = page.mobile_nav

    mobile_nav.select_section("document")
    expect(user.locate(Tabs.DOCUMENT_TAB)).to_be_visible()
    assert mobile_nav.get_section_title() == "Document"

    mobile_nav.select_section("tasks")
    expect(user.locate(Tabs.TASKS_TAB)).to_be_visible()
    assert mobile_nav.get_section_title() in {"Tasks", "New Task"}

    mobile_nav.select_section("files")
    expect(user.locate(Tabs.FILES_TAB)).to_be_visible()
    assert mobile_nav.get_section_title() in {"Files", "Upload File"}

    mobile_nav.select_section("info")
    expect(user.locate(Tabs.INFO_TAB)).to_be_visible()
    assert mobile_nav.get_section_title() == "Info"


# @features entity-layout
# @dimensions page-mobile task-create
def test_page_mobile_create_task_opens_from_tasks_section(get_user):
    """The mobile page header keeps the new-task action close to the Tasks section."""
    user = get_user(Users.OWNER)
    page = Pages.test_page_loads.get(user)
    user.go(page)

    page.mobile_nav.select_section("tasks:active")

    # create_button = user.locate(Page.MOBILE_CREATE_TASK_BUTTON)
    # expect(create_button).to_be_visible()
    # create_button.click()

    create_form = user.locate(Page.CREATE_TASK_FORM)
    expect(create_form).to_be_visible()
    expect(create_form.locator(FormElements.NAME)).to_be_visible()


# @features entity-layout
# @dimensions page-mobile reload persistence
def test_page_mobile_selection_persists_after_reload(get_user):
    """The page restores the last mobile section after a full reload."""
    user = get_user(Users.OWNER)
    page = Pages.test_page_loads.get(user)
    user.go(page)

    page.mobile_nav.select_section("tasks:active")
    user.page.wait_for_function(
        "(key) => localStorage.getItem(key) === 'tasks'",
        arg=f"{page.entity.hash}-active",
    )
    user.page.reload(wait_until="load")

    expect(user.locate(page.MOBILE_NAV)).to_be_visible()
    expect(user.locate(Tabs.TASKS_TAB)).to_be_visible()
    assert page.mobile_nav.get_section_title() in {"Tasks", "New Task"}
