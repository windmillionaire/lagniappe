"""
Tests for category index table column visibility and sorting.

Verified against:
- lagniappe/web/templates/categories/index.html
- lagniappe/web/templates/table.html
- lagniappe/core/properties/category.py (CategoryTable)
- src/script/widgets/tableVisibility.mjs
- src/script/widgets/tableSorting.mjs
"""

import re
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from testing.definitions import Categories, Pages, Submissions, Users
from testing.definitions.page_definitions import PageDefinition
from testing.resources import Page
from testing.resources.category import Category

pytestmark = pytest.mark.e2e

SORTABLE_PAGES = (
    Pages.test_category_sort_zebra_page,
    Pages.test_category_sort_alpha_page,
    Pages.test_category_sort_mango_page,
)
SORTABLE_PAGE_NAMES = tuple(page.value.definition.name for page in SORTABLE_PAGES)
SORTABLE_PAGE_NAME_PATTERN = re.compile(
    rf"^(?:{'|'.join(re.escape(name) for name in SORTABLE_PAGE_NAMES)})$"
)


def _seed_sortable_pages(owner):
    category = Categories.test_create_page.get(owner)
    for page in SORTABLE_PAGES:
        page.get(owner)
    return category


def _visible_sortable_titles(user):
    """Seeded page-title locators in their current visible table order."""
    titles = user.page.locator(
        f"{Category.VISIBLE_DATA_ROW} {Category.VISIBLE_NAME_CELL} "
        "a[data-role='title']"
    ).filter(has_text=SORTABLE_PAGE_NAME_PATTERN)
    expect(titles).to_have_count(len(SORTABLE_PAGE_NAMES))
    return titles


def _assert_visible_sortable_order(user, expected):
    expect(_visible_sortable_titles(user)).to_have_text(expected)


def _open_visibility_panel(user):
    toggle = user.locate(Category.TABLE_VISIBILITY_TOGGLE)
    expect(toggle).to_be_visible()
    toggle.click()
    panel = user.locate(Category.TABLE_VISIBILITY_PANEL)
    expect(panel).to_be_visible()
    return panel


def _open_name_sort_panel(user):
    filter_button = user.locate(
        Category.COLUMN_FILTER_BUTTON.format(column="name"),
    )
    expect(filter_button).to_be_visible()
    filter_button.click()
    panel = user.locate(Category.TABLE_SORTING_PANEL)
    expect(panel.locator('input[type="radio"][name="name"]').first).to_be_visible()
    return panel


def _select_name_sort(user, direction):
    panel = _open_name_sort_panel(user)
    radio = panel.locator(f'input[type="radio"][name="name"][value="{direction}"]')
    expect(radio).to_be_visible()
    radio.check()
    if direction != "none":
        _assert_visible_sortable_order(
            user,
            {
                "asc": ["Alpha Page", "Mango Page", "Zebra Page"],
                "desc": ["Zebra Page", "Mango Page", "Alpha Page"],
            }[direction],
        )


# @features table-controls
# @dimensions visibility-panel columns
def test_column_visibility_panel_opens(get_user):
    """Desktop column picker opens from the table header control."""
    user = get_user(Users.OWNER)
    user.go(Categories.test_create_page)

    panel = _open_visibility_panel(user)
    expect(panel.locator("input[type='checkbox'][name='image']")).to_be_visible()
    expect(panel.locator("input[type='checkbox'][name='name']")).to_be_visible()
    expect(panel.locator("input[type='checkbox'][name='form']")).to_be_visible()
    expect(panel.locator("input[type='checkbox'][name='modified']")).to_be_visible()


# @features table-controls
# @dimensions column-visibility
def test_hiding_column_updates_visible_headers_and_cells(get_user):
    """Unchecking a visible column hides its header and body cells."""
    user = get_user(Users.OWNER)
    _seed_sortable_pages(user)
    user.go(Categories.test_create_page)

    panel = _open_visibility_panel(user)
    modified = panel.locator("input[type='checkbox'][name='modified']")
    expect(modified).to_be_visible()
    expect(modified).to_be_checked()
    modified.set_checked(False)

    header = user.locate(Category.COLUMN_HEADER.format(column="modified"))
    expect(header).to_be_hidden()
    expect(
        user.page.locator(f"{Category.TABLE} td[data-column='modified']:visible"),
    ).to_have_count(0)


# @features table-controls
# @dimensions column-visibility persistence
def test_column_visibility_persists_after_reload(get_user):
    """Hidden columns stay hidden after a full page reload."""
    user = get_user(Users.OWNER)
    _seed_sortable_pages(user)
    category = user.go(Categories.test_create_page)

    panel = _open_visibility_panel(user)
    description = panel.locator("input[type='checkbox'][name='description']")
    expect(description).to_be_visible()
    description.set_checked(False)

    user.page.reload()
    category.initialize_view()

    expect(
        user.locate(Category.COLUMN_HEADER.format(column="description")),
    ).to_be_hidden()
    expect(
        user.page.locator(f"{Category.TABLE} td[data-column='description']:visible"),
    ).to_have_count(0)

    panel = _open_visibility_panel(user)
    expect(description).not_to_be_checked()


