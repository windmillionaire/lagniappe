"""
Tests for category creation and management from the home page.

Tests the category widget including form interactions, manual/AI creation modes,
form attachment, list toggle behavior, navigation, and category-menu deletion.

Related Files:
    Application:
        - lagniappe/web/routes/categories/main.py: Category routes
        - lagniappe/web/templates/home/categories.html: Category component template
        - lagniappe/web/templates/categories/: Category page templates
        - src/script/widgets/home/lists.mjs: HomeCategoryList widget
        - src/script/views/home.mjs: Category initialization

    Core Entity:
        - lagniappe/core/entities/category.py: Category entity

    Test Framework:
        - testing/definitions/categories.py: Categories enum with test definitions
        - testing/resources/category.py: Category resource with create() logic
        - testing/resources/home.py: HomePage selectors for category component

Category Features:
    Categories are containers for pages. They can have:
    - An attached form (defines fields for pages in this category)
    - AI-generated or manually entered name/description
"""

import re

import pytest
from playwright.sync_api import expect

from testing.definitions import Categories, SitePages, Users
from testing.elements import (
    HeaderSearch,
    FormSelect,
    Buttons,
    FormElements,
    Link,
    Modal,
    SpinnerButtons,
)
from testing.utility.network import expect_successful_response
from testing.utility.live_ai import LIVE_AI_RESPONSE_TIMEOUT_MS


def _create_category(user, home, definition):
    create_form = home.create_category_form()
    if not definition.description_for_ai:
        create_form.locator(FormElements.NAME).fill(definition.name)
    else:
        create_form.locator(Buttons.AI_MODE).click()
        create_form.locator(FormElements.AI_DESCRIPTION).fill(
            definition.description_for_ai
        )

    if definition.form:
        category_form = definition.form.get(user)
        FormSelect(create_form).select(category_form)

    with expect_successful_response(
        user.page,
        method="POST",
        path="/categories/create",
        timeout=LIVE_AI_RESPONSE_TIMEOUT_MS if definition.description_for_ai else None,
    ) as response_info:
        SpinnerButtons.CREATE.click(create_form)

    expect(create_form).not_to_be_visible()
    new_category_key = home.entity_key_from_response(response_info.value)
    category_list = home.category_list
    new_category = category_list.list.locator(f"li[data-key='{new_category_key}']")
    expect(new_category).to_be_visible()

    return new_category_key


# @matrix categories : attach-form manual-form
@pytest.mark.e2e
def test_create_category_form(get_user):
    """
    Verify create category form opens with expected fields.

    Tests:
        - Form hidden initially, visible after toggle
        - Name field present
        - Form selector button visible (for attaching a form definition)
        - Close button hides form

    Note: Categories have a form selector (Buttons.ASSIGN_FORM) for
    attaching a Form entity that defines page fields.
    """
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    form = user.locate(home.CREATE_CATEGORY_FORM)
    expect(form).to_be_hidden()

    user.locate(home.CREATE_CATEGORY_TOGGLE).click()
    expect(form).to_be_visible()

    expect(form.locator(FormElements.NAME)).to_be_visible()
    expect(form.get_by_role("button", name="Create Category")).to_be_visible()

    form_button = FormSelect(form).button
    expect(form_button).to_contain_text("Form")

    form.locator(Buttons.LP_CLOSE).click()
    expect(form).not_to_be_visible()


# @matrix categories : ai-form explain-button
@pytest.mark.e2e
def test_category_form_explain_button(get_user):
    """
    Verify AI explain button shows prompt preview modal.

    Same pattern as project form - in AI mode, explain button
    shows what the AI will generate based on the prompt.
    """
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    user.locate(home.CREATE_CATEGORY_TOGGLE).click()
    form = user.locate(home.CREATE_CATEGORY_FORM)
    expect(form).to_be_visible()

    form.locator(Buttons.AI_MODE).click()
    description = form.locator(FormElements.AI_DESCRIPTION)
    expect(description).to_be_visible()
    description.fill("Testing the explain button")

    explain_btn = form.locator(Buttons.EXPLAIN)
    expect(explain_btn).to_be_visible()
    explain_btn.click()

    modal = Modal(user.page)
    modal.close()
    expect(form).to_be_visible()


