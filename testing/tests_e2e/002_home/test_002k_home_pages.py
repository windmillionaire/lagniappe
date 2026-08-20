"""
Tests for the page widget on the home page.

The home page exposes a lightweight page list for users who can view pages and
a small create form for users who can create them.
"""

import re

from playwright.sync_api import expect
import pytest

from testing.definitions import Categories, Pages, SitePages, Users
from testing.elements import FormElements, Link, List, Select, SpinnerButtons

pytestmark = pytest.mark.e2e


# @features home pages
# @dimensions list load
# @template home/pages.html::list
# @template home/pages.html::page
def test_home_page_list_loads_recent_pages(get_user):
    user = get_user(Users.OWNER)
    existing_page = Pages.test_create_page.get(user)
    home = user.go(SitePages.HOME)

    page_list = home.page_list
    page_item = page_list.get_item(existing_page)

    expect(page_item).to_be_visible()


# @features home pages
# @dimensions create category-select default-category
# @template home/pages.html::create
# @template home/pages.html::page
def test_create_page_from_home(get_user):
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)
    create_form = home.create_page_form()
    page_name = "Home Created Page"

    expect(create_form.locator("[data-role='categories']")).to_be_visible()
    create_form.locator(FormElements.NAME).fill(page_name)
    create_form.locator(FormElements.DESCRIPTION).fill(
        "Created from the home page."
    )

    with user.page.expect_response("**/pages/create") as response_info:
        SpinnerButtons.CREATE.click(create_form)

    page_key = home.entity_key_from_response(response_info.value)
    page_list = List(user.locate(home.PAGE_LIST))
    page_item = page_list.new_item(page_name, flash=False)

    expect(page_item).to_have_attribute("data-key", page_key)
    Link(page_item).click()
    expect(user.page).to_have_title(re.compile(page_name))


# @pair permissions:category-edit
# @pair combobox:permission-filter
# @template home/home.html::create
# @template home/pages.html::create
def test_home_page_create_visible_for_category_editor(get_user):
    """Home page creation lists editable categories, not view-only categories."""
    owner = get_user(Users.OWNER)
    allowed = Categories.acl_create_allowed.get(owner)
    denied = Categories.acl_create_denied.get(owner)

    user = get_user(Users.single_category_create)
    home = user.go(SitePages.HOME)

    expect(user.locate(home.CREATE_PAGE_TOGGLE)).to_be_visible()
    expect(user.locate(home.CREATE_PROJECT_TOGGLE)).not_to_be_attached()
    expect(user.locate(home.CREATE_CATEGORY_TOGGLE)).not_to_be_attached()

    create_form = home.create_page_form()
    category_select = Select(create_form.locator("[data-role='categories']"))
    with user.page.expect_response(
        lambda response: "/l/search-index/category" in response.url
        and "permission=edit" in response.url
    ):
        category_select.fill("ACL Create")

    panel = category_select.panel
    expect(panel).to_be_visible()
    expect(
        panel.get_by_role("option", name=allowed.definition.name, exact=True)
    ).to_be_visible()
    expect(
        panel.get_by_role("option", name=denied.definition.name, exact=True)
    ).not_to_be_attached()
