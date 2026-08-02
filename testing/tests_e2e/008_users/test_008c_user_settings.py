"""
Tests for user settings and preferences.

Tests user page, profile updates, and application settings.
Verified against:
- lagniappe/templates/pages/page.html (user page variant)
- src/script/views/page.mjs
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import Flask
from flask.sessions import SecureCookieSessionInterface
from playwright.sync_api import expect

from config import SETTINGS
from lagniappe import CONFIG
from lagniappe.core.definitions import AI, Fetch, General, Levels, Site
from lagniappe.core.entities import Entities
from testing.definitions import Categories, Groups, SitePages, Submissions, Users
from testing.definitions.user_definitions import UserDefinition
from testing.resources import HomePage, Page
from testing.elements import (
    Buttons,
    DateSelect,
    Dropdown,
    FormElements,
    Modal,
    PermissionsForm,
    Select,
    SpinnerButtons,
    Tabs,
)

pytestmark = pytest.mark.e2e


def _open_user_settings(user, user_page):
    """Open the user settings subpanel from the page Info tab."""
    toggle = user.locate(user_page.USER_SETTINGS_TOGGLE).first
    expect(toggle).to_be_visible()
    toggle.click()
    settings_panel = user.locate(user_page.USER_SETTINGS_FORM)
    expect(settings_panel).to_have_attribute("initialized", "")
    expect(settings_panel).to_be_visible()
    return settings_panel


def _assert_single_user_settings_field_set(settings_panel):
    expect(settings_panel.locator(FormElements.NAME)).to_have_count(1)
    expect(settings_panel.locator(FormElements.EMAIL)).to_have_count(1)


def _assert_sign_out_button_in_user_header(settings_panel):
    user_header = settings_panel.locator("[data-role='user-card'] > header")
    user_actions = user_header.locator("[data-role='user-actions']")
    sign_out_button = user_actions.locator("button[data-action='logout']")
    expect(sign_out_button).to_be_visible()
    expect(sign_out_button).to_have_attribute("data-route", re.compile(r"/users/logout$"))
    expect(sign_out_button).to_contain_text("Sign out")
    user_fields_actions = settings_panel.locator(
        "[data-role='user-fields'] [data-role='user-actions']"
    )
    expect(user_fields_actions).to_have_count(0)


def _tabs_controls(user):
    return user.locate("#tabs [data-role='controls']")


def _open_help_and_expect(user, trigger, text):
    modal = Modal(user.page).open(trigger)
    expect(modal.element).to_contain_text(text)
    modal.close()


def _go_to_my_page(user):
    home = HomePage(user=user)
    with user.page.expect_navigation():
        home.user_page_button.click()


def _open_owner_site_settings(owner):
    owner.go(SitePages.HOME)
    owner.page.evaluate("localStorage.removeItem('lagniappe:site-settings-section')")
    admin = owner.go(SitePages.ADMIN)
    settings_panel = owner.locate(admin.SITE_SETTINGS_FORM)
    expect(settings_panel).to_have_attribute("initialized", "")
    expect(settings_panel).to_be_visible()
    return admin, settings_panel


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
        _go_to_my_page(user)
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
            response.url.endswith("/sync")
            and '"save":true' in post_data
            and text in post_data
        )

    return predicate


def _fetch_status(user, path, method="POST", data=None):
    return user.page.evaluate(
        """async ({ path, method, data }) => {
            const csrfMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);
            const bodyMethods = new Set(["POST", "PUT", "PATCH"]);
            const formBody = () => {
                const body = new FormData();
                for (const [key, value] of Object.entries(data || {})) {
                    const values = Array.isArray(value) ? value : [value];
                    values.forEach((item) => body.append(key, item));
                }
                return body;
            };
            const send = async () => {
                const headers = { "X-Lagniappe-Request": "true" };
                if (csrfMethods.has(method)) {
                    headers["X-CSRFToken"] =
                        document.getElementById("token")?.value || "";
                }
                return fetch(path, {
                    method,
                    credentials: "include",
                    headers,
                    body: bodyMethods.has(method) ? formBody() : undefined,
                });
            };

            let response = await send();
            if (response.status === 400 && csrfMethods.has(method)) {
                const tokenResponse = await fetch("/token");
                const token = await tokenResponse.text();
                const tokenElt = document.getElementById("token");
                if (tokenElt) tokenElt.value = token;
                response = await send();
            }

            return {
                status: response.status,
                text: (await response.text()).slice(0, 240),
            };
        }""",
        {"path": path, "method": method, "data": data or {}},
    )


def _site_settings_section(settings_panel, section):
    return settings_panel.locator(
        f"[data-role='site-settings-section'][data-section='{section}']"
    )


def _open_site_settings_section(settings_panel, section):
    section_panel = _site_settings_section(settings_panel, section)
    if section_panel.get_attribute("data-open") != "true":
        section_panel.locator("[data-role='expand']").click()
    expect(section_panel).to_have_attribute("data-open", "true")
    expect(section_panel.locator("[data-role='section-body']")).to_be_visible()
    return section_panel


def _select_deployment_option(user, form, field_name, option_name):
    select = form.locator(
        f"[data-role='deployment-select']:has(select[name='{field_name}'])"
    )
    select.locator("input[role='combobox']").click()
    user.page.get_by_role("option", name=option_name, exact=True).click()


def _create_user_page_reassign_target(owner, name):
    category = Categories.test_create_page.get(owner)
    page = Entities.PAGE.create(
        {
            "name": name,
            "model": category.entity,
            "attributes": [],
        }
    )
    page.save()
    return page


def _select_page_option(select, page):
    panel = select.open()
    select.input.fill(page.name)
    expect(panel).to_be_visible()
    option = panel.locator(f"[role='option'][data-id='{page.urlsafe_key}']")
    expect(option).to_be_visible()
    option.click()


def _submit_user_settings_and_wait_for_reload(user, settings_panel):
    with user.page.expect_response("**/pages/*/update") as response_info:
        SpinnerButtons.UPDATE.click(settings_panel)
    assert response_info.value.ok
    user.page.wait_for_load_state("load")
    expect(user.locate("[lp-view]")).to_have_attribute("initialized", "")


def _assert_site_image_links(site_image):
    expected_filenames = [
        "favicon-16x16.png",
        "favicon-32x32.png",
        "favicon.ico",
        "apple-touch-icon.png",
        "logo-192x192.png",
        "logo-512x512.png",
    ]

    preview = site_image.locator("img[alt='Site image']")
    expect(preview).to_be_visible()
    expect(preview).to_have_attribute("src", re.compile(r"/images/"))
    expect(preview).to_have_js_property("complete", True)
    assert preview.evaluate("(image) => image.naturalWidth") > 0
    for filename in expected_filenames:
        link = site_image.locator("a", has_text=filename)
        expect(link).to_be_visible()
        assert filename in link.get_attribute("href")


def _submission_payload(submission):
    return {field.id: field.submission_value for field in submission}


def _session_page_key(user):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=CONFIG.SECRET_KEY)
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    cookie = next(
        cookie
        for cookie in user.page.context.cookies()
        if cookie["name"] == "session"
    )
    return serializer.loads(cookie["value"])[CONFIG.LOGIN_USER_PAGE_KEY]


# @features user-settings
# @dimensions personal-page readonly-email sign-out group-selector-hidden
# @template pages/info.html::user_settings
def test_user_settings_panel_opens_from_my_page(get_user, browser_failures):
    """A signed-in user can open settings from their personal page."""
    owner = get_user(Users.OWNER)
    user = get_user(Users.create_user, creator=owner)
    user.go(SitePages.HOME)

    _go_to_my_page(user)
    expect(user.page).to_have_title(re.compile(user.name))

    user_page = Page(user=user, definition=user.definition)
    info_tab = Tabs(user).info
    expect(info_tab).to_be_visible()

    settings_panel = _open_user_settings(user, user_page)
    expect(info_tab.locator(user_page.INFO_FORM)).to_have_count(1)

    email_input = settings_panel.locator("input[name='email']")
    expect(email_input).to_be_visible()
    expect(email_input).to_have_attribute("readonly", "")

    expect(settings_panel.locator("[data-role='user-groups']")).to_have_count(0)
    expect(settings_panel.locator("input[name='ai_access']")).to_have_count(0)

    update_path = f"/pages/{user.entity.page.urlsafe_key}/update"
    with browser_failures.expect_http_error(user, status=403, path=update_path):
        forged = _fetch_status(
            user,
            update_path,
            method="PUT",
            data={
                "role": "user-settings",
                "name": user.name,
                "ai_access": "CREATE",
            },
        )
    assert forged["status"] == 403
    assert Entities.USER.load(user.email).ai_access == "NONE"

    _assert_sign_out_button_in_user_header(settings_panel)

    controls = _tabs_controls(user)
    expect(controls.locator(Buttons.LP_CLOSE)).to_be_visible()
    expect(controls.locator(Buttons.LP_CLOSE)).to_have_attribute(
        "lp-close", "info:PageInfo"
    )


# @features user-settings
# @dimensions owner-own-page readonly-email sign-out group-selector-hidden
# @template pages/info.html::user_settings
def test_owner_settings_hides_group_selector_on_own_page(get_user):
    owner = get_user(Users.OWNER)
    owner.go(SitePages.HOME)

    _go_to_my_page(owner)
    expect(owner.page).to_have_title(re.compile(owner.name))

    owner_page = Page(user=owner, definition=owner.definition)
    info_tab = Tabs(owner).info
    expect(info_tab).to_be_visible()

    settings_panel = _open_user_settings(owner, owner_page)
    expect(info_tab.locator(owner_page.INFO_FORM)).to_have_count(1)

    email_input = settings_panel.locator("input[name='email']")
    expect(email_input).to_be_visible()
    expect(email_input).to_have_attribute("readonly", "")

    expect(settings_panel.locator("[data-role='user-groups']")).to_have_count(0)
    expect(settings_panel).to_have_attribute("data-can-edit-ai", "true")
    expect(settings_panel.locator("input[name='ai_access']")).to_have_count(3)

    _assert_sign_out_button_in_user_header(settings_panel)
    controls = _tabs_controls(owner)
    expect(controls.locator("button[lp-help='user_settings']")).to_be_visible()
    expect(controls.locator(Buttons.LP_CLOSE)).to_be_visible()


# @features public-users
# @dimensions own-page file-photo-gates
# @template pages/page.html::main
def test_public_user_own_page_hides_photo_and_file_surfaces(limited_public_user):
    scenario = limited_public_user
    user = scenario.user
    page = scenario.page
    assert not scenario.entity.page.has("files")
    assert not scenario.entity.page.has("photo")

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
    expect(
        info_form.locator("[data-role='attribute'][data-attribute='files']")
    ).to_have_count(0)
    expect(
        info_form.locator("[data-role='attribute'][data-attribute='photo']")
    ).to_have_count(0)


# @features sync
# @dimensions document
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
    saved_page = Entities.fetch_one(
        scenario.entity.page.key, request=Fetch.direct()
    )
    assert text in (saved_page.properties.document.html or "")
    page.reload()
    editor = page.editor
    expect(editor.text_entry).to_contain_text(text)

    insert_menu = Dropdown(editor.toolbar.locator("[title='Insert']")).open()
    expect(insert_menu.get_by_role("option", name="Link", exact=True)).to_be_visible()
    expect(
        insert_menu.get_by_role("option", name="Image", exact=True)
    ).to_have_count(0)
    expect(
        insert_menu.get_by_role("option", name="Generate Text", exact=True)
    ).to_have_count(0)
    user.page.keyboard.press("Escape")


# @features tasks
# @dimensions create
# @template pages/tasks.html::action_buttons
def test_public_user_creates_task_with_reduced_schedule_options(limited_public_user):
    scenario = limited_public_user
    user = scenario.user
    page = scenario.page
    create_form = page.create_task_form
    expect(create_form.locator("button[type='submit']")).to_be_visible()
    expect(create_form.locator("[data-role='show-autofill']")).to_have_count(0)
    expect(create_form.locator("[data-role='file-select']")).to_have_count(0)

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


def _assert_routes_forbidden(user, routes, browser_failures):
    for method, path, data in routes:
        with browser_failures.expect_http_error(user, status=403, path=path):
            result = _fetch_status(user, path, method=method, data=data)
        assert result["status"] == 403, f"{method} {path}: {result}"


# @features public-users
# @dimensions metered-actions restriction-gate
def test_public_user_ai_actions_are_forbidden(
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


# @features public-users
# @dimensions file-photo-gates restriction-gate
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


# @features public-users
# @dimensions attribute-preservation ai-schedule-guard restriction-gate
def test_public_user_restricted_schedules_are_forbidden(
    limited_public_user, browser_failures
):
    scenario = limited_public_user
    page_key = scenario.entity.page.urlsafe_key
    task_key = scenario.task.urlsafe_key
    initial_attributes = {
        attribute.name
        for attribute in scenario.entity.page.attributes
        if attribute.active
    }
    metadata_update = _fetch_status(
        scenario.user,
        f"/pages/{page_key}/update",
        method="PUT",
        data={
            "name": scenario.entity.page.name,
            "photo": "on",
            "files": "on",
        },
    )
    assert metadata_update["status"] == 200
    saved_page = Entities.fetch_one(
        scenario.entity.page.key, request=Fetch.direct()
    )
    assert not saved_page.has("photo")
    assert not saved_page.has("files")
    assert {
        attribute.name for attribute in saved_page.attributes if attribute.active
    } == initial_attributes

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


# @pair user-settings:owner-other-page
# @pair user-settings:editable-email
# @pair user-settings:group-selector
# @pair user-settings:edit-groups
# @pair user-settings:ai-access
# @pair cache:invalidation-acknowledgement
# @template pages/info.html::user_settings
def test_owner_can_edit_user_settings_on_other_user_page(get_user):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    created_user = get_user(
        UserDefinition(
            name=f"User Settings AI Access {suffix}",
            email=f"user-settings-ai-access-{suffix}@example.test",
            ai_access=AI.NONE,
        ),
        creator=owner,
    )
    created_user_page_key = created_user.entity.page.urlsafe_key

    owner.go(SitePages.USER_INDEX)
    target_row = owner.locate(f"#table tr[data-key='{created_user.key}']")
    expect(target_row).to_be_visible()
    with owner.page.expect_navigation():
        target_row.get_by_role(
            "link", name=created_user.name, exact=True
        ).click()
    expect(owner.page).to_have_title(re.compile(created_user.name))
    assert created_user_page_key in owner.page.url

    created_user_page = Page(user=owner, definition=created_user.definition)
    info_tab = Tabs(owner).info
    expect(info_tab).to_be_visible()

    settings_panel = _open_user_settings(owner, created_user_page)
    _assert_single_user_settings_field_set(settings_panel)
    expect(info_tab.locator(created_user_page.INFO_FORM)).to_have_count(1)

    email_input = settings_panel.locator("input[name='email']")
    expect(email_input).to_be_visible()
    expect(email_input).not_to_have_attribute("readonly", re.compile(".+"))

    expect(settings_panel).to_have_attribute("data-can-edit-groups", "true")
    expect(settings_panel.locator("[data-role='user-groups']")).to_be_visible()
    expect(settings_panel).to_have_attribute("data-can-edit-ai", "true")
    ai_options = settings_panel.locator("input[name='ai_access']")
    expect(ai_options).to_have_count(3)
    expect(
        settings_panel.locator("input[name='ai_access'][value='NONE']")
    ).to_be_checked()

    expect(settings_panel.locator("button[data-action='logout']")).to_have_count(0)

    controls = _tabs_controls(owner)
    expect(controls.locator("button[lp-help='user_settings']")).to_be_visible()
    expect(controls.locator(Buttons.LP_CLOSE)).to_be_visible()
    expect(settings_panel.locator("[data-role='restrict-access']")).to_be_visible()
    expect(settings_panel.locator("[data-role='visible-to']")).to_be_visible()

    restrictions_help = controls.locator(Buttons.LP_HELP)
    restrictions_close = controls.locator(Buttons.LP_CLOSE)
    expect(restrictions_help).to_be_visible()
    expect(restrictions_help).to_have_attribute("lp-help", "user_settings")
    expect(restrictions_close).to_be_visible()
    expect(restrictions_close).to_have_attribute("lp-close", "info:PageInfo")
    _open_help_and_expect(owner, restrictions_help, "User Settings")

    settings_panel.locator("input[name='ai_access'][value='ASK']").check()
    with owner.page.expect_response("**/pages/*/update"):
        SpinnerButtons.UPDATE.click(settings_panel)
    assert SpinnerButtons.UPDATE_SUCCESS.successful(settings_panel)
    saved_user = Entities.USER.load(created_user.email)
    assert saved_user.ai_access == "ASK"
    assert saved_user.invalidate_cache is True

    restrictions_close.click()
    expect(settings_panel).not_to_be_visible()
    expect(info_tab.locator(created_user_page.INFO_FORM)).to_be_visible()

    with created_user.page.context.expect_event(
        "response",
        predicate=lambda response: (
            response.url.endswith("/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        created_user.navigate(SitePages.HOME.get(created_user).url)

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    assert Entities.USER.load(created_user.email).invalidate_cache is False
    expect(created_user.page).to_have_title("Home")


# @pair user-settings:group-selector
# @pair user-settings:preload
# @pair user-settings:relation-loading
# @template pages/info.html::user_settings
def test_user_settings_preloads_existing_groups(get_user):
    """The group selector shows every group already assigned to the user."""
    owner = get_user(Users.OWNER)
    created_user = get_user(Users.user_settings_group_preload, creator=owner)
    first_group = Groups.general_users_view_only.get(owner)
    second_group = Groups.test_user_one_category.get(owner)

    user_page = Page(user=owner, definition=created_user.definition)
    user_page.entity = created_user.entity.page
    owner.go(user_page)

    settings_panel = _open_user_settings(owner, user_page)
    groups = settings_panel.locator("[data-role='user-groups']")
    group_select = Select(groups)
    expected_group_ids = {
        first_group.entity.urlsafe_key,
        second_group.entity.urlsafe_key,
    }

    preload_attribute = groups.locator("[lp-select]").get_attribute("data-preload")
    preload = json.loads(preload_attribute)
    assert {group["id"] for group in preload} == expected_group_ids
    selected_group_ids = set(
        groups.evaluate(
            """root => Array.from(
                root.querySelector("select[name='group']").selectedOptions,
                option => option.value,
            )"""
        )
    )
    assert selected_group_ids == expected_group_ids
    assert first_group.definition.name in group_select.placeholder
    assert second_group.definition.name in group_select.placeholder


# @pair user-settings:owner-other-page
# @pair user-settings:page-reassign
# @pair user-settings:page-remove
# @pair cache:invalidation-acknowledgement
# @pair auth:canonical-page
# @template pages/info.html::user_settings
def test_owner_can_reassign_and_remove_user_from_page(get_user):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    created_user = get_user(
        UserDefinition(
            name=f"User Page Reassignment {suffix}",
            email=f"user-page-reassignment-{suffix}@example.test",
        ),
        creator=owner,
    )
    source_page_key = created_user.entity.page.key
    target_page_entity = _create_user_page_reassign_target(
        owner,
        f"User Reassign Target {suffix}",
    )
    target_page_key = target_page_entity.key

    source_page = Page(
        user=owner,
        definition=SimpleNamespace(name=created_user.entity.page.name),
    )
    source_page.entity = created_user.entity.page
    owner.go(source_page)

    settings_panel = _open_user_settings(owner, source_page)
    expect(settings_panel.locator("[data-role='remove-page']")).to_be_visible()
    page_select = Select(settings_panel.locator("[data-role='page-select']"))
    _select_page_option(page_select, target_page_entity)
    _submit_user_settings_and_wait_for_reload(owner, settings_panel)

    saved_user = Entities.USER.load(created_user.email)
    saved_source_page = Entities.fetch_one(
        source_page_key, request=Fetch.direct()
    )
    saved_target_page = Entities.fetch_one(
        target_page_key, request=Fetch.direct()
    )
    assert saved_source_page.user is None
    assert saved_user.page.key == target_page_key
    assert saved_target_page.user.email == created_user.email

    target_page = Page(
        user=owner,
        definition=SimpleNamespace(name=saved_target_page.name),
    )
    target_page.entity = saved_target_page
    owner.go(target_page)

    settings_panel = _open_user_settings(owner, target_page)
    settings_panel.locator("input[name='remove-user']").check()
    _submit_user_settings_and_wait_for_reload(owner, settings_panel)

    saved_user = Entities.USER.load(created_user.email)
    replacement_page = saved_user.page
    saved_target_page = Entities.fetch_one(
        target_page_key, request=Fetch.direct()
    )
    assert saved_target_page.user is None
    assert replacement_page.key not in {source_page_key, target_page_key}
    assert replacement_page.user.email == created_user.email
    assert saved_user.invalidate_cache is True

    with created_user.page.context.expect_event(
        "response",
        predicate=lambda response: (
            response.url.endswith("/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        created_user.navigate(SitePages.HOME.get(created_user).url)

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    assert Entities.USER.load(created_user.email).invalidate_cache is False
    expect(created_user.page).to_have_title("Home")
    assert _session_page_key(created_user) == replacement_page.urlsafe_key


# @features user-settings
# @dimensions submit-boundary attached-form categories restrictions
# @pair cache:invalidation-acknowledgement
def test_user_settings_submit_preserves_attached_form_and_categories(get_user):
    owner = get_user(Users.OWNER)
    category = Categories.test_basic_inputs_submission.get(owner)
    form = category.definition.form.get(owner)
    restriction_group = Groups.test_user_one_category.get(owner)
    membership_group = Groups.general_users_view_only.get(owner)
    initial_submission = Submissions.basic_inputs.get()
    suffix = uuid4().hex

    page_entity = Entities.PAGE.create(
        {
            "name": f"Attached User Settings Page {suffix}",
            "model": category.entity,
            "form": form.entity,
            "attributes": [],
            "submission": _submission_payload(initial_submission),
        }
    )
    page_entity.groups = [restriction_group.entity]
    page_entity.save()

    attached_user = Entities.USER.create(
        {
            "name": f"Attached Settings User {suffix}",
            "email": f"attached-settings-user-{suffix}@example.test",
            "page": page_entity,
            "test_user": True,
        }
    )
    attached_user.save()

    user_page = Page(
        user=owner,
        definition=SimpleNamespace(name=page_entity.name),
    )
    user_page.entity = page_entity
    owner.go(user_page)

    info_form = user_page.info_form
    expect(info_form).to_be_visible()
    assert user_page.verify_submission(initial_submission)

    category_keys = {c.key for c in page_entity.categories}
    form_key = page_entity.form.key
    restriction_keys = {g.key for g in page_entity.groups}

    settings_panel = _open_user_settings(owner, user_page)
    updated_name = f"Updated Settings User {suffix}"
    updated_email = f"updated-settings-user-{suffix}@example.test"
    settings_panel.locator("input[name='name']").fill(updated_name)
    settings_panel.locator("input[name='email']").fill(updated_email)
    Select(settings_panel.locator("[data-role='user-groups']")).select_by_name(
        membership_group.definition.name
    )

    with owner.page.expect_response("**/pages/*/update"):
        SpinnerButtons.UPDATE.click(settings_panel)
    assert SpinnerButtons.UPDATE_SUCCESS.successful(settings_panel)

    saved_page = Entities.fetch_one(user_page.key, request=Fetch.direct())
    saved_user = Entities.fetch_one(saved_page.user, request=Fetch.direct())
    assert saved_user.name == updated_name
    assert saved_user.email == updated_email
    assert {g.key for g in saved_user.groups} == {membership_group.entity.key}
    assert saved_user.invalidate_cache is True
    assert saved_page.form.key == form_key
    assert {c.key for c in saved_page.categories} == category_keys
    assert {g.key for g in saved_page.groups} == restriction_keys

    affected_user = get_user(Users.ANONYMOUS)
    login_page = affected_user.go(SitePages.LOGIN_PAGE)
    login_url = login_page.login_url(updated_email)
    with affected_user.page.context.expect_event(
        "response",
        predicate=lambda response: (
            response.url.endswith("/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        affected_user.page.goto(login_url)

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    assert Entities.USER.load(updated_email).invalidate_cache is False
    expect(affected_user.page).to_have_title("Home")

    _tabs_controls(owner).locator(Buttons.LP_CLOSE).click()
    expect(settings_panel).not_to_be_visible()
    assert user_page.verify_submission(initial_submission)

    updated_submission = Submissions.basic_inputs.get()
    updated_submission[0].submission_value = f"PageInfo still saves {suffix}"
    user_page.set_submission(updated_submission)
    user_page.submit_and_verify_submission(updated_submission)


# @features admin
# @dimensions site-settings owner-only route page-load
# @template home/admin.html::main
def test_site_settings_is_owner_only(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    user = get_user(Users.create_user, creator=owner)

    # Owner: admin settings page is available.
    admin = owner.go(SitePages.ADMIN)
    expect(owner.locate(admin.SITE_SETTINGS_FORM)).to_be_visible()

    # Non-owner: direct route is forbidden.
    admin_url = f"{SETTINGS.test_config['BASE_URL'].rstrip('/')}/admin"
    with browser_failures.expect_http_error(user, status=403, path=admin_url):
        response = user.page.goto(
            admin_url,
            wait_until="domcontentloaded",
        )
    assert response.status == 403


# @features admin
# @dimensions site-settings sections configuration-modal environment-variables service-providers external-links
# @template home/admin.html::main
# @template home/site_settings.html::site_settings
def test_site_settings_sections_expand_help_and_configuration(get_user):
    owner = get_user(Users.OWNER)
    _, settings_panel = _open_owner_site_settings(owner)

    maintenance = _site_settings_section(settings_panel, "maintenance")
    deployment = _site_settings_section(settings_panel, "deployment")
    ai_models = _site_settings_section(settings_panel, "ai-models")
    providers = _site_settings_section(settings_panel, "service-providers")
    site_image = _site_settings_section(settings_panel, "site-image")

    expect(maintenance).to_have_attribute("data-open", "true")
    expect(deployment).to_have_attribute("data-open", "false")
    expect(ai_models).to_have_attribute("data-open", "false")
    expect(providers).to_have_attribute("data-open", "false")
    expect(site_image).to_have_attribute("data-open", "false")
    _open_help_and_expect(
        owner,
        maintenance.locator("button[lp-help='site_maintenance']"),
        "Refresh Cache",
    )

    _open_site_settings_section(settings_panel, "deployment")
    _open_help_and_expect(
        owner,
        deployment.locator("button[lp-help='site_deployment']"),
        "Scaling",
    )

    _open_site_settings_section(settings_panel, "ai-models")
    expect(deployment).to_have_attribute("data-open", "false")
    expect(ai_models).to_have_attribute("data-open", "true")
    expect(ai_models.locator("input[role='combobox']")).to_have_count(3)
    expect(ai_models.locator("[data-role='section-summary']")).to_contain_text(
        "utility"
    )
    _open_help_and_expect(
        owner,
        ai_models.locator("button[lp-help='site_ai_models']"),
        "Primary",
    )

    _open_site_settings_section(settings_panel, "service-providers")
    expect(ai_models).to_have_attribute("data-open", "false")
    expect(providers).to_have_attribute("data-open", "true")
    expect(providers).to_contain_text("Google Cloud Console")
    _open_help_and_expect(
        owner,
        providers.locator("button[lp-help='site_service_providers']"),
        "outside services",
    )

    _open_site_settings_section(settings_panel, "site-image")
    _open_help_and_expect(
        owner,
        site_image.locator("button[lp-help='site_image']"),
        "browser tabs",
    )

    _open_site_settings_section(settings_panel, "maintenance")
    modal = Modal(owner.page).open(
        settings_panel.locator("[data-role='configuration']")
    )
    expect(modal.element).to_contain_text("Warning")
    expect(modal.element).to_contain_text("APP_NAME")
    expect(
        modal.element.get_by_role("link", name="Download Settings File")
    ).to_be_visible()
    modal.close()


# @features admin
# @dimensions deployment-settings metadata scaling-controls
# @template home/site_settings.html::site_settings
def test_site_settings_deployment_form_saves_and_updates_summary(get_user):
    owner = get_user(Users.OWNER)
    _, settings_panel = _open_owner_site_settings(owner)

    deployment = _open_site_settings_section(settings_panel, "deployment")
    form = deployment.locator("[data-role='deployment-settings']")

    expect(
        form.locator("[data-role='deployment-select'] input[role='combobox']")
    ).to_have_count(2)
    _select_deployment_option(owner, form, "DEPLOY_SCALING_TYPE", "Basic")
    _select_deployment_option(owner, form, "DEPLOY_SCALING_TYPE", "Automatic")
    expect(form.locator("select[name='DEPLOY_INSTANCE_CLASS']")).to_have_value("F2")
    expect(form.locator("[data-role='automatic-instance-counts']")).to_be_visible()
    form.locator("input[name='DEPLOY_WORKER_COUNT']").fill("3")
    form.locator("input[name='DEPLOY_MIN_IDLE_INSTANCES']").fill("1")
    form.locator(
        "[data-role='automatic-instance-counts'] input[name='DEPLOY_MAX_INSTANCES']"
    ).fill("2")

    with owner.page.expect_response("**/set-deployment-settings") as response_info:
        form.locator("button[type='submit']").click()

    response = response_info.value
    assert response.ok, response.text()
    deployment_data = response.json()["deployment"]
    assert deployment_data == {
        "DEPLOY_SCALING_TYPE": "automatic",
        "DEPLOY_WORKER_COUNT": "3",
        "DEPLOY_INSTANCE_CLASS": "F2",
        "DEPLOY_MAX_INSTANCES": "2",
        "DEPLOY_MIN_IDLE_INSTANCES": "1",
        "DEPLOY_IDLE_TIMEOUT": "15m",
    }

    expect(deployment.locator("[data-role='section-summary']")).to_contain_text(
        "Automatic"
    )
    expect(deployment.locator("[data-role='section-summary']")).to_contain_text(
        "3 workers"
    )
    expect(deployment.locator("[data-role='section-summary']")).to_contain_text("F2")
    expect(deployment.locator("[data-role='section-summary']")).to_contain_text(
        "1 min idle"
    )
    expect(deployment.locator("[data-role='section-summary']")).to_contain_text(
        "2 max instances"
    )


# @features admin
# @dimensions site-image-upload generated-images public-preview metadata lazy-initialization
# @template home/site_settings.html::site_settings
def test_site_settings_image_upload_generates_and_persists_site_images(get_user):
    owner = get_user(Users.OWNER)
    admin, settings_panel = _open_owner_site_settings(owner)

    upload_form = settings_panel.locator("[data-role='upload-site-image']")
    expect(upload_form).not_to_have_attribute("rendered", "")

    _open_site_settings_section(settings_panel, "site-image")
    expect(upload_form).to_have_attribute("rendered", "")

    image_path = Path("testing/files/site_image_test_image.jpeg").resolve()
    upload_form.locator(FormElements.FILE_INPUT).set_input_files(str(image_path))
    expect(upload_form.locator("[data-role='dropzone']")).to_contain_text(
        "site_image_test_image"
    )

    with owner.page.expect_response("**/set-site-image") as response_info:
        upload_form.locator("button[type='submit']").click()

    response = response_info.value
    assert response.ok, response.text()
    image_data = response.json()["site_image"]
    assert "favicon-32x32.png" in image_data
    assert "apple-touch-icon.png" in image_data
    assert "logo-192x192.png" in image_data

    site_image = settings_panel.locator("[data-role='site-image']")
    _assert_site_image_links(site_image)

    owner.reload(admin)
    settings_panel = owner.locate(admin.SITE_SETTINGS_FORM)
    expect(settings_panel).to_be_visible()
    _open_site_settings_section(settings_panel, "site-image")

    persisted_site_image = settings_panel.locator("[data-role='site-image']")
    _assert_site_image_links(persisted_site_image)
