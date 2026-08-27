import json
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import Flask
from flask.sessions import SecureCookieSessionInterface
from playwright.sync_api import expect
import yaml

from config import SETTINGS, recovery
from lagniappe import CONFIG
from lagniappe.core.definitions import AI, Action, Fetch, General, Levels, Site
from lagniappe.core.entities import Entities
from lagniappe.core.tools.database import get as database_get
from lagniappe.core.tools.database import site as site_database
from lagniappe.core.tools.email.notifications.links import absolute_url
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


def _user_settings_field_order(settings_panel):
    return settings_panel.locator("[data-role='user-fields'] > *").evaluate_all(
        """(elements) => elements.map((element) => {
            if (element.dataset.role && element.dataset.role !== "label") {
                return element.dataset.role;
            }
            const input = element.matches("[name]")
                ? element
                : element.querySelector("[name]");
            return input?.name || element.id;
        })"""
    )


def _assert_sign_out_button_in_user_header(settings_panel):
    user_header = settings_panel.locator("[data-role='user-card'] > header")
    user_actions = user_header.locator("[data-role='user-actions']")
    sign_out_button = user_actions.locator("button[data-action='logout']")
    expect(sign_out_button).to_be_visible()
    expect(sign_out_button).to_have_attribute(
        "data-route", re.compile(r"/users/logout$")
    )
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
            response.url.endswith("/l/sync")
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
                const tokenResponse = await fetch("/l/token");
                const token = await tokenResponse.text();
                const tokenElt = document.getElementById("token");
                if (tokenElt) tokenElt.value = token;
                response = await send();
            }

            const text = await response.text();
            let parsed = text;
            try { parsed = JSON.parse(text); } catch {}
            return {status: response.status, text: text.slice(0, 240), data: parsed};
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


def _select_ai_option(user, form, field_name, option_value):
    select = form.locator(f"[data-role='ai-select']:has(select[name='{field_name}'])")
    option_name = select.locator(
        f"select option[value='{option_value}']"
    ).text_content()
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


def _assert_site_image_links(site_image, image_data):
    required_filenames = {
        "favicon-16x16.png",
        "favicon-32x32.png",
        "favicon.ico",
        "apple-touch-icon.png",
        "logo-192x192.png",
        "logo-512x512.png",
    }
    assert required_filenames.issubset(image_data)
    displayed_images = {
        filename: url
        for filename, url in image_data.items()
        if not filename.startswith("splash-")
    }

    preview = site_image.locator("img[alt='Site image']")
    expect(preview).to_be_visible()
    expect(preview).to_have_attribute("src", re.compile(r"/images/"))
    expect(preview).to_have_js_property("complete", True)
    assert preview.evaluate("(image) => image.naturalWidth") > 0
    expect(site_image.locator("a")).to_have_count(len(displayed_images))
    for filename, url in displayed_images.items():
        link = site_image.locator("a", has_text=filename)
        expect(link).to_be_visible()
        expect(link).to_have_attribute("href", url)


def _submission_payload(submission):
    return {field.id: field.submission_value for field in submission}


def _session_page_key(user):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=CONFIG.SECRET_KEY)
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    cookie = next(
        cookie for cookie in user.page.context.cookies() if cookie["name"] == "session"
    )
    return serializer.loads(cookie["value"])[CONFIG.LOGIN_USER_PAGE_KEY]