# @pairs table-controls:column-visibility table-controls:form-columns
# @pairs category-index:mixed-form category-index:missing-field category-index:render
def test_visibility_panel_includes_category_form_columns(get_user):
    """Categories with a default form expose schema fields as optional columns."""
    user = get_user(Users.OWNER)
    matching_page = Pages.test_category_filter_match_page.get(user)
    public_document_page = Pages.test_category_filter_public_document_page.get(user)
    user.go(Categories.test_category_filter_pages)

    panel = _open_visibility_panel(user)
    expect(
        panel.locator("input[type='checkbox'][name='category-filter-notes']")
    ).to_be_visible()
    expect(
        panel.locator("input[type='checkbox'][name='category-filter-score']")
    ).to_be_visible()
    expect(
        panel.locator("input[type='checkbox'][name='category-filter-flagged']")
    ).to_be_visible()
    expect(
        panel.locator("input[type='checkbox'][name='category-filter-decision']")
    ).to_be_visible()

    notes = panel.locator("input[type='checkbox'][name='category-filter-notes']")
    expect(notes).not_to_be_checked()
    notes.set_checked(True)

    expect(
        user.locate(
            Category.COLUMN_HEADER.format(column="category-filter-notes")
        )
    ).to_be_visible()
    expect(
        user.page.locator(
            f"{Category.TABLE} td[data-column='category-filter-notes']:visible"
        ).first
    ).to_be_visible()

    matching_row = user.page.locator(Category.VISIBLE_DATA_ROW).filter(
        has_text=matching_page.definition.name
    )
    public_row = user.page.locator(Category.VISIBLE_DATA_ROW).filter(
        has_text=public_document_page.definition.name
    )
    expect(
        matching_row.locator("td[data-column='category-filter-notes']")
    ).to_contain_text("Urgent permit packet")
    public_notes = public_row.locator("td[data-column='category-filter-notes']")
    expect(public_notes).to_have_text("")
    expect(public_notes).not_to_contain_text("False")


# @features table-controls
# @dimensions sorting exists-column
def test_image_column_sort_panel_offers_presence_options(get_user):
    """The image column opens existence-style sort/filter controls."""
    user = get_user(Users.OWNER)
    Pages.test_category_filter_match_page.get(user)
    user.go(Categories.test_category_filter_pages)

    visibility = _open_visibility_panel(user)
    image = visibility.locator("input[type='checkbox'][name='image']")
    expect(image).to_be_visible()
    image.set_checked(True)

    filter_button = user.locate(
        Category.COLUMN_FILTER_BUTTON.format(column="image"),
    )
    expect(filter_button).to_be_visible()
    filter_button.click()

    sorting = user.locate(Category.TABLE_SORTING_PANEL)
    expect(
        sorting.locator('input[type="radio"][name="image"][value="with"]')
    ).to_be_visible()
    expect(
        sorting.locator('input[type="radio"][name="image"][value="without"]')
    ).to_be_visible()


# @features table-controls
# @dimensions sorting boolean-column sort-clear
def test_boolean_column_filter_clear_restores_rows(get_user):
    """Clearing an active boolean column filter restores rows hidden by it."""
    user = get_user(Users.OWNER)
    matching_page = Pages.test_category_filter_match_page.get(user)
    nonmatching_page = Pages.test_category_filter_nonmatch_page.get(user)
    user.go(Categories.test_category_filter_pages)

    visibility = _open_visibility_panel(user)
    flagged = visibility.locator(
        "input[type='checkbox'][name='category-filter-flagged']"
    )
    expect(flagged).to_be_visible()
    flagged.set_checked(True)

    filter_button = user.locate(
        Category.COLUMN_FILTER_BUTTON.format(column="category-filter-flagged"),
    )
    expect(filter_button).to_be_visible()
    filter_button.click()

    sorting = user.locate(Category.TABLE_SORTING_PANEL)
    true_filter = sorting.locator(
        'input[type="radio"][name="category-filter-flagged"][value="true"]'
    )
    false_filter = sorting.locator(
        'input[type="radio"][name="category-filter-flagged"][value="false"]'
    )
    expect(true_filter).to_be_visible()
    expect(false_filter).to_be_visible()
    true_filter.check()

    matching_row = user.page.locator(Category.VISIBLE_DATA_ROW).filter(
        has_text=matching_page.definition.name
    )
    nonmatching_row = user.page.locator(Category.VISIBLE_DATA_ROW).filter(
        has_text=nonmatching_page.definition.name
    )
    expect(matching_row).to_be_visible()
    expect(nonmatching_row).to_be_hidden()

    false_filter.check()
    expect(matching_row).to_be_hidden()
    expect(nonmatching_row).to_be_visible()

    true_filter.check()
    expect(matching_row).to_be_visible()
    expect(nonmatching_row).to_be_hidden()

    sort_header = user.locate(
        Category.COLUMN_HEADER.format(column="category-filter-flagged")
    )
    expect(sort_header).to_have_attribute("data-sorting", "true")
    filter_button.click()

    expect(sort_header).to_have_attribute("data-sorting", "false")
    expect(matching_row).to_be_visible()
    expect(nonmatching_row).to_be_visible()


