import pytest
import requests
from playwright.sync_api import expect

from testing.definitions import Categories, Pages, SitePages, Users
from testing.elements import HeaderSearch, Table
from testing.resources.category import Category
from testing.utility.network import (
    assert_lagniappe_error_response,
    manual_mutation_headers,
)

pytestmark = pytest.mark.e2e


def test_page_acl_user_sees_one_page_on_category_index_home_and_search(get_admin, get_user):
    owner = get_admin()
    category = Categories.acl_two_pages_lab.get(owner)
    visible = Pages.acl_lab_visible.get(owner)
    hidden = Pages.acl_lab_hidden.get(owner)

    subject = get_user(Users.page_acl_one_visible)
    category.user = subject
    subject.navigate(category.url)

    table = Table(subject)
    expect(table.get_row(visible.definition.name)).to_be_visible()
    expect(table.get_row(hidden.definition.name)).not_to_be_attached()

    home = subject.go(SitePages.HOME)
    category_list = home.category_list
    expect(category_list.get_item(category)).to_be_visible()

    search = HeaderSearch(subject)
    search.verify_entity_not_in_results(category)
    search.verify_entity_in_results(visible)
    search.verify_entity_not_in_results(hidden)


def test_category_create_scoped_to_one_category(get_admin, get_user):
    owner = get_admin()
    allowed_cat = Categories.acl_create_allowed.get(owner)
    denied_cat = Categories.acl_create_denied.get(owner)

    subject = get_user(Users.single_category_create)

    subject.go(allowed_cat)
    expect(subject.locate(Category.CREATE_PAGE_TOGGLE)).to_be_visible()
    expect(subject.locate(Category.FILTER_BAR_WIDGET)).to_be_visible()

    subject.go(denied_cat)
    expect(subject.locate(Category.CREATE_PAGE_TOGGLE)).not_to_be_attached()
    expect(subject.locate(Category.FILTER_BAR_WIDGET)).to_be_visible()


# @template categories/index.html::view_header
# @template categories/index.html::view
def test_category_viewer_opens_readonly_settings(get_admin, get_user):
    owner = get_admin()
    category = Categories.test_category_readonly_settings.get(owner)
    form = category.definition.form.get(owner)
    description = "Readonly category settings description."
    if category.entity.description != description:
        category.entity.description = description
        category.entity.save()
    subject = get_user(Users.models_forms_view_only)
    subject.go(category)

    expect(subject.locate("[lp-view]")).to_have_attribute("data-can-edit", "false")
    expect(subject.locate(Category.CATEGORY_TITLE)).to_contain_text(
        category.definition.name
    )
    description_el = subject.locate(Category.CATEGORY_DESCRIPTION)
    expect(description_el).to_have_attribute("data-editable", "false")
    expect(description_el).to_contain_text(description)
    expect(subject.locate(Category.CREATE_PAGE_TOGGLE)).not_to_be_attached()
    expect(subject.locate("#tools")).not_to_be_attached()

    menu = category.open_actions_menu()
    expect(menu.locator("[data-category-action='rename']")).not_to_be_attached()
    expect(menu.locator("[data-category-action='description']")).not_to_be_attached()
    expect(menu.locator("[data-category-action='default-form']")).not_to_be_attached()
    expect(menu.locator("button[lp-show='table:TableEditor']")).not_to_be_attached()

    expect(subject.locate(Category.FILTER_BAR_WIDGET)).to_be_visible()
    expect(
        subject.locate(f"{Category.FILTER_BAR_WIDGET} button[data-role='save-filter']")
    ).not_to_be_attached()

    cookies = {
        cookie["name"]: cookie["value"]
        for cookie in subject.page.context.cookies()
    }
    forbidden_description = "Forbidden category settings description."
    response = requests.put(
        f"{category.url}/update",
        data={
            "name": category.entity.name,
            "description": forbidden_description,
            "form": form.key,
        },
        cookies=cookies,
        headers=manual_mutation_headers(
            subject.page.url,
            subject.locate("#token").input_value(),
        ),
        allow_redirects=False,
        timeout=10,
    )

    assert_lagniappe_error_response(response, status=403)

    subject.go(category)
    expect(subject.locate(Category.CATEGORY_DESCRIPTION)).to_contain_text(description)
