import pytest
from playwright.sync_api import expect

from testing.definitions import Pages, Users
from testing.elements import FormElements, MobileNav, Tabs
from testing.resources import Page
from testing.utility import scoped_browser_route

pytestmark = pytest.mark.e2e


def _empty_main_script(route):
    route.fulfill(status=200, content_type="text/javascript", body="")


# @template pages/page.html::main
# @style entity.tabIcon
def test_page_mobile_desktop_tabs_start_hidden_before_ui_initializes(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_page_loads.get(user)
    page.user = user
    user.page.set_viewport_size({"width": 375, "height": 667})

    with scoped_browser_route(user.page, "**/script.js?*", _empty_main_script):
        response = user.page.goto(page.url, wait_until="load")

    assert response.ok
    expect(user.locate("[lp-view]")).not_to_have_attribute("initialized", "")
    tabs_card = user.locate(page.TABS_CARD)
    expect(tabs_card).to_have_attribute("data-visible", "false")
    expect(tabs_card).to_be_hidden()
    expect(user.locate(page.DESKTOP_TAB_NAV)).to_be_hidden()
    expect(user.locate(page.MOBILE_NAV)).to_be_hidden()


# @features entity-layout
# @dimensions page-mobile nav visibility
def test_page_mobile_nav_replaces_desktop_tabs(get_user):
    user = get_user(Users.OWNER)
    page = user.go(Pages.test_page_loads)

    expect(user.locate(page.MOBILE_NAV)).to_be_hidden()
    expect(user.locate(page.TABS_CARD)).to_be_visible()
    expect(user.locate(page.DESKTOP_TAB_NAV)).to_be_visible()

    user.mobile = True

    mobile_nav = MobileNav(user)
    expect(mobile_nav.nav).to_be_visible()
    expect(user.locate(page.DESKTOP_TAB_NAV)).to_be_hidden()
    assert mobile_nav.get_section_title() == "Info"


# @features entity-layout
# @dimensions page-mobile flipper
def test_page_mobile_flipper_reveals_sections(get_user):
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
    user = get_user(Users.OWNER)
    page = Pages.test_page_loads.get(user)
    user.go(page)

    page.mobile_nav.select_section("tasks:active")

    create_form = user.locate(Page.CREATE_TASK_FORM)
    expect(create_form).to_be_visible()
    expect(create_form.locator(FormElements.NAME)).to_be_visible()


# @features entity-layout
# @dimensions page-mobile reload persistence
def test_page_mobile_selection_persists_after_reload(get_user):
    user = get_user(Users.OWNER)
    page = Pages.test_page_loads.get(user)
    user.go(page)

    page.mobile_nav.select_section("tasks:active")
    expect(user.locate(Tabs.TASKS_TAB)).to_be_visible()
    assert page.mobile_nav.get_section_title() in {"Tasks", "New Task"}

    page = page.reload()

    expect(user.locate(page.MOBILE_NAV)).to_be_visible()
    expect(user.locate(Tabs.TASKS_TAB)).to_be_visible()
    assert page.mobile_nav.get_section_title() in {"Tasks", "New Task"}
