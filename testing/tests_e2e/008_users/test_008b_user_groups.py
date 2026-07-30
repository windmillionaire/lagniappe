import re

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import General, Levels, Site
from testing.definitions import Users, SitePages, Groups, Permissions
from testing.elements import Buttons, Modal, SpinnerButtons, PermissionsForm, Table

pytestmark = pytest.mark.e2e


def _set_and_verify_permissions(user, group, permissions):
    permissions_form = PermissionsForm(user, group)
    expect(permissions_form.form).to_be_visible()

    for p in permissions.definition:
        resource = p[0].get(user) if hasattr(p[0], "get") else p[0]
        permissions_form.set(resource, p[1])

    permissions_form.submit()
    for p in permissions.definition:
        resource = p[0].get(user) if hasattr(p[0], "get") else p[0]
        permissions_form.verify(resource, p[1])


def _create_group(user, user_index, group):
    groups = user_index.create_user_group_form
    name = group.definition.name
    groups.locator(user_index.GROUP_NAME_INPUT).fill(name)

    with user.page.expect_response("**/create-group") as response_info:
        SpinnerButtons.CREATE.click(groups)

    response = response_info.value
    assert response.ok, response.text()
    created_keys = set(re.findall(r'data-key="([^"]+)"', response.text()))
    assert len(created_keys) == 1, "Create-group response did not identify one group"
    group.key = created_keys.pop()

    title = f"{name} Permissions"
    title_matches = user.locate(f"[data-title='{title}']")
    expect(title_matches).to_have_count(1)
    permissions_widget = user.locate(
        f"form[data-key='{group.key}'][data-title='{title}']"
    )
    expect(permissions_widget).to_have_count(1)
    expect(permissions_widget).to_be_visible()

    return title


# @features user-groups
# @dimensions column-link query-route same-page-navigation reload
# @template common.html::format_name
# @template users/tools.html::group_permissions
def test_group_column_link_opens_group_tools_and_tracks_url(get_user):
    """A group cell deep-link opens its permissions and survives a reload."""
    owner = get_user(Users.OWNER)
    member = get_user(Users.general_users_view_only, creator=owner)
    group = Groups.general_users_view_only.get(owner)
    user_index = owner.go(SitePages.USER_INDEX)

    row = owner.locate(f"#table tbody tr[data-key='{member.key}']")
    expect(row).to_be_visible()
    group_link = row.locator("td[data-column='groups'] a[data-kind='group']")
    expect(group_link).to_have_attribute(
        "href", re.compile(rf"/users/index\?group={re.escape(group.key)}$")
    )

    group_link.click()

    permissions = owner.locate(
        f"form[data-widget^='GroupPermissions/'][data-key='{group.key}']"
    )
    expect(permissions).to_be_visible()
    expect(owner.page).to_have_url(
        re.compile(rf"/users/index\?group={re.escape(group.key)}$")
    )

    owner.reload(user_index)
    expect(permissions).to_be_visible()

    owner.locate(user_index.GROUPS_NAV).locator(
        "button[lp-control='reset']"
    ).click()
    expect(owner.page).to_have_url(re.compile(r"/users/index$"))


# @features user-groups
# @dimensions group-create nav permission-update general-permissions
# @template users/tools.html::create_user_group
# @template users/tools.html::group_permissions
def test_set_general_permissions(get_user):
    user = get_user(Users.OWNER)
    user_index = user.go(SitePages.USER_INDEX)
    group = Groups.test_set_general_permissions.get(user, create=False)

    nav_title = _create_group(user, user_index, group)

    groups_nav = user.locate(user_index.GROUPS_NAV)
    expect(groups_nav.locator('[data-role="title"]')).to_have_text(nav_title)
    permissions = Permissions.test_set_general.get(user)

    _set_and_verify_permissions(user, group, permissions)


# @features user-groups
# @dimensions group-create nav permission-update entity-permissions selection-render responsive-layout
# @template users/tools.html::create_user_group
# @template users/tools.html::group_permissions
def test_set_entity_specific_permissions(get_user):
    user = get_user(Users.OWNER)
    user_index = user.go(SitePages.USER_INDEX)
    group = Groups.test_set_entity_specific_permissions.get(user, create=False)

    nav_title = _create_group(user, user_index, group)

    groups_nav = user.locate(user_index.GROUPS_NAV)
    expect(groups_nav.locator('[data-role="title"]')).to_have_text(nav_title)
    permissions = Permissions.test_set_entity_specific.get(user)

    _set_and_verify_permissions(user, group, permissions)


