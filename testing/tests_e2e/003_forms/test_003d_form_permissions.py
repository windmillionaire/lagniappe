"""
Permission tests for form index and form builder templates.

Verified against:
    - lagniappe/web/templates/forms/index.html
    - lagniappe/web/templates/forms/builder.html
    - lagniappe/web/routes/forms/main.py
"""

import pytest
from playwright.sync_api import expect

from testing.definitions import Categories, Forms, SitePages, Users
from testing.elements import Tools
from testing.resources.form import Builder
from testing.resources.site import FormIndex

pytestmark = pytest.mark.e2e


# @features forms
# @dimensions permission-gates index-view
# @template forms/index.html::view
def test_form_index_forbidden_without_forms_view(get_user, browser_failures):
    user = get_user(Users.user_one_category)
    Categories.test_create_category_manual_mode.get(user)
    url = SitePages.FORM_INDEX.get(user).url
    with browser_failures.expect_http_error(user, status=403, path=url):
        user.navigate(url)
        expect(user.page).to_have_title("Error 403")


# @features forms
# @dimensions index-view create-control
# @template forms/index.html::view
def test_form_index_lists_forms_but_hides_create_without_forms_create(get_user):
    owner = get_user(Users.OWNER)
    Forms.test_create_page_form.get(owner)

    viewer = get_user(Users.general_forms_view_only)
    viewer.go(SitePages.FORM_INDEX)

    expect(viewer.locate(FormIndex.TABLE_BODY)).to_have_attribute("loaded", "")
    expect(viewer.locate("#tools[lp-component]")).not_to_be_attached()
    expect(viewer.locate(FormIndex.CREATE_FORM_BUTTON)).not_to_be_attached()


# @features forms
# @dimensions index-view create-control
# @template forms/index.html::view
def test_form_index_shows_create_for_user_with_forms_create(get_user):
    user = get_user(Users.admin)
    user.go(SitePages.FORM_INDEX)

    expect(user.locate("#tools[lp-component]")).to_be_attached()
    tools = Tools(user)
    tools.open()
    expect(user.locate(FormIndex.CREATE_FORM_BUTTON)).to_be_visible()


# @features forms
# @dimensions builder-edit permission-gates
# @template forms/builder.html::main
def test_form_builder_hides_edit_affordances_without_forms_edit(get_user):
    owner = get_user(Users.OWNER)
    form = Forms.test_create_page_form.get(owner)

    viewer = get_user(Users.general_forms_view_only)
    form.user = viewer
    form.builder

    expect(viewer.locate(Builder.FORM_NAME)).to_be_visible()
    readonly_notice = viewer.locate(Builder.READONLY_NOTICE)
    expect(readonly_notice).to_be_visible()
    expect(readonly_notice).to_contain_text("Read-only mode")
    expect(readonly_notice).to_contain_text(
        "You can explore the builder and preview changes, "
        "but your changes won't be saved."
    )
    expect(viewer.locate(Builder.SAVE_BUTTON)).not_to_be_attached()
    expect(viewer.locate("[data-role='form-settings']")).not_to_be_attached()
    expect(viewer.locate("[data-role='generate']")).not_to_be_attached()


# @features forms
# @dimensions builder-edit permission-gates
# @template forms/builder.html::main
def test_form_builder_shows_edit_affordances_with_forms_edit(get_user):
    owner = get_user(Users.OWNER)
    form = Forms.test_create_page_form.get(owner)

    user = get_user(Users.admin)
    form.user = user
    form.builder

    expect(user.locate(Builder.READONLY_NOTICE)).not_to_be_attached()
    expect(user.locate(Builder.SAVE_BUTTON)).to_be_attached()
    expect(user.locate("[data-role='form-settings']")).to_be_attached()
    expect(user.locate("[data-role='generate']")).to_be_attached()


# @features forms
# @dimensions restriction-control permission-gates
# @template forms/restrictions.html::restrict_access
def test_form_builder_restrictions_visible_only_for_site_owner(get_user):
    owner = get_user(Users.OWNER)
    form = Forms.test_create_page_form.get(owner)

    admin = get_user(Users.admin)
    form.user = admin
    form.builder
    expect(admin.locate("[data-role='restrict-access']")).not_to_be_attached()

    form.user = owner
    form.builder
    expect(owner.locate("[data-role='restrict-access']")).to_be_attached()
