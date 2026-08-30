from dataclasses import replace
from uuid import uuid4

from playwright.sync_api import expect
import pytest

from testing.definitions import Categories, Forms, Pages, Users
from testing.resources import Page
from testing.elements import FormElements, FormSelect, SpinnerButtons, Table, Tools
from testing.elements.filters import CategoryFilterConditions, Filters
from testing.utility.polling import expect_poll_result
from testing.utility.reconnect import expect_reconnect_refresh

pytestmark = pytest.mark.e2e

def _category_filter_context(user):
    category = Categories.test_category_filter_pages.get(user)
    matching_page = Pages.test_category_filter_match_page.get(user)
    excluded_page = Pages.test_category_filter_nonmatch_page.get(user)
    public_document_page = Pages.test_category_filter_public_document_page.get(user)
    extra_category = Categories.test_category_filter_extra.get(user)

    if (
        extra_category.entity.key
        not in matching_page.entity.properties.categories.keys
    ):
        matching_page.entity.properties.categories.add(extra_category.entity)
        matching_page.entity.save()

    document_marker = "Category filter document marker."
    public_document_changed = False
    if not public_document_page.entity.is_public:
        public_document_page.entity.is_public = True
        public_document_changed = True
    if document_marker not in (
        public_document_page.entity.properties.document.html or ""
    ):
        public_document_page.entity.properties.document.save(
            html=f"<p>{document_marker}</p>"
        )
        public_document_changed = True
    if public_document_changed:
        public_document_page.entity.save()

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