def _acknowledge_user_cache_invalidation(user, destination=None):
    """Consume a permission mutation through the browser-owned protocol."""
    assert Entities.USER.load(user.email).invalidate_cache is True
    destination = destination or SitePages.HOME.get(user).url
    with user.page.context.expect_event(
        "response",
        predicate=lambda response: (
            response.url.endswith("/l/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        response = user.navigate(destination)

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    user.entity = Entities.USER.load(user.email)
    assert user.entity.invalidate_cache is False
    return response


# @matrix notification-email : default-daily user-setting
# @matrix user-settings : field-order group-selector-hidden personal-page readonly-email sign-out
# @template pages/info.html::user_settings
def test_user_settings_panel_opens_from_my_page(get_user, browser_failures):
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
    expect(settings_panel).to_have_attribute("data-title", "User Info")
    expect(
        settings_panel.locator("[data-role='user-card'] > header").first
    ).to_contain_text("Settings")

    email_input = settings_panel.locator("input[name='email']")
    expect(email_input).to_be_visible()
    expect(email_input).to_have_attribute("readonly", "")

    expect(settings_panel.locator("[data-role='user-groups']")).to_have_count(0)
    expect(settings_panel.locator("input[name='ai_access']")).to_have_count(0)
    notification_options = settings_panel.locator(
        "input[name='notification_email_mode']"
    )
    expect(notification_options).to_have_count(3)
    expect(
        settings_panel.locator("input[name='notification_email_mode'][value='DAILY']")
    ).to_be_checked()
    expect(
        settings_panel.locator("fieldset[data-role='notification-email']")
    ).to_be_visible()
    assert _user_settings_field_order(settings_panel) == [
        "name",
        "user-email",
        "notification-email",
    ]

    settings_panel.locator(
        "input[name='notification_email_mode'][value='IMMEDIATE']"
    ).check()
    with user.page.expect_response("**/pages/*/update"):
        SpinnerButtons.UPDATE.click(settings_panel)
    assert SpinnerButtons.UPDATE_SUCCESS.successful(settings_panel)
    assert Entities.USER.load(user.email).notification_email_mode == "IMMEDIATE"

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


# @matrix user-settings : field-order group-selector-hidden owner-own-page readonly-email sign-out
# @pair notification-email:default-daily
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
    expect(
        settings_panel.locator("input[name='notification_email_mode']")
    ).to_have_count(3)
    expect(
        settings_panel.locator("input[name='notification_email_mode'][value='DAILY']")
    ).to_be_checked()
    assert _user_settings_field_order(settings_panel) == [
        "name",
        "user-email",
        "ai-access",
        "notification-email",
        "owner-inbound",
    ]

    _assert_sign_out_button_in_user_header(settings_panel)
    controls = _tabs_controls(owner)
    expect(controls.locator("button[lp-help='user_settings']")).to_be_visible()
    expect(controls.locator(Buttons.LP_CLOSE)).to_be_visible()


# @matrix public-users : email-consent file-photo-gates own-page
# @pairs notification-email:public-user user-settings:field-order
# @template pages/page.html::main
# @template pages/info.html::user_settings
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

    settings_panel = _open_user_settings(user, page)
    expect(
        settings_panel.locator("input[name='notification_email_mode']")
    ).to_have_count(0)
    consent = settings_panel.locator("input[name='allow_site_email']")
    expect(consent).to_be_visible()
    expect(consent).not_to_be_checked()
    expect(
        settings_panel.locator("[data-role='public-email-consent']")
    ).to_contain_text(f"Allow {CONFIG.APP_NAME} to email me")
    assert _user_settings_field_order(settings_panel) == [
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


# @pair tasks:create
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


# @matrix ai : access-gate batch-summary provider-boundary
def test_page_editor_without_ai_create_is_rejected_before_batch_summary(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    user = get_user(Users.create_user, creator=owner)
    page = user.entity.page
    assert page.allowed(Action.EDIT, user=user.entity)
    assert not user.entity.access(AI.CREATE)
    user.go(SitePages.HOME)
    path = f"/files/{page.urlsafe_key}/upload"

    with browser_failures.expect_http_error(user, status=403, path=path):
        result = user.page.evaluate(
            """async (path) => {
                const body = new FormData();
                body.append("summarize", "on");
                body.append("file-upload", new File(["one"], "one.txt"));
                body.append("file-upload", new File(["two"], "two.txt"));
                const response = await fetch(path, {
                    method: "POST",
                    credentials: "include",
                    headers: {
                        "X-CSRFToken": document.getElementById("token")?.value,
                        "X-Lagniappe-Request": "true",
                    },
                    body,
                });
                return response.status;
            }""",
            path,
        )

    assert result == 403


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


# @matrix public-users : ai-schedule-guard attribute-preservation restriction-gate
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
    saved_page = Entities.fetch_one(scenario.entity.page.key, request=Fetch.direct())
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


# @matrix user-settings : ai-access edit-groups editable-email field-order group-selector owner-other-page
# @pairs cache:invalidation-acknowledgement notification-email:user-only
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
        target_row.get_by_role("link", name=created_user.name, exact=True).click()
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
    expect(
        settings_panel.locator("input[name='notification_email_mode']")
    ).to_have_count(0)
    user_page_group = settings_panel.locator("fieldset[data-role='user-page']")
    expect(user_page_group).to_be_visible()
    expect(user_page_group.locator("legend")).to_have_text("User Page")
    assert _user_settings_field_order(settings_panel) == [
        "name",
        "user-email",
        "user-groups",
        "ai-access",
        "user-page",
    ]

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
            response.url.endswith("/l/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        created_user.navigate(SitePages.HOME.get(created_user).url)

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    assert Entities.USER.load(created_user.email).invalidate_cache is False
    expect(created_user.page).to_have_title("Home")


# @matrix user-settings : group-selector preload relation-loading
# @template pages/info.html::user_settings
def test_user_settings_preloads_existing_groups(get_user):
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

    preload_element = groups.locator("[lp-select]")
    expect(preload_element).to_have_attribute("data-preload", re.compile(r"\S+"))
    preload_attribute = preload_element.get_attribute("data-preload")
    preload = json.loads(preload_attribute)
    assert {group["id"] for group in preload} == expected_group_ids
    selected_options = groups.locator("select[name='group'] option:checked")
    expect(selected_options).to_have_count(len(expected_group_ids))
    for group_id in expected_group_ids:
        expect(
            groups.locator(f"select[name='group'] option[value='{group_id}']:checked")
        ).to_have_count(1)
    for group_name in (
        first_group.definition.name,
        second_group.definition.name,
    ):
        expect(group_select.input).to_have_attribute(
            "placeholder", re.compile(re.escape(group_name))
        )


# @matrix user-settings : owner-other-page page-reassign page-remove
# @pairs auth:canonical-page cache:invalidation-acknowledgement
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
    saved_source_page = Entities.fetch_one(source_page_key, request=Fetch.direct())
    saved_target_page = Entities.fetch_one(target_page_key, request=Fetch.direct())
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
    saved_target_page = Entities.fetch_one(target_page_key, request=Fetch.direct())
    assert saved_target_page.user is None
    assert replacement_page.key not in {source_page_key, target_page_key}
    assert replacement_page.user.email == created_user.email
    assert saved_user.invalidate_cache is True

    with created_user.page.context.expect_event(
        "response",
        predicate=lambda response: (
            response.url.endswith("/l/validate-user")
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


# @matrix user-settings : attached-form categories restrictions submit-boundary
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
            response.url.endswith("/l/validate-user")
            and response.request.method == "POST"
        ),
    ) as validation_info:
        affected_user.page.goto(login_url)

    validation = validation_info.value
    assert validation.status == 200
    assert validation.json()["cacheCleared"] is True
    assert Entities.USER.load(updated_email).invalidate_cache is False
    expect(affected_user.page).to_have_title("Home")

    user_page.reload()
    info_form = user_page.info_form
    expect(info_form).to_be_visible()
    assert user_page.verify_submission(initial_submission)
    categories = info_form.locator("[data-role='categories']")
    expect(categories).to_be_visible()
    expect(Select(categories).input).to_have_attribute(
        "placeholder", re.compile(re.escape(category.definition.name))
    )
    expect(info_form.locator("[data-role='form-select']")).to_contain_text(
        form.definition.name
    )

    settings_panel = _open_user_settings(owner, user_page)
    expect(settings_panel.locator("input[name='name']")).to_have_value(updated_name)
    expect(settings_panel.locator("input[name='email']")).to_have_value(updated_email)
    settings_groups = settings_panel.locator("[data-role='user-groups']")
    expect(
        settings_groups.locator(
            "select[name='group'] "
            f"option[value='{membership_group.entity.urlsafe_key}']:checked"
        )
    ).to_have_count(1)
    expect(Select(settings_groups).input).to_have_attribute(
        "placeholder", re.compile(re.escape(membership_group.definition.name))
    )
    expect(
        settings_panel.locator(Page.PAGE_RESTRICTED_GROUP_LIST).filter(
            has_text=restriction_group.definition.name
        )
    ).to_be_visible()

    _tabs_controls(owner).locator(Buttons.LP_CLOSE).click()
    expect(settings_panel).not_to_be_visible()
    assert user_page.verify_submission(initial_submission)

    updated_submission = Submissions.basic_inputs.get()
    updated_submission[0].submission_value = f"PageInfo still saves {suffix}"
    user_page.set_submission(updated_submission)
    user_page.submit_and_verify_submission(updated_submission)


# @matrix admin : admin-only page-load route site-settings
# @pair cache:invalidation-acknowledgement
# @template home/admin.html::main
def test_site_settings_requires_administrator(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    user = get_user(
        UserDefinition(
            name=f"Temporary Administrator {suffix[:8]}",
            email=f"temporary-administrator-{suffix}@example.test",
        ),
        creator=owner,
    )

    admin = owner.go(SitePages.ADMIN)
    expect(owner.locate(admin.SITE_SETTINGS_FORM)).to_be_visible()

    admin_url = f"{SETTINGS.test_config['BASE_URL'].rstrip('/')}/admin"
    with browser_failures.expect_http_error(user, status=403, path=admin_url):
        user.navigate(admin_url)
    expect(user.locate(admin.SITE_SETTINGS_FORM)).to_have_count(0)

    user.entity.is_admin = True
    user.entity.save()
    try:
        _acknowledge_user_cache_invalidation(user)
        admin = user.go(SitePages.ADMIN)
        expect(user.locate(admin.SITE_SETTINGS_FORM)).to_be_visible()
    finally:
        user.entity = Entities.USER.load(user.email)
        user.entity.is_admin = False
        user.entity.save()
        _acknowledge_user_cache_invalidation(user)


# @matrix admin : account-preservation confirmation-modal demotion failure-state managed-user-search managed-users owner-only privileged-account promotion read-only responsive roster
# @matrix cache : cache-invalidation invalidation-acknowledgement
# @matrix owner : awaiting-first-sign-in owner-only role-controls
# @template home/site_settings.html::site_settings
def test_site_administrator_roster_and_owner_controls(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    managed = get_user(
        UserDefinition(
            name=f"Administrator Roster User {suffix[:8]}",
            email=f"administrator-roster-{suffix}@example.test",
        ),
        creator=owner,
    )
    _, settings_panel = _open_owner_site_settings(owner)
    section = _open_site_settings_section(settings_panel, "administrators")
    form = section.locator("[data-role='administrator-form']")
    roster = section.locator("[data-role='administrator-list']")

    expect(form).to_have_attribute("data-visible", "true")
    expect(roster.locator("[data-owner='true']")).to_contain_text("Primary Owner")
    expect(roster.locator("[data-owner='true']")).to_contain_text(owner.email)

    selector = form.locator("[data-role='managed-user-selector']")
    expect(selector).to_have_attribute("role", "combobox")
    expect(selector).to_have_attribute("aria-haspopup", "listbox")
    submit = form.locator("button[type='submit']")
    selector_box = selector.bounding_box()
    submit_box = submit.bounding_box()
    assert selector_box and submit_box
    assert abs(selector_box["width"] - submit_box["width"]) <= 2
    assert abs(selector_box["height"] - submit_box["height"]) <= 2
    selector.fill(managed.entity.name)
    option = owner.page.locator(
        f"[role='option'][data-id='{managed.entity.page.urlsafe_key}']"
    )
    expect(option).to_contain_text(managed.entity.name)
    option.click()
    expect(form.locator("select[name='user_key']")).to_have_value(
        managed.entity.page.urlsafe_key
    )
    with owner.page.expect_response(
        lambda response: (
            response.url.endswith("/l/site-administrators")
            and response.request.method == "POST"
        )
    ) as promotion:
        submit.click()
    assert promotion.value.status == 200
    expect(roster).to_contain_text(managed.email)
    promoted = Entities.USER(database_get.user(managed.email))
    assert promoted.is_admin
    assert promoted.invalidate_cache
    assert not promoted.is_owner

    admin_url = f"{SETTINGS.test_config['BASE_URL'].rstrip('/')}/admin"
    managed.entity = promoted
    response = _acknowledge_user_cache_invalidation(managed, admin_url)
    assert response.status == 200
    expect(managed.locate("button[data-role='configuration']")).to_have_count(0)
    admin_section = _open_site_settings_section(
        managed.locate("[data-widget='SiteSettings']"), "administrators"
    )
    expect(admin_section.locator("[data-role='administrator-form']")).to_have_attribute(
        "data-visible", "false"
    )
    expect(admin_section.locator("[data-role='demote-administrator']")).to_have_count(0)

    protected_path = f"/users/{owner.entity.urlsafe_key}/delete"
    with browser_failures.expect_http_error(managed, status=403, path=protected_path):
        protected_delete = _fetch_status(managed, protected_path, "DELETE")
    assert protected_delete["status"] == 403
    self_demote_path = f"/l/site-administrators/{managed.entity.urlsafe_key}"
    with browser_failures.expect_http_error(managed, status=403, path=self_demote_path):
        self_demote = _fetch_status(managed, self_demote_path, "DELETE")
    assert self_demote["status"] == 403

    administrator_row = roster.locator(
        f"[data-role='administrator']:has(button[data-key='{managed.entity.urlsafe_key}'])"
    )
    expect(administrator_row).to_have_class(re.compile(r".*\bsm:flex-row\b.*"))
    demote_button = administrator_row.locator(
        "[data-role='demote-administrator']"
    )
    demote_button.click()
    modal = owner.locate("#modal")
    expect(modal).to_be_visible()
    expect(modal.get_by_role("heading")).to_have_text("Remove Administrator")
    expect(modal).to_contain_text(
        f"Remove Administrator access from {managed.entity.name}?"
    )
    expect(modal).to_contain_text("Their account and content will be kept.")
    modal.get_by_role("button", name="Cancel").click()
    expect(modal).not_to_be_attached()
    expect(administrator_row).to_contain_text(managed.email)
    assert Entities.USER(database_get.user(managed.email)).is_admin

    demote_button.click()
    modal = owner.locate("#modal")
    expect(modal).to_be_visible()
    with owner.page.expect_response(
        lambda response: (
            response.url.endswith(
                f"/l/site-administrators/{managed.entity.urlsafe_key}"
            )
            and response.request.method == "DELETE"
        )
    ) as demotion:
        modal.get_by_role("button", name="Remove Administrator").click()
    assert demotion.value.status == 200
    expect(modal).not_to_be_attached()
    expect(roster).not_to_contain_text(managed.email)
    demoted = Entities.USER(database_get.user(managed.email))
    assert not demoted.is_admin
    assert demoted.invalidate_cache
    managed.entity = demoted

    with browser_failures.expect_http_error(managed, status=403, path=admin_url):
        response = _acknowledge_user_cache_invalidation(managed, admin_url)
    assert response.status == 403


# @matrix owner : configuration recovery-export route-gate sensitive-configuration
# @pair admin:site-settings
def test_additional_admin_cannot_access_owner_configuration(get_user, browser_failures):
    owner = get_user(Users.OWNER)
    suffix = uuid4().hex
    administrator = get_user(
        UserDefinition(
            name=f"Restricted Administrator {suffix[:8]}",
            email=f"restricted-administrator-{suffix}@example.test",
        ),
        creator=owner,
    )
    owner.go(SitePages.HOME)
    administrator.go(SitePages.HOME)
    promotion = _fetch_status(
        owner,
        "/l/site-administrators",
        "POST",
        {"user_key": administrator.entity.urlsafe_key},
    )
    assert promotion["status"] == 200

    try:
        persisted_administrator = Entities.USER(database_get.user(administrator.email))
        assert persisted_administrator.is_admin
        administrator.entity = persisted_administrator
        _acknowledge_user_cache_invalidation(administrator)
        admin = administrator.go(SitePages.ADMIN)
        settings_panel = administrator.locate(admin.SITE_SETTINGS_FORM)
        expect(settings_panel).to_be_visible()
        expect(
            settings_panel.locator("button[data-role='configuration']")
        ).to_have_count(0)

        site_settings = _fetch_status(administrator, "/l/site-settings", "GET")
        assert site_settings["status"] == 200
        assert site_settings["data"]["can_manage_administrators"] is False
        assert site_settings["data"]["can_view_sensitive_configuration"] is False
        assert "installation_access" not in site_settings["data"]
        expect(
            settings_panel.locator(
                "[data-role='site-settings-section'][data-section='installation-access']"
            )
        ).to_have_count(0)
        assert (
            _fetch_status(administrator, "/reference/environment-variables", "GET")[
                "status"
            ]
            == 200
        )
        with browser_failures.expect_http_error(
            administrator, status=403, path="/l/site-configuration"
        ):
            configuration = _fetch_status(administrator, "/l/site-configuration", "GET")
        assert configuration["status"] == 403
        with browser_failures.expect_http_error(
            administrator, status=403, path="/reference/download-settings"
        ):
            recovery = _fetch_status(
                administrator, "/reference/download-settings", "GET"
            )
        assert recovery["status"] == 403
    finally:
        demotion = _fetch_status(
            owner,
            f"/l/site-administrators/{administrator.entity.urlsafe_key}",
            "DELETE",
        )
        assert demotion["status"] == 200
        administrator.entity = Entities.USER.load(administrator.email)
        assert not administrator.entity.is_admin
        _acknowledge_user_cache_invalidation(administrator)


# @matrix owner : authentication-email delegated-handoff identity-metadata provider-cleanup
# @template home/site_settings.html::site_settings
def test_owner_installation_access_distinguishes_handoff_from_provider_cleanup(
    get_user,
    monkeypatch,
):
    owner = get_user(Users.OWNER)
    owner_email = owner.email.casefold()
    installer_email = "temporary-installer@example.test"
    project_id = "delegated-installation-test"
    runtime_email = f"lagniappe@{project_id}.iam.gserviceaccount.com"
    monkeypatch.setattr(CONFIG, "ADMIN_EMAIL", owner_email)
    monkeypatch.setattr(CONFIG, "INSTALLER_EMAIL", installer_email)
    monkeypatch.setattr(CONFIG, "DEPLOYER_EMAIL", installer_email)
    monkeypatch.setattr(CONFIG, "BOOTSTRAP_ADMIN_EMAIL", installer_email)
    monkeypatch.setattr(CONFIG, "GOOGLE_CLOUD_PROJECT", project_id)
    monkeypatch.setattr(CONFIG, "RUNTIME_SERVICE_ACCOUNT_EMAIL", runtime_email)
    monkeypatch.setattr(
        CONFIG,
        "AUTH_EMAIL_CONFIG",
        {
            "provider": "smtp",
            "service": "Gmail",
            "host": "smtp.gmail.com",
            "port": 587,
            "security": "starttls",
            "username": installer_email,
            "password": "not-returned-to-browser",
            "senderEmail": installer_email,
            "senderName": "Delegated Installation Test",
        },
    )

    _, settings_panel = _open_owner_site_settings(owner)
    access = _open_site_settings_section(settings_panel, "installation-access")
    expect(access).to_have_attribute("data-state", "pending")
    expect(access.locator("[data-role='status-title']")).to_have_text(
        "Delegated handoff pending"
    )
    expect(access.locator("[data-field='owner']")).to_have_text(owner_email)
    expect(access.locator("[data-field='installer']")).to_have_text(
        installer_email
    )
    expect(access.locator("[data-field='deployer']")).to_have_text(
        installer_email
    )
    expect(access.locator("[data-field='bootstrap']")).to_have_text(
        installer_email
    )
    expect(access.locator("[data-field='runtime']")).to_have_text(runtime_email)
    expect(access.locator("[data-field='email-service']")).to_have_text("Gmail")
    expect(access.locator("[data-field='email-sender']")).to_have_text(
        installer_email
    )
    expect(access.locator("[data-role='handoff-instructions']")).to_be_visible()
    expect(access.locator("[data-role='handoff-instructions']")).to_contain_text(
        "the installer normally runs"
    )
    expect(
        access.locator("[data-role='handoff-instructions'] code")
    ).to_have_text("./setup.sh handoff")
    expect(access.locator("code[data-field]")).to_have_count(8)
    expect(
        access.locator("[data-role='installer-email-warning']")
    ).to_be_visible()
    expect(access.locator("[data-role='project-iam-link']")).to_have_attribute(
        "href",
        f"https://console.cloud.google.com/iam-admin/iam?project={project_id}",
    )

    payload = _fetch_status(owner, "/l/site-settings", "GET")["data"][
        "installation_access"
    ]
    assert payload["state"] == "pending"
    assert payload["authentication_email"] == {
        "configured": True,
        "service": "Gmail",
        "sender_email": installer_email,
        "login": installer_email,
        "uses_installer": True,
    }
    assert "password" not in json.dumps(payload).casefold()
    assert "not-returned-to-browser" not in json.dumps(payload)

    monkeypatch.setattr(CONFIG, "DEPLOYER_EMAIL", owner_email)
    monkeypatch.setattr(CONFIG, "BOOTSTRAP_ADMIN_EMAIL", "")
    _, settings_panel = _open_owner_site_settings(owner)
    access = _open_site_settings_section(settings_panel, "installation-access")
    expect(access).to_have_attribute("data-state", "application-complete")
    expect(access.locator("[data-role='status-title']")).to_have_text(
        "Application handoff configured"
    )
    expect(access.locator("[data-field='bootstrap']")).to_have_text("None")
    expect(
        access.locator("[data-role='installer-email-warning']")
    ).to_be_visible()
    expect(access.locator("[data-role='handoff-instructions']")).to_be_hidden()

    monkeypatch.setattr(CONFIG, "INSTALLER_EMAIL", owner_email)
    _, settings_panel = _open_owner_site_settings(owner)
    expect(
        _site_settings_section(settings_panel, "installation-access")
    ).to_have_count(0)
    assert "installation_access" not in _fetch_status(
        owner, "/l/site-settings", "GET"
    )["data"]


# @matrix admin : configuration-display configuration-modal environment-variables external-links recovery-export secrets sections service-providers site-settings web-headers
# @template home/admin.html::main
# @template home/site_settings.html::site_settings
def test_site_settings_sections_expand_help_and_configuration(get_user):
    owner = get_user(Users.OWNER)
    _, settings_panel = _open_owner_site_settings(owner)

    maintenance = _site_settings_section(settings_panel, "maintenance")
    installation_access = _site_settings_section(
        settings_panel, "installation-access"
    )
    deployment = _site_settings_section(settings_panel, "deployment")
    ai_models = _site_settings_section(settings_panel, "ai-models")
    providers = _site_settings_section(settings_panel, "service-providers")
    site_image = _site_settings_section(settings_panel, "site-image")

    expect(maintenance).to_have_attribute("data-open", "true")
    expect(installation_access).to_have_attribute("data-open", "false")
    expect(deployment).to_have_attribute("data-open", "false")
    expect(ai_models).to_have_attribute("data-open", "false")
    expect(providers).to_have_attribute("data-open", "false")
    expect(site_image).to_have_attribute("data-open", "false")
    _open_help_and_expect(
        owner,
        maintenance.locator("button[lp-help='site_maintenance']"),
        "Refresh Cache",
    )

    _open_site_settings_section(settings_panel, "installation-access")
    _open_help_and_expect(
        owner,
        installation_access.locator("button[lp-help='site_installation_access']"),
        "Why there is no Remove IAM button",
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
    expect(modal.element).to_contain_text(recovery.REDACTED_VALUE)
    download_link = modal.element.get_by_role("link", name="Download Settings File")
    with owner.page.expect_response("**/reference/download-settings") as response_info:
        with owner.page.expect_download() as download_info:
            download_link.click()
    response = response_info.value
    download = download_info.value
    downloaded = yaml.safe_load(Path(download.path()).read_text())
    assert response.status == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["content-type"].startswith("application/yaml")
    assert downloaded["CONFIG_KIND"] == recovery.CONFIG_KIND
    assert downloaded["CONFIG_SCHEMA_VERSION"] == recovery.CONFIG_SCHEMA_VERSION
    live_deployment = site_database.deployment()
    if live_deployment:
        assert (
            downloaded["DEPLOY_MAX_INSTANCES"]
            == dict(live_deployment)["DEPLOY_MAX_INSTANCES"]
        )
    live_ai = site_database.ai()
    if live_ai:
        assert downloaded["AI_MODEL"] == dict(live_ai)["AI_MODEL"]
    modal.close()


# @matrix admin : deployment-settings metadata scaling-controls validation
# @template home/site_settings.html::site_settings
def test_site_settings_deployment_form_saves_and_updates_summary(
    get_user,
    browser_failures,
):
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

    with owner.page.expect_response("**/l/set-deployment-settings") as response_info:
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

    with browser_failures.expect_http_error(
        owner,
        status=422,
        path="/l/set-deployment-settings",
    ):
        rejected = _fetch_status(
            owner,
            "/l/set-deployment-settings",
            data={**deployment_data, "DEPLOY_WORKER_COUNT": "0"},
        )
    assert rejected["status"] == 422
    assert "Worker count" in rejected["text"]


# @matrix admin : ai-settings metadata model-selection saved-values validation
# @template home/site_settings.html::site_settings
def test_site_settings_ai_form_saves_current_models_through_route(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    admin, settings_panel = _open_owner_site_settings(owner)
    ai_models = _open_site_settings_section(settings_panel, "ai-models")
    form = ai_models.locator("[data-role='ai-settings']")

    primary = form.locator("select[name='AI_MODEL']")
    current_primary = primary.input_value()
    primary_options = primary.locator("option").evaluate_all(
        "options => options.map(option => option.value)"
    )
    selected_primary = next(
        (option for option in primary_options if option != current_primary),
        None,
    )
    assert selected_primary, "AI model chooser did not offer an alternate model"
    _select_ai_option(owner, form, "AI_MODEL", selected_primary)
    expect(primary).to_have_value(selected_primary)

    expected = {
        name: form.locator(f"[name='{name}']").input_value()
        for name in (
            "AI_MODEL",
            "AI_UTILITY_MODEL",
            "AI_IMAGE_MODEL",
            "AI_LOCATION",
        )
    }

    with owner.page.expect_response("**/l/set-ai-settings") as response_info:
        form.locator("button[type='submit']").click()

    response = response_info.value
    assert response.status == 200
    assert response.json()["ai_settings"] == expected
    expect(form.locator("button[type='submit']")).to_contain_text(
        "AI Model Settings Saved"
    )
    saved = dict(site_database.ai())
    assert {name: saved[name] for name in expected} == expected

    owner.page.reload(wait_until="domcontentloaded")
    reloaded_settings_panel = owner.locate(admin.SITE_SETTINGS_FORM)
    expect(reloaded_settings_panel).to_have_attribute("initialized", "")
    reloaded_ai_models = _open_site_settings_section(
        reloaded_settings_panel,
        "ai-models",
    )
    reloaded_form = reloaded_ai_models.locator("[data-role='ai-settings']")
    for name, value in expected.items():
        expect(reloaded_form.locator(f"[name='{name}']")).to_have_value(value)

    with browser_failures.expect_http_error(
        owner,
        status=422,
        path="/l/set-ai-settings",
    ):
        rejected = _fetch_status(
            owner,
            "/l/set-ai-settings",
            data={**expected, "AI_LOCATION": "not-global"},
        )
    assert rejected["status"] == 422
    assert "global" in rejected["text"]


# @matrix admin public-pages : live-settings sitemap-invalidation validation
# @matrix public-pages sitemap : disabled enabled redis-cache
# @matrix robots : disabled enabled
# @template home/site_settings.html::site_settings
def test_site_settings_public_page_indexing_saves_live_setting(
    get_user,
    browser_failures,
):
    owner = get_user(Users.OWNER)
    _, settings_panel = _open_owner_site_settings(owner)
    section = _open_site_settings_section(settings_panel, "public-pages")
    form = section.locator("[data-role='public-page-settings']")
    field = form.locator("[name='PUBLIC_PAGE_INDEXING']")
    stored = site_database.public_pages()
    original = (
        bool(stored.get("PUBLIC_PAGE_INDEXING"))
        if stored
        else bool(getattr(CONFIG, "PUBLIC_PAGE_INDEXING", False))
    )
    loaded = _fetch_status(owner, "/l/site-settings/public-pages", "GET")
    assert loaded["status"] == 200
    assert loaded["data"]["public_pages"]["PUBLIC_PAGE_INDEXING"] is original

    def save(enabled):
        field.set_checked(enabled)
        with owner.page.expect_response(
            "**/l/site-settings/public-pages"
        ) as response_info:
            form.locator("button[type='submit']").click()
        response = response_info.value
        assert response.status == 200
        assert response.json()["public_pages"]["PUBLIC_PAGE_INDEXING"] is enabled
        expect(section.locator("[data-role='section-summary']")).to_have_text(
            f"Search discovery is {'on' if enabled else 'off'}"
        )

    try:
        save(True)
        assert site_database.public_pages()["PUBLIC_PAGE_INDEXING"] is True
        origin = owner.page.evaluate("location.origin")

        robots = owner.page.context.request.get(f"{origin}/robots.txt")
        assert robots.status == 200
        assert "Allow: /pages/public/" in robots.text()
        assert f"Sitemap: {absolute_url('/sitemap.xml')}" in robots.text()

        first_sitemap = owner.page.context.request.get(
            f"{origin}/sitemap.xml"
        )
        second_sitemap = owner.page.context.request.get(
            f"{origin}/sitemap.xml"
        )
        assert first_sitemap.status == second_sitemap.status == 200
        assert first_sitemap.text() == second_sitemap.text()
        assert "<urlset" in first_sitemap.text()

        with browser_failures.expect_http_error(
            owner,
            status=422,
            path="/l/site-settings/public-pages",
        ):
            rejected = _fetch_status(
                owner,
                "/l/site-settings/public-pages",
                data={"PUBLIC_PAGE_INDEXING": "sometimes"},
            )
        assert rejected["status"] == 422

        save(False)
        disabled_robots = owner.page.context.request.get(
            f"{origin}/robots.txt"
        )
        assert "Sitemap:" not in disabled_robots.text()
        disabled_sitemap = owner.page.context.request.get(
            f"{origin}/sitemap.xml"
        )
        assert disabled_sitemap.status == 404
    finally:
        if field.is_checked() is not original:
            save(original)


# @matrix admin : site-update success
# @pair cache:current
# @template home/site_settings.html::site_settings
def test_site_maintenance_update_and_cache_refresh_use_real_routes(get_user):
    owner = get_user(Users.OWNER)
    _, settings_panel = _open_owner_site_settings(owner)
    maintenance = _open_site_settings_section(settings_panel, "maintenance")

    update = _fetch_status(owner, "/l/site-update", method="POST")
    assert update["status"] == 200
    assert update["data"]["migration_status"]["status"] == "current"

    cache_button = maintenance.locator("[data-role='rebuild-cache']")
    expect(cache_button).to_be_enabled()
    with owner.page.expect_response("**/l/rebuild-cache") as response_info:
        cache_button.click()
    assert response_info.value.status == 200
    expect(cache_button).to_contain_text("Cache Refreshed")


# @matrix admin : generated-images lazy-initialization metadata public-preview site-image-upload
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

    with owner.page.expect_response("**/l/set-site-image") as response_info:
        upload_form.locator("button[type='submit']").click()

    response = response_info.value
    assert response.ok, response.text()
    image_data = response.json()["site_image"]
    assert "favicon-32x32.png" in image_data
    assert "apple-touch-icon.png" in image_data
    assert "logo-192x192.png" in image_data

    site_image = settings_panel.locator("[data-role='site-image']")
    _assert_site_image_links(site_image, image_data)

    owner.reload(admin)
    settings_panel = owner.locate(admin.SITE_SETTINGS_FORM)
    expect(settings_panel).to_be_visible()
    _open_site_settings_section(settings_panel, "site-image")

    persisted_site_image = settings_panel.locator("[data-role='site-image']")
    _assert_site_image_links(persisted_site_image, image_data)
