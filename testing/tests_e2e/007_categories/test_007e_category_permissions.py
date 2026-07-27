"""
Category permission and restriction behavior (home, search, index, create).

Templates:
    - lagniappe/web/templates/categories/index.html
    - lagniappe/web/templates/categories/tools.html
Routes:
    - lagniappe/web/routes/categories/main.py
    - lagniappe/web/routes/pages/main.py (create page)

If an assertion fails in a way that contradicts the intended product behavior,
do not weaken the test silently: treat it as a possible bug and investigate
with the team (see category-permissions plan risks).
"""

import re

import pytest
from playwright.sync_api import expect

from testing.definitions import Categories, Pages, SitePages, Users
from testing.elements import HeaderSearch, Table, Tools
from testing.resources.category import Category

pytestmark = pytest.mark.e2e


# @features categories
# @dimensions permission-gates index-filter
def test_page_acl_user_sees_one_page_on_category_index_home_and_search(get_user):
    """
    Group has VIEW on one page only in a category with two pages (parent category
    RESTRICTED in permissions, mirroring UI-created groups).

    Expect: category index lists only that page; restricted category appears on home
    for navigation but not in search; permitted page appears in search, hidden page
    does not. If category index is 403 or home omits the category, fail with guidance.
    """
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


# @features categories
# @dimensions create-control permission-gates
def test_category_create_scoped_to_one_category(get_user):
    """
    User has CATEGORY EDIT on ``acl_create_allowed``, CATEGORY VIEW on
    ``acl_create_denied``, and General.FORMS VIEW (no global MODELS VIEW).

    Allowed category: tools panel with New Page / Generate / category settings /
    filters. Denied category: same tools shell with settings + filters, but no
    create or generate affordances.

    Other permission gates on this view (not asserted here — add tests if they
    regress):
        - ``view_header``: star (no category gate); table column editor requires
          EDIT; tools dropdown requires CREATE | EDIT | VIEW.
        - ``tools.html``: default-form / page-form pickers require
          ``Resource.FORMS.allowed(VIEW)`` inside CategoryInfo, CreatePage,
          GeneratePages.
    """
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


# @features categories
# @dimensions readonly default-form
# @template categories/index.html::tools_section
# @template categories/tools.html::category_info
def test_category_viewer_opens_readonly_settings(get_user):
    """VIEW-only users can open category settings without edit-only controls."""
    owner = get_user(Users.OWNER)
    category = Categories.test_category_readonly_settings.get(owner)
    form = category.definition.form.get(owner)
    description = "Readonly category settings description."
    category.entity.description = description
    category.entity.save()

    subject = get_user(Users.models_forms_view_only)
    subject.go(category)

    tools = Tools(subject)
    tools.open()

    settings = tools.locate(Category.CATEGORY_INFO_WIDGET)
    expect(settings).to_be_visible()
    expect(settings).to_have_attribute("data-readonly", "true")
    expect(settings.locator("#name")).to_contain_text(category.definition.name)
    expect(settings.locator("#description")).to_contain_text(description)
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
