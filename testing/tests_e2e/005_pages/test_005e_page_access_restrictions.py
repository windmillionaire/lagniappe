"""
Tests for page-level access restrictions.

Verified against:
- lagniappe/web/templates/pages/info.html
- lagniappe/web/templates/pages/restrictions.html
- lagniappe/web/routes/pages/main.py
- src/script/widgets/pagePermissions.mjs
"""

import re

import pytest
from playwright.sync_api import expect

from testing.definitions import Categories, Groups, Pages, Users
from testing.elements import Select, Table, Tabs
from testing.resources import Page

pytestmark = pytest.mark.e2e


def _open_page_permissions(user, page):
    user.go(page)
    Tabs(user).info
    toggle = user.locate(Page.PAGE_PERMISSIONS_TOGGLE)
    expect(toggle).to_be_visible()
    toggle.click()

    permissions = user.locate(Page.PAGE_PERMISSIONS_FORM)
    expect(permissions).to_be_visible()
    return permissions


def _restrict_page_to_owner(user, page):
    permissions = _open_page_permissions(user, page)
    owner_checkbox = permissions.locator(Page.PAGE_RESTRICT_OWNER)
    expect(owner_checkbox).to_be_visible()

    if not owner_checkbox.is_checked():
        with user.page.expect_response("**/view-access"):
            owner_checkbox.check()

    expect(owner_checkbox).to_be_checked()
    return permissions


def _restrict_page_to_group(user, page, group):
    permissions = _open_page_permissions(user, page)
    group_list = permissions.locator(Page.PAGE_RESTRICTED_GROUP_LIST)

    if group.definition.name not in permissions.inner_text():
        group_input = permissions.locator(Page.PAGE_RESTRICT_GROUP_INPUT)
        expect(group_input).to_be_visible()
        expect(group_input).to_have_attribute("data-combobox-id", re.compile(".+"))
        with user.page.expect_response("**/view-access"):
            Select(group_input).select_by_key(
                group.key,
                query=group.definition.name,
            )

    expect(group_list.filter(has_text=group.definition.name)).to_be_visible()
    return permissions


# @features pages
# @dimensions access-restrictions owner-restricted
def test_owner_restricted_page_is_hidden_from_model_viewer(
    get_user, browser_failures
):
    """The owner marks a page owner-only; a normal model viewer can no longer open it."""
    owner = get_user(Users.OWNER)
    page = Pages.test_owner_restricted_page.get(owner)

    _restrict_page_to_owner(owner, page)

    viewer = get_user(Users.general_models_view_only)
    with browser_failures.expect_http_error(viewer, status=403, path=page.url):
        viewer.navigate(page.url)
        expect(viewer.page).to_have_title("Error 403")


# @features pages
# @dimensions access-restrictions group-restricted
def test_group_restricted_page_opens_for_member_only(get_user, browser_failures):
    """The owner restricts a page to a group; members keep access and others lose it."""
    owner = get_user(Users.OWNER)
    page = Pages.test_group_restricted_page.get(owner)
    group = Groups.general_models_view_only.get(owner)

    _restrict_page_to_group(owner, page, group)

    member = get_user(Users.general_models_view_only)
    member.go(page)
    expect(member.locate(Page.PAGE_TITLE)).to_contain_text(page.definition.name)

    outsider = get_user(Users.admin)
    with browser_failures.expect_http_error(outsider, status=403, path=page.url):
        outsider.navigate(page.url)
        expect(outsider.page).to_have_title("Error 403")


# @features pages
# @dimensions access-restrictions index-filter
def test_restricted_page_is_not_listed_for_outsider_on_category_index(get_user):
    """Category tables should not leak pages the current user cannot open."""
    owner = get_user(Users.OWNER)
    page = Pages.test_group_restricted_page.get(owner)
    category = Categories.test_page_access_restrictions.get(owner)
    group = Groups.general_models_view_only.get(owner)
    _restrict_page_to_group(owner, page, group)

    member = get_user(Users.general_models_view_only)
    member.go(category)
    member_table = Table(member)
    expect(member_table.get_row(page.definition.name)).to_be_visible()

    outsider = get_user(Users.admin)
    outsider.go(category)
    outsider_table = Table(outsider)
    # Possible product bug: PageIndex currently loads category pages by query
    # restrictions, then templates render every row without checking page.allowed(VIEW).
    expect(outsider_table.get_row(page.definition.name)).not_to_be_attached()
