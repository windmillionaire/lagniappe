"""
Tests for Category (Page) filter functionality.

Tests filter builder, comparators, results, and saved filters.
Verified against:
- lagniappe/templates/filters.html
- src/script/widgets/category.mjs (CategoryFilters)
- src/script/components/filters.mjs
"""

import json

from playwright.sync_api import expect
import pytest

from testing.definitions import Categories, Forms, Pages, Users
from testing.elements import FormElements, FormSelect, SpinnerButtons, Table, Tools
from testing.elements.filters import CategoryFilterConditions, Filters

pytestmark = pytest.mark.e2e

_CATEGORY_FILTER_CONTEXT_READY = False


def _category_filter_context(user):
    global _CATEGORY_FILTER_CONTEXT_READY

    category = Categories.test_category_filter_pages.get(user)
    matching_page = Pages.test_category_filter_match_page.get(user)
    excluded_page = Pages.test_category_filter_nonmatch_page.get(user)
    public_document_page = Pages.test_category_filter_public_document_page.get(user)
    extra_category = Categories.test_category_filter_extra.get(user)

    if not _CATEGORY_FILTER_CONTEXT_READY:
        matching_page.entity.properties.categories.add(extra_category.entity)
        matching_page.entity.save()

        public_document_page.entity.is_public = True
        public_document_page.entity.properties.document.save(
            html="<p>Category filter document marker.</p>"
        )
        public_document_page.entity.save()

        _CATEGORY_FILTER_CONTEXT_READY = True

    return category, matching_page, excluded_page, public_document_page, extra_category


def _expect_result_includes_excludes(results, matching_page, excluded_page):
    matching_row = results.locator("tr").filter(
        has_text=matching_page.definition.name
    )
    excluded_row = results.locator("tr").filter(
        has_text=excluded_page.definition.name
    )

    expect(matching_row).to_be_visible()
    expect(excluded_row).not_to_be_visible()


def _create_category_page(user, page, create_form):
    with user.page.expect_response("**/create"):
        SpinnerButtons.CREATE.click(create_form)

    table = Table(user)
    new_row = table.new_row(page.definition.name)
    return new_row.get_attribute("data-key")


def _attached_form_filter_context(user):
    category, matching_page, excluded_page, _, _ = _category_filter_context(user)
    attached_form = Forms.test_category_filter_page_form.get(user)
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(attached_form)
    expect(filters.badges).to_contain_text(attached_form.definition.name)
    expect(filters.form_conditions).to_be_visible()

    return filters, matching_page, excluded_page


# @features filters
# @dimensions related-forms
def test_category_filter_select_includes_form_from_created_page(get_user):
    """Creating a page with a form registers that form for category filters."""
    user = get_user(Users.OWNER)
    category = Categories.test_category_filter_related_form_registration.get(user)
    page = Pages.test_category_filter_related_form_registration_page.get(
        user, create=False
    )
    form = Forms.test_category_filter_page_form.get(user)
    user.go(category)

    create_form = category.new_page_form()
    create_form.locator(FormElements.NAME).fill(page.definition.name)
    create_form.locator(FormElements.DESCRIPTION).fill(page.definition.description)
    FormSelect(create_form).select(form)
    page.key = _create_category_page(user, page, create_form)

    user.reload(category)
    filters = Filters(user, category)
    filters.set_condition(form)
    expect(filters.form_conditions).to_be_visible()


# @features filters
# @dimensions tab-open
def test_category_filters_form_opens(get_user):
    """Category index exposes the shared filters builder."""
    user = get_user(Users.OWNER)
    category = Categories.test_create_page.get(user)
    user.go(category)
    filters = category.filter_section

    expect(filters).to_be_visible()
    expect(filters.locator("[data-role='conditions']")).to_be_visible()
    expect(filters.locator("button[data-role='run']")).to_be_visible()
    expect(filters.locator("button[data-role='save']")).to_be_visible()


# @features filters
# @dimensions empty-validation
def test_category_filters_require_at_least_one_condition(get_user):
    """Running an empty filter shows the expected validation error."""
    user = get_user(Users.OWNER)
    category = Categories.test_create_page.get(user)
    user.go(category)
    filters = Filters(user, category)

    filters.run_button.click()
    # expect(results).not_to_be_visible()
    expect(filters.error).to_contain_text("Please add at least one filter condition")


# @features filters
# @dimensions saved-filters empty-state
def test_category_saved_filters_empty_state(get_user):
    """Saved Filters opens with a clear empty state before any filters are saved."""
    user = get_user(Users.OWNER)
    category = Categories.test_empty_category.get(user)
    user.go(category)

    tools = Tools(user)
    tools.open()

    with user.page.expect_response("**/filters/*/get"):
        tools.locate(category.SAVED_FILTERS_TOGGLE).click()

    saved = tools.locate("[data-role='saved-filters']")
    expect(saved).to_be_visible()
    expect(saved.locator("[data-role='empty']")).to_contain_text(
        "No filters saved yet"
    )


