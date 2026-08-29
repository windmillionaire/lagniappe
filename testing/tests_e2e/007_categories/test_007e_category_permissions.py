import re

import pytest
import requests
from playwright.sync_api import expect

from testing.definitions import Categories, Pages, SitePages, Users
from testing.elements import FormElements, HeaderSearch, Table, Tools
from testing.resources.category import Category
from testing.utility.network import (
    assert_lagniappe_error_response,
    manual_mutation_headers,
)

pytestmark = pytest.mark.e2e


# @matrix categories : index-filter permission-gates
def test_page_acl_user_sees_one_page_on_category_index_home_and_search(get_user):
    owner = get_user(Users.OWNER)
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


# @matrix categories : create-control permission-gates
def test_category_create_scoped_to_one_category(get_user):
    owner = get_user(Users.OWNER)
    allowed_cat = Categories.acl_create_allowed.get(owner)
    denied_cat = Categories.acl_create_denied.get(owner)

    subject = get_user(Users.single_category_create)

    subject.go(allowed_cat)
    tools_allowed = Tools(subject)
    tools_allowed.open()

    expect(tools_allowed.locate(Category.CREATE_PAGE_TOGGLE)).to_be_visible()
    expect(tools_allowed.locate(Category.GENERATE_PAGES_TOGGLE)).to_be_visible()
    expect(tools_allowed.locate(Category.CATEGORY_INFO_TOGGLE)).to_be_visible()
    expect(tools_allowed.locate(Category.CATEGORY_FILTERS_TOGGLE)).to_be_visible()

    subject.go(denied_cat)
    tools_denied = Tools(subject)
    tools_denied.open()

    expect(tools_denied.locate(Category.CREATE_PAGE_TOGGLE)).not_to_be_attached()
    expect(tools_denied.locate(Category.GENERATE_PAGES_TOGGLE)).not_to_be_attached()
    expect(tools_denied.locate(Category.CATEGORY_INFO_TOGGLE)).to_be_visible()
    expect(tools_denied.locate(Category.CATEGORY_FILTERS_TOGGLE)).to_be_visible()


# @matrix categories : default-form info-form labels permission-gates readonly
# @template categories/index.html::tools_section
# @template categories/tools.html::category_info
def test_category_viewer_opens_readonly_settings(get_user):
    owner = get_user(Users.OWNER)
    category = Categories.test_category_readonly_settings.get(owner)
    form = category.definition.form.get(owner)
    description = "Readonly category settings description."
    if category.entity.description != description:
        category.entity.description = description
        category.entity.save()
    subject = get_user(Users.models_forms_view_only)
    subject.go(category)

    tools = Tools(subject)
    tools.open()

    settings = tools.locate(Category.CATEGORY_INFO_WIDGET)
    expect(settings).to_be_visible()
    expect(settings).to_have_attribute("data-readonly", "true")
    name_field = settings.locator("#name")
    description_field = settings.locator("#description")
    expect(name_field).to_contain_text("Category Name")
    expect(name_field).to_contain_text(category.definition.name)
    expect(description_field).to_contain_text("Category Description")
    expect(description_field).to_contain_text(description)
    expect(settings.locator(FormElements.NAME)).not_to_be_attached()
    expect(settings.locator(FormElements.DESCRIPTION)).not_to_be_attached()
    form_select = settings.locator("[data-role='form-select']")
    expect(form_select).to_be_visible()
    form_link = form_select.get_by_role("link", name=form.definition.name)
    expect(form_link).to_be_visible()
    expect(form_link).to_have_attribute("href", re.compile(r"/forms/"))
    expect(form_select.locator("[data-action='select-form']")).not_to_be_attached()
    expect(form_select.locator("[data-combobox-id]")).not_to_be_attached()
    expect(settings.locator("[data-role='clear']")).not_to_be_attached()
    expect(settings.locator("[data-role='attributes']")).not_to_be_attached()
    expect(settings.locator("button[type='submit']")).not_to_be_attached()

    expect(tools.locate(Category.CREATE_PAGE_TOGGLE)).not_to_be_attached()
    expect(tools.locate(Category.GENERATE_PAGES_TOGGLE)).not_to_be_attached()
    expect(tools.locate(Category.CATEGORY_INFO_TOGGLE)).to_be_visible()
    expect(tools.locate(Category.CATEGORY_FILTERS_TOGGLE)).to_be_visible()

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
            **{attribute.name: "true" for attribute in category.entity.attributes},
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
    refreshed_tools = Tools(subject)
    refreshed_tools.open()
    expect(
        refreshed_tools.locate(Category.CATEGORY_INFO_WIDGET).locator(
            "#description"
        )
    ).to_contain_text(description)
