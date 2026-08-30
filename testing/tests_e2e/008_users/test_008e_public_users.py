import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from lagniappe import CONFIG
from lagniappe.core.definitions import (
    Action,
    Fetch,
    FetchReason,
    General,
    Levels,
    Site,
)
from lagniappe.core.entities import Entities
from testing.definitions import SitePages, Users
from testing.elements import (
    DateSelect,
    Dropdown,
    FormElements,
    PermissionsForm,
    SpinnerButtons,
    Tabs,
)
from testing.resources import Page
from testing.utility.network import browser_fetch
from testing.utility.user_settings import (
    go_to_my_page,
    open_user_settings,
    user_settings_field_order,
)

pytestmark = pytest.mark.e2e


def _set_public_registration(owner, enabled):
    user_index = owner.go(SitePages.USER_INDEX)
    permissions_form = PermissionsForm(
        owner,
        form=user_index.public_permissions_form,
    )
    permissions_form.set(Site.PUBLIC, Levels.TRUE if enabled else Levels.FALSE)
    if enabled:
        permissions_form.set(General.MODELS, Levels.VIEW)
        permissions_form.set(General.FORMS, Levels.VIEW)
    permissions_form.submit()


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


def _login_public_test_user(get_user, email):
    public_user = get_user(Users.ANONYMOUS)
    public_user.go(SitePages.LOGIN_PAGE, query_params={"test_user": email})
    public_user.go(SitePages.HOME)
    return public_user


@pytest.fixture
def limited_public_user(get_user):
    owner = get_user(Users.OWNER)
    _set_public_registration(owner, True)
    email = f"public-limited-{uuid4().hex}@example.test"
    name = "Public Limited User"
    public_entity = _create_public_user(email, name)
    task = Entities.TASK.create(
        {
            "name": "Public Limited Task",
            "page": public_entity.page,
        }
    )
    task.save()

    try:
        user = _login_public_test_user(get_user, email)
        go_to_my_page(user)
        page = Page(user=user, definition=SimpleNamespace(name=name))
        page.entity = public_entity.page
        yield SimpleNamespace(
            owner=owner,
            user=user,
            entity=public_entity,
            page=page,
            task=task,
        )
    finally:
        _set_public_registration(owner, False)


def _document_save_response(text):
    def predicate(response):
        post_data = response.request.post_data or ""
        return (
            response.url.endswith("/l/sync")
            and '"save":true' in post_data
            and text in post_data
        )

    return predicate


def _assert_routes_forbidden(user, routes, browser_failures):
    for method, path, data in routes:
        with browser_failures.expect_http_error(user, status=403, path=path):
            result = browser_fetch(user, path, method=method, data=data)
        assert result["status"] == 403, f"{method} {path}: {result}"


# @matrix public-users : email-consent file-photo-gates own-page
# @pairs notification-email:public-user user-settings:field-order
# @template pages/page.html::main
# @template pages/info.html::user_settings
def test_public_user_own_page_hides_photo_and_file_surfaces(limited_public_user):
    scenario = limited_public_user
    user = scenario.user
    page = scenario.page

    expect(user.locate(Tabs.FILES_TOGGLE_DESKTOP)).to_have_count(0)
    expect(
        user.locate("[data-nav='tabs'] button[lp-show='photo:active']")
    ).to_have_count(0)
    expect(user.locate(page.UPLOAD_FILE_TOGGLE)).to_have_count(0)
    expect(user.locate(page.PHOTO_PROMPT)).to_have_count(0)

    info_form = page.info_form
    expect(info_form.locator("button[type='submit']")).to_be_visible()
    expect(info_form.locator("[data-role='show-autofill']")).to_have_count(0)
    expect(info_form.locator("[data-role='autofill']")).to_have_count(0)
    settings_panel = open_user_settings(user, page)
    expect(
        settings_panel.locator("input[name='notification_email_mode']")
    ).to_have_count(0)
    consent = settings_panel.locator("input[name='allow_site_email']")
    expect(consent).to_be_visible()
    expect(consent).not_to_be_checked()
    expect(
        settings_panel.locator("[data-role='public-email-consent']")
    ).to_contain_text(f"Allow {CONFIG.APP_NAME} to email me")
    assert user_settings_field_order(settings_panel) == [
        "name",
        "user-email",
        "public-email-consent",
    ]

    consent.check()
    with user.page.expect_response("**/pages/*/update"):
        SpinnerButtons.UPDATE.click(settings_panel)
    assert SpinnerButtons.UPDATE_SUCCESS.successful(settings_panel)
    expect(settings_panel.locator("input[name='allow_site_email']")).to_be_checked()
    assert Entities.USER.load(scenario.entity.email).allow_site_email is True