# @features pages
# @dimensions tool-switch
def test_category_saved_filters_hide_create_page_tool(get_user):
    """Switching category tools hides the New Page form before showing saved filters."""
    user = get_user(Users.OWNER)
    category = Categories.test_empty_category.get(user)
    user.go(category)

    tools = Tools(user)
    tools.open()
    tools.locate(category.CREATE_PAGE_TOGGLE).click()
    create_page = tools.locate(category.CREATE_PAGE_WIDGET)
    expect(create_page).to_be_visible()

    tools.locate(category.GENERATE_PAGES_TOGGLE).click()
    expect(tools.locate(category.GENERATE_PAGES_WIDGET)).to_be_visible()
    expect(create_page).to_be_hidden()

    tools.locate(category.CATEGORY_INFO_TOGGLE).click()
    expect(tools.locate(category.CATEGORY_INFO_WIDGET)).to_be_visible()
    expect(create_page).to_be_hidden()

    with user.page.expect_response("**/filters/*/get"):
        tools.locate(category.SAVED_FILTERS_TOGGLE).click()

    saved = tools.locate("[data-role='saved-filters']")
    expect(saved).to_be_visible()
    expect(create_page).to_be_hidden()


# @features filters
# @dimensions saved-filters query-tool
def test_category_url_tool_opens_saved_filters(get_user):
    """A tool query parameter opens the matching category tools widget."""
    user = get_user(Users.OWNER)
    category = Categories.test_empty_category.get(user)
    user.go(category, query_params={"tool": "saved-filters"})

    tools = user.locate("#tools")
    expect(tools).to_be_visible()
    expect(tools.locator(category.SAVED_FILTERS_TOGGLE)).to_have_attribute(
        "data-selected", "true"
    )

    saved = tools.locator("[data-role='saved-filters']")
    expect(saved).to_be_visible()
    expect(saved.locator("[data-role='empty']")).to_contain_text(
        "No filters saved yet"
    )


# @features filters
# @dimensions string-condition run-results
def test_category_filter_by_page_name(get_user):
    """Category filters match page-name substrings and render matching rows."""
    user = get_user(Users.OWNER)
    category, matching_page, excluded_page, _, _ = _category_filter_context(user)
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(CategoryFilterConditions.NAME)
    badges = filters.name_contains("Urgent").add_filter()

    expect(badges).to_contain_text(CategoryFilterConditions.NAME.value)
    results = filters.run()
    expect(results).to_be_visible()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @features filters
# @dimensions string-condition run-results view-access
def test_category_filter_results_respect_page_permissions(get_user):
    """Category filters return only matching pages the viewer can see."""
    owner = get_user(Users.OWNER)
    category = Categories.test_category_filter_pages.get(owner)
    visible = Pages.test_category_filter_permission_visible.get(owner)
    hidden = Pages.test_category_filter_permission_hidden.get(owner)
    hidden.entity.properties.restricted_to.add("owner")
    hidden.entity.save()

    subject = get_user(Users.general_models_view_only)
    category = subject.go(category)

    filters = Filters(subject, category)
    filters.set_condition(CategoryFilterConditions.NAME)
    badges = filters.name_contains("Permission Filter").add_filter()

    expect(badges).to_contain_text(CategoryFilterConditions.NAME.value)
    results = filters.run()
    expect(results).to_be_visible()
    _expect_result_includes_excludes(results, visible, hidden)


# @features filters
# @dimensions string-condition description run-results
def test_category_filter_by_page_description(get_user):
    """Category filters match page descriptions through the shared builder."""
    user = get_user(Users.OWNER)
    category, matching_page, excluded_page, _, _ = _category_filter_context(user)
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(CategoryFilterConditions.DESCRIPTION)
    badges = filters.text("contains", "permit", field="description").add_filter()

    expect(badges).to_contain_text(CategoryFilterConditions.DESCRIPTION.value)
    results = filters.run()
    expect(results).to_be_visible()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @features filters
# @dimensions entity-condition category run-results
def test_category_filter_by_additional_category(get_user):
    """The page category facet can select pages tagged with another category."""
    user = get_user(Users.OWNER)
    category, matching_page, excluded_page, _, extra_category = (
        _category_filter_context(user)
    )
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(CategoryFilterConditions.CATEGORY)
    badges = filters.category(extra_category.definition.name).add_filter()

    expect(badges).to_contain_text(extra_category.definition.name)
    results = filters.run()
    expect(results).to_be_visible()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @features filters
# @dimensions boolean-condition public run-results
def test_category_filter_by_public_page(get_user):
    """Public/private page visibility is available as a category filter."""
    user = get_user(Users.OWNER)
    category, _, excluded_page, public_document_page, _ = (
        _category_filter_context(user)
    )
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(CategoryFilterConditions.PUBLIC)
    badges = filters.boolean("public").add_filter()

    expect(badges).to_contain_text(CategoryFilterConditions.PUBLIC.value)
    results = filters.run()
    expect(results).to_be_visible()
    _expect_result_includes_excludes(results, public_document_page, excluded_page)


