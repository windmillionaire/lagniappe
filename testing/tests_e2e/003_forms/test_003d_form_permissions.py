import pytest
import requests
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Categories, Forms, SitePages, Users
from testing.elements import Tools
from testing.resources.form import Builder
from testing.resources.site import FormIndex
from testing.utility import manual_mutation_headers

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


# @features forms ai
# @dimensions submitted-reference
def test_schema_generation_requires_edit_access_to_submitted_form(get_user):
    owner = get_user(Users.OWNER)
    form = Forms.test_owner_restricted_form.get(owner)
    form.builder.restrict_to_owner()

    admin = get_user(Users.admin)
    admin.go(SitePages.FORM_INDEX)
    persisted_before = Entities.fetch_one(form.key, request=Fetch.direct())
    assert not persisted_before.allowed(Action.EDIT, user=admin.entity)
    before = (persisted_before.schema, persisted_before.modified)
    cookies = {
        cookie["name"]: cookie["value"] for cookie in admin.page.context.cookies()
    }
    headers = manual_mutation_headers(
        admin.page.url,
        admin.locate("#token").input_value(),
    )

    response = requests.post(
        f"{SETTINGS.test_config['BASE_URL']}/forms/create-schema",
        data={
            "form-key": form.key,
            "form-type": "task",
            "description": "Attempt to overwrite a restricted form.",
            "explain": "true",
        },
        cookies=cookies,
        headers=headers,
        allow_redirects=False,
        timeout=10,
    )
    assert response.status_code == 422
    assert response.text == "One or more selected items are unavailable."

    persisted_after = Entities.fetch_one(form.key, request=Fetch.direct())
    assert (persisted_after.schema, persisted_after.modified) == before