# @pair sync:document
# @template pages/document.html::document_tab
def test_public_user_edits_document_without_ai_or_image_tools(limited_public_user):
    scenario = limited_public_user
    user = scenario.user
    page = scenario.page
    editor = page.editor
    text = f"public document edit {uuid4().hex}"
    editor.clear_text()
    editor.type_text(text)
    editor.wait_for_render()
    with user.page.expect_response(_document_save_response(text)) as response_info:
        editor.text_entry.blur()
    assert response_info.value.ok
    post_data = response_info.value.request.post_data or ""
    assert json.loads(post_data)["client_id"]
    assert '"token"' not in post_data
    saved_page = Entities.fetch_one(scenario.entity.page.key, request=Fetch.direct())
    assert text in (saved_page.properties.document.html or "")
    page.reload()
    editor = page.editor
    expect(editor.text_entry).to_contain_text(text)

    insert_menu = Dropdown(editor.toolbar.locator("[title='Insert']")).open()
    expect(insert_menu.get_by_role("option", name="Link", exact=True)).to_be_visible()
    expect(insert_menu.get_by_role("option", name="Image", exact=True)).to_have_count(0)
    expect(
        insert_menu.get_by_role("option", name="Generate Text", exact=True)
    ).to_have_count(0)
    user.page.keyboard.press("Escape")


# @pairs tasks:create public-users:task-project-link
# @template pages/tasks.html::action_buttons
def test_public_user_creates_task_with_reduced_schedule_options(
    limited_public_user, browser_failures
):
    scenario = limited_public_user
    user = scenario.user
    page = scenario.page
    create_form = page.create_task_form
    expect(create_form.locator("button[type='submit']")).to_be_visible()
    expect(create_form.locator("[data-role='show-autofill']")).to_have_count(0)
    expect(create_form.locator("[data-role='file-select']")).to_have_count(0)
    expect(create_form.locator("[data-role='project-select']")).to_have_count(0)

    project = Entities.PROJECT.create(
        {
            "name": f"Public task boundary {uuid4().hex}",
            "description": "Project used to verify public task tracking restrictions.",
        }
    )
    project.save()
    assert project.allowed(Action.VIEW, user=scenario.entity)

    page_key = scenario.entity.page.urlsafe_key
    task_key = scenario.task.urlsafe_key
    _assert_routes_forbidden(
        user,
        [
            (
                "POST",
                f"/tasks/{page_key}/create",
                {
                    "name": "Forged project-linked public task",
                    "project": project.urlsafe_key,
                },
            ),
            (
                "POST",
                f"/tasks/{page_key}/create",
                {
                    "name": "Forged model-linked public task",
                    "model": "forged-model-key",
                },
            ),
            (
                "PUT",
                f"/tasks/{task_key}/update",
                {
                    "active": "TaskSettings",
                    "name": scenario.task.name,
                    "project": project.urlsafe_key,
                },
            ),
        ],
        browser_failures,
    )

    scenario.task.project = project
    scenario.task.save()
    renamed_task = f"Public task without tracking controls {uuid4().hex}"
    ordinary_update = browser_fetch(
        user,
        f"/tasks/{task_key}/update",
        method="PUT",
        data={"active": "TaskSettings", "name": renamed_task},
    )
    assert ordinary_update["status"] == 200
    saved_task = Entities.fetch_one(
        scenario.task.key,
        request=Fetch.nested(because=FetchReason.TASK_SAVE_REQUIREMENTS),
    )
    assert saved_task.name == renamed_task
    assert saved_task.project.key == project.key

    schedule_button = create_form.locator("[data-role='date-select']")
    expect(schedule_button).to_have_attribute("data-ai-enabled", "false")
    date_form = DateSelect(create_form).form()
    expect(date_form.locator("input[name='due-date']")).to_be_visible()
    expect(date_form).to_contain_text("This task repeats when completed")
    expect(date_form).to_contain_text("This task repeats on a schedule")
    expect(date_form).not_to_contain_text("This task repeats periodically")

    date_form.locator("input[name='scheduled']").check()
    expect(
        date_form.locator("input[name='schedule-type'][value='daily']")
    ).to_have_count(1)
    expect(
        date_form.locator("input[name='schedule-type'][value='weekly']")
    ).to_have_count(1)
    expect(
        date_form.locator("input[name='schedule-type'][value='monthly']")
    ).to_have_count(0)
    expect(
        date_form.locator("input[name='schedule-type'][value='yearly']")
    ).to_have_count(0)
    expect(
        date_form.locator("button[data-role='explain'][data-explain='schedule']")
    ).to_have_count(0)
    date_form.locator("input[name='scheduled']").uncheck()

    task_name = f"Public personal task {uuid4().hex}"
    create_form.locator(FormElements.NAME).fill(task_name)
    with user.page.expect_response("**/tasks/*/create") as task_response:
        SpinnerButtons.CREATE.click(create_form)
    assert task_response.value.ok
    page.active_task_list.new_item(task_name)