# @features user-groups
# @dimensions group-create rename permission-update nav reload
# @template users/tools.html::group_permissions
# @template users/tools.html::group_selector
def test_rename_group(get_user):
    """A group name can be changed from its permissions panel."""
    user = get_user(Users.OWNER)
    user_index = user.go(SitePages.USER_INDEX)
    group = Groups.rename_group.get(user, create=False)
    _create_group(user, user_index, group)

    permissions = PermissionsForm(user, group)
    renamed = "Renamed User Group"
    name_input = permissions.form.locator("input[name='name']")
    expect(name_input).to_have_value(group.definition.name)
    name_input.fill(renamed)
    expect(name_input).to_have_value(renamed)
    permissions.submit()

    groups = user.locate(user_index.USER_GROUPS_COMPONENT)
    selector = groups.locator(f"button[data-key='{group.key}']")
    expect(selector.locator("[data-role='group-name']")).to_have_text(renamed)
    expect(permissions.form).to_have_attribute(
        "data-title", f"{renamed} Permissions"
    )
    expect(groups.locator("[data-role='title']")).to_have_text(
        f"{renamed} Permissions"
    )
    expect(name_input).to_have_value(renamed)

    user.reload(user_index)
    expect(selector.locator("[data-role='group-name']")).to_have_text(renamed)
    expect(name_input).to_have_value(renamed)


# @features public-groups permissions
# @dimensions public active permission-update
# @template users/tools.html::public_permissions
def test_set_public_permissions(get_user):
    owner = get_user(Users.OWNER)
    user_index = owner.go(SitePages.USER_INDEX)
    public_form = user_index.public_permissions_form
    permissions_form = PermissionsForm(owner, form=public_form)

    permissions_form.set(Site.PUBLIC, Levels.FALSE)
    permissions_form.submit()
    permissions_form.verify(Site.PUBLIC, Levels.FALSE)

    anonymous = get_user(Users.ANONYMOUS)
    login_page = anonymous.go(SitePages.LOGIN_PAGE)
    expect(anonymous.locate(login_page.EMAIL_CHECK_FORM)).to_be_visible()
    expect(anonymous.locate(login_page.SIGN_IN_FORM)).not_to_be_visible()

    try:
        permissions_form.set(Site.PUBLIC, Levels.TRUE)
        permissions_form.set(General.MODELS, Levels.VIEW)
        permissions_form.set(General.FORMS, Levels.VIEW)
        permissions_form.submit()
        permissions_form.verify(Site.PUBLIC, Levels.TRUE)

        anonymous = get_user(Users.ANONYMOUS)
        login_page = anonymous.go(SitePages.LOGIN_PAGE)
        sign_in = anonymous.locate(login_page.SIGN_IN_FORM)
        expect(sign_in).to_be_visible()
        expect(sign_in.locator("button[data-role='switch-to-create']")).to_be_visible()
        expect(anonymous.locate(login_page.EMAIL_CHECK_FORM)).not_to_be_visible()
    finally:
        user_index = owner.go(SitePages.USER_INDEX)
        public_form = user_index.public_permissions_form
        permissions_form = PermissionsForm(owner, form=public_form)
        permissions_form.set(Site.PUBLIC, Levels.FALSE)
        permissions_form.submit()


# @features user-groups
# @dimensions group-delete nav-refresh polling
# @template users/tools.html::group_nav
def test_delete_group_refreshes_group_navigation(get_user):
    user = get_user(Users.OWNER)
    user_index = user.go(SitePages.USER_INDEX)
    group = Groups.delete_group_refreshes_navigation.get(user, create=False)

    _create_group(user, user_index, group)

    groups = user.locate(user_index.USER_GROUPS_COMPONENT)
    selector = groups.locator(f"button[data-key='{group.key}']")
    form = groups.locator(f"form[data-key='{group.key}']")
    expect(selector).to_have_count(1)
    expect(form).to_be_visible()

    delete_button = groups.locator(Buttons.LP_DELETE)
    expect(delete_button).to_be_visible()
    with user.page.expect_response("**/delete-group/*"):
        Modal(user.page).open(delete_button).delete()

    expect(selector).to_have_count(0)
    expect(form).to_have_count(0)
    expect(groups.locator("[data-role='title']")).to_have_text("User Groups")
