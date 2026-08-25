import pytest
import requests
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe.core.definitions import Action, Fetch
from lagniappe.core.entities import Entities
from testing.definitions import Categories, Pages, Uploads, Users
from testing.definitions.schema_definitions import load_schema
from testing.elements import FormElements, Tabs
from testing.resources import File, Page
from testing.utility import manual_mutation_headers

pytestmark = pytest.mark.e2e


# @pair pages:permission-gates
def test_page_is_forbidden_without_model_or_page_permission(
    get_user, browser_failures
):
    owner = get_user(Users.OWNER)
    page = Pages.test_create_page.get(owner)

    blocked = get_user(Users.user_no_access)
    with browser_failures.expect_http_error(blocked, status=403, path=page.url):
        blocked.navigate(page.url)
        expect(blocked.page).to_have_title("Error 403")


# @matrix pages : load permission-gates readonly tabs
# @template pages/info.html::info_form
def test_page_viewer_reads_page_without_page_editing_affordances(get_user):
    owner = get_user(Users.OWNER)
    page = Pages.acl_lab_visible.get(owner)

    viewer = get_user(Users.page_acl_one_visible)
    viewer.go(page)

    tabs = Tabs(viewer)
    expect(tabs.info).to_be_visible()
    expect(viewer.locate(Tabs.DOCUMENT_TOGGLE_DESKTOP)).not_to_be_attached()
    expect(viewer.locate(Tabs.DOCUMENT_TAB)).not_to_be_attached()
    expect(tabs.tasks).to_be_visible()

    expect(viewer.locate(Page.CREATE_TASK_TOGGLE)).not_to_be_attached()
    expect(viewer.locate(Page.SITE_SETTINGS_TOGGLE)).not_to_be_attached()
    expect(viewer.locate(Page.PAGE_PERMISSIONS_TOGGLE)).not_to_be_attached()

    info_form = page.info_form
    name_field = info_form.locator(Page.INFO_NAME)
    description_field = info_form.locator(Page.INFO_DESCRIPTION)
    expect(name_field).to_contain_text("Name")
    expect(name_field).to_contain_text(page.definition.name)
    expect(description_field).to_contain_text("Description")
    expect(description_field).to_contain_text(page.definition.description)
    expect(info_form.locator(FormElements.NAME)).not_to_be_attached()
    expect(info_form.locator(FormElements.DESCRIPTION)).not_to_be_attached()
    expect(info_form.locator(Page.INFO_ATTRIBUTES)).not_to_be_attached()
    expect(info_form.locator("[data-role='categories']")).not_to_be_attached()
    expect(info_form.locator("[data-role='autofill']")).not_to_be_attached()


# @matrix pages : document-tab readonly
# @template pages/page.html::main
def test_page_viewer_sees_document_tab_only_when_content_exists(get_user):
    owner = get_user(Users.OWNER)
    page = Pages.acl_lab_document.get(owner)
    marker = "Readonly document content marker"
    if marker not in (page.entity.properties.document.html or ""):
        page.entity.properties.document.save(html=f"<p>{marker}</p>", ydoc=None)
        page.entity.save()

    viewer = get_user(Users.page_acl_one_visible)
    viewer.go(page)

    expect(viewer.locate(Tabs.DOCUMENT_TOGGLE_DESKTOP)).to_be_visible()
    document = Tabs(viewer).document
    expect(document).to_be_visible()
    expect(document).to_contain_text(marker)


# @matrix files : async-load empty-state permission-gates readonly
# @template pages/files.html::file_list
def test_page_viewer_sees_empty_files_tab_without_upload_affordances(get_user):
    owner = get_user(Users.OWNER)
    page = Pages.acl_lab_visible.get(owner)

    viewer = get_user(Users.page_acl_one_visible)
    viewer.go(page)

    files = Tabs(viewer).files
    expect(files).to_be_visible()
    expect(viewer.locate(Page.FILE_LIST)).to_have_attribute("loaded", "")
    expect(viewer.locate(Page.EMPTY_FILE_LIST_ITEM)).to_contain_text(
        "No files have been uploaded to this page"
    )

    expect(viewer.locate(Page.UPLOAD_FILE_TOGGLE)).not_to_be_attached()
    expect(files.locator(Page.UPLOAD_FILE_FORM)).not_to_be_attached()


# @matrix pages : permission-gates permissions-panel
def test_owner_can_open_page_permissions_panel(get_user):
    owner = get_user(Users.OWNER)
    owner.go(Pages.test_create_page)

    Tabs(owner).info
    permissions_toggle = owner.locate(Page.PAGE_PERMISSIONS_TOGGLE)
    expect(permissions_toggle).to_be_visible()
    permissions_toggle.click()

    permissions = owner.locate(Page.PAGE_PERMISSIONS_FORM)
    expect(permissions).to_be_visible()
    expect(permissions.locator(Page.PAGE_PERMISSIONS_VISIBLE_TO)).to_be_visible()
    expect(permissions.locator(Page.PAGE_PERMISSIONS_RESTRICT_ACCESS)).to_be_visible()


# @pair pages:submitted-reference
def test_page_submission_rejects_hidden_internal_link_target(get_user):
    owner = get_user(Users.OWNER)
    category = Categories.acl_create_allowed.get(owner)
    hidden_file_resource = File.upload_from_page(
        owner,
        Pages.test_file_upload_page,
        Uploads.plain_text_file,
    )
    hidden_file = Entities.fetch_one(
        hidden_file_resource.key,
        request=Fetch.direct(),
    )
    form = Entities.FORM.create(
        {
            "name": "Submitted reference internal links",
            "form-type": "page",
            "schema": [
                field.to_dict()
                for field in load_schema("submission_integration_links")
            ],
        }
    )
    form.save()
    page = Entities.PAGE.create(
        {
            "name": "Submitted reference internal-link page",
            "description": "Reject hidden link targets.",
            "attributes": [],
            "categories": [],
            "model": category.entity,
            "form": form,
        }
    )
    page.save()

    actor = get_user(Users.single_category_create)
    actor.navigate(
        f"{SETTINGS.test_config['BASE_URL']}/pages/{page.urlsafe_key}"
    )
    assert page.allowed(Action.EDIT, user=actor.entity)
    assert form.allowed(Action.VIEW, user=actor.entity)
    assert not hidden_file.allowed(Action.VIEW, user=actor.entity)
    cookies = {
        cookie["name"]: cookie["value"] for cookie in actor.page.context.cookies()
    }
    headers = manual_mutation_headers(
        actor.page.url,
        actor.locate("#token").input_value(),
    )
    before = Entities.fetch_one(page.key, request=Fetch.direct())
    before_state = (before.db.get("submission"), before.modified, before.fingerprint)

    response = requests.put(
        f"{SETTINGS.test_config['BASE_URL']}/pages/{page.urlsafe_key}/update",
        data={
            "name": page.name,
            "description": page.description,
            "category": category.key,
            "form": form.urlsafe_key,
            "top_link": hidden_file.urlsafe_key,
        },
        cookies=cookies,
        headers=headers,
        allow_redirects=False,
        timeout=10,
    )
    assert response.status_code == 422
    assert response.text == "One or more selected items are unavailable."

    after = Entities.fetch_one(page.key, request=Fetch.direct())
    assert (after.db.get("submission"), after.modified, after.fingerprint) == before_state
