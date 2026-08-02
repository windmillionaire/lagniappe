import json
import re
from types import SimpleNamespace
from uuid import uuid4

from playwright.sync_api import expect
import pytest

from lagniappe.core.definitions import Fetch, Levels, Site
from lagniappe.core.entities import Entities
from testing.definitions import Categories, Groups, SitePages, Users
from testing.elements import (
    Dropdown,
    MobileTableControls,
    Modal,
    PermissionsForm,
    Select,
    SpinnerButtons,
    Table,
    Tabs,
)
from testing.resources import Page
from testing.utility import expect_reconnect_refresh

pytestmark = pytest.mark.e2e

"""
Tests for the Users index page (/users).

Tests user list, user creation, user groups, and permissions management.
Verified against:
- lagniappe/templates/users/index.html
- lagniappe/templates/users/tools.html
- src/script/views/indexes/user.mjs
- src/script/views/forms/user.mjs
- src/script/components/permissions.mjs
"""


def _set_public_users_allowed(owner, enabled):
    user_index = owner.go(SitePages.USER_INDEX)
    permissions = PermissionsForm(
        owner,
        form=user_index.public_permissions_form,
    )
    permissions.set(Site.PUBLIC, Levels.TRUE if enabled else Levels.FALSE)
    permissions.submit()


def _create_public_user(email, name):
    user = Entities.USER.create(
        {
            "email": email,
            "name": name,
            "is_public": True,
            "test_user": True,
        }
    )
    user.save()
    return user


def _user_rows_response(mode):
    suffix = "/users/rows?mode=public" if mode == "public" else "/users/rows"
    return lambda response: (
        response.request.method == "GET" and response.url.endswith(suffix)
    )


def _post_form_status(user, path, data):
    return user.page.evaluate(
        """async ({ path, data }) => {
            const send = async () => {
                const body = new FormData();
                for (const [key, value] of Object.entries(data)) {
                    body.set(key, value);
                }
                return fetch(path, {
                    method: "POST",
                    credentials: "include",
                    headers: {
                        "X-CSRFToken":
                            document.getElementById("token")?.value || "",
                        "X-Lagniappe-Request": "true",
                    },
                    body,
                });
            };

            let response = await send();
            if (response.status === 400) {
                const token = await (await fetch("/token")).text();
                const tokenElt = document.getElementById("token");
                if (tokenElt) tokenElt.value = token;
                response = await send();
            }
            return response.status;
        }""",
        {"path": path, "data": data},
    )


# @features users
# @dimensions index-mode-toggle disabled
# @template users/index.html::public_users_toggle
def test_users_index_public_toggle_hidden_when_public_users_disabled(get_user):
    owner = get_user(Users.OWNER)
    _set_public_users_allowed(owner, False)

    user_index = owner.go(SitePages.USER_INDEX)

    expect(owner.locate(user_index.PUBLIC_USERS_TOGGLE)).to_have_count(0)