# @features filters
# @dimensions boolean-condition document run-results
def test_category_filter_by_document_asset(get_user):
    """The category filter cache can select pages that have documents."""
    user = get_user(Users.OWNER)
    category, _, excluded_page, public_document_page, _ = (
        _category_filter_context(user)
    )
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(CategoryFilterConditions.DOCUMENT)
    badges = filters.boolean("document").add_filter()

    expect(badges).to_contain_text(CategoryFilterConditions.DOCUMENT.value)
    results = filters.run()
    expect(results).to_be_visible()
    _expect_result_includes_excludes(results, public_document_page, excluded_page)


# @features filters
# @dimensions attached-form string-condition run-results
def test_category_filter_by_attached_form_text_condition(get_user):
    """Text fields from the category's default page form filter page rows."""
    user = get_user(Users.OWNER)
    filters, matching_page, excluded_page = _attached_form_filter_context(user)

    badges = (
        filters.set_form_condition("Inspection Notes")
        .text("contains", "Urgent")
        .add_filter()
    )

    expect(badges).to_contain_text("Inspection Notes")
    results = filters.run()
    expect(results).to_be_visible()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @features filters
# @dimensions attached-form number-condition run-results
def test_category_filter_by_attached_form_number_condition(get_user):
    """Number fields from page form submissions can filter category results."""
    user = get_user(Users.OWNER)
    filters, matching_page, excluded_page = _attached_form_filter_context(user)

    badges = (
        filters.set_form_condition("Risk Score")
        .number("is greater than or equal to", "90")
        .add_filter()
    )

    expect(badges).to_contain_text("Risk Score")
    results = filters.run()
    expect(results).to_be_visible()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @features filters
# @dimensions attached-form boolean-condition run-results
def test_category_filter_by_attached_form_checkbox_condition(get_user):
    """Checkbox page form fields expose checked/not checked filter options."""
    user = get_user(Users.OWNER)
    filters, matching_page, excluded_page = _attached_form_filter_context(user)

    badges = (
        filters.set_form_condition("Requires Follow Up").checkbox(True).add_filter()
    )

    expect(badges).to_contain_text("Requires Follow Up")
    results = filters.run()
    expect(results).to_be_visible()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @features filters
# @dimensions attached-form select-condition run-results
def test_category_filter_by_attached_form_select_condition(get_user):
    """Single-select page form fields filter by the selected option label."""
    user = get_user(Users.OWNER)
    filters, matching_page, excluded_page = _attached_form_filter_context(user)

    badges = (
        filters.set_form_condition("Review Decision")
        .choice("Approved")
        .add_filter()
    )

    expect(badges).to_contain_text("Review Decision")
    results = filters.run()
    expect(results).to_be_visible()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @features filters
# @dimensions saved-filters save reload-persistence
def test_category_saved_filter_save_and_run(get_user):
    """Saving a category filter persists after reload and the run link works."""
    user = get_user(Users.OWNER)
    category, matching_page, excluded_page, _, _ = _category_filter_context(user)
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(CategoryFilterConditions.NAME)
    filters.name_contains("Urgent").add_filter()

    saved = filters.save_filter()
    expect(saved.locator("[data-role='empty']")).not_to_be_attached()

    saved_filter = saved.locator("li").filter(has_text="Urgent")
    expect(saved_filter).to_be_visible()
    expect(saved_filter).to_contain_text(CategoryFilterConditions.NAME.value)

    user.reload(category)
    tools = Tools(user)
    tools.open()
    with user.page.expect_response("**/filters/*/get"):
        tools.locate(category.SAVED_FILTERS_TOGGLE).click()

    reloaded_saved = tools.locate("[data-role='saved-filters']")
    reloaded_filter = reloaded_saved.locator("li").filter(has_text="Urgent")
    expect(reloaded_filter).to_be_visible()
    expect(reloaded_filter).to_contain_text(CategoryFilterConditions.NAME.value)

    with user.page.expect_navigation():
        reloaded_filter.locator("a[href*='/filters/']").click()
    user.page.wait_for_selector("[lp-view][initialized]")

    table = user.locate("#table")
    expect(
        table.locator("tr").filter(has_text=matching_page.definition.name)
    ).to_be_visible()
    expect(
        table.locator("tr").filter(has_text=excluded_page.definition.name)
    ).not_to_be_visible()

    filter_hash = user.locate("[lp-view]").get_attribute("data-hash")
    filter_key = user.locate("[lp-view]").get_attribute("data-key")
    with user.page.expect_response("**/refresh") as refresh_info:
        user.page.evaluate(
            "document.querySelector('[lp-view]')._lp_view.refresh(true)"
        )

    request_payload = json.loads(refresh_info.value.request.post_data or "{}")
    assert request_payload["view"]["key"] == filter_key
    assert request_payload["view"]["hash"] == filter_hash
    assert {target["id"] for target in request_payload["targets"]} == {"table"}

    response_payload = refresh_info.value.json()
    assert response_payload["targets"] == []
    assert response_payload["fingerprint"] == request_payload["view"]["fingerprint"]
