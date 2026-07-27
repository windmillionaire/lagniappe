"""
Tests for category index mobile controls.

Verified against:
- lagniappe/web/templates/categories/index.html
- lagniappe/web/templates/table.html
- src/script/views/base/index.mjs
- src/script/widgets/mobileTableControls.mjs
"""

import re

import pytest
from playwright.sync_api import expect

from testing.definitions import Categories, Pages, Users
from testing.elements import Dropdown, MobileTableControls
from testing.resources.category import Category

pytestmark = pytest.mark.e2e


def _clear_category_column_prefs(user):
    category_hash = user.locate("[lp-view][data-kind='category']").get_attribute(
        "data-hash"
    )
    user.page.evaluate(
        """([columnsKey, sortsKey]) => {
            localStorage.removeItem(columnsKey);
            sessionStorage.removeItem(sortsKey);
        }""",
        [f"columns-{category_hash}", f"sorts-{category_hash}"],
    )


# @features table-controls
# @dimensions mobile-controls columns
def test_category_mobile_controls_open_with_page_columns(get_user):
    """A phone user opens category table controls and sees page-oriented columns."""
    user = get_user(Users.OWNER)
    Pages.test_create_page.get(user)
    category = user.go(Categories.test_create_page)
    _clear_category_column_prefs(user)
    user.reload(category)

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


# @features table-controls
# @dimensions mobile-controls column-visibility
def test_category_mobile_visibility_toggle_hides_column(get_user):
    """Mobile controls hide a category column without leaving cells behind."""
    user = get_user(Users.OWNER)
    Pages.test_create_page.get(user)
    category = user.go(Categories.test_create_page)
    _clear_category_column_prefs(user)
    user.reload(category)
    user.mobile = True

    controls = MobileTableControls(user)
    controls.open()
    modified_toggle = controls.toggle_column("modified")

    expect(modified_toggle).to_have_attribute("data-active", "false")
    expect(
        user.locate(Category.COLUMN_HEADER.format(column="modified"))
    ).to_be_hidden()
    expect(user.locate("#table td[data-column='modified']:visible")).to_have_count(0)


# @features table-controls
# @dimensions mobile-controls sorting
def test_category_mobile_filter_button_opens_sorting_panel(get_user):
    """The mobile filter button opens sorting controls for the selected column."""
    user = get_user(Users.OWNER)
    Pages.test_create_page.get(user)
    category = user.go(Categories.test_create_page)
    _clear_category_column_prefs(user)
    user.reload(category)
    user.mobile = True

    controls = MobileTableControls(user)
    controls.open()
    controls.filter_button("name").click()

    sorting = user.locate("#mobile-controls [data-sorts='name']")
    expect(sorting).to_be_visible()
    expect(
        sorting.locator('input[type="radio"][name="name"][value="asc"]')
    ).to_be_visible()


# @features table-controls
# @dimensions mobile-controls form-columns sorting
def test_category_mobile_controls_handle_form_columns(get_user):
    """Mobile table controls include category form columns and open their sorts."""
    user = get_user(Users.OWNER)
    Pages.test_category_filter_match_page.get(user)
    category = user.go(Categories.test_category_filter_pages)
    _clear_category_column_prefs(user)
    user.reload(category)
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


# @features pages
# @dimensions create category-index mobile-tools
def test_category_mobile_tools_dropdown_opens_new_page_form(get_user):
    """The mobile tools menu still gives page creators the New Page flow."""
    user = get_user(Users.OWNER)
    user.go(Categories.test_empty_category)

    user.mobile = True
    dropdown_button = user.locate("[data-role='tools-dropdown']")
    expect(dropdown_button).to_be_visible()
    expect(dropdown_button).to_have_attribute("data-combobox-id", re.compile(".+"))

    Dropdown(dropdown_button).select_by_name("New Page")

    create_page = user.locate(Category.CREATE_PAGE_WIDGET)
    expect(create_page).to_be_visible()
    expect(create_page.locator("[data-role='attributes']")).to_be_visible()
