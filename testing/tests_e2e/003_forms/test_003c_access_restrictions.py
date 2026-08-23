import pytest
from playwright.sync_api import expect

from testing.definitions import Forms, Groups, SitePages, Users
from testing.elements import Table
from testing.resources.form import Builder

pytestmark = pytest.mark.e2e


# @features forms
# @dimensions access-restrictions owner-restricted
# @template forms/restrictions.html::restrict_access
def test_owner_can_restrict_form_to_site_owner(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    form = Forms.test_owner_restricted_form.get(owner)

    form.builder.restrict_to_owner()

    viewer = get_user(Users.general_forms_view_only)
    with browser_failures.expect_http_error(viewer, status=403, path=form.url):
        viewer.navigate(form.url)
        expect(viewer.page).to_have_title("Error 403")


# @features forms
# @dimensions access-restrictions group-restricted
# @template forms/restrictions.html::restrict_access
def test_group_restricted_form_opens_for_group_member_only(
    get_user, browser_failures
):
    owner = get_user(Users.OWNER)
    form = Forms.test_group_restricted_form.get(owner)
    group = Groups.general_forms_view_only.get(owner)

    form.builder.restrict_to_group(group)

    member = get_user(Users.general_forms_view_only)
    form.user = member
    form.builder
    expect(member.locate(Builder.FORM_NAME)).to_have_text(form.definition.name)

    outsider = get_user(Users.admin)
    with browser_failures.expect_http_error(outsider, status=403, path=form.url):
        outsider.navigate(form.url)
        expect(outsider.page).to_have_title("Error 403")


# @features forms
# @dimensions access-restrictions index-filter
def test_form_index_lists_group_restricted_form_only_for_group_member(get_user):
    owner = get_user(Users.OWNER)
    form = Forms.test_index_restricted_form.get(owner)
    group = Groups.general_forms_view_only.get(owner)
    form.builder.restrict_to_group(group)

    member = get_user(Users.general_forms_view_only)
    member.go(SitePages.FORM_INDEX)
    member_table = Table(member)
    expect(member_table.get_row(form.definition.name)).to_be_visible()

    outsider = get_user(Users.admin)
    outsider.go(SitePages.FORM_INDEX)
    outsider_table = Table(outsider)
    expect(outsider_table.get_row(form.definition.name)).not_to_be_attached()
