import re
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe.core.definitions import Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Categories, Groups, Pages, Users
from testing.elements import Select, Table, Tabs
from testing.resources import Page, Task
from testing.utility.network import browser_fetch, expect_successful_response

pytestmark = pytest.mark.e2e


def _open_page_permissions(user, page):
    user.go(page)
    Tabs(user).info
    toggle = user.locate(Page.PAGE_PERMISSIONS_TOGGLE)
    expect(toggle).to_be_visible()
    toggle.click()

    permissions = user.locate(Page.PAGE_PERMISSIONS_FORM)
    expect(permissions).to_be_visible()
    return permissions


def _restrict_page_to_owner(user, page):
    permissions = _open_page_permissions(user, page)
    owner_checkbox = permissions.locator(Page.PAGE_RESTRICT_OWNER)
    expect(owner_checkbox).to_be_visible()

    if not owner_checkbox.is_checked():
        owner_checkbox.check()
        permissions = _save_page_restrictions(user, page)

    expect(permissions.locator(Page.PAGE_RESTRICT_OWNER)).to_be_checked()
    return permissions


def _restrict_page_to_group(user, page, group):
    permissions = _open_page_permissions(user, page)
    group_list = permissions.locator(Page.PAGE_RESTRICTED_GROUP_LIST)
    owner_checkbox = permissions.locator(Page.PAGE_RESTRICT_OWNER)
    changed = owner_checkbox.is_checked()
    owner_checkbox.uncheck()

    if group_list.filter(has_text=group.definition.name).count() == 0:
        group_input = permissions.locator(Page.PAGE_RESTRICT_GROUP_INPUT)
        expect(group_input).to_be_visible()
        expect(group_input).to_have_attribute("data-combobox-id", re.compile(".+"))
        Select(group_input).select_by_key(
            group.key,
            query=group.definition.name,
        )
        changed = True

    if changed:
        permissions = _save_page_restrictions(user, page)

    expect(
        permissions.locator(Page.PAGE_RESTRICTED_GROUP_LIST).filter(
            has_text=group.definition.name
        )
    ).to_be_visible()
    return permissions


def _save_page_restrictions(user, page):
    with expect_successful_response(
        user.page,
        method="PUT",
        path=f"/pages/{page.key}/view-access",
    ):
        user.locate(Page.PAGE_PERMISSIONS_FORM).get_by_role(
            "button", name="Save Restrictions", exact=True
        ).click()
    permissions = user.locate(Page.PAGE_PERMISSIONS_FORM)
    expect(permissions).to_be_visible()
    expect(permissions.locator("[data-icon='builder.unsaved']")).to_have_count(0)
    return permissions


# @matrix pages : access-restrictions owner-restricted
def test_owner_restricted_page_is_hidden_from_model_viewer(
    get_user, browser_failures
):
    owner = get_user(Users.OWNER)
    page = Pages.test_owner_restricted_page.get(owner)

    _restrict_page_to_owner(owner, page)

    viewer = get_user(Users.general_models_view_only)
    with browser_failures.expect_http_error(viewer, status=403, path=page.url):
        viewer.navigate(page.url)
        expect(viewer.page).to_have_title("Error 403")


