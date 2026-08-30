import re

import pytest
from playwright.sync_api import expect

from testing.definitions import Categories, Pages, Users
from testing.elements import Dropdown, MobileTableControls
from testing.resources.category import Category

pytestmark = pytest.mark.e2e


# @matrix table-controls : columns mobile-controls
def test_category_mobile_controls_open_with_page_columns(get_user):
    user = get_user(Users.OWNER)
    Pages.test_create_page.get(user)
    user.go(Categories.test_create_page)

    controls = MobileTableControls(user)
    expect(controls.panel).to_be_hidden()

    user.mobile = True
    controls = MobileTableControls(user)
    controls.open()

    expect(controls.row("image")).to_be_visible()
    expect(controls.row("name")).to_be_visible()
    expect(controls.row("form")).to_be_visible()
    expect(controls.row("description")).to_be_visible()
    expect(controls.row("modified")).to_be_visible()


# @template categories/index.html::view_header
# @template categories/index.html::view
def test_category_viewer_mobile_controls_do_not_require_edit_permission(get_user):
    owner = get_user(Users.OWNER)
    category = Categories.acl_create_denied.get(owner)

    subject = get_user(Users.single_category_create)
    subject.go(category)
    subject.mobile = True

    controls = MobileTableControls(subject)
    expect(controls.panel).to_be_hidden()
    controls.open()

    expect(controls.row("name")).to_be_visible()
    expect(controls.row("modified")).to_be_visible()


# @matrix table-controls : column-visibility mobile-controls
def test_category_mobile_visibility_toggle_hides_column(get_user):
    user = get_user(Users.OWNER)
    Pages.test_create_page.get(user)
    user.go(Categories.test_create_page)
    user.mobile = True

    controls = MobileTableControls(user)
    controls.open()
    modified_toggle = controls.toggle_column("modified")

    expect(modified_toggle).to_have_attribute("data-active", "false")
    expect(
        user.locate(Category.COLUMN_HEADER.format(column="modified"))
    ).to_be_hidden()
    expect(user.locate("#table td[data-column='modified']:visible")).to_have_count(0)


# @matrix table-controls : mobile-controls sorting
def test_category_mobile_filter_button_opens_sorting_panel(get_user):
    user = get_user(Users.OWNER)
    Pages.test_create_page.get(user)
    user.go(Categories.test_create_page)
    user.mobile = True

    controls = MobileTableControls(user)
    controls.open()
    controls.filter_button("name").click()

    sorting = user.locate("#mobile-controls [data-sorts='name']")
    expect(sorting).to_be_visible()
    expect(
        sorting.locator('input[type="radio"][name="name"][value="asc"]')
    ).to_be_visible()


# @matrix table-controls : form-columns mobile-controls sorting
def test_category_mobile_controls_handle_form_columns(get_user):
    user = get_user(Users.OWNER)
    Pages.test_category_filter_match_page.get(user)
    user.go(Categories.test_category_filter_pages)
    user.mobile = True

    controls = MobileTableControls(user)
    controls.open()

    expect(controls.row("category-filter-notes")).to_be_visible()
    expect(controls.row("category-filter-score")).to_be_visible()

    controls.filter_button("category-filter-notes").click()
    notes_sorting = user.locate(
        "#mobile-controls [data-sorts='category-filter-notes']"
    )
    expect(notes_sorting).to_be_visible()
    expect(
        notes_sorting.locator(
            'input[type="radio"][name="category-filter-notes"][value="asc"]'
        )
    ).to_be_visible()

    controls.filter_button("category-filter-score").click()
    score_sorting = user.locate(
        "#mobile-controls [data-sorts='category-filter-score']"
    )
    expect(score_sorting).to_be_visible()
    expect(
        score_sorting.locator(
            'input[type="radio"][name="category-filter-score"][value="asc"]'
        )
    ).to_be_visible()


# @matrix pages : category-index create mobile-tools
def test_category_mobile_tools_dropdown_opens_new_page_form(get_user):
    user = get_user(Users.OWNER)
    user.go(Categories.test_empty_category)

    user.mobile = True
    dropdown_button = user.locate("[data-role='tools-dropdown']")
    expect(dropdown_button).to_be_visible()
    expect(dropdown_button).to_have_attribute("data-combobox-id", re.compile(".+"))

    Dropdown(dropdown_button).select_by_name("New Page")

    create_page = user.locate(Category.CREATE_PAGE_WIDGET)
    expect(create_page).to_be_visible()