# @pair users:index-mode-toggle
# @pair users:table-row
# @pair users:refresh
# @pair reconnect-refresh:batched-request
# @pair reconnect-refresh:root-fingerprint
# @pair permissions:authorization
# @template users/index.html::public_users_toggle
def test_users_index_public_toggle_shows_public_users(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    public_name = f"Public Toggle User {uuid4().hex}"
    public_email = f"{uuid4().hex}@public-toggle.example"
    refreshed_public_name = f"Reconnect Public User {uuid4().hex}"
    refreshed_public_email = f"{uuid4().hex}@public-toggle.example"

    try:
        _set_public_users_allowed(owner, True)
        _create_public_user(public_email, public_name)

        user_index = owner.go(SitePages.USER_INDEX)
        table = Table(owner)
        public_toggle = owner.locate(user_index.PUBLIC_USERS_TOGGLE_DESKTOP)

        expect(public_toggle).to_be_visible()
        expect(public_toggle).to_have_attribute("data-active", "false")
        expect(table.get_row(public_name)).to_have_count(0)
        expect(table.get_row(owner.name)).to_be_visible()

        with owner.page.expect_response(_user_rows_response("public")):
            public_toggle.click()

        expect(owner.locate("[lp-view]")).to_have_attribute("data-user-mode", "public")
        expect(owner.locate(user_index.TABLE_BODY)).to_have_attribute("loaded", "")
        expect(public_toggle).to_have_attribute("data-active", "true")
        expect(public_toggle).to_have_attribute("title", "Show regular users")
        expect(table.get_row(public_name)).to_be_visible()
        expect(table.get_row(owner.name)).to_have_count(0)

        root = owner.locate("[lp-view]")
        expect(root).to_have_attribute("data-fingerprint", re.compile(r"\S+"))
        fingerprint = root.get_attribute("data-fingerprint")
        refreshed_public_user = _create_public_user(
            refreshed_public_email,
            refreshed_public_name,
        )
        with expect_reconnect_refresh(owner, browser_failures) as refresh_info:
            owner.offline = False

        refresh_request = json.loads(refresh_info.value.request.post_data or "{}")
        assert refresh_request["view"]["index"] == "users"
        assert refresh_request["view"]["mode"] == "public"
        assert refresh_request["view"]["fingerprint"] == fingerprint
        assert {target["id"] for target in refresh_request["targets"]} == {"table"}
        refresh_payload = refresh_info.value.json()
        assert refresh_payload["fingerprint"] != fingerprint
        table_refresh = next(
            target for target in refresh_payload["targets"] if target["id"] == "table"
        )
        assert table_refresh["fallback"] is False
        assert refreshed_public_user.urlsafe_key in {
            row["key"] for row in table_refresh["upsert"]
        }

        expect(table.get_row(public_name)).to_be_visible()
        expect(table.get_row(refreshed_public_name)).to_be_visible()
        expect(table.get_row(owner.name)).to_have_count(0)

        with owner.page.expect_response(_user_rows_response("regular")):
            public_toggle.click()

        expect(owner.locate("[lp-view]")).to_have_attribute("data-user-mode", "regular")
        expect(owner.locate(user_index.TABLE_BODY)).to_have_attribute("loaded", "")
        expect(public_toggle).to_have_attribute("data-active", "false")
        expect(public_toggle).to_have_attribute("title", "Show public users")
        expect(table.get_row(public_name)).to_have_count(0)
        expect(table.get_row(owner.name)).to_be_visible()
    finally:
        _set_public_users_allowed(owner, False)


def _create_user(user, create_form, definition):
    with user.page.expect_response("**/create"):
        SpinnerButtons.CREATE.click(create_form)
    table = Table(user)
    new_row = table.new_row(definition.name)
    return new_row


# @features users
# @dimensions create-form create-submit created-row ai-access
# @template users/index.html::tools_section
# @template users/tools.html::create_user
def test_create_user_from_index(get_user):
    """
    Create a user through the user index tools panel UI.

    Opens the tools panel, fills name and email in the CreateUser
    widget, submits, and verifies the user appears in the table.
    """
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    created_user = SimpleNamespace(
        name=f"User from Index {suffix}",
        email=f"user-from-index-{suffix}@example.test",
    )
    user_index = owner.go(SitePages.USER_INDEX)
    create_form = user_index.create_user_form

    create_form.locator("label").filter(has_text="Name").locator(
        "input[name='name']"
    ).fill(created_user.name)
    create_form.locator("label").filter(has_text="Email").locator(
        "input[name='email']"
    ).fill(created_user.email)
    ai_options = create_form.locator("input[name='ai_access']")
    expect(ai_options).to_have_count(3)
    expect(
        create_form.locator("input[name='ai_access'][value='NONE']")
    ).to_be_checked()
    create_form.locator("input[name='ai_access'][value='ASK']").check()

    payload = create_form.evaluate(
        "form => Object.fromEntries(new FormData(form).entries())"
    )
    assert payload["name"] == created_user.name
    assert payload["email"] == created_user.email
    assert payload["ai_access"] == "ASK"

    new_row = _create_user(owner, create_form, created_user)
    assert Entities.USER.load(created_user.email).ai_access == "ASK"

    new_row.locator(Table.ENTITY_URL).click()
    expect(owner.page).to_have_title(re.compile(created_user.name))
    settings_toggle = owner.locate(Page.USER_SETTINGS_TOGGLE).first
    expect(settings_toggle).to_be_visible()
    settings_toggle.click()
    settings_panel = owner.locate(Page.USER_SETTINGS_FORM)
    expect(settings_panel).to_be_visible()
    expect(
        settings_panel.locator("input[name='ai_access'][value='ASK']")
    ).to_be_checked()


# @features users
# @dimensions owner-only
# @template users/tools.html::create_user
def test_non_owner_cannot_set_ai_access_when_creating_user(
    get_user, browser_failures
):
    owner = get_user(Users.OWNER)
    admin = get_user(Users.admin, creator=owner)
    suffix = uuid4().hex
    email = f"forged-ai-access-{suffix}@example.test"

    user_index = admin.go(SitePages.USER_INDEX)
    create_form = user_index.create_user_form
    expect(create_form).to_have_attribute("data-can-edit-ai", "false")
    expect(create_form.locator("input[name='ai_access']")).to_have_count(0)

    with browser_failures.expect_http_error(
        admin,
        status=403,
        path="/users/create",
    ):
        status = _post_form_status(
            admin,
            "/users/create",
            {
                "name": f"Forged AI Access {suffix}",
                "email": email,
                "ai_access": "CREATE",
            },
        )
    assert status == 403
    assert Entities.USER.load(email) is None


# @pair users:group-selector
# @pair users:multiple
# @template users/tools.html::create_user
def test_create_user_group_selector_accepts_multiple_groups(get_user):
    """A new user can be assigned to more than one group."""
    owner = get_user(Users.OWNER)
    first_group = Groups.general_users_view_only.get(owner)
    second_group = Groups.test_user_one_category.get(owner)
    suffix = uuid4().hex
    created_user = SimpleNamespace(
        name=f"Multi-group User {suffix}",
        email=f"multi-group-user-{suffix}@example.test",
    )
    user_index = owner.go(SitePages.USER_INDEX)
    create_form = user_index.create_user_form

    create_form.locator("input[name='name']").fill(created_user.name)
    create_form.locator("input[name='email']").fill(created_user.email)
    group_select = Select(
        create_form.locator("label").filter(has_text="User Group(s)")
    )
    expect(group_select.input).to_have_attribute("data-multiple", "true")
    group_select.select_by_name(first_group.definition.name)
    group_select.select_by_name(second_group.definition.name)

    selected_groups = create_form.evaluate(
        "form => new FormData(form).getAll('group')"
    )
    assert set(selected_groups) == {
        first_group.entity.urlsafe_key,
        second_group.entity.urlsafe_key,
    }

    new_row = _create_user(owner, create_form, created_user)
    saved_user = Entities.USER.load(created_user.email)
    assert {group.key for group in saved_user.groups} == {
        first_group.entity.key,
        second_group.entity.key,
    }

    new_row.locator(Table.ENTITY_URL).click()
    expect(owner.page).to_have_title(re.compile(created_user.name))
    settings_toggle = owner.locate(Page.USER_SETTINGS_TOGGLE).first
    expect(settings_toggle).to_be_visible()
    settings_toggle.click()
    groups = owner.locate(Page.USER_SETTINGS_FORM).locator(
        "[data-role='user-groups']"
    )
    expect(groups.locator("select[name='group'] option:checked")).to_have_count(2)
    group_input = Select(groups).input
    for group in (first_group, second_group):
        expect(
            groups.locator(
                "select[name='group'] "
                f"option[value='{group.entity.urlsafe_key}']:checked"
            )
        ).to_have_count(1)
        expect(group_input).to_have_attribute(
            "placeholder", re.compile(re.escape(group.definition.name))
        )


# @pair table-controls:mobile-startup
# @pair table-controls:mobile-tools
# @pair table-controls:sorting
# @template users/index.html::view_header
# @template table.html::mobile_toggles
def test_user_index_initializes_mobile_tools_and_sorting_on_mobile_load(get_user):
    """Loading the index at phone width initializes both mobile control paths."""
    owner = get_user(Users.OWNER)
    user_index = owner.go(SitePages.USER_INDEX)

    owner.mobile = True
    owner.page.reload()
    user_index.initialize_view()

    dropdown_button = owner.locate("[data-role='tools-dropdown']")
    expect(dropdown_button).to_be_visible()
    expect(dropdown_button).to_have_attribute("data-combobox-id", re.compile(".+"))
    Dropdown(dropdown_button).select_by_name("New User")
    expect(owner.locate(user_index.CREATE_USER_WIDGET)).to_be_visible()

    controls = MobileTableControls(owner)
    controls.open()
    controls.filter_button("name").click()

    sorting = owner.locate("#mobile-controls [data-sorts='name']")
    expect(sorting).to_be_visible()
    expect(
        sorting.locator('input[type="radio"][name="name"][value="asc"]')
    ).to_be_visible()


# @features users
# @dimensions create-form attach-existing-page page-form-preserved
def test_create_user_attached_to_existing_page_preserves_page_info_form(get_user):
    """Assigning a user to an existing form-backed page keeps normal PageInfo."""
    owner = get_user(Users.OWNER)
    category = Categories.test_basic_inputs_submission.get(owner)
    form = category.definition.form.get(owner)
    user_index = owner.go(SitePages.USER_INDEX)
    create_form = user_index.create_user_form

    suffix = uuid4().hex
    existing_page = Entities.PAGE.create(
        {
            "name": f"Attach Existing Page {suffix}",
            "model": category.entity,
            "form": form.entity,
            "attributes": [],
        }
    )
    existing_page.save()
    created_user = SimpleNamespace(
        name=f"Attached Page User {suffix}",
        email=f"attached-page-user-{suffix}@example.test",
    )

    create_form.locator("label").filter(has_text="Name").locator(
        "input[name='name']"
    ).fill(created_user.name)
    create_form.locator("label").filter(has_text="Email").locator(
        "input[name='email']"
    ).fill(created_user.email)
    page_select = create_form.locator("label").filter(
        has_text="Attach to Existing Page"
    )
    page_select = Select(page_select)
    page_select.input.fill(existing_page.name)
    page_select.select_by_key(existing_page.urlsafe_key)

    new_row = _create_user(owner, create_form, created_user)
    new_row.locator(Table.ENTITY_URL).click()

    expect(owner.page).to_have_title(re.compile(existing_page.name))
    assert existing_page.urlsafe_key in owner.page.url

    info_tab = Tabs(owner).info
    expect(info_tab).to_be_visible()
    info_form = info_tab.locator(Page.INFO_FORM)
    expect(info_form).to_be_visible()
    expect(info_form.locator("input[name='input-textab12']")).to_be_visible()

    settings_toggle = owner.locate(Page.USER_SETTINGS_TOGGLE).first
    expect(settings_toggle).to_be_visible()
    settings_toggle.click()
    settings_panel = owner.locate(Page.USER_SETTINGS_FORM)
    expect(settings_panel).to_be_visible()
    expect(settings_panel.locator("input[name='name']")).to_have_value(
        created_user.name
    )
    expect(settings_panel.locator("input[name='email']")).to_have_value(
        created_user.email
    )


# @pairs users:delete users:default-cascade users:preserve-page
# @pairs users:category-fallback users:options
# @pairs pages:delete pages:default-cascade pages:preserve-page
# @pair pages:category-fallback
def test_delete_user_can_preserve_page(get_user):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    cascade_user = Entities.USER.create(
        {
            "name": f"Cascade Page User {suffix}",
            "email": f"cascade-page-user-{suffix}@example.test",
            "test_user": True,
        }
    )
    cascade_user.save()
    cascade_user_key = cascade_user.key
    cascade_page_key = cascade_user.page.key

    created_user = Entities.USER.create(
        {
            "name": f"Preserve Page User {suffix}",
            "email": f"preserve-page-user-{suffix}@example.test",
            "test_user": True,
        }
    )
    created_user.save()
    user_key = created_user.key
    page_key = created_user.page.key

    try:
        owner.go(SitePages.USER_INDEX)
        cascade_row = Table(owner).get_row(cascade_user.name)
        expect(cascade_row).to_be_visible()

        cascade_row.locator("td[data-column='delete'] button[lp-delete]").click()
        cascade_modal = Modal(owner.page)
        cascade_delete_page = cascade_modal.element.locator(
            "input[name='delete-page']"
        )
        expect(cascade_delete_page).to_be_visible()
        expect(cascade_delete_page).to_be_checked()

        with owner.page.expect_response("**/users/*/delete") as response_info:
            cascade_modal.delete()

        expect(cascade_row).not_to_be_attached()
        assert response_info.value.request.post_data_json == {"delete-page": True}
        assert Entities.fetch_one(cascade_user_key, request=Fetch.root()) is None
        assert Entities.fetch_one(cascade_page_key, request=Fetch.root()) is None

        row = Table(owner).get_row(created_user.name)
        expect(row).to_be_visible()

        row.locator("td[data-column='delete'] button[lp-delete]").click()
        modal = Modal(owner.page)
        delete_page = modal.element.locator("input[name='delete-page']")
        expect(delete_page).to_be_visible()
        expect(delete_page).to_be_checked()
        delete_page.uncheck()

        with owner.page.expect_response("**/users/*/delete") as response_info:
            modal.delete()

        expect(row).not_to_be_attached()
        assert response_info.value.request.post_data_json == {"delete-page": False}
        assert Entities.fetch_one(user_key, request=Fetch.root()) is None

        preserved_page = Entities.fetch_one(page_key, request=Fetch.direct())
        assert preserved_page is not None
        assert preserved_page.user is None
        assert preserved_page.model.name == "Uncategorized Pages"

        owner.page.reload()
        expect(owner.locate("[lp-view]")).to_have_attribute("initialized", "")
        expect(Table(owner).get_row(cascade_user.name)).to_have_count(0)
        expect(Table(owner).get_row(created_user.name)).to_have_count(0)

        preserved_resource = Page(
            user=owner,
            definition=SimpleNamespace(name=preserved_page.name),
        )
        preserved_resource.entity = preserved_page
        owner.go(preserved_resource)
        expect(owner.page).to_have_title(re.compile(preserved_page.name))
        expect(owner.locate(Page.PAGE_TITLE)).to_contain_text(preserved_page.name)
        expect(owner.locate(Page.USER_SETTINGS_TOGGLE)).to_have_count(0)
    finally:
        cascade_page = Entities.fetch_one(cascade_page_key, request=Fetch.direct())
        if cascade_page:
            Entities.delete(cascade_page)
        preserved_page = Entities.fetch_one(page_key, request=Fetch.direct())
        if preserved_page:
            Entities.delete(preserved_page)