# @matrix categories : ai-form manual-form
@pytest.mark.e2e
def test_category_form_generate_toggle(get_user):
    """
    Verify manual/AI mode toggle switches form fields.

    Manual mode shows name field.
    AI mode shows AI description prompt field.
    """
    user = get_user(Users.OWNER)
    home = user.go(SitePages.HOME)

    user.locate(home.CREATE_CATEGORY_TOGGLE).click()
    form = user.locate(home.CREATE_CATEGORY_FORM)
    expect(form).to_be_visible()

    manual_name = form.locator(FormElements.NAME)
    expect(manual_name).to_be_visible()

    form.locator(Buttons.AI_MODE).click()
    ai_description = form.locator(FormElements.AI_DESCRIPTION)
    expect(ai_description).to_be_visible()
    expect(manual_name).not_to_be_visible()

    form.locator(Buttons.MANUAL_MODE).click()
    expect(manual_name).to_be_visible()
    expect(ai_description).not_to_be_visible()


# @pair categories:create-manual
@pytest.mark.e2e
def test_create_category_manual_mode(get_user):
    """
    Verify category creation in manual mode.

    Uses Categories.test_create_category_manual_mode definition.
    Verifies category appears in search after creation.
    """
    user = get_user(Users.OWNER)
    category = Categories.test_create_category_manual_mode.get(user, create=False)
    home = user.go(SitePages.HOME)
    category.key = _create_category(user, home, category.definition)

    header_search = HeaderSearch(user)
    header_search.verify_entity_in_results(category)


# @matrix categories : ai-create ai-generated
@pytest.mark.ai
def test_create_category_ai_mode(get_user, results):
    """
    Verify category creation in AI mode.

    Uses AI to generate category name and description from a prompt.
    The provider-backed create request gets the complete configured retry budget.
    """
    user = get_user(Users.OWNER)
    category = Categories.test_create_category_ai_mode.get(user, create=False)
    home = user.go(SitePages.HOME)

    category.key = _create_category(user, home, category.definition)
    results.record("category", category.entity.db)


# @pair categories:navigate
@pytest.mark.e2e
def test_navigate_to_category(get_user):
    """
    Verify navigation from category list to category index page.

    Framework usage:
        - home.category_list: Opens list and asserts List.is_loaded
        - Link helper: Clicks the title link
    """
    user = get_user(Users.OWNER)
    category = Categories.test_navigate_to_category.get(user)
    home = user.go(SitePages.HOME)

    category_element = home.category_list.get_item(category)
    Link(category_element).click()
    expect(user.page).to_have_title(re.compile(category.definition.name))


# @matrix categories : attach-form create-manual
@pytest.mark.e2e
def test_create_category_with_form(get_user):
    """
    Verify category with attached form shows form fields.

    When a category has an attached Form entity, pages created in
    that category will have the form's fields. This test verifies
    the new page form on the category index shows all schema fields.

    Framework usage:
        - category.schema: List of field definitions from attached form
        - category.new_page_form(): Opens and returns the create page form
    """
    user = get_user(Users.OWNER)
    category = Categories.test_create_category_with_form.get(user, create=False)
    home = user.go(SitePages.HOME)
    category.key = _create_category(user, home, category.definition)
    category_form = category.definition.form.get(user)

    category_page = user.go(category)
    new_page_form = category_page.new_page_form()
    assert FormSelect(new_page_form).contains(category_form)


# @pair categories:delete
# @template categories/index.html::view_header
# @template menus.html::title
# @template menus.html::delete
def test_delete_category(get_user):
    """Verify category deletion from its title menu."""
    user = get_user(Users.OWNER)
    category = Categories.test_delete_category.get(user)
    user.go(category)

    user.page.get_by_role("button", name="Category actions").click()
    menu = user.page.get_by_role("menu", name="Category actions")
    menu.get_by_role("menuitem", name="Delete").click()

    Modal(user.page).delete()
    expect(user.page).to_have_url(re.compile(r"/$"))
