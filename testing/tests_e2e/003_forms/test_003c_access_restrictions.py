from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Forms, Groups, SitePages, Users
from testing.elements import Select, Table
from testing.resources.form import Builder, Form

pytestmark = pytest.mark.e2e


# @matrix forms : access-restrictions owner-restricted
# @template forms/restrictions.html::restrict_access
def test_owner_can_restrict_form_to_site_owner(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    form = Forms.test_owner_restricted_form.get(owner)

    form.builder.restrict_to_owner()

    viewer = get_user(Users.general_forms_view_only)
    with browser_failures.expect_http_error(viewer, status=403, path=form.url):
        viewer.navigate(form.url)
        expect(viewer.page).to_have_title("Error 403")


# @matrix forms : access-restrictions group-restricted
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


# @matrix forms : access-restrictions index-filter
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


# @matrix forms : access-restrictions explicit-submit group-restricted owner-restricted
# @source lagniappe/web/routes/forms/main.py::restrictions
# @template forms/restrictions.html::restrict_access
def test_form_admin_only_replaces_groups_until_explicitly_selected_again(get_user):
    owner = get_user(Users.OWNER)
    group = Groups.general_forms_view_only.get(owner)
    form = Form(user=owner)
    form.entity = Entities.FORM.create({
        "name": f"Exclusive restrictions {uuid4().hex[:12]}", "form-type": "page",
    })
    form.entity.groups = [group.entity]
    form.entity.save()

    builder = form.builder
    restrictions = builder.restrictions()
    expect(restrictions.locator("input[name='group-key']")).to_have_count(1)
    restrictions.locator(Builder.SPECIFIC_ACCESS_OWNER).check()
    expect(restrictions.locator("input[name='group-key']")).to_have_count(0)
    assert Entities.fetch_one(form.key, request=Fetch.root()).db["restricted_to"] == [group.entity.hash]

    builder.save_restrictions()
    saved = Entities.fetch_one(form.key, request=Fetch.root())
    assert saved.db["restricted_to"] == ["admin"]
    assert not saved.db.get("groups")

    builder = form.builder
    restrictions = builder.restrictions()
    expect(restrictions.locator(Builder.SPECIFIC_ACCESS_OWNER)).to_be_checked()
    expect(restrictions.locator("input[name='group-key']")).to_have_count(0)
    restrictions.locator(Builder.SPECIFIC_ACCESS_OWNER).uncheck()
    expect(restrictions.locator("input[name='group-key']")).to_have_count(0)
    assert Entities.fetch_one(form.key, request=Fetch.root()).db["restricted_to"] == ["admin"]
    builder.save_restrictions()
    assert not Entities.fetch_one(form.key, request=Fetch.root()).db.get("restricted_to")

    restrictions.locator(Builder.SPECIFIC_ACCESS_OWNER).check()
    Select(restrictions.locator(Builder.RESTRICT_GROUP_INPUT)).select_by_key(
        group.key, query=group.definition.name,
    )
    expect(restrictions.locator(Builder.SPECIFIC_ACCESS_OWNER)).not_to_be_checked()
    expect(restrictions.locator("input[name='group-key']")).to_have_count(1)
    assert not Entities.fetch_one(form.key, request=Fetch.root()).db.get("restricted_to")
    builder.save_restrictions()

    saved = Entities.fetch_one(form.key, request=Fetch.root())
    assert saved.db["restricted_to"] == [group.entity.hash]
    assert saved.db["groups"] == [group.entity.key]
    restrictions = form.builder.restrictions()
    expect(restrictions.locator(Builder.SPECIFIC_ACCESS_OWNER)).not_to_be_checked()
    expect(restrictions.locator("input[name='group-key']")).to_have_count(1)