# @matrix pages : access-restrictions group-restricted
# @template pages/restrictions.html::visible_to
def test_group_restricted_page_opens_for_member_only(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    page = Pages.test_group_restricted_page.get(owner)
    group = Groups.general_models_view_only.get(owner)

    _restrict_page_to_owner(owner, page)
    permissions = _restrict_page_to_group(owner, page, group)
    expect(permissions.locator(Page.PAGE_RESTRICT_OWNER)).not_to_be_checked()
    page_summary = permissions.locator(
        "[data-role='restriction-summary'][data-source='page']"
    )
    expect(page_summary.get_by_role("heading", name="Page restrictions")).to_be_visible()
    expect(page_summary.locator("[data-role='badges']")).to_contain_text(
        group.definition.name
    )
    expect(page_summary.locator("[data-role='badges'] > *")).to_have_count(1)

    member = get_user(Users.general_models_view_only)
    member.go(page)
    expect(member.locate(Page.PAGE_TITLE)).to_contain_text(page.definition.name)

    outsider = get_user(Users.admin)
    with browser_failures.expect_http_error(outsider, status=403, path=page.url):
        outsider.navigate(page.url)
        expect(outsider.page).to_have_title("Error 403")


# @matrix pages : access-restrictions index-filter
def test_restricted_page_is_not_listed_for_outsider_on_category_index(get_user):
    owner = get_user(Users.OWNER)
    page = Pages.test_group_restricted_page.get(owner)
    category = Categories.test_page_access_restrictions.get(owner)
    group = Groups.general_models_view_only.get(owner)
    _restrict_page_to_group(owner, page, group)

    member = get_user(Users.general_models_view_only)
    member.go(category)
    member_table = Table(member)
    expect(member_table.get_row(page.definition.name)).to_be_visible()

    outsider = get_user(Users.admin)
    outsider.go(category)
    outsider_table = Table(outsider)
    expect(outsider_table.get_row(page.definition.name)).not_to_be_attached()


# @matrix pages : access-restrictions explicit-submit group-restricted owner-restricted source-summary
# @pair tasks:page-task
# @source lagniappe/web/routes/tasks/main.py::view
# @template pages/restrictions.html::visible_to
# @template pages/restrictions.html::restrict_access
# @template pages/restrictions.html::restricted_group_list
def test_page_restrictions_save_drafts_and_show_each_source(get_user):
    owner = get_user(Users.OWNER)
    page_group = Groups.general_models_view_only.get(owner)
    form_group = Groups.general_forms_view_only.get(owner)
    token = uuid4().hex[:12]
    form = Entities.FORM.create({"name": f"Restriction form {token}", "form-type": "page"})
    form.groups = [form_group.entity]
    form.save()
    category = Entities.CATEGORY.create({"name": f"Restriction category {token}"})
    category.save()
    page = Page(user=owner)
    page.entity = Entities.PAGE.create(
        {"name": f"Restriction page {token}", "model": category, "form": form}
    )
    page.entity.save()
    permissions = _open_page_permissions(owner, page)
    page_summary = permissions.locator(
        "[data-role='restriction-summary'][data-source='page']"
    )
    form_summary = permissions.locator(
        "[data-role='restriction-summary'][data-source='page_form']"
    )
    note = permissions.locator("[data-role='combined-restrictions-note']")
    expect(page_summary).to_have_count(0)
    expect(form_summary.get_by_role("heading", name="Form restrictions")).to_be_visible()
    expect(form_summary.locator("[data-role='badges']")).to_contain_text(form_group.definition.name)
    expect(form_summary.locator("[data-role='badges'] > *")).to_have_count(1)
    expect(note).to_have_count(0)

    requests = []
    save_path = f"/pages/{page.key}/view-access"

    def record_save(request):
        if request.method == "PUT" and urlsplit(request.url).path == save_path:
            requests.append(request)

    owner.page.on("request", record_save)
    try:
        Select(permissions.locator(Page.PAGE_RESTRICT_GROUP_INPUT)).select_by_key(
            page_group.key, query=page_group.definition.name
        )
        expect(permissions.locator(f"input[name='group-key'][value='{page_group.key}']")).to_have_count(1)
        expect(permissions.locator("[data-icon='builder.unsaved']")).to_be_visible()
        assert requests == []
        assert not Entities.fetch_one(page.key, request=Fetch.root()).db.get("restricted_to")
        expect(page_summary).to_have_count(0)

        permissions = _save_page_restrictions(owner, page)
        assert len(requests) == 1
        expect(page_summary.locator("[data-role='badges']")).to_contain_text(page_group.definition.name)
        expect(form_summary.locator("[data-role='badges']")).to_contain_text(form_group.definition.name)
        expect(page_summary.locator("[data-role='badges'] > *")).to_have_count(1)
        expect(form_summary.locator("[data-role='badges'] > *")).to_have_count(1)
        expect(page_summary.locator("[data-role='badges']")).not_to_contain_text(form_group.definition.name)
        expect(form_summary.locator("[data-role='badges']")).not_to_contain_text(page_group.definition.name)
        expect(note).to_contain_text("at least one group in each set")
        expect(note).to_contain_text("Administrators")
        assert Entities.fetch_one(page.key, request=Fetch.root()).db["restricted_to"] == [page_group.entity.hash]
        permissions.screenshot(path="/tmp/page-restrictions-ui.png")

        task = Task(user=owner)
        task.entity = Entities.TASK.create(
            {
                "name": f"Restriction task {token}",
                "page": Entities.fetch_one(page.key, request=Fetch.direct()),
            }
        )
        task.entity.save()
        owner.go(task)
        Tabs(owner).info
        owner.locate(Page.PAGE_PERMISSIONS_TOGGLE).click()
        expect(page_summary.locator("[data-role='badges']")).to_contain_text(page_group.definition.name)
        expect(form_summary.locator("[data-role='badges']")).to_contain_text(form_group.definition.name)

        permissions = _open_page_permissions(owner, page)
        expect(page_summary.locator("[data-role='badges']")).to_contain_text(page_group.definition.name)
        expect(form_summary.locator("[data-role='badges']")).to_contain_text(form_group.definition.name)
        permissions.locator(Page.PAGE_RESTRICT_OWNER).check()
        expect(permissions.locator("input[name='group-key']")).to_have_count(0)
        expect(permissions.locator("[data-icon='builder.unsaved']")).to_be_visible()
        assert len(requests) == 1
        assert Entities.fetch_one(page.key, request=Fetch.root()).db["restricted_to"] == [page_group.entity.hash]
        expect(page_summary.locator("[data-role='badges']")).to_contain_text(page_group.definition.name)

        permissions = _save_page_restrictions(owner, page)
        assert len(requests) == 2
        expect(page_summary.locator("[data-role='badges']")).to_contain_text("Administrators")
        expect(page_summary.locator("[data-role='badges'] > *")).to_have_count(1)
        expect(form_summary.locator("[data-role='badges']")).to_contain_text(form_group.definition.name)
        expect(note).to_have_count(0)
        assert Entities.fetch_one(page.key, request=Fetch.root()).db["restricted_to"] == ["admin"]
        assert not Entities.fetch_one(page.key, request=Fetch.root()).db.get("groups")
        expect(permissions.locator("input[name='group-key']")).to_have_count(0)

        permissions = _open_page_permissions(owner, page)
        expect(permissions.locator(Page.PAGE_RESTRICT_OWNER)).to_be_checked()
        expect(permissions.locator("input[name='group-key']")).to_have_count(0)
        expect(page_summary.locator("[data-role='badges']")).to_contain_text("Administrators")
        permissions.locator(Page.PAGE_RESTRICT_OWNER).uncheck()
        assert len(requests) == 2
        assert Entities.fetch_one(page.key, request=Fetch.root()).db["restricted_to"] == ["admin"]
        _save_page_restrictions(owner, page)
        assert len(requests) == 3
        expect(page_summary).to_have_count(0)
        expect(form_summary.locator("[data-role='badges']")).to_contain_text(form_group.definition.name)
        expect(note).to_have_count(0)
        assert not Entities.fetch_one(page.key, request=Fetch.root()).db.get("restricted_to")
        expect(permissions.locator("input[name='group-key']")).to_have_count(0)

        permissions.locator(Page.PAGE_RESTRICT_OWNER).check()
        Select(permissions.locator(Page.PAGE_RESTRICT_GROUP_INPUT)).select_by_key(
            page_group.key, query=page_group.definition.name
        )
        expect(permissions.locator(Page.PAGE_RESTRICT_OWNER)).not_to_be_checked()
        assert len(requests) == 3
        assert not Entities.fetch_one(page.key, request=Fetch.root()).db.get("restricted_to")
        permissions = _save_page_restrictions(owner, page)
        assert len(requests) == 4
        assert Entities.fetch_one(page.key, request=Fetch.root()).db["restricted_to"] == [page_group.entity.hash]
        expect(page_summary.locator("[data-role='badges']")).to_contain_text(page_group.definition.name)
    finally:
        owner.page.remove_listener("request", record_save)


# @matrix pages : access-restrictions source-summary
# @template pages/restrictions.html::visible_to
@pytest.mark.parametrize("form_admin_only", [False, True])
def test_page_restriction_summary_does_not_invent_local_badges(get_user, form_admin_only):
    owner = get_user(Users.OWNER)
    token = uuid4().hex[:12]
    form = Entities.FORM.create({"name": f"Summary form {token}", "form-type": "page"})
    if form_admin_only:
        form.properties.restricted_to.materialize(admin_only=True)
    form.save()
    category = Entities.CATEGORY.create({"name": f"Summary category {token}"})
    category.save()
    page = Page(user=owner)
    page.entity = Entities.PAGE.create(
        {"name": f"Summary page {token}", "model": category, "form": form}
    )
    page.entity.save()

    permissions = _open_page_permissions(owner, page)
    page_summary = permissions.locator(
        "[data-role='restriction-summary'][data-source='page']"
    )
    form_summary = permissions.locator(
        "[data-role='restriction-summary'][data-source='page_form']"
    )
    expect(page_summary).to_have_count(0)
    if form_admin_only:
        expect(form_summary.locator("[data-role='badges'] > *")).to_have_count(1)
        expect(form_summary.locator("[data-role='badges']")).to_contain_text("Administrators")
    else:
        expect(form_summary).to_have_count(0)
        expect(permissions.locator("[data-role='visible-to']")).to_be_hidden()
    expect(permissions.locator("[data-role='combined-restrictions-note']")).to_have_count(0)


# @matrix pages : access-restrictions submitted-reference
# @source lagniappe/web/routes/pages/main.py::_apply_page_access_restrictions
def test_page_restrictions_reject_non_group_references(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    group = Groups.general_models_view_only.get(owner)
    token = uuid4().hex[:12]
    category = Entities.CATEGORY.create({"name": f"Restriction validation {token}"})
    category.save()
    page = Page(user=owner)
    page.entity = Entities.PAGE.create(
        {"name": f"Validate restrictions {token}", "model": category}
    )
    page.entity.groups = [group.entity]
    page.entity.save()
    owner.go(page)
    modified = page.entity.modified
    path = f"/pages/{page.key}/view-access"

    with browser_failures.expect_http_error(owner, status=422, path=path):
        response = browser_fetch(
            owner,
            path,
            method="PUT",
            data={"group-key": page.key},
        )
    assert response["status"] == 422
    assert response["text"] == "One or more selected items are unavailable."
    saved = Entities.fetch_one(page.key, request=Fetch.root())
    assert saved.modified == modified
    assert saved.db["restricted_to"] == [group.entity.hash]

    permissions = _open_page_permissions(owner, page)
    expect(
        permissions.locator(
            "[data-role='restriction-summary'][data-source='page'] [data-role='badges']"
        )
    ).to_contain_text(group.definition.name)
    expect(
        permissions.locator(
            "[data-role='restriction-summary'][data-source='page'] [data-role='badges'] > *"
        )
    ).to_have_count(1)