# @pair filters:related-forms
def test_category_filter_select_includes_form_from_created_page(get_user):
    user = get_user(Users.OWNER)
    category = Categories.test_category_filter_related_form_registration.get(user)
    page = Page(
        user=user,
        definition=replace(
            Pages.test_category_filter_related_form_registration_page.value.definition,
            name=f"Related Form Registration {uuid4().hex}",
        ),
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


# @pair filters:tab-open
def test_category_filters_form_opens(get_user):
    user = get_user(Users.OWNER)
    category = Categories.test_create_page.get(user)
    user.go(category)
    filters = category.filter_section

    expect(filters).to_be_visible()
    expect(filters.locator("[data-role='conditions']")).to_be_visible()
    expect(filters.locator("button[data-role='run']")).to_be_visible()
    expect(filters.locator("button[data-role='save']")).to_be_visible()


# @pair filters:empty-validation
def test_category_filters_require_at_least_one_condition(get_user):
    user = get_user(Users.OWNER)
    category = Categories.test_create_page.get(user)
    user.go(category)
    filters = Filters(user, category)

    filters.run_button.click()
    expect(filters.error).to_contain_text("Please add at least one filter condition")


# @matrix filters : empty-state saved-filters
def test_category_saved_filters_empty_state(get_user):
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


# @pair pages:tool-switch
def test_category_saved_filters_hide_create_page_tool(get_user):
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


# @matrix filters : query-tool saved-filters
def test_category_url_tool_opens_saved_filters(get_user):
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


# @matrix filters : run-results string-condition
def test_category_filter_by_page_name(get_user):
    user = get_user(Users.OWNER)
    category, matching_page, excluded_page, _, _ = _category_filter_context(user)
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(CategoryFilterConditions.NAME)
    filters.name_contains("Urgent").add_filter()
    results = filters.run()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @matrix filters : run-results string-condition view-access
def test_category_filter_results_respect_page_permissions(get_user):
    owner = get_user(Users.OWNER)
    category = Categories.test_category_filter_pages.get(owner)
    visible = Pages.test_category_filter_permission_visible.get(owner)
    hidden = Pages.test_category_filter_permission_hidden.get(owner)
    if "owner" not in hidden.entity.properties.restricted_to.stored:
        hidden.entity.properties.restricted_to.add("owner")
        hidden.entity.save()

    subject = get_user(Users.general_models_view_only)
    category = subject.go(category)

    filters = Filters(subject, category)
    filters.set_condition(CategoryFilterConditions.NAME)
    filters.name_contains("Permission Filter").add_filter()
    results = filters.run()
    _expect_result_includes_excludes(results, visible, hidden)


# @matrix filters : description run-results string-condition
def test_category_filter_by_page_description(get_user):
    user = get_user(Users.OWNER)
    category, matching_page, excluded_page, _, _ = _category_filter_context(user)
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(CategoryFilterConditions.DESCRIPTION)
    filters.text("contains", "permit", field="description").add_filter()
    results = filters.run()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @matrix filters : category entity-condition run-results
def test_category_filter_by_additional_category(get_user):
    user = get_user(Users.OWNER)
    category, matching_page, excluded_page, _, extra_category = (
        _category_filter_context(user)
    )
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(CategoryFilterConditions.CATEGORY)
    filters.category(extra_category.definition.name).add_filter()
    results = filters.run()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @matrix filters : boolean-condition public run-results
def test_category_filter_by_public_page(get_user):
    user = get_user(Users.OWNER)
    category, _, excluded_page, public_document_page, _ = (
        _category_filter_context(user)
    )
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(CategoryFilterConditions.PUBLIC)
    filters.boolean("public").add_filter()
    results = filters.run()
    _expect_result_includes_excludes(results, public_document_page, excluded_page)


# @matrix filters : boolean-condition document run-results
def test_category_filter_by_document_asset(get_user):
    user = get_user(Users.OWNER)
    category, _, excluded_page, public_document_page, _ = (
        _category_filter_context(user)
    )
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(CategoryFilterConditions.DOCUMENT)
    filters.boolean("document").add_filter()
    results = filters.run()
    _expect_result_includes_excludes(results, public_document_page, excluded_page)


# @matrix filters : attached-form run-results string-condition
def test_category_filter_by_attached_form_text_condition(get_user):
    user = get_user(Users.OWNER)
    filters, matching_page, excluded_page = _attached_form_filter_context(user)

    (
        filters.set_form_condition("Inspection Notes")
        .text("contains", "Urgent")
        .add_filter()
    )

    results = filters.run()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @matrix filters : attached-form number-condition run-results
def test_category_filter_by_attached_form_number_condition(get_user):
    user = get_user(Users.OWNER)
    filters, matching_page, excluded_page = _attached_form_filter_context(user)

    (
        filters.set_form_condition("Risk Score")
        .number("is greater than or equal to", "90")
        .add_filter()
    )

    results = filters.run()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @matrix filters : attached-form boolean-condition run-results
def test_category_filter_by_attached_form_checkbox_condition(get_user):
    user = get_user(Users.OWNER)
    filters, matching_page, excluded_page = _attached_form_filter_context(user)

    (
        filters.set_form_condition("Requires Follow Up").checkbox(True).add_filter()
    )

    results = filters.run()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @matrix filters : attached-form run-results select-condition
def test_category_filter_by_attached_form_select_condition(get_user):
    user = get_user(Users.OWNER)
    filters, matching_page, excluded_page = _attached_form_filter_context(user)

    (
        filters.set_form_condition("Review Decision")
        .choice("Approved")
        .add_filter()
    )

    results = filters.run()
    _expect_result_includes_excludes(results, matching_page, excluded_page)


# @matrix filters : reload-persistence save saved-filters
# @pairs polling:category-index reconnect-refresh:category-index
# @template categories/index.html::view
def test_category_saved_filter_save_and_run(get_user, browser_failures):
    user = get_user(Users.OWNER)
    category, matching_page, excluded_page, _, _ = _category_filter_context(user)
    user.go(category)

    filters = Filters(user, category)
    filters.set_condition(CategoryFilterConditions.NAME)
    filters.name_contains("Urgent").add_filter()

    saved_filter = filters.save_filter()
    filter_key = saved_filter.get_attribute("data-key")

    user.reload(category)
    tools = Tools(user)
    tools.open()
    with user.page.expect_response("**/filters/*/get"):
        tools.locate(category.SAVED_FILTERS_TOGGLE).click()

    reloaded_saved = tools.locate("[data-role='saved-filters']")
    reloaded_filter = reloaded_saved.locator(f"li[data-key='{filter_key}']")
    expect(reloaded_filter).to_be_visible()
    expect(reloaded_filter).to_contain_text(CategoryFilterConditions.NAME.value)

    with user.page.expect_navigation():
        reloaded_filter.locator("a[href*='/filters/']").click()
    user.page.wait_for_selector("[lp-view][initialized]")

    root = user.locate("[lp-view]")
    expect(root).to_have_attribute("data-key", filter_key)
    expect(root).to_have_attribute("data-poll-channel", "categories")
    assert root.get_attribute("data-fingerprint")
    assert root.get_attribute("data-poll-revision")

    table = user.locate("#table")
    expect(
        table.locator("tr").filter(has_text=matching_page.definition.name)
    ).to_be_visible()
    expect(
        table.locator("tr").filter(has_text=excluded_page.definition.name)
    ).not_to_be_visible()

    refreshed_page = Page(
        user=user,
        definition=replace(
            matching_page.definition,
            name=f"Urgent Filter Reconnect Page {uuid4().hex}",
        ),
    )
    refreshed_row = table.locator("tr").filter(
        has_text=refreshed_page.definition.name
    )
    expect(refreshed_row).not_to_be_attached()

    with expect_poll_result(
        user.page,
        subscription_id="view:channel:categories",
    ):
        with expect_reconnect_refresh(user, browser_failures):
            refreshed_page.create()
            user.offline = False

    expect(refreshed_row).to_be_visible()