# @matrix public-users : metered-actions restriction-gate
def test_public_user_ai_actions_are_forbidden(limited_public_user, browser_failures):
    scenario = limited_public_user
    page_key = scenario.entity.page.urlsafe_key
    task_key = scenario.task.urlsafe_key
    _assert_routes_forbidden(
        scenario.user,
        [
            (
                "POST",
                f"/assets/{page_key}/document/generate",
                {"prompt": "Write a paragraph"},
            ),
            (
                "POST",
                f"/assets/{page_key}/document/generate",
                {"role": "explain", "prompt": "Show the prompt"},
            ),
            (
                "POST",
                f"/assets/{page_key}/document/image",
                {"role": "generate", "prompt": "A header image", "content": "text"},
            ),
            (
                "POST",
                f"/assets/{page_key}/generate-page-image",
                {"prompt": "A page image"},
            ),
            ("POST", f"/assets/{page_key}/add-page-image", {}),
            ("DELETE", f"/assets/{page_key}/remove-page-image", {}),
            (
                "PUT",
                f"/pages/{page_key}/update",
                {"role": "autofill-submit", "name": scenario.entity.page.name},
            ),
            (
                "PUT",
                f"/pages/{page_key}/update",
                {"role": "explain", "name": scenario.entity.page.name},
            ),
            (
                "PUT",
                f"/tasks/{task_key}/update",
                {"explain": "autofill", "name": scenario.task.name},
            ),
        ],
        browser_failures,
    )


# @matrix public-users : file-photo-gates restriction-gate
def test_public_user_file_and_photo_actions_are_forbidden(
    limited_public_user, browser_failures
):
    scenario = limited_public_user
    page_key = scenario.entity.page.urlsafe_key
    task_key = scenario.task.urlsafe_key
    _assert_routes_forbidden(
        scenario.user,
        [
            (
                "POST",
                f"/assets/{page_key}/document/image",
                {"role": "upload"},
            ),
            ("POST", f"/assets/{page_key}/add-page-image", {}),
            ("DELETE", f"/assets/{page_key}/remove-page-image", {}),
            ("GET", f"/pages/{page_key}/files", {}),
            ("POST", f"/files/{page_key}/upload", {}),
            ("POST", f"/tasks/{task_key}/upload-file", {}),
        ],
        browser_failures,
    )


# @matrix public-users : ai-schedule-guard restriction-gate
def test_public_user_restricted_schedules_are_forbidden(
    limited_public_user, browser_failures
):
    scenario = limited_public_user
    page_key = scenario.entity.page.urlsafe_key
    task_key = scenario.task.urlsafe_key
    metadata_update = browser_fetch(
        scenario.user,
        f"/pages/{page_key}/update",
        method="PUT",
        data={
            "name": scenario.entity.page.name,
        },
    )
    assert metadata_update["status"] == 200
    saved_page = Entities.fetch_one(scenario.entity.page.key, request=Fetch.direct())
    assert saved_page.name == scenario.entity.page.name

    _assert_routes_forbidden(
        scenario.user,
        [
            (
                "PUT",
                f"/tasks/{task_key}/update",
                {
                    "active": "TaskSettings",
                    "name": scenario.task.name,
                    "scheduled": "on",
                    "schedule-type": "monthly",
                    "monthly-description": "first Monday",
                },
            ),
            (
                "PUT",
                f"/tasks/{task_key}/update",
                {
                    "active": "TaskSettings",
                    "name": scenario.task.name,
                    "scheduled": "on",
                },
            ),
            (
                "POST",
                f"/tasks/{page_key}/create",
                {
                    "name": "Forged AI scheduled task",
                    "scheduled": "on",
                    "schedule-type": "monthly",
                    "monthly-description": "first Monday",
                },
            ),
        ],
        browser_failures,
    )