# @features table-controls
# @dimensions sorting exists-column phone
def test_exists_column_filter_treats_phone_values_as_present(get_user):
    """With/without filters treat phone strings as present values."""
    user = get_user(Users.OWNER)
    suffix = uuid4().hex[:8]
    with_phone = Page(
        user=user,
        definition=PageDefinition(
            name=f"Phone Present Page {suffix}",
            category=Categories.test_basic_inputs_submission,
            submission=Submissions.basic_inputs,
        ),
    ).create()
    without_phone = Page(
        user=user,
        definition=PageDefinition(
            name=f"Phone Missing Page {suffix}",
            category=Categories.test_basic_inputs_submission,
        ),
    ).create()
    user.go(Categories.test_basic_inputs_submission)

    visibility = _open_visibility_panel(user)
    phone = visibility.locator("input[type='checkbox'][name='input-telkl12']")
    expect(phone).to_be_visible()
    phone.set_checked(True)

    filter_button = user.locate(
        Category.COLUMN_FILTER_BUTTON.format(column="input-telkl12"),
    )
    expect(filter_button).to_be_visible()
    filter_button.click()

    sorting = user.locate(Category.TABLE_SORTING_PANEL)
    with_filter = sorting.locator(
        'input[type="radio"][name="input-telkl12"][value="with"]'
    )
    without_filter = sorting.locator(
        'input[type="radio"][name="input-telkl12"][value="without"]'
    )
    expect(with_filter).to_be_visible()
    expect(without_filter).to_be_visible()

    phone_row = user.page.locator(Category.VISIBLE_DATA_ROW).filter(
        has_text=with_phone.definition.name
    )
    blank_row = user.page.locator(Category.VISIBLE_DATA_ROW).filter(
        has_text=without_phone.definition.name
    )

    with_filter.check()
    expect(phone_row).to_be_visible()
    expect(blank_row).to_be_hidden()

    without_filter.check()
    expect(phone_row).to_be_hidden()
    expect(blank_row).to_be_visible()


# @features table-controls
# @dimensions sorting sort-asc
def test_name_column_sort_ascending_reorders_rows(get_user):
    """Name column A→Z sort reorders visible category page rows."""
    user = get_user(Users.OWNER)
    _seed_sortable_pages(user)
    user.go(Categories.test_create_page)

    _select_name_sort(user, "asc")
    _assert_visible_sortable_order(
        user, ["Alpha Page", "Mango Page", "Zebra Page"]
    )


# @features table-controls
# @dimensions sorting persistence
def test_name_column_sort_persists_after_back_navigation(get_user):
    """A table sort is restored after following a row link and going back."""
    user = get_user(Users.OWNER)
    _seed_sortable_pages(user)
    category = user.go(Categories.test_create_page)

    _select_name_sort(user, "asc")

    alpha_row = user.page.locator(Category.VISIBLE_DATA_ROW).filter(
        has_text="Alpha Page"
    ).first
    expect(alpha_row).to_be_visible()
    alpha_row.locator("td[data-column='name'] a[data-role='title']").click()
    expect(user.locate("[lp-view][data-kind='page']")).to_have_attribute(
        "initialized", ""
    )

    user.page.go_back()
    category.initialize_view()

    _assert_visible_sortable_order(
        user, ["Alpha Page", "Mango Page", "Zebra Page"]
    )
    sort_header = user.locate(Category.COLUMN_HEADER.format(column="name"))
    expect(sort_header).to_have_attribute("data-sorting", "true")


# @features table-controls
# @dimensions sorting sort-desc
def test_name_column_sort_descending_reorders_rows(get_user):
    """Name column Z→A sort reverses visible row order."""
    user = get_user(Users.OWNER)
    _seed_sortable_pages(user)
    user.go(Categories.test_create_page)

    _select_name_sort(user, "desc")
    _assert_visible_sortable_order(
        user, ["Zebra Page", "Mango Page", "Alpha Page"]
    )


# @features table-controls
# @dimensions sorting sort-clear
def test_clearing_sort_restores_default_order(get_user):
    """Toggling the name filter again restores the initial visible row order."""
    user = get_user(Users.OWNER)
    _seed_sortable_pages(user)
    user.go(Categories.test_create_page)

    initial_order = _visible_sortable_titles(user).all_inner_texts()

    _select_name_sort(user, "asc")
    _assert_visible_sortable_order(
        user, ["Alpha Page", "Mango Page", "Zebra Page"]
    )

    filter_button = user.locate(
        Category.COLUMN_FILTER_BUTTON.format(column="name"),
    )
    expect(filter_button).to_be_visible()
    filter_button.click()

    expect(_visible_sortable_titles(user)).to_have_text(initial_order)
